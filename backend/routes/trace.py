from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from backend import db, deps, trace
from backend.routes import proctor, terminal

router = APIRouter()


class VerifyRequest(BaseModel):
    csv: str
    # Also store every verified row the server never received (marked via='export').
    import_missing: bool = False


def _summary(kind: str, p: dict) -> str:
    if kind == "terminal":
        return f"$ {p.get('line', '')}"
    if kind == "proctor":
        return f"{p.get('kind', '')}: {p.get('detail') or ''}".strip(": ")
    if kind == "paste":
        return f"paste into {p.get('target', '?')} ({p.get('source', '?')}): {len(p.get('text') or '')} chars"
    if kind in ("chat_user", "chat_tutor"):
        return (p.get("text") or "")[:160]
    return ""


def _chunks(text: str) -> list[str]:
    n = terminal._CHUNK_MAX
    return [text[i:i + n] for i in range(0, len(text), n)][:terminal._CHUNKS_MAX]


def _on_server(c, session_id: str, kind: str, client_id: str, p: dict):
    """True/False whether the server already has this row; None when it can't tell."""
    if kind == "terminal":
        row = c.execute("SELECT output_chunks FROM terminal_commands WHERE session_id = ? AND client_id = ?",
                        (session_id, client_id)).fetchone()
        if row is None:
            return False
        have = c.execute("SELECT COUNT(*) FROM terminal_output WHERE session_id = ? AND client_id = ?",
                         (session_id, client_id)).fetchone()[0]
        return have >= (row["output_chunks"] or 0)
    if kind in ("proctor", "paste"):
        table = "proctor_events" if kind == "proctor" else "pastes"
        return c.execute(f"SELECT 1 FROM {table} WHERE session_id = ? AND client_id = ?",
                         (session_id, client_id)).fetchone() is not None
    if kind in ("chat_user", "chat_tutor"):
        role = "user" if kind == "chat_user" else "assistant"
        return c.execute("SELECT 1 FROM messages WHERE session_id = ? AND role = ? AND body = ?",
                         (session_id, role, p.get("text") or "")).fetchone() is not None
    return None


def _import(c, session_id: str, kind: str, client_id: str, at_utc: str, p: dict) -> bool:
    p = {**p, "session_id": session_id, "client_id": client_id}
    p.setdefault("client_at", at_utc)
    try:
        if kind == "terminal":
            output = p.get("output") or ""
            pieces = _chunks(output)
            if pieces:
                p.setdefault("output_chars", len(output))
                p["output_chunks"] = len(pieces)
            terminal.insert_command(c, terminal.TerminalCommandRequest.model_validate(p), via="export")
            for i, text in enumerate(pieces):
                terminal.insert_output(c, terminal.TerminalOutputRequest(
                    session_id=session_id, client_id=client_id, seq=i, text=text))
            return True
        if kind == "proctor":
            ev = proctor.ProctorEventRequest.model_validate(p)
            if ev.kind not in proctor._VALID_KINDS:
                return False
            proctor.insert_event(c, session_id, ev.kind, ev.detail, ev.away_ms,
                                 ev.client_id, ev.client_at, via="export")
            return True
        if kind == "paste":
            proctor.insert_paste(c, session_id, proctor.PasteRequest.model_validate(p), via="export")
            return True
        if kind in ("chat_user", "chat_tutor"):
            mode = c.execute("SELECT mode FROM sessions WHERE id = ?", (session_id,)).fetchone()["mode"]
            c.execute(
                "INSERT INTO messages (session_id, role, body, mode_at_time, via) VALUES (?, ?, ?, ?, 'export')",
                (session_id, "user" if kind == "chat_user" else "assistant", p.get("text") or "", mode),
            )
            return True
    except ValidationError:
        return False
    return False


@router.post("/trace/verify")
def verify_trace(req: VerifyRequest, teacher: dict = Depends(deps.require_teacher)):
    """Check a student's exported trace (CSV from the plugin's "Export my log")
    for edits, and say which rows the server never received. With
    import_missing, store those rows (only rows whose signature checks out)."""
    if len(req.csv.encode("utf-8", "ignore")) > trace.MAX_CSV_BYTES:
        raise HTTPException(413, "The file is too large.")
    try:
        rows = trace.parse(req.csv)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception:
        raise HTTPException(422, "Couldn't read the file as CSV.")

    with db.conn() as c:
        def key_for(session_id):
            r = c.execute("SELECT trace_key FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return r["trace_key"] if r else None

        result = trace.verify(rows, key_for)
        session_id = result.get("session_id")
        student = None
        if session_id:
            u = c.execute("SELECT u.username FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
                          (session_id,)).fetchone()
            student = u["username"] if u else None

        imported = missing = 0
        out_rows = []
        for r in result["rows"]:
            p = r.pop("payload") or {}
            r["summary"] = _summary(r["kind"], p)
            r["on_server"] = None
            r["imported"] = False
            if r["valid"] and session_id:
                r["on_server"] = _on_server(c, session_id, r["kind"], r["client_id"], p)
                if r["on_server"] is False:
                    missing += 1
                    if req.import_missing and _import(c, session_id, r["kind"], r["client_id"], r["at_utc"], p):
                        r["imported"] = True
                        imported += 1
            out_rows.append(r)

    result.update(rows=out_rows, student=student, missing_on_server=missing, imported=imported)
    return result
