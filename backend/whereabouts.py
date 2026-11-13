"""Where a student is in the lab, and what happened in their chat just before a
question: the context the teacher needs next to a one-line question in the
review queue ("it doesn't work" means nothing without the step and the last
exchange).

`step_of` reads the lab's own progress records (backend/pacing.py for
class-paced labs, backend/steps.py for labs with teacher sign-off), so the
card says the same as the pacing panel. `before` reads the chat as the
student saw it (backend/transcript.py: steps handed out, pasted outputs,
check results, quiz questions) and, for an exercise that keeps no transcript,
the model turns in `messages`.
"""
from typing import Any, Optional

from backend import db, pacing, steps, transcript

# How many chat entries the card shows before the question, and how long each one is cut to.
RECENT_ENTRIES = 5
ENTRY_CHARS = 400


def _same(a: str, b: str) -> bool:
    return " ".join((a or "").split()).lower() == " ".join((b or "").split()).lower()


def _cut(text: str, n: int = ENTRY_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def step_of(session: dict[str, Any], ex: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The step the session works on, with its status, or None for an
    exercise without steps.

    status: open (working on it) · waiting_teacher (finished every open step,
    the teacher opens the next) · waiting_review (their output didn't match;
    the teacher can let them through) · quiz (answering the step's quiz) ·
    quiz_review (a quiz answer about the step was graded too low and waits
    for the teacher) · waiting_check (wrote "done", waiting for the teacher's approval) ·
    not_started (the first step isn't open yet) · finished (all steps done).
    """
    lab = steps.steps_of(ex)
    if not lab:
        return None
    sid = session["id"]
    total = len(lab)
    if pacing.is_paced(ex):
        st = pacing.state(session, ex)
        cur = st["current"]
        if st["finished"]:
            status = "finished"
        elif st["waiting_review"]:
            status = "waiting_review"
        elif st["quiz_pending"]:
            status = "quiz"
        elif st["quiz_review"]:
            status = "quiz_review"
        elif st["waiting_teacher"]:
            status = "not_started" if cur == 1 else "waiting_teacher"
        else:
            status = "open"
        if status in ("quiz", "quiz_review"):
            # The question (open, or its answer waiting for the teacher) is
            # about a step they finished: usually the last one, but a question
            # approved late (pacing.ask_finished) can be about an earlier one.
            held = pacing.pending_quiz(sid) if status == "quiz" else pacing.held_quiz(sid)
            shown = (held[0]["quiz_step"] if held else None) or max(1, cur - 1)
        else:
            # Not open to them yet: the step they finished last is the one that matters.
            shown = cur if status in ("open", "waiting_review") or cur == 1 else cur - 1
        label = pacing.label(ex, shown)
    else:
        cur = steps.current_step(sid)
        if cur > total:
            status = "finished"
        else:
            with db.conn() as c:
                pending = c.execute(
                    "SELECT 1 FROM step_checks WHERE session_id = ? AND step = ? AND status = 'pending'",
                    (sid, cur)).fetchone() is not None
            status = "waiting_check" if pending else "open"
        shown = cur
        label = str(shown)
    shown = min(shown, total)
    return {
        "n": shown,
        "total": total,
        "label": label,
        "title": lab[shown - 1].get("title") or "",
        "status": status,
    }


def before(session_id: str, ex: Optional[dict[str, Any]], question: str, asked_at: str,
           limit: int = RECENT_ENTRIES) -> dict[str, Any]:
    """The last `limit` chat entries before the question (oldest first), each cut
    to ENTRY_CHARS. The question itself is left out. `source` says where they
    come from: the transcript (the chat as the student saw it) or the messages
    (the model turns) when the exercise keeps no transcript."""
    source = "transcript" if transcript.enabled(ex) else "messages"
    with db.conn() as c:
        if source == "transcript":
            # The chat records the question before it asks the server, so an
            # entry up to a second after the question's row still comes before it.
            rows = c.execute(
                "SELECT author, kind, step, content, created_at FROM chat_transcript "
                "WHERE session_id = ? AND created_at <= datetime(?, '+1 second') "
                "ORDER BY id DESC LIMIT ?", (session_id, asked_at, limit + 1)).fetchall()
            out = [dict(r) for r in rows]
        else:
            rows = c.execute(
                "SELECT role, body AS content, created_at, answer_level FROM messages "
                "WHERE session_id = ? AND trim(body) != '' AND created_at <= ? "
                "ORDER BY id DESC LIMIT ?", (session_id, asked_at, limit + 1)).fetchall()
            out = [{"author": "student" if r["role"] == "user" else "tutor",
                    "kind": "note" if r["answer_level"] == "class" else "text",
                    "step": None, "content": r["content"], "created_at": r["created_at"]}
                   for r in rows]
    # Newest first here: the question is the newest student line, when it is recorded.
    for i, e in enumerate(out):
        if e["author"] == "student" and _same(e["content"], question):
            del out[i]
            break
    out = out[:limit]
    out.reverse()
    for e in out:
        e["content"] = _cut(e["content"])
    return {"source": source, "entries": out}
