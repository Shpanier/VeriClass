from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend import auth

router = APIRouter()


class LoginRequest(BaseModel):
    code: str


@router.post("/login")
def login(req: LoginRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    result = auth.login_with_code(req.code.strip().upper(), ip)
    if not result:
        raise HTTPException(status_code=401, detail="Code not found. Ask the instructor for your code.")
    return result
