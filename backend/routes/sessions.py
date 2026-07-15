import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend import db, deps, exercises, variants

router = APIRouter()


class StartSessionRequest(BaseModel):
    exercise_id: Optional[str] = None  # defaults to the active exercise


@router.post("/sessions")
def start_session(req: StartSessionRequest, user: dict = Depends(deps.current_user)):
    user_id = user["id"]
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
