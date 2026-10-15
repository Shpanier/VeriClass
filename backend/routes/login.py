from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend import auth, deps

router = APIRouter()


class LoginRequest(BaseModel):
    code: str


@router.post("/login")
def login(req: LoginRequest, request: Request):
    ip = deps.client_ip(request)
    result = auth.login_with_code(
        req.code.strip().upper(), ip,
        allow_teacher=not deps.teacher_blocked("teacher", request),
    )
    if result and result.get("blocked"):
        raise HTTPException(status_code=403, detail="Instructor login is only allowed from the instructor's computer.")
    if not result:
        raise HTTPException(status_code=401, detail="Code not found. Ask the instructor for your code.")
    return result
