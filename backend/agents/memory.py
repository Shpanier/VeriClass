"""Conversation memory for the agents — explicit context threading.

Deterministic and Gemini-only: instead of an embeddings store, we read the
per-session transcript and prior probes straight from SQLite and hand them to
the agent task. Everything that leaves for Gemini is PII-scrubbed first via the
existing `sanitize`.
"""
from backend import db
from backend.sanitize import sanitize


def session_transcript(session_id: str, limit: int = 40) -> str:
    """Recent conversation for a session as '[role] body' lines, oldest first.

    Mirrors the history query in routes/ask.py; returns sanitized text so it is
    safe to send to the cloud model.
    """
    with db.conn() as c:
        rows = c.execute(
            "SELECT role, body FROM messages WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    if not rows:
        return "(no conversation yet)"
    lines = [f"[{r['role']}] {r['body']}" for r in reversed(rows)]
    return sanitize("\n".join(lines))


def prior_probes(session_id: str) -> list[str]:
    """Bodies of probes already sent for this session (any status).

    The probe agent is told to NOT repeat these, so 'Suggest more' yields fresh
    questions instead of the same ones each time.
    """
    with db.conn() as c:
        rows = c.execute(
            "SELECT body FROM probes WHERE session_id = ? ORDER BY sent_at DESC",
            (session_id,),
        ).fetchall()
    return [sanitize(r["body"]) for r in rows]
