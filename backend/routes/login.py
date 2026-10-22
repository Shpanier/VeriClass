from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend import auth, courses, deps

router = APIRouter()


class LoginRequest(BaseModel):
    code: str
    # Required. Plugins before 0.4.0 don't send one: they get a 401 asking to update.
    password: Optional[str] = None


@router.post("/login")
def login(req: LoginRequest, request: Request):
    if not req.password:
        raise HTTPException(
            status_code=401,
            detail="Enter your password too. (No password field? Update the VeriExam plugin.)",
        )
    ip = deps.client_ip(request)
    result = auth.login_with_code(
        req.code.strip().upper(), req.password, ip,
        allow_teacher=not deps.teacher_blocked("teacher", request),
        # The instructor's own machine (dashboard, local student app) is never
        # rate-limited; only tunnelled logins are.
        rate_limit=not deps.is_local_request(request),
    )
    if result and result.get("rate_limited"):
        raise HTTPException(status_code=429, detail="Too many failed logins. Wait 5 minutes and try again.")
    if result and result.get("blocked"):
        raise HTTPException(status_code=403, detail="Instructor login is only allowed from the instructor's computer.")
    if not result:
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    # The courses this user may open, each with the exercises it offers, so the
    # client can let the student pick (or skip the picker when there is one).
    result["courses"] = courses.for_user(result["user_id"], result["role"])
    return result
