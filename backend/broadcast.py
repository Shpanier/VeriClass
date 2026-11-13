"""A note from the teacher to the whole class.

Sent to every student active on an exercise (by default in the last
BROADCAST_ACTIVE_MINUTES minutes, 30, the same window the dashboard's live view
uses) in the course it concerns; no course (None or '') means the students
outside every course, as everywhere else in the dashboard. Students only: not
a teacher's own test sessions, and not the student who asked (none of their
sessions), who got the answer itself. The note goes into each session's chat
transcript as a server entry (backend/transcript.py), so the student chat and
the IDE plugin show it at once if they are open, or after the next login; and
into the session's messages, so the tutor remembers what the class was told.

Used by the review queue's "send to all students" (routes/review.py), and by
POST /api/broadcast for a free note from the dashboard.
"""
import os
from typing import Any, Optional

from backend import db, exercises, transcript


def active_minutes() -> int:
    try:
        return max(1, int(os.environ.get("BROADCAST_ACTIVE_MINUTES", "30")))
    except ValueError:
        return 30


def recipients(exercise_id: str, course_id: Optional[str] = None,
               exclude_session: Optional[str] = None, minutes: Optional[int] = None) -> list[dict[str, Any]]:
    """The sessions a class note goes to: one per student (their latest session
    on the exercise), active within `minutes`, in `course_id` (None or '':
    students outside every course). `exclude_session`: the asker's session;
    none of that user's sessions gets the note."""
    minutes = minutes or active_minutes()
    where = ["s.exercise = ?", "s.last_active_at >= datetime('now', ?)",
             "COALESCE(s.course_id, '') = ?", "u.role = 'student'"]
    args: list[Any] = [exercise_id, f"-{minutes} minutes", course_id or ""]
    if exclude_session:
        where.append("s.user_id NOT IN (SELECT user_id FROM sessions WHERE id = ?)")
        args.append(exclude_session)
    with db.conn() as c:
        rows = c.execute(
            "SELECT s.id, s.user_id, s.mode, s.exercise, s.course_id FROM sessions s "
            "JOIN users u ON u.id = s.user_id "
            "WHERE " + " AND ".join(where) + " ORDER BY s.last_active_at DESC", args).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["user_id"] in seen:
            continue
        seen.add(r["user_id"])
        out.append(dict(r))
    return out


def send(exercise_id: str, text: str, course_id: Optional[str] = None,
         exclude_session: Optional[str] = None, minutes: Optional[int] = None,
         kind: str = "note") -> dict[str, Any]:
    """Deliver `text` to every recipient. Returns {"sent": n, "skipped": m}:
    skipped = sessions of an exercise that keeps no chat transcript (the note
    can't reach their chat; it is still kept in their messages)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing to send (empty note)")
    try:
        ex = exercises.get(exercise_id)
    except KeyError:
        ex = None
    keep_transcript = transcript.enabled(ex)
    sent = skipped = 0
    for s in recipients(exercise_id, course_id, exclude_session, minutes):
        with db.conn() as c:
            c.execute(
                "INSERT INTO messages (session_id, role, body, mode_at_time, answer_level) "
                "VALUES (?, 'assistant', ?, ?, 'class')",
                (s["id"], text, s["mode"]),
            )
        if keep_transcript:
            transcript.record(s["id"], "tutor", text, kind=kind, origin="server")
            sent += 1
        else:
            skipped += 1
    return {"sent": sent, "skipped": skipped}
