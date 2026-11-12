"""Class-paced labs (backend/pacing.py). Students: where they are, and "done
with this step" with the pasted output. Teacher: the class's progress, opening
steps for a course, letting a student past a step or sending their output
back, and approving the quiz questions."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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


@router.post("/steps/finish")
def finish_step(req: FinishRequest, user: dict = Depends(deps.current_user)):
    s = deps.require_owns_session(req.session_id, user)
    return pacing.finish(s, _paced(s["exercise"]), req.step, req.output)


class DetectRequest(BaseModel):
    session_id: str
    text: str


@router.post("/steps/detect")
def detect_output(req: DetectRequest, user: dict = Depends(deps.current_user)):
    """Is a chat message the current step's answer, a question, or should the
    chat ask the student? (exercise.yaml output_in_chat)"""
    s = deps.require_owns_session(req.session_id, user)
    return pacing.detect_output(s, _paced(s["exercise"]), req.text)


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


class LetThroughRequest(BaseModel):
    session_id: str
    step: int


@router.post("/pacing/{exercise_id}/let-through")
def let_through(exercise_id: str, req: LetThroughRequest, teacher: dict = Depends(deps.require_teacher)):
    """Let a student continue although their output for the step didn't match."""
    ex = _paced(exercise_id)
    if not pacing.let_through(ex, req.session_id, req.step):
        raise HTTPException(409, "Nothing of this student waits at that step.")
    return {"ok": True}


class DeclineRequest(BaseModel):
    session_id: str
    step: int
    note: Optional[str] = None  # shown to the student with the request to try again


@router.post("/pacing/{exercise_id}/decline")
def decline(exercise_id: str, req: DeclineRequest, teacher: dict = Depends(deps.require_teacher)):
    """Send a student's non-matching output back: they stay on the step and paste again."""
    ex = _paced(exercise_id)
    if not pacing.decline(ex, req.session_id, req.step, req.note):
        raise HTTPException(409, "Nothing of this student waits at that step.")
    return {"ok": True}


class QuizRequest(BaseModel):
    approved: bool
    body: Optional[str] = None  # new wording; None keeps the current one
    # Also ask it now of this course's students who already finished its step.
    ask_finished: bool = False
    # Withdrawing: also take it back from this course's students who were asked
    # it (each one is told, with their answer, which no longer counts).
    withdraw_asked: bool = False
    course_id: Optional[str] = None  # None / "": students outside every course


@router.post("/pacing/{exercise_id}/quiz/{key}")
def set_quiz(exercise_id: str, key: str, req: QuizRequest, teacher: dict = Depends(deps.require_teacher)):
    ex = _paced(exercise_id)
    try:
        item = pacing.set_quiz(ex, key, req.approved, req.body)
    except KeyError:
        raise HTTPException(404, "Unknown question")
    asked = pacing.ask_finished(ex, key, req.course_id) if req.approved and req.ask_finished else 0
    # Withdrawn: take it back from this course's students who were asked it.
    told = pacing.withdraw_asked(ex, key, req.course_id) if not req.approved and req.withdraw_asked else 0
    return {**item, "asked_now": asked, "withdrawn_now": told}


class AnswerReviewRequest(BaseModel):
    probe_id: int
    action: Literal["approve", "return"]
    note: Optional[str] = None  # the text for the student, sent with the decision
    grade: Optional[int] = Field(default=None, ge=0, le=2)  # on an approve: replaces the grader's


@router.post("/pacing/{exercise_id}/answer-review")
def review_answer(exercise_id: str, req: AnswerReviewRequest, teacher: dict = Depends(deps.require_teacher)):
    """Decide about a quiz answer that waits for the teacher (graded too low,
    exercise.yaml quiz_review): let the student continue, or ask them again."""
    ex = _paced(exercise_id)
    approve = req.action == "approve"
    if not pacing.review_answer(ex, req.probe_id, approve, req.note, req.grade if approve else None):
        raise HTTPException(409, "This answer doesn't wait for a decision.")
    return {"ok": True}
