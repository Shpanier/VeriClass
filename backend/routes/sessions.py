import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from backend import auth, db, exercises, variants

router = APIRouter()


class StartSessionRequest(BaseModel):
    exercise_id: Optional[str] = None  # defaults to the active exercise


@router.post("/sessions")
def start_session(req: StartSessionRequest, authorization: str = Header(None)):
    user_id = _user_or_401(authorization)
    exercise = exercises.get(req.exercise_id) if req.exercise_id else exercises.active()

    with db.conn() as c:
        # Resume any session for this (user, exercise) that's still active.
        # Matches the dashboard's 30-min "active" window so a refresh doesn't
        # spawn duplicate rows.
        existing = c.execute(
            """
            SELECT id, mode, variant FROM sessions
            WHERE user_id = ? AND exercise = ?
              AND last_active_at >= datetime('now', '-30 minutes')
            ORDER BY last_active_at DESC LIMIT 1
            """,
            (user_id, exercise["exercise_id"]),
        ).fetchone()

        if existing:
            c.execute(
                "UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?",
                (existing["id"],),
            )
            return {
                "session_id": existing["id"],
                "exercise_id": exercise["exercise_id"],
                "variant": existing["variant"],
                "mode": existing["mode"],
            }

        session_id = str(uuid.uuid4())
        variant_id = variants.assign(exercise["exercise_id"])
        c.execute(
            "INSERT INTO sessions (id, user_id, exercise, mode, variant) VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, exercise["exercise_id"], exercise["default_mode"], variant_id),
        )

    return {
        "session_id": session_id,
        "exercise_id": exercise["exercise_id"],
        "variant": variant_id,
        "mode": exercise["default_mode"],
    }


def _user_or_401(authorization: Optional[str]) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    user_id = auth.user_id_for_token(authorization.removeprefix("Bearer ").strip())
    if user_id is None:
        raise HTTPException(401, "Invalid token")
    return user_id
