import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import db, deps
from backend.routes import proctor

router = APIRouter()

# Stored sizes. The plugin already trims; these keep a buggy or hostile client
# from filling the DB.
_LINE_MAX = 2000
_OUTPUT_MAX = 8000
_TEXT_MAX = 500
_COMMANDS_MAX = 50
# Full output arrives in pieces of at most _CHUNK_MAX characters; past
# _CHUNKS_MAX pieces (~4 MB) a command's output is not stored any further.
_CHUNK_MAX = 16000
_CHUNKS_MAX = 256


class TerminalCommandRequest(BaseModel):
    session_id: str
    line: str
    cwd: Optional[str] = None
    # False = the plugin refused the line (it never ran).
    allowed: bool
    reason: Optional[str] = None
    # Every program name the plugin found in the line.
    commands: list[str] = Field(default_factory=list)
    # Refused only because it doesn't parse (unclosed quote): logged, not alerted.
    syntax_error: bool = False
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    output_tail: Optional[str] = None
    # Newer plugins: an id that makes a retry idempotent, when the line was
    # entered, and how the full output (POST /terminal/output) was split.
    client_id: Optional[str] = None
    client_at: Optional[str] = None
    output_chars: Optional[int] = None
    output_chunks: Optional[int] = None
    # Plugin 0.3.1+: the student's OS ("Windows 11 amd64") and the shell that
    # ran the line ("BusyBox (bundled)"). The same line can behave differently.
    client_os: Optional[str] = None
    shell: Optional[str] = None


class TerminalOutputRequest(BaseModel):
    session_id: str
    client_id: str
    seq: int
    text: str


def _clip(s: Optional[str], n: int) -> Optional[str]:
    return s[:n] if s else None


def insert_command(c, req: TerminalCommandRequest, via: str = "live") -> tuple[Optional[int], bool]:
    """Store one terminal line (and its blocked_command alert). Returns
    (id, alert); id is None when this client_id is already stored."""
    line = req.line[:_LINE_MAX]
    commands = [x[:64] for x in req.commands[:_COMMANDS_MAX]]
    alert = not req.allowed and not req.syntax_error
    cur = c.execute(
        "INSERT OR IGNORE INTO terminal_commands "
        "(session_id, line, cwd, allowed, reason, commands, syntax_error, "
        " exit_code, duration_ms, output_tail, client_id, client_at, "
        " output_chars, output_chunks, via, client_os, shell) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            req.session_id,
            line,
            _clip(req.cwd, _TEXT_MAX),
            1 if req.allowed else 0,
            _clip(req.reason, _TEXT_MAX),
            json.dumps(commands),
            1 if req.syntax_error else 0,
            req.exit_code,
            req.duration_ms if (req.duration_ms is None or req.duration_ms >= 0) else None,
            _clip(req.output_tail, _OUTPUT_MAX),
            _clip(req.client_id, 64),
            _clip(req.client_at, 40),
            req.output_chars if (req.output_chars or 0) > 0 else None,
            min(req.output_chunks, _CHUNKS_MAX) if (req.output_chunks or 0) > 0 else None,
            via,
            _clip(req.client_os, 80),
            _clip(req.shell, 80),
        ),
    )
    if not cur.rowcount:
        return None, alert
    if alert:
        detail = f"$ {line}"
        if req.reason:
            detail += f" — {req.reason}"
        proctor.insert_event(c, req.session_id, "blocked_command", detail,
                             client_at=req.client_at, via=via)
    return cur.lastrowid, alert


def insert_output(c, req: TerminalOutputRequest) -> bool:
    if not (0 <= req.seq < _CHUNKS_MAX):
        return False
    cur = c.execute(
        "INSERT OR IGNORE INTO terminal_output (session_id, client_id, seq, text) VALUES (?, ?, ?, ?)",
        (req.session_id, req.client_id[:64], req.seq, req.text[:_CHUNK_MAX]),
    )
    return cur.rowcount > 0


@router.post("/terminal/command")
def record_command(req: TerminalCommandRequest, user: dict = Depends(deps.current_user)):
    """The VeriExam terminal logs every line the student enters here — run or
    refused. A refused line (not a mere syntax error) also becomes a
    `blocked_command` proctor event, so it shows in the proctor trail and
    raises the dashboard alarm like leaving the IDE does.

    Bound to the caller's own session, like the proctor events. A retried
    report (same client_id) is acknowledged but stored once.
    """
    deps.require_owns_session(req.session_id, user)
    with db.conn() as c:
        cur = c.execute(
            "UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?",
            (req.session_id,),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Unknown session")
        command_id, alert = insert_command(c, req)
    return {"ok": True, "id": command_id, "alert": alert, "duplicate": command_id is None}


@router.post("/terminal/output")
def record_output(req: TerminalOutputRequest, user: dict = Depends(deps.current_user)):
    """One piece of a command's full output (the command itself carries how
    many pieces there are). Idempotent per (client_id, seq)."""
    deps.require_owns_session(req.session_id, user)
    with db.conn() as c:
        stored = insert_output(c, req)
    return {"ok": True, "stored": stored}


@router.get("/terminal/commands/{command_id}/output")
def full_output(command_id: int, teacher: dict = Depends(deps.require_teacher)):
    """A command's full output, put back together. `complete` is False while
    pieces are missing (still in the student's outbox, or never sent)."""
    with db.conn() as c:
        cmd = c.execute(
            "SELECT session_id, client_id, output_tail, output_chars, output_chunks "
            "FROM terminal_commands WHERE id = ?",
            (command_id,),
        ).fetchone()
        if cmd is None:
            raise HTTPException(404, "Unknown command")
        pieces = []
        if cmd["client_id"]:
            pieces = c.execute(
                "SELECT seq, text FROM terminal_output WHERE session_id = ? AND client_id = ? ORDER BY seq",
                (cmd["session_id"], cmd["client_id"]),
            ).fetchall()
    expected = cmd["output_chunks"] or 0
    if not pieces:
        return {"output": cmd["output_tail"] or "", "complete": expected == 0,
                "chunks": 0, "expected_chunks": expected, "chars": cmd["output_chars"]}
    have = {p["seq"]: p["text"] for p in pieces}
    out = [
        have.get(i, f"\n[… piece {i + 1} of {expected} was not received …]\n")
        for i in range(max(expected, max(have) + 1))
    ]
    return {"output": "".join(out), "complete": set(range(expected)) <= have.keys(),
            "chunks": len(pieces), "expected_chunks": expected, "chars": cmd["output_chars"]}


@router.get("/terminal/commands")
def list_commands(
    session_id: str,
    limit: int = 300,
    teacher: dict = Depends(deps.require_teacher),
):
    """One student's terminal log, newest first (the dashboard's terminal view)."""
    limit = max(1, min(limit, 2000))
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, session_id, line, cwd, allowed, reason, commands, syntax_error, "
            "       exit_code, duration_ms, output_tail, output_chars, output_chunks, "
            "       client_at, via, created_at, client_os, shell "
            "FROM terminal_commands WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["allowed"] = bool(d["allowed"])
        d["syntax_error"] = bool(d["syntax_error"])
        try:
            d["commands"] = json.loads(d["commands"] or "[]")
        except ValueError:
            d["commands"] = []
        out.append(d)
    return out
