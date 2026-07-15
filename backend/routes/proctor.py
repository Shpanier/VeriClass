from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import db, deps

router = APIRouter()

# Events that mean the student left the IDE. The dashboard counts these as
# violations and the students endpoint uses them to decide whether a student is
# currently "away". Kept here as the single source of truth.
ALERT_KINDS = ("focus_lost", "minimized", "fullscreen_exited")

# Every kind the exam client is allowed to report. Anything else is rejected so
# a bug in the client can't pollute the proctor trail.
_VALID_KINDS = ALERT_KINDS + (
    "exam_started",
    "focus_regained",
    "window_restored",
)


class ProctorEventRequest(BaseModel):
    session_id: str
    kind: str
    detail: Optional[str] = None
    away_ms: Optional[int] = None


class HeartbeatRequest(BaseModel):
    session_id: str


def _touch_session(c, session_id: str) -> bool:
    """Bump last_active_at so the student stays visible on the live grid even
    while they're away. Returns False if the session is unknown."""
    cur = c.execute(
        "UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?",
        (session_id,),
    )
    return cur.rowcount > 0


@router.post("/proctor/event")
def record_event(req: ProctorEventRequest, user: dict = Depends(deps.current_user)):
    """The exam client reports a focus/minimize/fullscreen change here.

    Bound to the caller's own session so a student can't forge focus_regained
    to mask a leave, nor inject focus_lost into a classmate's session.
    """
    deps.require_owns_session(req.session_id, user)
    kind = req.kind.strip().lower()
    if kind not in _VALID_KINDS:
        raise HTTPException(422, f"Unknown proctor event kind: {req.kind!r}")
    detail = (req.detail or "").strip()[:500] or None
    away_ms = req.away_ms if (req.away_ms is not None and req.away_ms >= 0) else None

    with db.conn() as c:
        if not _touch_session(c, req.session_id):
            raise HTTPException(404, "Unknown session")
        cur = c.execute(
            "INSERT INTO proctor_events (session_id, kind, detail, away_ms) "
            "VALUES (?, ?, ?, ?)",
            (req.session_id, kind, detail, away_ms),
        )
    return {"ok": True, "id": cur.lastrowid}


@router.post("/proctor/heartbeat")
def heartbeat(req: HeartbeatRequest, user: dict = Depends(deps.current_user)):
    """Cheap keep-alive: keeps a quiet exam student on the live grid without
    writing an event row. Bound to the caller's own session so presence can't
    be spoofed from a script while the real client is closed."""
    deps.require_owns_session(req.session_id, user)
    with db.conn() as c:
        if not _touch_session(c, req.session_id):
            raise HTTPException(404, "Unknown session")
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
    with db.conn() as c:
        if session_id:
            rows = c.execute(
                "SELECT id, session_id, kind, detail, away_ms, created_at "
                "FROM proctor_events WHERE session_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, session_id, kind, detail, away_ms, created_at "
                "FROM proctor_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]
