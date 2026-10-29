import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import db, deps, exercises, open_questions, pacing
from backend.agents import grader, probe

router = APIRouter()
log = logging.getLogger(__name__)


class ProbeSuggestRequest(BaseModel):
    session_id: str
    lang: Literal["en", "he"] = "en"


class ProbeSendRequest(BaseModel):
    session_id: str
    bodies: list[str]
    source: str = "suggested"  # suggested | edited | manual


class ProbeAnswerRequest(BaseModel):
    probe_id: int
    answer: str


class ProbeClassifyRequest(BaseModel):
    session_id: str
    text: str


class ProbeOverrideRequest(BaseModel):
    probe_id: int
    grade: int


def _exercise(s: dict):
    try:
        return exercises.get(s["exercise"])
    except KeyError:
        return None


@router.get("/probes/pending/{session_id}")
def pending(session_id: str, user: dict = Depends(deps.current_user)):
    """The questions waiting for the student's answer, oldest first. source
    'quiz': a class-paced lab's question after a step (quiz_step, shown by its
    label, e.g. "B6")."""
    s = deps.require_owns_session(session_id, user)
    return open_questions.pending(session_id, _exercise(s))


@router.post("/probes/classify")
def classify(req: ProbeClassifyRequest, user: dict = Depends(deps.current_user)):
    """A message the student wrote while a question is open: its answer, a
    question of their own, or unsure (the chat then asks them). exercise.yaml
    answer_in_chat; see backend/open_questions.py."""
    s = deps.require_owns_session(req.session_id, user)
    return open_questions.classify(s, _exercise(s), req.text)


@router.post("/probes/answer")
async def answer(req: ProbeAnswerRequest, user: dict = Depends(deps.current_user)):
    with db.conn() as c:
        p = c.execute("SELECT session_id, body, quiz_key, status FROM probes WHERE id = ?",
                      (req.probe_id,)).fetchone()
        if not p:
            raise HTTPException(404, "Unknown probe")
        s = c.execute(
            "SELECT exercise, variant FROM sessions WHERE id = ?", (p["session_id"],)
        ).fetchone()
    # A student may only answer probes on their own session.
    deps.require_owns_session(p["session_id"], user)
    # Answered meanwhile (another tab), or withdrawn when the teacher reset the student.
    if p["status"] != "pending":
        raise HTTPException(409, f"This question is {p['status']}")
    variant = exercises.variant(s["exercise"], s["variant"])
    # A quiz question is graded against the teacher's model answer.
    reference = pacing.quiz_reference(exercises.get(s["exercise"]), p["quiz_key"]) if p["quiz_key"] else None
    # Auto-grading is best-effort: a transient LLM outage must never lose the
    # student's answer or 500 the request. On failure, save with no grade so the
    # teacher can grade it manually (via /probe/override) later.
    try:
        score, why = await grader.grade(p["body"], req.answer, variant["params"], reference)
    except Exception:
        log.exception("auto-grading failed for probe %s; saving ungraded", req.probe_id)
        score, why = None, "Auto-grading is temporarily unavailable — your answer was saved."
    with db.conn() as c:
        cur = c.execute(
            "UPDATE probes SET answer = ?, auto_grade = ?, status = 'answered', "
            "answered_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'pending'",
            (req.answer, score, req.probe_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "This question was answered or withdrawn meanwhile")
    return {"auto_grade": score, "why": why}


@router.post("/probe/suggest")
async def suggest(req: ProbeSuggestRequest, teacher: dict = Depends(deps.require_teacher)):
    with db.conn() as c:
        s = c.execute(
            "SELECT exercise, variant FROM sessions WHERE id = ?", (req.session_id,)
        ).fetchone()
        if not s:
            raise HTTPException(404, "Unknown session")

    variant = exercises.variant(s["exercise"], s["variant"])
    # The probe agent threads in the full session transcript as memory and is
    # told not to repeat already-sent probes, so suggestions stay grounded and
    # fresh. Language is the teacher's per-request choice.
    suggestions = await probe.suggest_probes(
        req.session_id, s["variant"], variant["params"], req.lang
    )
    return [item.model_dump() for item in suggestions]


@router.post("/probe/send")
def send(req: ProbeSendRequest, teacher: dict = Depends(deps.require_teacher)):
    with db.conn() as c:
        if not c.execute("SELECT 1 FROM sessions WHERE id = ?", (req.session_id,)).fetchone():
            raise HTTPException(404, "Unknown session")
        inserted = []
        for body in req.bodies:
            cur = c.execute(
                "INSERT INTO probes (session_id, body, source) VALUES (?, ?, ?)",
                (req.session_id, body, req.source),
            )
            inserted.append(cur.lastrowid)
    return {"probe_ids": inserted}


@router.post("/probe/override")
def override(req: ProbeOverrideRequest, teacher: dict = Depends(deps.require_teacher)):
    # Grades are 0-2; reject anything else instead of silently storing it.
    if req.grade < 0 or req.grade > 2:
        raise HTTPException(422, "grade must be between 0 and 2")
    with db.conn() as c:
        result = c.execute(
            "UPDATE probes SET override_grade = ? WHERE id = ?",
            (req.grade, req.probe_id),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Unknown probe")
    return {"ok": True}
