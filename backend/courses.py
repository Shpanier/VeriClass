"""Courses: which students see which exercises.

A course has members (students), the exercises it offers, and a default
exercise. After logging in, a student picks one of their courses, then one of
the exercises that course offers; the default is preselected. With one course
and one exercise there is nothing to pick, so the clients skip the picker.

Students who are in no course at all get the global active exercise, as before
courses existed (exercises.active()). Teachers may open any exercise, to try it.
"""
import datetime
import re
from typing import Any, Optional

from backend import db, exercises

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CourseError(Exception):
    """A request about courses that can't be done. `status` is the HTTP code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _exercise_entry(exercise_id: str) -> Optional[dict[str, Any]]:
    try:
        ex = exercises.get(exercise_id)
    except KeyError:
        return None  # removed since the course was set up
    return {"exercise_id": ex["exercise_id"], "title_en": ex["title_en"], "title_he": ex.get("title_he")}


def _rows(c, course_id: Optional[str] = None) -> list[dict[str, Any]]:
    where, args = ("WHERE course_id = ?", (course_id,)) if course_id else ("", ())
    out = []
    for r in c.execute(f"SELECT course_id, name, default_exercise FROM courses {where} ORDER BY name", args):
        cid = r["course_id"]
        ex_ids = [x["exercise_id"] for x in c.execute(
            "SELECT exercise_id FROM course_exercises WHERE course_id = ? ORDER BY exercise_id", (cid,))]
        members = [x["user_id"] for x in c.execute(
            "SELECT user_id FROM course_members WHERE course_id = ? ORDER BY user_id", (cid,))]
        out.append({"course_id": cid, "name": r["name"], "default_exercise": r["default_exercise"],
                    "exercises": ex_ids, "members": members})
    return out


def all_courses() -> list[dict[str, Any]]:
    """Every course with its exercise ids and member ids (the teacher's view)."""
    with db.conn() as c:
        return _rows(c)


def get(course_id: str) -> Optional[dict[str, Any]]:
    with db.conn() as c:
        rows = _rows(c, course_id)
    return rows[0] if rows else None


def for_user(user_id: int, role: str) -> list[dict[str, Any]]:
    """The courses this user can open, each with the exercises it offers (only
    ones that still exist) and its default. Courses with no exercise are left
    out: there is nothing to open. Teachers get every course."""
    with db.conn() as c:
        if role == "teacher":
            rows = _rows(c)
        else:
            mine = {r["course_id"] for r in c.execute(
                "SELECT course_id FROM course_members WHERE user_id = ?", (user_id,))}
            rows = [r for r in _rows(c) if r["course_id"] in mine]
    out = []
    for r in rows:
        offered = [e for e in map(_exercise_entry, r["exercises"]) if e]
        if not offered:
            continue
        ids = [e["exercise_id"] for e in offered]
        default = r["default_exercise"] if r["default_exercise"] in ids else ids[0]
        # A meeting today: its exercise is preselected, and the plugin (0.4.3+)
        # opens it without asking when this is the student's only course.
        today = today_exercise(r["course_id"])
        today = today if today in ids else None
        out.append({"course_id": r["course_id"], "name": r["name"],
                    "default_exercise": today or default, "exercises": offered,
                    "today_exercise": today})
    return out


def resolve(user: dict, course_id: Optional[str], exercise_id: Optional[str]) -> tuple[Optional[str], dict]:
    """Which (course, exercise) a new session opens. Missing choices are filled
    in when there is only one possibility (or from the course's default), so a
    client that doesn't know about courses still works for a student with one
    course. Raises CourseError when the choice isn't allowed or is ambiguous."""
    if user["role"] == "teacher":
        if exercise_id:
            return course_id, _exercise(exercise_id)
        if course_id:
            course = next((c for c in for_user(user["id"], "teacher") if c["course_id"] == course_id), None)
            if course is None:
                raise CourseError(404, f"Unknown course '{course_id}'.")
            return course_id, _exercise(course["default_exercise"])
        return None, exercises.active() or exercises.first()

    mine = for_user(user["id"], "student")
    if not mine:
        # No courses set up for this student: the global active exercise, as before.
        active = exercises.active()
        if active is None:
            raise CourseError(403, "No exercise is open right now. Ask your teacher.")
        if exercise_id and exercise_id != active["exercise_id"]:
            raise CourseError(403, "That exercise isn't open for you.")
        return None, active

    if course_id is None:
        if len(mine) > 1:
            raise CourseError(400, "Choose a course first.")
        course = mine[0]
    else:
        course = next((c for c in mine if c["course_id"] == course_id), None)
        if course is None:
            raise CourseError(403, "You are not in that course.")

    offered = [e["exercise_id"] for e in course["exercises"]]
    if exercise_id is None:
        exercise_id = course["default_exercise"]
    elif exercise_id not in offered:
        raise CourseError(403, "That exercise isn't open in this course.")
    return course["course_id"], _exercise(exercise_id)


def _exercise(exercise_id: str) -> dict:
    try:
        return exercises.get(exercise_id)
    except KeyError:
        raise CourseError(404, f"Unknown exercise '{exercise_id}'.")


# --- teacher edits ------------------------------------------------------------


def create(course_id: str, name: str) -> dict[str, Any]:
    course_id, name = course_id.strip(), name.strip()
    if not _ID_RE.match(course_id):
        raise CourseError(400, "A course id uses lowercase letters, digits and hyphens, e.g. devops-2026.")
    if not name:
        raise CourseError(400, "Give the course a name.")
    with db.conn() as c:
        if c.execute("SELECT 1 FROM courses WHERE course_id = ?", (course_id,)).fetchone():
            raise CourseError(409, f"A course '{course_id}' already exists.")
        c.execute("INSERT INTO courses (course_id, name) VALUES (?, ?)", (course_id, name))
    return get(course_id)


def update(course_id: str, name: str, exercise_ids: list[str], default_exercise: Optional[str],
           member_ids: list[int]) -> dict[str, Any]:
    """Replace a course's name, offered exercises, default and members."""
    name = name.strip()
    if not name:
        raise CourseError(400, "Give the course a name.")
    exercise_ids = list(dict.fromkeys(exercise_ids))
    unknown = [e for e in exercise_ids if _exercise_entry(e) is None]
    if unknown:
        raise CourseError(400, f"Unknown exercise: {', '.join(unknown)}.")
    if exercise_ids and default_exercise not in exercise_ids:
        raise CourseError(400, "The default exercise must be one of the course's exercises.")
    if not exercise_ids:
        default_exercise = None
    member_ids = list(dict.fromkeys(member_ids))
    with db.conn() as c:
        if not c.execute("SELECT 1 FROM courses WHERE course_id = ?", (course_id,)).fetchone():
            raise CourseError(404, f"Unknown course '{course_id}'.")
        if member_ids:
            marks = ",".join("?" * len(member_ids))
            found = {r["id"] for r in c.execute(f"SELECT id FROM users WHERE id IN ({marks})", member_ids)}
            missing = [str(m) for m in member_ids if m not in found]
            if missing:
                raise CourseError(400, f"Unknown user id: {', '.join(missing)}.")
        c.execute("UPDATE courses SET name = ?, default_exercise = ? WHERE course_id = ?",
                  (name, default_exercise, course_id))
        c.execute("DELETE FROM course_exercises WHERE course_id = ?", (course_id,))
        c.executemany("INSERT INTO course_exercises (course_id, exercise_id) VALUES (?, ?)",
                      [(course_id, e) for e in exercise_ids])
        c.execute("DELETE FROM course_members WHERE course_id = ?", (course_id,))
        c.executemany("INSERT INTO course_members (course_id, user_id) VALUES (?, ?)",
                      [(course_id, m) for m in member_ids])
    return get(course_id)


def delete(course_id: str) -> None:
    """Remove a course. Its students keep their accounts and past sessions."""
    with db.conn() as c:
        if not c.execute("SELECT 1 FROM courses WHERE course_id = ?", (course_id,)).fetchone():
            raise CourseError(404, f"Unknown course '{course_id}'.")
        c.execute("DELETE FROM course_exercises WHERE course_id = ?", (course_id,))
        c.execute("DELETE FROM course_members WHERE course_id = ?", (course_id,))
        c.execute("DELETE FROM course_meetings WHERE course_id = ?", (course_id,))
        c.execute("DELETE FROM courses WHERE course_id = ?", (course_id,))


# --- meetings and attendance --------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _today() -> str:
    """The server's local date (the lecturer's machine, so the class's date)."""
    return datetime.date.today().isoformat()


def today_exercise(course_id: str) -> Optional[str]:
    with db.conn() as c:
        row = c.execute(
            "SELECT exercise_id FROM course_meetings WHERE course_id = ? AND meeting_date = ? "
            "ORDER BY id DESC LIMIT 1", (course_id, _today()),
        ).fetchone()
    return row["exercise_id"] if row else None


def meetings(course_id: str) -> list[dict[str, Any]]:
    """The course's meetings, oldest first, each with how many students came."""
    with db.conn() as c:
        if not c.execute("SELECT 1 FROM courses WHERE course_id = ?", (course_id,)).fetchone():
            raise CourseError(404, f"Unknown course '{course_id}'.")
        members = c.execute("SELECT COUNT(*) AS n FROM course_members WHERE course_id = ?",
                            (course_id,)).fetchone()["n"]
        rows = [dict(r) for r in c.execute(
            "SELECT id, course_id, meeting_date, exercise_id, title FROM course_meetings "
            "WHERE course_id = ? ORDER BY meeting_date, id", (course_id,))]
    for m in rows:
        m["members"] = members
        m["attended"] = sum(1 for r in attendance(m["id"])["rows"] if r["attended"])
        entry = _exercise_entry(m["exercise_id"])
        m["exercise_title"] = entry["title_en"] if entry else None
    return rows


def add_meeting(course_id: str, meeting_date: str, exercise_id: str, title: Optional[str] = None) -> dict[str, Any]:
    """A meeting on [meeting_date] with [exercise_id]; the course starts offering
    the exercise if it didn't."""
    if not _DATE_RE.match(meeting_date or ""):
        raise CourseError(400, "The date must look like 2026-11-05.")
    try:
        datetime.date.fromisoformat(meeting_date)
    except ValueError:
        raise CourseError(400, f"There is no date {meeting_date}.")
    if _exercise_entry(exercise_id) is None:
        raise CourseError(400, f"Unknown exercise '{exercise_id}'.")
    with db.conn() as c:
        if not c.execute("SELECT 1 FROM courses WHERE course_id = ?", (course_id,)).fetchone():
            raise CourseError(404, f"Unknown course '{course_id}'.")
        c.execute("INSERT OR IGNORE INTO course_exercises (course_id, exercise_id) VALUES (?, ?)",
                  (course_id, exercise_id))
        c.execute("UPDATE courses SET default_exercise = COALESCE(default_exercise, ?) WHERE course_id = ?",
                  (exercise_id, course_id))
        mid = c.execute(
            "INSERT INTO course_meetings (course_id, meeting_date, exercise_id, title) VALUES (?, ?, ?, ?)",
            (course_id, meeting_date, exercise_id, (title or "").strip() or None),
        ).lastrowid
    return next(m for m in meetings(course_id) if m["id"] == mid)


def delete_meeting(meeting_id: int) -> None:
    with db.conn() as c:
        if c.execute("DELETE FROM course_meetings WHERE id = ?", (meeting_id,)).rowcount == 0:
            raise CourseError(404, "Unknown meeting.")


def attendance(meeting_id: int) -> dict[str, Any]:
    """Each member of the meeting's course: whether they opened the meeting's
    exercise that day, when, and how far they got."""
    with db.conn() as c:
        m = c.execute("SELECT * FROM course_meetings WHERE id = ?", (meeting_id,)).fetchone()
        if m is None:
            raise CourseError(404, "Unknown meeting.")
        m = dict(m)
        rows = []
        for u in c.execute(
            "SELECT u.id, u.username, u.email, u.group_name FROM course_members cm JOIN users u ON u.id = cm.user_id "
            "WHERE cm.course_id = ? ORDER BY u.username", (m["course_id"],),
        ).fetchall():
            ses = c.execute(
                "SELECT id, started_at, last_active_at FROM sessions WHERE user_id = ? AND exercise = ? "
                "AND (date(started_at, 'localtime') = ? OR date(last_active_at, 'localtime') = ?)",
                (u["id"], m["exercise_id"], m["meeting_date"], m["meeting_date"]),
            ).fetchall()
            ids = [s["id"] for s in ses]
            marks = ",".join("?" * len(ids))
            questions = approved = submissions = 0
            if ids:
                questions = c.execute(
                    f"SELECT COUNT(*) AS n FROM messages WHERE role = 'user' AND session_id IN ({marks}) "
                    "AND date(created_at, 'localtime') = ?", (*ids, m["meeting_date"])).fetchone()["n"]
                approved = c.execute(
                    f"SELECT COUNT(DISTINCT step) AS n FROM step_checks WHERE status = 'approved' "
                    f"AND session_id IN ({marks})", ids).fetchone()["n"]
                submissions = c.execute(
                    f"SELECT COUNT(*) AS n FROM step_checks WHERE session_id IN ({marks})", ids).fetchone()["n"]
            rows.append({
                "user_id": u["id"], "username": u["username"], "email": u["email"], "group": u["group_name"],
                "attended": bool(ses),
                "first_seen": min((s["started_at"] for s in ses), default=None),
                "last_seen": max((s["last_active_at"] for s in ses), default=None),
                "messages": questions, "steps_approved": approved, "step_submissions": submissions,
            })
    return {"meeting": m, "rows": rows,
            "counts": {"members": len(rows), "attended": sum(r["attended"] for r in rows)}}


def add_members(course_id: str, user_ids: list[int]) -> None:
    """Add users to a course, keeping the members it already has."""
    with db.conn() as c:
        if not c.execute("SELECT 1 FROM courses WHERE course_id = ?", (course_id,)).fetchone():
            raise CourseError(404, f"Unknown course '{course_id}'.")
        c.executemany("INSERT OR IGNORE INTO course_members (course_id, user_id) VALUES (?, ?)",
                      [(course_id, u) for u in user_ids])
