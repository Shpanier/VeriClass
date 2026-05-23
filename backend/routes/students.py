from fastapi import APIRouter, HTTPException

from backend import db

router = APIRouter()


@router.get("/students")
def list_students():
    """Returns one row per active session (last_active_at within 30 min)."""
    with db.conn() as c:
        rows = c.execute(
            """
            SELECT s.id AS session_id, u.username, s.exercise, s.variant,
                   s.mode, s.started_at, s.last_active_at,
                   (SELECT COUNT(*) FROM probes p WHERE p.session_id = s.id) AS probe_count
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.last_active_at >= datetime('now', '-30 minutes')
            ORDER BY s.last_active_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/students/{session_id}/messages")
def session_messages(session_id: str):
    """Full chat transcript + probes for one student session."""
    with db.conn() as c:
        sess = c.execute(
            """
            SELECT s.id AS session_id, u.username, s.exercise, s.variant, s.mode,
                   s.started_at, s.last_active_at
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()
        if not sess:
            raise HTTPException(404, "Unknown session")
        messages = c.execute(
            "SELECT id, role, body, mode_at_time, created_at FROM messages "
            "WHERE session_id = ? ORDER BY created_at ASC, id ASC",
            (session_id,),
        ).fetchall()
        probes = c.execute(
            "SELECT id, body, status, answer, auto_grade, override_grade, source, "
            "sent_at, answered_at FROM probes WHERE session_id = ? ORDER BY sent_at ASC",
            (session_id,),
        ).fetchall()
    return {
        "session": dict(sess),
        "messages": [dict(m) for m in messages],
        "probes": [dict(p) for p in probes],
    }
