from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import cloud_llm, db, exercises, student_llm

router = APIRouter()


class ProbeSuggestRequest(BaseModel):
    session_id: str


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
def pending(session_id: str):
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, body FROM probes WHERE session_id = ? AND status = 'pending'",
            (session_id,),
        ).fetchall()
    return [{"id": r["id"], "body": r["body"]} for r in rows]


@router.post("/probes/answer")
async def answer(req: ProbeAnswerRequest):
    with db.conn() as c:
        p = c.execute("SELECT session_id, body FROM probes WHERE id = ?", (req.probe_id,)).fetchone()
        if not p:
            raise HTTPException(404, "Unknown probe")
        s = c.execute(
            "SELECT exercise, variant FROM sessions WHERE id = ?", (p["session_id"],)
        ).fetchone()
    variant = exercises.variant(s["exercise"], s["variant"])
    score, why = await student_llm.grade_answer(p["body"], req.answer, variant["params"])
    with db.conn() as c:
        c.execute(
            "UPDATE probes SET answer = ?, auto_grade = ?, status = 'answered', "
            "answered_at = CURRENT_TIMESTAMP WHERE id = ?",
            (req.answer, score, req.probe_id),
        )
    return {"auto_grade": score, "why": why}


@router.post("/probe/suggest")
async def suggest(req: ProbeSuggestRequest):
    with db.conn() as c:
        s = c.execute(
            "SELECT exercise, variant FROM sessions WHERE id = ?", (req.session_id,)
        ).fetchone()
        if not s:
            raise HTTPException(404, "Unknown session")
        msgs = c.execute(
            "SELECT role, body, created_at FROM messages WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT 10",
            (req.session_id,),
        ).fetchall()

    variant = exercises.variant(s["exercise"], s["variant"])
    recent = "\n".join(f"[{m['role']}] {m['body']}" for m in reversed(msgs))
    ctx = cloud_llm.ProbeContext(
        variant_id=s["variant"],
        variant_params=variant["params"],
        recent_chat=recent,
        latest_code="(not yet wired to file upload)",
        action_log="(not yet wired)",
    )
    suggestions = await cloud_llm.suggest_probes(ctx)
    return [s.__dict__ for s in suggestions]


@router.post("/probe/send")
def send(req: ProbeSendRequest):
    inserted = []
    with db.conn() as c:
        for body in req.bodies:
            cur = c.execute(
                "INSERT INTO probes (session_id, body, source) VALUES (?, ?, ?)",
                (req.session_id, body, req.source),
            )
            inserted.append(cur.lastrowid)
    return {"probe_ids": inserted}


@router.post("/probe/override")
def override(req: ProbeOverrideRequest):
    with db.conn() as c:
        c.execute(
            "UPDATE probes SET override_grade = ? WHERE id = ?",
            (req.grade, req.probe_id),
        )
    return {"ok": True}
