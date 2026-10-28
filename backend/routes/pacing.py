"""Class-paced labs (backend/pacing.py). Students: where they are, and "done
with this step" with the pasted output. Teacher: the class's progress, opening
steps for a course, and approving the quiz questions."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import deps, exercises, pacing

router = APIRouter()


def _paced(exercise_id: str) -> dict:
    try:
        ex = exercises.get(exercise_id)
    except KeyError:
        raise HTTPException(404, "Unknown exercise")
    if not pacing.is_paced(ex):
        raise HTTPException(400, "This exercise is not class-paced (pacing: class).")
    return ex


# --- students -------------------------------------------------------------------------

@router.get("/steps/state/{session_id}")
def step_state(session_id: str, user: dict = Depends(deps.current_user)):
    s = deps.require_owns_session(session_id, user)
    return pacing.state(s, _paced(s["exercise"]))


class FinishRequest(BaseModel):
    session_id: str
    step: int
    output: str = ""
    # Continue although the output lacks something (the teacher sees it).
    force: bool = False


@router.post("/steps/finish")
def finish_step(req: FinishRequest, user: dict = Depends(deps.current_user)):
    s = deps.require_owns_session(req.session_id, user)
    return pacing.finish(s, _paced(s["exercise"]), req.step, req.output, req.force)


# --- the teacher ---------------------------------------------------------------------------

@router.get("/pacing/{exercise_id}")
def overview(exercise_id: str, teacher: dict = Depends(deps.require_teacher)):
    return pacing.overview(_paced(exercise_id))


class ReleaseRequest(BaseModel):
    course_id: Optional[str] = None  # None / "": students outside every course
    released: int


@router.post("/pacing/{exercise_id}/release")
def release(exercise_id: str, req: ReleaseRequest, teacher: dict = Depends(deps.require_teacher)):
    ex = _paced(exercise_id)
    return {"released": pacing.set_released(ex, req.course_id, req.released)}


class QuizRequest(BaseModel):
    approved: bool
    body: Optional[str] = None  # new wording; None keeps the current one


@router.post("/pacing/{exercise_id}/quiz/{key}")
def set_quiz(exercise_id: str, key: str, req: QuizRequest, teacher: dict = Depends(deps.require_teacher)):
    ex = _paced(exercise_id)
    try:
        return pacing.set_quiz(ex, key, req.approved, req.body)
    except KeyError:
        raise HTTPException(404, "Unknown question")
