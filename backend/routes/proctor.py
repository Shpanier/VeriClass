import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import db, deps

router = APIRouter()

# Events that mean the student left the IDE (or its full screen). The dashboard
# counts these as violations. Kept here as the single source of truth.
ALERT_KINDS = ("focus_lost", "minimized", "fullscreen_exited",
               # Windows: the OS has another app in front (GetForegroundWindow).
               "other_app_in_front",
               # The window was made smaller than maximized ("restore down").
               "window_unmaximized",
               # The student closed the IDE (or the exam project) during the exam.
               "ide_closed")

# Terminal violations: a refused command in the VeriExam terminal (written by
# routes/terminal.py, never by the client directly) and an attempt to open the
# IDE's own, unmonitored Terminal during an exam. Alerts, but not "away".
TERMINAL_ALERT_KINDS = ("blocked_command", "stock_terminal_opened")

# Inside-the-IDE violations: a panel outside the exam allowlist (the plugin has
# already closed it), a dialog or another project window, and a paste whose
# clipboard came from another app (written by POST /proctor/paste).
IDE_ALERT_KINDS = ("tool_window_opened", "other_window_opened", "paste_external")

# The events that decide whether a student is in the IDE / in full screen right
# now (the last one of these wins). Everything else is a one-off.
FOCUS_STATE_KINDS = ALERT_KINDS + ("exam_started", "focus_regained", "window_restored", "fullscreen_restored",
                                   "window_maximized")

# Every kind the exam client is allowed to report. Anything else is rejected so
# a bug in the client can't pollute the proctor trail.
_VALID_KINDS = FOCUS_STATE_KINDS + (
    "stock_terminal_opened",
    "tool_window_opened",
    "other_window_opened",
    "other_window_closed",
    "file_opened",
)

_DETAIL_MAX = 500
_PASTE_MAX = 20000
_STATUS_MAX = 8000
_PASTE_TARGETS = ("editor", "terminal", "chat", "other")
_PASTE_SOURCES = ("outside", "ide", "tutor")


class ProctorEventRequest(BaseModel):
    session_id: str
    kind: str
    detail: Optional[str] = None
    away_ms: Optional[int] = None
    # Set by plugins that queue and retry reports; see db.py.
    client_id: Optional[str] = None
    client_at: Optional[str] = None


class PasteRequest(BaseModel):
    session_id: str
    target: str
    source: str
    text: str
    file: Optional[str] = None
    client_id: Optional[str] = None
    client_at: Optional[str] = None


class HeartbeatRequest(BaseModel):
    session_id: str
    # The exam client's live snapshot: focused, fullscreen, fullscreen_supported,
    # tool_windows, forbidden_tool_windows, other_windows, open_files, active_file.
    status: Optional[dict[str, Any]] = None


def _touch_session(c, session_id: str) -> bool:
    """Bump last_active_at so the student stays visible on the live grid even
    while they're away. Returns False if the session is unknown."""
    cur = c.execute(
        "UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?",
        (session_id,),
    )
    return cur.rowcount > 0


def _clip(s: Optional[str], n: int) -> Optional[str]:
    s = (s or "").strip()
    return s[:n] or None


def insert_event(c, session_id: str, kind: str, detail: Optional[str] = None,
                 away_ms: Optional[int] = None, client_id: Optional[str] = None,
                 client_at: Optional[str] = None, via: str = "live") -> Optional[int]:
    """Store one proctor event. Returns its id, or None when this client_id is
    already stored (a retry of a report that got through)."""
    cur = c.execute(
        "INSERT OR IGNORE INTO proctor_events "
        "(session_id, kind, detail, away_ms, client_id, client_at, via) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, kind, _clip(detail, _DETAIL_MAX),
         away_ms if (away_ms is not None and away_ms >= 0) else None,
         _clip(client_id, 64), _clip(client_at, 40), via),
    )
    return cur.lastrowid if cur.rowcount else None


def insert_paste(c, session_id: str, req: PasteRequest, via: str = "live") -> Optional[int]:
    """Store a paste and its proctor event (paste_external is an alert,
    paste_internal is not). Returns the paste id, or None for a retry."""
    target = req.target if req.target in _PASTE_TARGETS else "other"
    source = req.source if req.source in _PASTE_SOURCES else "outside"
    text = req.text or ""
    lines = text.count("\n") + 1 if text else 0
    cur = c.execute(
        "INSERT OR IGNORE INTO pastes "
        "(session_id, client_id, target, source, chars, lines, text, file, client_at, via) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, _clip(req.client_id, 64), target, source, len(text), lines,
         text[:_PASTE_MAX], _clip(req.file, _DETAIL_MAX), _clip(req.client_at, 40), via),
    )
    if not cur.rowcount:
        return None
    where = {"editor": "the editor", "terminal": "the terminal", "chat": "the chat"}.get(target, "the IDE")
    origin = {"outside": "from outside the IDE", "ide": "copied inside the IDE",
              "tutor": "copied from the tutor's answer"}[source]
    preview = " ".join(text.split())[:120]
    detail = f"{len(text)} chars, {lines} lines into {where}"
    if req.file:
        detail += f" ({req.file})"
    detail += f" — {origin}: {preview}"
    insert_event(c, session_id, "paste_external" if source == "outside" else "paste_internal",
                 detail=detail, client_at=req.client_at, via=via)
    return cur.lastrowid


@router.post("/proctor/event")
def record_event(req: ProctorEventRequest, user: dict = Depends(deps.current_user)):
    """The exam client reports a focus/minimize/fullscreen change, a panel or
    window it wasn't allowed to open, or an editor tab here.

    Bound to the caller's own session so a student can't forge focus_regained
    to mask a leave, nor inject focus_lost into a classmate's session.
    """
    deps.require_owns_session(req.session_id, user)
    kind = req.kind.strip().lower()
    if kind not in _VALID_KINDS:
        raise HTTPException(422, f"Unknown proctor event kind: {req.kind!r}")

    with db.conn() as c:
        if not _touch_session(c, req.session_id):
            raise HTTPException(404, "Unknown session")
        event_id = insert_event(c, req.session_id, kind, req.detail, req.away_ms,
                                req.client_id, req.client_at)
    return {"ok": True, "id": event_id, "duplicate": event_id is None}


@router.post("/proctor/paste")
def record_paste(req: PasteRequest, user: dict = Depends(deps.current_user)):
    """The exam client saw a paste (editor, VeriExam terminal or chat box)."""
    deps.require_owns_session(req.session_id, user)
    with db.conn() as c:
        if not _touch_session(c, req.session_id):
            raise HTTPException(404, "Unknown session")
        paste_id = insert_paste(c, req.session_id, req)
    return {"ok": True, "id": paste_id, "duplicate": paste_id is None}


@router.post("/proctor/heartbeat")
def heartbeat(req: HeartbeatRequest, user: dict = Depends(deps.current_user)):
    """Keep-alive that also carries the exam client's live snapshot (see
    HeartbeatRequest.status). Bound to the caller's own session so presence
    can't be spoofed from a script while the real client is closed."""
    deps.require_owns_session(req.session_id, user)
    with db.conn() as c:
        if not _touch_session(c, req.session_id):
            raise HTTPException(404, "Unknown session")
        if req.status is not None:
            data = json.dumps(req.status)[:_STATUS_MAX]
            c.execute(
                "INSERT INTO live_status (session_id, data, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(session_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                (req.session_id, data),
            )
    return {"ok": True}


@router.get("/proctor/events")
def list_events(
    session_id: Optional[str] = None,
    limit: int = 200,
    teacher: dict = Depends(deps.require_teacher),
):
    """Recent proctor events (newest first). Scope to one student with
    ?session_id=…; the dashboard uses it to render a per-student log."""
    limit = max(1, min(limit, 1000))
    cols = "id, session_id, kind, detail, away_ms, client_at, via, created_at"
    with db.conn() as c:
        if session_id:
            rows = c.execute(
                f"SELECT {cols} FROM proctor_events WHERE session_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT {cols} FROM proctor_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


@router.get("/proctor/pastes")
def list_pastes(
    session_id: str,
    limit: int = 200,
    teacher: dict = Depends(deps.require_teacher),
):
    """One student's pastes with the pasted text, newest first."""
    limit = max(1, min(limit, 1000))
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, target, source, chars, lines, text, file, client_at, via, created_at "
            "FROM pastes WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]
