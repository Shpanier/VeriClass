from fastapi import APIRouter, HTTPException

from backend import db
from backend.routes.proctor import ALERT_KINDS

router = APIRouter()

# Build the "(?, ?, ?)" placeholder list + params once for the alert-count subquery.
_ALERT_PLACEHOLDERS = ", ".join("?" for _ in ALERT_KINDS)


@router.get("/students")
def list_students():
    """Returns one row per active session (last_active_at within 30 min),
    enriched with the exam/proctor signals the dashboard flags on:

      focus_alerts    how many times the student left the IDE
      last_focus_kind the most recent proctor event ('focus_lost', 'minimized',
                      'focus_regained', …) or None
      last_focus_at   when that event happened
      away            True if the student is currently outside the IDE
                      (last event is a leave that wasn't followed by a return)
    """
    with db.conn() as c:
        rows = c.execute(
            f"""
            SELECT s.id AS session_id, u.username, s.exercise, s.variant,
                   s.mode, s.started_at, s.last_active_at,
                   (SELECT COUNT(*) FROM probes p WHERE p.session_id = s.id) AS probe_count,
                   (SELECT COUNT(*) FROM proctor_events e
                      WHERE e.session_id = s.id
                        AND e.kind IN ({_ALERT_PLACEHOLDERS})) AS focus_alerts,
                   (SELECT e.kind FROM proctor_events e
                      WHERE e.session_id = s.id
                      ORDER BY e.id DESC LIMIT 1) AS last_focus_kind,
                   (SELECT e.created_at FROM proctor_events e
                      WHERE e.session_id = s.id
                      ORDER BY e.id DESC LIMIT 1) AS last_focus_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.last_active_at >= datetime('now', '-30 minutes')
            ORDER BY s.last_active_at DESC
            """,
            ALERT_KINDS,
        ).fetchall()

    students = []
    for r in rows:
        d = dict(r)
        d["away"] = d["last_focus_kind"] in ALERT_KINDS
        students.append(d)
    return students


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
