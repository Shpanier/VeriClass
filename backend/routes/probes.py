import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import db, deps, exercises
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


class ProbeOverrideRequest(BaseModel):
    probe_id: int
    grade: int


@router.get("/probes/pending/{session_id}")
def pending(session_id: str, user: dict = Depends(deps.current_user)):
    deps.require_owns_session(session_id, user)
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, body FROM probes WHERE session_id = ? AND status = 'pending'",
            (session_id,),
        ).fetchall()
    return [{"id": r["id"], "body": r["body"]} for r in rows]


@router.post("/probes/answer")
async def answer(req: ProbeAnswerRequest, user: dict = Depends(deps.current_user)):
    with db.conn() as c:
        p = c.execute("SELECT session_id, body FROM probes WHERE id = ?", (req.probe_id,)).fetchone()
        if not p:
            raise HTTPException(404, "Unknown probe")
        s = c.execute(
            "SELECT exercise, variant FROM sessions WHERE id = ?", (p["session_id"],)
        ).fetchone()
    # A student may only answer probes on their own session.
    deps.require_owns_session(p["session_id"], user)
    variant = exercises.variant(s["exercise"], s["variant"])
    # Auto-grading is best-effort: a transient LLM outage must never lose the
    # student's answer or 500 the request. On failure, save with no grade so the
    # teacher can grade it manually (via /probe/override) later.
    try:
        score, why = await grader.grade(p["body"], req.answer, variant["params"])
    except Exception:
        log.exception("auto-grading failed for probe %s; saving ungraded", req.probe_id)
        score, why = None, "Auto-grading is temporarily unavailable — your answer was saved."
    with db.conn() as c:
        c.execute(
            "UPDATE probes SET answer = ?, auto_grade = ?, status = 'answered', "
            "answered_at = CURRENT_TIMESTAMP WHERE id = ?",
            (req.answer, score, req.probe_id),
        )
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
