"""Teacher side of courses (backend/courses.py) and of user passwords
(backend/passwords.py): the dashboard's Courses tab."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import courses, db, deps, passwords

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


@router.get("/users")
def list_users(teacher: dict = Depends(deps.require_teacher)):
    """Every account, for picking course members. `custom_password` is False
    while the password is still the login code."""
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, username, login_code, role, password_hash IS NOT NULL AS custom_password "
            "FROM users ORDER BY role DESC, username"
        ).fetchall()
        member_of: dict[int, list[str]] = {}
        for r in c.execute("SELECT course_id, user_id FROM course_members ORDER BY course_id"):
            member_of.setdefault(r["user_id"], []).append(r["course_id"])
    return [
        {"id": r["id"], "username": r["username"], "login_code": r["login_code"].lower(),
         "role": r["role"], "custom_password": bool(r["custom_password"]),
         "courses": member_of.get(r["id"], [])}
        for r in rows
    ]


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
