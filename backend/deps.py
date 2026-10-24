"""Shared FastAPI auth dependencies.

Every /api route (except /login, /healthz and the non-sensitive /client-config)
authenticates through one of these, so the authorization model lives in exactly
one place:

  current_user       — any valid bearer token (student or teacher)
  require_teacher    — token whose user has role='teacher'
  require_owns_session(session_id, user) — the user owns that session, or is a
                       teacher (teachers may act on any session)

Ownership is enforced in the handler (not as a pure Depends) because the
session_id usually arrives in the request body, which a dependency can't see
without re-reading it.
"""
import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request

from backend import auth, db, packages


def _token_from_header(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    return authorization.removeprefix("Bearer ").strip()


# Teacher accounts work only on the instructor's own machine (the dashboard on
# localhost). Set TEACHER_LOCAL_ONLY=false to allow them over the tunnel, e.g.
# to run veriexam_plugin/publish.sh from another computer.
TEACHER_LOCAL_ONLY = os.environ.get("TEACHER_LOCAL_ONLY", "true").strip().lower() not in ("0", "false", "no", "off")
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
# Proxies/tunnels (ngrok, Cloudflare) add these; the local Vite proxy does not.
_FORWARD_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded", "cf-connecting-ip")


def is_local_request(request: Request) -> bool:
    """True only for a request made on this machine, not relayed by a tunnel.
    A tunnel agent connects from 127.0.0.1 too, so the forwarding headers are
    what tell the two apart."""
    host = request.client.host if request.client else ""
    if host not in _LOOPBACK:
        return False
    return not any(h in request.headers for h in _FORWARD_HEADERS)


def client_ip(request: Request) -> str:
    """The real client address when relayed by a tunnel (otherwise every
    tunnelled student shares 127.0.0.1). The tunnel appends the address it saw,
    so take the LAST X-Forwarded-For hop — earlier hops are client-supplied."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def teacher_blocked(role: str, request: Request) -> bool:
    return TEACHER_LOCAL_ONLY and role == "teacher" and not is_local_request(request)


# The lecturer's own tools on this machine (the MCP server, veriexam_mcp/)
# authenticate with a random key the server keeps in the private data folder,
# readable only by the lecturer's account: no password to store anywhere.
LOCAL_TOKEN_FILE = packages.DATA_DIR / ".local-token"


def ensure_local_token() -> str:
    """Create the local tools' key on first start (mode 600)."""
    if LOCAL_TOKEN_FILE.is_file():
        return LOCAL_TOKEN_FILE.read_text(encoding="utf-8").strip()
    LOCAL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd = os.open(LOCAL_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    return token


def _local_tool_user(request: Request, token: str) -> Optional[dict]:
    """The lecturer, for a request made on this machine with the local key."""
    try:
        expected = LOCAL_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not expected or not is_local_request(request) or not secrets.compare_digest(token, expected):
        return None
    with db.conn() as c:
        row = c.execute("SELECT id, username FROM users WHERE role = 'teacher' ORDER BY id LIMIT 1").fetchone()
    return {"id": row["id"] if row else 0, "username": row["username"] if row else "local tools",
            "role": "teacher", "via": "local-token"}


def current_user(request: Request, authorization: Optional[str] = Header(None),
                 x_veriexam_local_token: Optional[str] = Header(None)) -> dict:
    """Any authenticated user. Returns {id, username, role}."""
    if not authorization and x_veriexam_local_token:
        user = _local_tool_user(request, x_veriexam_local_token.strip())
        if user is None:
            raise HTTPException(401, "Invalid local key (only tools on the lecturer's computer may use it)")
        return user
    user = auth.user_for_token(_token_from_header(authorization))
    if user is None:
        raise HTTPException(401, "Invalid token")
    if teacher_blocked(user.get("role", ""), request):
        raise HTTPException(403, "Instructor access is only allowed from the instructor's computer.")
    return user


def require_teacher(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "teacher":
        raise HTTPException(403, "Teacher access required")
    return user


def is_teacher(user: dict) -> bool:
    return user.get("role") == "teacher"


def require_owns_session(session_id: str, user: dict) -> dict:
    """404 if the session is unknown, 403 if it belongs to another student.
    Teachers pass for any session. Returns the session row."""
    with db.conn() as c:
        row = c.execute(
            "SELECT id, user_id, exercise, mode, variant FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Unknown session")
    if not is_teacher(user) and row["user_id"] != user["id"]:
        raise HTTPException(403, "Not your session")
    return dict(row)


def user_has_variant(user_id: int, exercise: str, variant: str) -> bool:
    """True if the user has a session for this (exercise, variant) — used to
    stop a student from pulling another variant's test inputs/answer key."""
    with db.conn() as c:
        row = c.execute(
            "SELECT 1 FROM sessions WHERE user_id = ? AND exercise = ? AND variant = ?",
            (user_id, exercise, variant),
        ).fetchone()
    return row is not None
