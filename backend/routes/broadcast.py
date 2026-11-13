"""A note from the teacher to every student active on an exercise
(backend/broadcast.py)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import broadcast, deps, exercises

router = APIRouter()


class BroadcastRequest(BaseModel):
    exercise_id: str
    text: str = Field(max_length=20_000)
    course_id: Optional[str] = None   # only that course's students (None / "": students outside every course)
    minutes: Optional[int] = Field(default=None, ge=1, le=24 * 60)  # active within (default BROADCAST_ACTIVE_MINUTES)


@router.get("/broadcast/recipients")
def who(exercise_id: str, course_id: Optional[str] = None, minutes: Optional[int] = None,
        teacher: dict = Depends(deps.require_teacher)):
    """How many students a note would reach now."""
    return {"count": len(broadcast.recipients(exercise_id, course_id, minutes=minutes)),
            "minutes": minutes or broadcast.active_minutes()}


@router.post("/broadcast")
def send(req: BroadcastRequest, teacher: dict = Depends(deps.require_teacher)):
    try:
        exercises.get(req.exercise_id)
    except KeyError:
        raise HTTPException(404, "Unknown exercise")
    try:
        return broadcast.send(req.exercise_id, req.text, req.course_id, minutes=req.minutes)
    except ValueError as e:
        raise HTTPException(422, str(e))
