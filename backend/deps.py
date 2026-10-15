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
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request

from backend import auth, db


def _token_from_header(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    return authorization.removeprefix("Bearer ").strip()


# Teacher accounts work only on the instructor's own machine (the dashboard on
# localhost). Set TEACHER_LOCAL_ONLY=false to allow them over the tunnel, e.g.
# to run oslab_plugin/publish.sh from another computer.
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


def current_user(request: Request, authorization: Optional[str] = Header(None)) -> dict:
    """Any authenticated user. Returns {id, username, role}."""
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
