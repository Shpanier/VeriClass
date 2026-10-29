"""Teacher side of step-by-step labs: see answers next to the expected values,
then approve (release the next step) or send back with a note; and send a
student, or a whole course, back to an earlier step."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import db, deps, exercises, pacing, steps

router = APIRouter()


@router.get("/step-checks/pending")
def pending_step_checks(teacher: dict = Depends(deps.require_teacher)):
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
        questions = steps.question_count(step) if step else None
        items.append({
            "id": r["id"],
            "session_id": r["session_id"],
            "username": r["username"],
            "exercise_id": r["exercise"],
            "step": r["step"],
            "total": len(st),
            "title": step.get("title", ""),
            "answer": r["answer"],
            "expected": step.get("expected", ""),
            "created_at": r["created_at"],
            # How many questions the step asks, and roughly how many this answers.
            "questions": questions,
            "answered": steps.answered_count(r["answer"], questions),
            # The student's terminal lines and the step's evidence rules.
            "evidence": steps.evidence(r["session_id"], step),
            # The plugin's attachment: open file, Run console, check output.
            "code": {
                "filename": r["code_filename"],
                "source": r["code_text"],
                "console": r["console_text"],
                "check_output": r["check_output"],
            } if (r["code_text"] or r["console_text"] or r["check_output"]) else None,
        })
    # Show the panel when any exercise students can open has steps: the global
    # active one, or one offered in a course.
    offered = {c["exercise_id"] for c in _offered()}
    has_steps = bool(items) or any(steps.steps_of(ex) for ex in exercises.all()
                                   if ex["exercise_id"] in offered)
    return {"has_steps": has_steps, "items": items}


def _offered() -> list[dict]:
    aid = exercises.active_id() if exercises.all() else None
    rows = [{"exercise_id": aid}] if aid else []
    with db.conn() as c:
        rows += [dict(r) for r in c.execute("SELECT DISTINCT exercise_id FROM course_exercises")]
    return rows


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


# --- going back to an earlier step ---------------------------------------------------

def _reset_note(ex: dict, n: int) -> str:
    label = pacing.label(ex, n)
    if pacing.hebrew(ex):
        return (f"↩️ המרצה החזיר אתכם להתחלה (שלב {label})." if n == 1
                else f"↩️ המרצה החזיר אתכם לשלב {label}. ממשיכים משם.")
    return (f"↩️ Your teacher sent you back to the beginning (step {label})." if n == 1
            else f"↩️ Your teacher sent you back to step {label}. Carry on from there.")


def _step_lab(exercise_id: str) -> dict:
    try:
        ex = exercises.get(exercise_id)
    except KeyError:
        raise HTTPException(404, "Unknown exercise")
    if not steps.steps_of(ex):
        raise HTTPException(400, "This exercise has no steps.")
    return ex


class ResetRequest(BaseModel):
    step: int = 1  # 1 = from the beginning


@router.post("/sessions/{session_id}/reset")
def reset_session(session_id: str, req: ResetRequest, teacher: dict = Depends(deps.require_teacher)):
    """Send one student's session back to step `step`."""
    s = deps.require_owns_session(session_id, teacher)
    ex = _step_lab(s["exercise"])
    return steps.reset_to(session_id, req.step, _reset_note(ex, max(1, req.step)))


class CourseResetRequest(BaseModel):
    step: int = 1
    course_id: Optional[str] = None  # None / "": students outside every course
    # Only these sessions; None = every student of the course in this exercise.
    session_ids: Optional[list[str]] = None


@router.post("/exercises/{exercise_id}/reset")
def reset_course(exercise_id: str, req: CourseResetRequest, teacher: dict = Depends(deps.require_teacher)):
    """Send every student of a course (each one's latest session in this
    exercise) back to step `step`. Students already at or before it stay."""
    ex = _step_lab(exercise_id)
    with db.conn() as c:
        rows = c.execute(
            "SELECT s.id, s.user_id FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.exercise = ? AND COALESCE(s.course_id, '') = ? AND u.role = 'student' "
            "ORDER BY s.last_active_at", (exercise_id, req.course_id or "")).fetchall()
    latest = {r["user_id"]: r["id"] for r in rows}
    ids = list(latest.values())
    if req.session_ids is not None:
        ids = [i for i in ids if i in set(req.session_ids)]
    note = _reset_note(ex, max(1, req.step))
    results = [steps.reset_to(sid, req.step, note) for sid in ids]
    return {"sessions": len(results), "moved": sum(1 for r in results if r["to"] < r["from"]),
            "results": results}
