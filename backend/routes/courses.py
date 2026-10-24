"""Teacher side of courses (backend/courses.py) and of user passwords
(backend/passwords.py): the dashboard's Courses tab."""
import base64
import binascii
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import courses, db, deps, passwords, roster

router = APIRouter()


def _raise(e: courses.CourseError):
    raise HTTPException(e.status, str(e))


class NewCourse(BaseModel):
    course_id: str
    name: str


class CourseUpdate(BaseModel):
    name: str
    exercises: list[str] = Field(default_factory=list)
    default_exercise: Optional[str] = None
    members: list[int] = Field(default_factory=list)


@router.get("/courses")
def list_courses(teacher: dict = Depends(deps.require_teacher)):
    return courses.all_courses()


@router.post("/courses", status_code=201)
def create_course(req: NewCourse, teacher: dict = Depends(deps.require_teacher)):
    try:
        return courses.create(req.course_id, req.name)
    except courses.CourseError as e:
        _raise(e)


@router.put("/courses/{course_id}")
def update_course(course_id: str, req: CourseUpdate, teacher: dict = Depends(deps.require_teacher)):
    try:
        return courses.update(course_id, req.name, req.exercises, req.default_exercise, req.members)
    except courses.CourseError as e:
        _raise(e)


@router.delete("/courses/{course_id}")
def delete_course(course_id: str, teacher: dict = Depends(deps.require_teacher)):
    try:
        courses.delete(course_id)
    except courses.CourseError as e:
        _raise(e)
    return {"ok": True}


class MeetingRequest(BaseModel):
    date: str            # YYYY-MM-DD
    exercise_id: str
    title: Optional[str] = None


@router.get("/courses/{course_id}/meetings")
def list_meetings(course_id: str, teacher: dict = Depends(deps.require_teacher)):
    try:
        return courses.meetings(course_id)
    except courses.CourseError as e:
        _raise(e)


@router.post("/courses/{course_id}/meetings", status_code=201)
def add_meeting(course_id: str, req: MeetingRequest, teacher: dict = Depends(deps.require_teacher)):
    """On that date the course's students open this exercise (the course
    starts offering it if it didn't)."""
    try:
        return courses.add_meeting(course_id, req.date, req.exercise_id, req.title)
    except courses.CourseError as e:
        _raise(e)


@router.delete("/meetings/{meeting_id}")
def delete_meeting(meeting_id: int, teacher: dict = Depends(deps.require_teacher)):
    try:
        courses.delete_meeting(meeting_id)
    except courses.CourseError as e:
        _raise(e)
    return {"ok": True}


@router.get("/meetings/{meeting_id}/attendance")
def meeting_attendance(meeting_id: int, teacher: dict = Depends(deps.require_teacher)):
    try:
        return courses.attendance(meeting_id)
    except courses.CourseError as e:
        _raise(e)


@router.get("/users")
def list_users(teacher: dict = Depends(deps.require_teacher)):
    """Every account, for picking course members. `custom_password` is False
    while the password is still the login code."""
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, username, login_code, role, password_hash IS NOT NULL AS custom_password, "
            "email, student_id, group_name FROM users ORDER BY role DESC, username"
        ).fetchall()
        member_of: dict[int, list[str]] = {}
        for r in c.execute("SELECT course_id, user_id FROM course_members ORDER BY course_id"):
            member_of.setdefault(r["user_id"], []).append(r["course_id"])
    return [
        {"id": r["id"], "username": r["username"], "login_code": r["login_code"].lower(),
         "role": r["role"], "custom_password": bool(r["custom_password"]),
         "courses": member_of.get(r["id"], []),
         "email": r["email"], "student_id": r["student_id"], "group": r["group_name"]}
        for r in rows
    ]


class ImportRequest(BaseModel):
    # The CSV file's bytes, base64 (so a Hebrew file saved by Excel keeps its encoding).
    content_base64: str
    # For rows without a course column; None: just create the accounts.
    course_id: Optional[str] = None
    dry_run: bool = True


_IMPORT_MAX = 2_000_000


@router.post("/students/import")
def import_students(req: ImportRequest, teacher: dict = Depends(deps.require_teacher)):
    """A student list from CSV (backend/roster.py): preview with dry_run, then
    import. The result lists each row's status and login code, and codes_csv."""
    try:
        data = base64.b64decode(req.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "The file couldn't be read (expected base64).")
    if len(data) > _IMPORT_MAX:
        raise HTTPException(413, "The file is too large (2 MB at most).")
    if req.course_id and courses.get(req.course_id) is None:
        raise HTTPException(404, f"Unknown course '{req.course_id}'.")
    text = roster.decode(data)
    if req.dry_run:
        return roster.plan(text, req.course_id)
    result = roster.apply(text, req.course_id)
    result["codes_csv"] = roster.codes_csv(result["rows"])
    return result


class PasswordRequest(BaseModel):
    # None (or omitted): back to the default, the login code.
    password: Optional[str] = None


@router.post("/users/{user_id}/password")
def set_password(user_id: int, req: PasswordRequest, teacher: dict = Depends(deps.require_teacher)):
    """Set a user's password, or reset it to the login code (password: null)."""
    stored = None
    if req.password is not None:
        problem = passwords.check_new(req.password)
        if problem:
            raise HTTPException(400, problem)
        stored = passwords.hash_password(req.password)
    with db.conn() as c:
        cur = c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (stored, user_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "Unknown user")
    return {"ok": True, "custom_password": stored is not None}
