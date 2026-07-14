"""Recommended-grade endpoints (teacher-only).

Mirrors the probe grading surface: an auto-computed recommendation the teacher
can trigger on demand, plus a manual override. Correctness comes from the
student's real compile/run; wise-use from the reviewer agent. See
backend/grading/service.py for the blend.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import deps
from backend.grading import service

router = APIRouter()


class RecommendRequest(BaseModel):
    session_id: str
    lang: Literal["en", "he"] = "en"


class OverrideRequest(BaseModel):
    session_id: str
    grade: float


@router.post("/grade/recommend")
async def recommend(req: RecommendRequest, teacher: dict = Depends(deps.require_teacher)):
    """Compute (or recompute) the recommended grade for one session. `lang` sets
    the language of the rationale + signals."""
    try:
        return await service.compute(req.session_id, req.lang)
    except KeyError:
        raise HTTPException(404, "Unknown session")


@router.get("/grade/{session_id}")
def get_grade(session_id: str, teacher: dict = Depends(deps.require_teacher)):
    """The current recommendation for a session, or null if none computed yet."""
    return service.get(session_id)


@router.post("/grade/override")
def override(req: OverrideRequest, teacher: dict = Depends(deps.require_teacher)):
    """Teacher sets the final grade (0-100). A recommendation must exist first."""
    if req.grade < 0 or req.grade > 100:
        raise HTTPException(422, "grade must be between 0 and 100")
    if not service.override(req.session_id, req.grade):
        raise HTTPException(404, "No recommendation for this session yet — compute one first.")
    return {"ok": True}
