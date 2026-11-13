import asyncio
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend import (
    answer_cache, bank, db, deps, environment, exercises, pacing, prompting, settings, steps, student_llm, textutil, transcript,
)
from backend.routes import review as review_mod

REVIEW_TIMEOUT_SECONDS = 600  # how long the student request waits for the teacher

log = logging.getLogger("vericlass.ask")

router = APIRouter()


class Attachment(BaseModel):
    """What the plugin (0.4.3+) attaches to a step submission ("Done with step N")."""
    filename: Optional[str] = None
    source: Optional[str] = None        # the open editor's file
    console: Optional[str] = None       # the Run console's text
    check_output: Optional[str] = None  # the exercise's check command, run on submit


class AskRequest(BaseModel):
    session_id: str
    message: str
    # "Ask again": answer this (already asked) question with the stronger model.
    reask: bool = False
    # Plugin 0.4.3+: the student's OS, e.g. "Windows 11 amd64" (also sent as a header).
    client_os: Optional[str] = None
    attachment: Optional[Attachment] = None


# Sent with replies that can be asked again; the value is the button's model name.
REASK_HEADER = "X-VeriClass-Reask"
# Sent with a reply that waits for the teacher's review (up to REVIEW_TIMEOUT_SECONDS):
# the student chat stays usable meanwhile instead of showing itself busy.
REVIEW_HEADER = "X-VeriClass-Review"
_REASK_INSTRUCTION = (
    "The student found a shorter answer to this question not detailed enough. Give a "
    "complete, detailed explanation, still following every rule above."
)


_DENYLIST_PHRASES = [
    "ignore previous",
    "ignore the above",
    "you are now",
    "system prompt",
]


@router.post("/ask")
async def ask(req: AskRequest, request: Request, user: dict = Depends(deps.current_user)):
    # 404 unknown / 403 someone else's session — before we touch the LLM.
    s = deps.require_owns_session(req.session_id, user)
    if any(p in req.message.lower() for p in _DENYLIST_PHRASES):
        raise HTTPException(400, "Request looks like prompt injection — refused.")

    ex = exercises.get(s["exercise"])
    environment.remember_os(req.session_id, req.client_os or request.headers.get("x-vericlass-client-os"))
    # Older IDE plugins (Java HTTP client) showed replies as plain text; newer ones
    # announce Markdown support with X-VeriClass-Render.
    plain = ("java" in request.headers.get("user-agent", "").lower()
             and request.headers.get("x-vericlass-render", "").lower() != "markdown")
    sys_prompt = prompting.system_prompt_for(s, plain)
    if req.reask:
        return _reask(req, s, ex, sys_prompt)
    msgs = _history(req.session_id)
    msgs.append({"role": "user", "content": req.message})

    with db.conn() as c:
        c.execute(
            "INSERT INTO messages (session_id, role, body, mode_at_time) VALUES (?, ?, ?, ?)",
            (req.session_id, "user", req.message, s["mode"]),
        )

    # Class-paced labs: a step is finished with the chat's button, not by text.
    if pacing.is_paced(ex) and steps.parse_done(req.message) is not None:
        text = ("כדי לסיים שלב, לחצו על הכפתור «סיימתי» שמתחת לשלב, והדביקו את הפלט שקיבלתם בטרמינל."
                if pacing.hebrew(ex) else
                "To finish a step, click the \"Done\" button under the step and paste the output "
                "you got in the terminal.")
        _save_reply(req.session_id, s["mode"], text)
        return StreamingResponse(_stream(text), media_type="text/plain")

    # Class-paced labs: the current step's output pasted as a message finishes the
    # step, as the "Done" button would (exercise.yaml output_in_chat). A client
    # that asks /api/steps/detect first (the student chat) never gets here with it.
    if pacing.is_paced(ex) and pacing.detect_output(s, ex, req.message)["kind"] == "output":
        r = pacing.finish(s, ex, pacing.state(s, ex)["current"], req.message)
        lbl = pacing.label(ex, r["state"]["current"] - 1) if r["status"] == "done" else ""
        text = ((f"📋 זיהיתי את הפלט של שלב {lbl}, והשלב הושלם." if pacing.hebrew(ex) else
                 f"📋 That's the output of step {lbl}: the step is done.") if r["status"] == "done" else
                ("כדי לסיים שלב, לחצו על «סיימתי» שמתחת לשלב." if pacing.hebrew(ex) else
                 "To finish a step, click \"Done\" under the step."))
        _save_reply(req.session_id, s["mode"], text)
        return StreamingResponse(_stream(text), media_type="text/plain")

    # Step-by-step labs: "Done with step N" goes to the teacher, not the LLM; a
    # decision the students haven't seen yet is delivered before anything else.
    if steps.steps_of(ex) and not pacing.is_paced(ex) and (
        steps.undelivered_decision(req.session_id) or steps.parse_done(req.message) is not None
    ):
        return StreamingResponse(_gen_step(req, s, ex, plain), media_type="text/plain")

    if review_mod.review_mode_enabled():
        return StreamingResponse(
            _gen_review(req, s, sys_prompt, msgs, plain,
                        # A client that shows the session's transcript (X-VeriClass-Transcript: 1,
                        # the student chat) can receive an answer after it stopped waiting.
                        late_ok=request.headers.get("x-vericlass-transcript") == "1"
                        and transcript.enabled(ex)),
            media_type="text/plain", headers={REVIEW_HEADER: "1"},
        )

    # Question bank (BANK_AUTO_ANSWER): a near-identical question gets its ready
    # answer, in the student's language, with no model call.
    if bank.AUTO_ANSWER:
        match = bank.match_for_session(req.session_id, req.message)
        if match and match["score"] >= bank.AUTO_THRESHOLD:
            answer = match["answers"].get("normal") or next(iter(match["answers"].values()))
            text = answer[textutil.detect_lang(req.message)]
            _save_reply(req.session_id, s["mode"], text, model="bank")
            return StreamingResponse(_stream(text), media_type="text/plain")

    async def gen():
        collected = []
        try:
            async for tok in student_llm.stream_chat(sys_prompt, msgs):
                collected.append(tok)
                yield tok
        except (httpx.HTTPStatusError, httpx.RequestError, student_llm.MissingKey) as e:
            yield _llm_error(e, student_llm.NAME, review_mod.hebrew_for(req.message, s["exercise"]))
        else:
            settings.note_llm(True)
        finally:
            # Only persist a real reply. Storing an empty assistant turn
            # (transient Gemini error / safety block) poisons the session:
            # it comes back as an empty model part with broken user/model
            # alternation, which Gemini mishandles — the model then answers
            # as if it forgot the conversation.
            _save_reply(req.session_id, s["mode"], "".join(collected), model=student_llm.MODEL)

    headers = {}
    if student_llm.strong_available():
        headers[REASK_HEADER] = student_llm.model_label(student_llm.STRONG_MODEL)
    return StreamingResponse(gen(), media_type="text/plain", headers=headers)


def _history(session_id: str, before_id: int | None = None) -> list[dict]:
    """The last 20 non-empty turns, oldest first (only those before [before_id])."""
    with db.conn() as c:
        rows = c.execute(
            "SELECT role, body FROM messages WHERE session_id = ? AND trim(body) != '' "
            + ("AND id < ? " if before_id is not None else "")
            + "ORDER BY created_at DESC, id DESC LIMIT 20",
            (session_id, before_id) if before_id is not None else (session_id,),
        ).fetchall()
    return [{"role": r["role"], "content": r["body"]} for r in reversed(rows)]


def _llm_error(e: Exception, name: str, he: bool = False) -> str:
    """The line shown to the student when the LLM call fails. The student is
    told to turn to the lecturer; what went wrong is kept for the lecturer's
    dashboard (settings.note_llm), not shown to the student."""
    if isinstance(e, student_llm.MissingKey):
        why = "No API key is set. Add one in Settings."
    elif isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code if e.response is not None else 0
        try:
            detail = e.response.json().get("error", "")
            if isinstance(detail, dict):
                detail = detail.get("message", "")
        except Exception:
            detail = ""
        if status in (401, 403):
            why = "The provider refused the API key. Check it in Settings."
        elif status == 429:
            why = "The provider's rate or spending limit was reached."
        else:
            why = f"The provider answered with an error ({status}). {str(detail)[:200]}".strip()
    else:
        why = "The provider couldn't be reached. Check this computer's internet connection."
    log.warning("Student LLM (%s): %s (%s)", name, why, type(e).__name__)
    settings.note_llm(False, why)
    return ("\n\n_⚠️ העוזר לא זמין כרגע. ספרו למרצה, ונסו שוב בעוד רגע._\n" if he else
            "\n\n_⚠️ The tutor can't answer right now. Tell your lecturer, then try again in a moment._\n")


def _reask(req: AskRequest, s, ex, sys_prompt: str) -> StreamingResponse:
    """Answer the student's earlier question again with the stronger model, from
    the same point in the conversation (the first answer isn't sent). Served from
    the answer cache when this question was already answered in this context."""
    if not student_llm.strong_available():
        raise HTTPException(400, "Asking again with another model is turned off.")
    # Only what went to the LLM the first time: not past the teacher's review,
    # not a finished lab step (both are offered no "ask again" button either).
    if review_mod.review_mode_enabled():
        raise HTTPException(400, "Your teacher is reviewing answers, so asking again is off.")
    if steps.steps_of(ex) and steps.parse_done(req.message) is not None:
        raise HTTPException(400, "A finished step goes to your teacher, not to a model.")
    with db.conn() as c:
        asked = c.execute(
            "SELECT id FROM messages WHERE session_id = ? AND role = 'user' AND body = ? "
            "ORDER BY id DESC LIMIT 1",
            (req.session_id, req.message),
        ).fetchone()
    if asked is None:
        raise HTTPException(400, "Ask the question first, then ask again.")
    model = student_llm.STRONG_MODEL
    sys_prompt += "\n\n" + _REASK_INSTRUCTION
    msgs = _history(req.session_id, before_id=asked["id"])
    cache_key = answer_cache.key(model, sys_prompt, msgs, req.message)
    msgs.append({"role": "user", "content": req.message})

    async def gen():
        cached = answer_cache.get(cache_key)
        if cached is not None:
            log.info("answer cache hit (%s) for session %s", model, req.session_id)
            _save_reply(req.session_id, s["mode"], cached, model=model, cached=True)
            async for chunk in _stream(cached):
                yield chunk
            return
        collected = []
        complete = False
        try:
            async for tok in student_llm.stream_strong(sys_prompt, msgs):
                collected.append(tok)
                yield tok
            complete = True
        except (httpx.HTTPStatusError, httpx.RequestError, student_llm.MissingKey) as e:
            yield _llm_error(e, model, review_mod.hebrew_for(req.message, s["exercise"]))
        finally:
            reply = "".join(collected)
            _save_reply(req.session_id, s["mode"], reply, model=model)
            # Never cache a reply cut short by an error or the student closing the chat.
            if complete:
                answer_cache.put(cache_key, model, s["exercise"], req.message, reply)

    return StreamingResponse(gen(), media_type="text/plain")


async def _gen_review(req: "AskRequest", s, sys_prompt: str, msgs: list[dict], plain: bool = False,
                      late_ok: bool = False):
    """Review-mode generator: hand the question to the teacher at once, draft
    the answers meanwhile (each shown as soon as it is ready), wait for the
    teacher's pick, stream the chosen text."""
    # Tell the student something is happening so they don't think it hung.
    he = review_mod.hebrew_for(req.message, s["exercise"])
    yield ("🧑‍🏫 _המרצה בודק את השאלה שלכם — רגע…_\n\n" if he
           else "🧑‍🏫 _Your teacher is reviewing your question — one moment…_\n\n")

    review_id = review_mod.enqueue(req.session_id, req.message, plain)
    review_mod.start_drafting(review_id, s, sys_prompt, req.message)
    ev = review_mod.start_waiting(review_id)
    # late_ok: the client shows the transcript, so an answer after the timeout
    # still reaches the student there. Any other client (the IDE plugin) can't
    # get one, so for it a timeout still ends the question.
    try:
        try:
            await asyncio.wait_for(ev.wait(), timeout=REVIEW_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            pass
        # From here on a decision is delivered late (review_mod.deliver_late).
        status = review_mod.stop_waiting(review_id)
        if status == "deleted":
            with db.conn() as c:
                note = c.execute("SELECT final_text FROM pending_reviews WHERE id = ?",
                                 (review_id,)).fetchone()["final_text"]
            yield review_mod.deleted_message(req.message, note, s["exercise"])
            return
        if status != "answered":
            if late_ok:
                yield ("⏳ _המרצה עוד לא ענה. כשיענה, התשובה תופיע כאן, גם אם תסגרו את הצ'אט בינתיים._\n"
                       if he else
                       "⏳ _Your teacher hasn't answered yet. The answer will appear here when they do, "
                       "even if you close the chat meanwhile._\n")
                return
            with db.conn() as c:
                c.execute(
                    "UPDATE pending_reviews SET status='expired', closed_at=CURRENT_TIMESTAMP WHERE id = ? "
                    "AND status='pending'", (review_id,),
                )
            yield "_⚠️ No teacher response in time. Please ping the instructor and try again._\n"
            return

        chosen, text = review_mod.chosen_text(review_id)
        # Save BEFORE streaming: a connection dropped mid-stream (the student
        # closed the IDE, the tunnel blinked) must not lose an answer the teacher
        # already approved. In October 2026 two approved answers were lost that way.
        with db.conn() as c:
            c.execute(
                "INSERT INTO messages (session_id, role, body, mode_at_time, answer_level, model) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (req.session_id, "assistant", text, s["mode"], chosen, review_mod.model_of(review_id)),
            )
            c.execute(
                "UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?",
                (req.session_id,),
            )

        # Stream it back in small chunks so the UI animates rather than thudding.
        for word in text.split(" "):
            yield word + " "
            await asyncio.sleep(0.01)
    finally:
        # The request ends however it ends (the student closed the chat, the
        # connection dropped): the question no longer has anyone waiting.
        review_mod.stop_waiting(review_id)


STEP_WAIT_SECONDS = 540  # under the plugin's 10-minute read timeout


def _save_reply(session_id: str, mode: str, text: str,
                model: str | None = None, cached: bool = False) -> None:
    """Store an assistant turn (skipped when empty) and bump the session."""
    with db.conn() as c:
        if text.strip():
            c.execute(
                "INSERT INTO messages (session_id, role, body, mode_at_time, model, cached) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, "assistant", text, mode, model, int(cached)),
            )
        c.execute(
            "UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,)
        )


async def _stream(text: str):
    for word in text.split(" "):
        yield word + " "
        await asyncio.sleep(0.005)


async def _gen_step(req: "AskRequest", s, ex, plain: bool = False):
    """Hand a finished step to the teacher and wait for the decision."""
    sid = req.session_id
    pending = steps.undelivered_decision(sid)
    if pending:
        text = steps.decision_message(ex, pending, plain)
        steps.mark_delivered(pending["id"])
        _save_reply(sid, s["mode"], text)
        async for chunk in _stream(text):
            yield chunk
        return

    total = len(steps.steps_of(ex))
    cur = steps.current_step(sid)
    said = steps.parse_done(req.message) or cur
    if cur > total:
        text = "You already finished all the steps of this lab. 🎉"
    elif said < cur:
        text = f"Step {said} is already approved. You are now on step {cur}."
    elif said > cur:
        text = (f"You are still on step {cur}. Finish it first, then write "
                f"\"Done with step {cur}\" and your answers.")
    else:
        text = None
    if text:
        _save_reply(sid, s["mode"], text)
        async for chunk in _stream(text):
            yield chunk
        return

    check_id = steps.submit(sid, cur, req.message,
                            req.attachment.model_dump() if req.attachment else None)
    yield (f"📋 Sent to your teacher. Please wait: step {cur + 1 if cur < total else cur} "
           "will appear right here when your teacher approves step "
           f"{cur}. (You can keep working on your code meanwhile.)\n\n")
    try:
        await asyncio.wait_for(steps.event_for(check_id).wait(), timeout=STEP_WAIT_SECONDS)
    except asyncio.TimeoutError:
        text = (f"⏳ Your teacher has not checked step {cur} yet. Keep working, and "
                f"write \"Done with step {cur}\" again in a minute or two.")
        _save_reply(sid, s["mode"], text)
        yield text
        return
    finally:
        steps.drop_event(check_id)

    check = steps.get(check_id)
    if check and not check["delivered"]:
        text = steps.decision_message(ex, check, plain)
        steps.mark_delivered(check_id)
        _save_reply(sid, s["mode"], text)
        async for chunk in _stream(text):
            yield chunk
