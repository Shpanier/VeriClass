"""Teacher side of step-by-step labs: see answers next to the expected values,
then approve (release the next step) or send back with a note."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import db, deps, exercises, steps

router = APIRouter()


@router.get("/step-checks/pending")
def pending_step_checks(teacher: dict = Depends(deps.require_teacher)):
    try:
        active = exercises.active()
    except Exception:
        active = None
    with db.conn() as c:
        rows = c.execute(
            "SELECT sc.*, u.username, s.exercise FROM step_checks sc "
            "JOIN sessions s ON s.id = sc.session_id JOIN users u ON u.id = s.user_id "
            "WHERE sc.status = 'pending' ORDER BY sc.created_at, sc.id"
        ).fetchall()
    items = []
    for r in rows:
        ex = exercises.get(r["exercise"])
        st = steps.steps_of(ex)
        step = st[r["step"] - 1] if 0 < r["step"] <= len(st) else {}
        items.append({
            "id": r["id"],
            "session_id": r["session_id"],
            "username": r["username"],
            "step": r["step"],
            "total": len(st),
            "title": step.get("title", ""),
            "answer": r["answer"],
            "expected": step.get("expected", ""),
            "created_at": r["created_at"],
        })
    return {"has_steps": bool(steps.steps_of(active)), "items": items}


class Decision(BaseModel):
    action: Literal["approve", "return"]
    note: str = ""


@router.post("/step-checks/{check_id}/decide")
def decide(check_id: int, req: Decision, teacher: dict = Depends(deps.require_teacher)):
    check = steps.get(check_id)
    if not check:
        raise HTTPException(404, "Unknown step check")
    if check["status"] != "pending":
        raise HTTPException(409, "Already decided")
    status = "approved" if req.action == "approve" else "returned"
    with db.conn() as c:
        c.execute(
            "UPDATE step_checks SET status = ?, teacher_note = ?, decided_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (status, req.note.strip() or None, check_id),
        )
    steps.event_for(check_id).set()
    return {"ok": True, "status": status}
