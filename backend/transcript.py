"""A session's chat transcript: everything the student's chat showed and
everything the student wrote, in order, kept on the server.

Its purpose is continuity: a student who closes the browser or restarts the
computer logs in again, gets the same session back (backend/routes/sessions.py,
`resume_minutes`) and sees the whole conversation replayed before the chat
carries on from the same place. Any client can use it; the student chat
(student_app) records every message it shows.

Entries come from two origins:
- 'client': written by the student's chat (POST /api/transcript/{session_id}),
  tagged with that chat's `client` id.
- 'server': written by the server itself: the note that the teacher sent the
  student back to an earlier step (backend/steps.py reset_to), deleted a
  question, or answered one the student no longer waited for (routes/review.py).
An open chat polls GET ...?after=<last id>&exclude_client=<its id> and shows
what it didn't write itself: the server's notes, and what another open chat of
the same session wrote (a second tab, or an earlier chat that was still
waiting for an answer when the student reloaded the page).

Configuration:
- exercise.yaml `chat_history: false` turns recording and replay off for an
  exercise (default on).
- CHAT_HISTORY_REPLAY_MAX (environment, default 400): how many of the latest
  entries a new login replays.
"""
import os
from typing import Any, Optional

from backend import db

AUTHORS = ("student", "tutor", "system")
# What an entry is, so a client can resume sensibly (e.g. a "step" entry with
# its step number tells the chat the step's text is already on screen).
KINDS = ("text", "brief", "step", "output", "result", "quiz", "answer", "note", "reset")
_CONTENT_MAX = 60_000


def replay_max() -> int:
    try:
        return max(1, int(os.environ.get("CHAT_HISTORY_REPLAY_MAX", "400")))
    except ValueError:
        return 400


def enabled(ex: Optional[dict[str, Any]]) -> bool:
    """Does this exercise keep a transcript? (exercise.yaml chat_history, default on)"""
    return (ex or {}).get("chat_history", True) is not False


def record(session_id: str, author: str, content: str, kind: str = "text",
           step: Optional[int] = None, origin: str = "client", client: Optional[str] = None) -> int:
    """Append one entry; returns its id. Raises ValueError for an unknown
    author or kind."""
    if author not in AUTHORS:
        raise ValueError(f"author must be one of {', '.join(AUTHORS)}")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO chat_transcript (session_id, author, kind, step, content, origin, client) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, author, kind, step, (content or "")[:_CONTENT_MAX], origin, client),
        )
        return cur.lastrowid


def entries(session_id: str, after: int = 0, origin: Optional[str] = None,
            limit: Optional[int] = None, exclude_client: Optional[str] = None) -> dict[str, Any]:
    """The session's entries after id `after`, oldest first: the latest `limit`
    of them (default CHAT_HISTORY_REPLAY_MAX), and whether older ones were left out."""
    limit = limit or replay_max()
    where, args = "session_id = ? AND id > ?", [session_id, after]
    if origin:
        where += " AND origin = ?"
        args.append(origin)
    if exclude_client:
        where += " AND (client IS NULL OR client != ?)"
        args.append(exclude_client)
    with db.conn() as c:
        total = c.execute(f"SELECT COUNT(*) AS n FROM chat_transcript WHERE {where}", args).fetchone()["n"]
        rows = c.execute(
            f"SELECT id, author, kind, step, content, origin, created_at FROM chat_transcript "
            f"WHERE {where} ORDER BY id DESC LIMIT ?", [*args, limit]).fetchall()
    return {"entries": [dict(r) for r in reversed(rows)], "truncated": total > len(rows)}


def last_id(session_id: str) -> int:
    with db.conn() as c:
        row = c.execute("SELECT MAX(id) AS m FROM chat_transcript WHERE session_id = ?",
                        (session_id,)).fetchone()
    return row["m"] or 0
