"""The question the chat asked a student and still waits for: a quiz question
after a step (backend/pacing.py) or one the teacher sent (a probe). Both are
`probes` rows with status 'pending'; the oldest one is the open question.

An open question doesn't lock the chat: the student can still ask the teacher
something meanwhile. So a message while a question is open is either its answer
or a question of the student's own, and the server decides which
(POST /api/probes/classify), by exercise.yaml `answer_in_chat`:
- 'detect' (default): an answer, unless it looks like a question (a question
  mark, a question word, "I don't understand"); then the chat asks the student.
- 'confirm': the chat asks the student about every message.
- 'answer': every message is the answer (the chat as it was before).
In a class-paced lab a teacher's question can be open while a step is: a
message that matches the step's output checks is the step's output, not the
answer (kind 'step'; the chat goes on as it does for a pasted output).
While a question is open, the tutor knows it and never answers it for them.
"""
from typing import Any, Optional

from backend import db, pacing, textutil

ANSWER_IN_CHAT = ("detect", "confirm", "answer")


def answer_in_chat(ex: Optional[dict[str, Any]]) -> str:
    value = (ex or {}).get("answer_in_chat")
    return value if value in ANSWER_IN_CHAT else "detect"


def pending(session_id: str, ex: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """The questions waiting for this student's answer, oldest first. A quiz
    question's step is shown by its label (e.g. "B6")."""
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, body, source, quiz_step FROM probes WHERE session_id = ? AND status = 'pending' "
            "ORDER BY id", (session_id,)).fetchall()
    return [{"id": r["id"], "body": r["body"], "source": r["source"],
             "quiz_step": pacing.label(ex, r["quiz_step"]) if r["quiz_step"] and ex else None}
            for r in rows]


def classify(session: dict[str, Any], ex: Optional[dict[str, Any]], text: str) -> dict[str, Any]:
    """Is `text` the answer to the open question? kind: 'none' (no question is
    open, so it's an ordinary message), 'step' (the open step's output),
    'answer', or 'maybe' (ask the student)."""
    open_q = pending(session["id"], ex)
    mode = answer_in_chat(ex)
    if not open_q or not (text or "").strip():
        return {"kind": "none", "probe": None, "mode": mode}
    if pacing.is_paced(ex):
        out = pacing.detect_output(session, ex, text)
        if out["kind"] == "output" or out.get("matched"):
            return {"kind": "step", "probe": open_q[0], "mode": mode}
    asks = textutil.looks_like_question(text)
    if mode == "answer":
        kind = "answer"
    elif mode == "confirm":
        kind = "maybe"
    else:
        kind = "maybe" if asks else "answer"
    return {"kind": kind, "probe": open_q[0], "mode": mode, "looks_like_question": asks}


def tutor_block(session_id: str) -> str:
    """System-prompt block: the questions the student was asked and hasn't
    answered, so the tutor helps them understand what is asked but doesn't
    answer for them; and the quiz answers that wait for the teacher, which
    the student may have to give again. Empty when there is neither."""
    open_q = pending(session_id)
    # Answered, graded too low, and waiting for the teacher, who may ask again.
    held = pacing.held_quiz(session_id)
    blocks = []
    if open_q:
        lines = "\n".join(f"- {q['body']}" for q in open_q)
        blocks.append(
            "OPEN QUESTIONS: the student was asked these and hasn't answered yet:\n" + lines + "\n"
            "They may ask you about them. Help them understand what is asked (a term, where to "
            "look in their own output), but never answer them, never say what to write, and never "
            "judge or correct a draft answer. Their answer goes to the teacher.")
    if held:
        lines = "\n".join(f"- {q['body']}" for q in held)
        blocks.append(
            "ANSWERS WITH THE TEACHER: the student answered these, and the teacher is reading the "
            "answer and may ask them to answer again:\n" + lines + "\n"
            "Never answer these questions, never say what they should have written, and never "
            "judge their answer. You may explain the ideas of the steps they did.")
    return "\n\n".join(blocks)
