import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend import db, deps, exercises, steps, student_llm
from backend.agents import tutor
from backend.prompts import course_name, student_system_prompt
from backend.routes import review as review_mod

REVIEW_TIMEOUT_SECONDS = 600  # how long the student request waits for the teacher

log = logging.getLogger("veriexam.ask")

router = APIRouter()


class AskRequest(BaseModel):
    session_id: str
    message: str


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

    with db.conn() as c:
        history = c.execute(
            "SELECT role, body FROM messages WHERE session_id = ? "
            "AND trim(body) != '' "
            "ORDER BY created_at DESC, id DESC LIMIT 20",
            (req.session_id,),
        ).fetchall()

    ex = exercises.get(s["exercise"])
    variant = exercises.variant(s["exercise"], s["variant"])
    sys_prompt = student_system_prompt(ex, variant, s["mode"])
    # Older IDE plugins (Java HTTP client) showed replies as plain text; newer ones
    # announce Markdown support with X-VeriExam-Render.
    plain = ("java" in request.headers.get("user-agent", "").lower()
             and request.headers.get("x-veriexam-render", "").lower() != "markdown")
    if steps.steps_of(ex):
        sys_prompt += "\n\n" + steps.tutor_context(ex, req.session_id, plain)
    msgs = [{"role": h["role"], "body": h["body"]} for h in reversed(history)]
    msgs = [{"role": m["role"], "content": m["body"]} for m in msgs]
    msgs.append({"role": "user", "content": req.message})

    with db.conn() as c:
        c.execute(
            "INSERT INTO messages (session_id, role, body, mode_at_time) VALUES (?, ?, ?, ?)",
            (req.session_id, "user", req.message, s["mode"]),
        )

    # Step-by-step labs: "Done with step N" goes to the teacher, not the LLM; a
    # decision the students haven't seen yet is delivered before anything else.
    if steps.steps_of(ex) and (
        steps.undelivered_decision(req.session_id) or steps.parse_done(req.message) is not None
    ):
        return StreamingResponse(_gen_step(req, s, ex, plain), media_type="text/plain")

    if review_mod.review_mode_enabled():
        return StreamingResponse(
            _gen_review(req, s, sys_prompt, msgs),
            media_type="text/plain",
        )

    async def gen():
        collected = []
        try:
            async for tok in student_llm.stream_chat(sys_prompt, msgs):
                collected.append(tok)
                yield tok
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("error", "")
            except Exception:
                detail = e.response.text[:200] if e.response is not None else ""
            log.warning("Student LLM (%s) HTTP %s: %s", student_llm.NAME,
                        e.response.status_code if e.response else "?", detail)
            yield f"\n\n_⚠️ Student LLM ({student_llm.NAME}) error: {detail or e}_\n"
        except httpx.RequestError as e:
            log.warning("Student LLM (%s) unreachable: %s", student_llm.NAME, e)
            yield f"\n\n_⚠️ Student LLM ({student_llm.NAME}) unreachable. Check network / {student_llm.KEY_ENV}._\n"
        finally:
            reply = "".join(collected)
            with db.conn() as c:
                # Only persist a real reply. Storing an empty assistant turn
                # (transient Gemini error / safety block) poisons the session:
                # it comes back as an empty model part with broken user/model
                # alternation, which Gemini mishandles — the model then answers
                # as if it forgot the conversation.
                if reply.strip():
                    c.execute(
                        "INSERT INTO messages (session_id, role, body, mode_at_time) VALUES (?, ?, ?, ?)",
                        (req.session_id, "assistant", reply, s["mode"]),
                    )
                c.execute(
                    "UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (req.session_id,),
                )

    return StreamingResponse(gen(), media_type="text/plain")


async def _gen_review(req: "AskRequest", s, sys_prompt: str, msgs: list[dict]):
    """Review-mode generator: enqueue 3 variants, wait for teacher pick, stream chosen."""
    # Tell the student something is happening so they don't think it hung.
    yield "🧑‍🏫 _Your teacher is reviewing your question — one moment…_\n\n"

    try:
        variants = await tutor.generate_variants(
            sys_prompt, req.session_id, req.message,
            course=course_name(exercises.get(s["exercise"])),
        )
    except Exception as e:
        log.exception("variant generation failed")
        yield f"_⚠️ Could not generate review options: {e}_\n"
        return

    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO pending_reviews(session_id, question, "
            "variant_nudge, variant_normal, variant_more, "
            "variant_nudge_he, variant_normal_he, variant_more_he) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (req.session_id, req.message,
             variants["nudge"]["en"], variants["normal"]["en"], variants["more"]["en"],
             variants["nudge"]["he"], variants["normal"]["he"], variants["more"]["he"]),
        )
        review_id = cur.lastrowid

    ev = review_mod.event_for(review_id)
    try:
        try:
            await asyncio.wait_for(ev.wait(), timeout=REVIEW_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            with db.conn() as c:
                c.execute(
                    "UPDATE pending_reviews SET status='expired' WHERE id = ? "
                    "AND status='pending'", (review_id,),
                )
            yield "_⚠️ No teacher response in time. Please ping the instructor and try again._\n"
            return

        with db.conn() as c:
            row = c.execute(
                "SELECT chosen_level, chosen_lang, final_text, "
                "variant_nudge, variant_normal, variant_more, "
                "variant_nudge_he, variant_normal_he, variant_more_he "
                "FROM pending_reviews WHERE id = ?", (review_id,),
            ).fetchone()
        chosen = row["chosen_level"]
        # Prefer the exact text the teacher sent (it may be edited and/or Hebrew).
        # Fall back to the stored variant in the chosen language for safety.
        suffix = "_he" if row["chosen_lang"] == "he" else ""
        fallback = row[f"variant_{chosen}{suffix}"] or row[f"variant_{chosen}"]
        text = row["final_text"] or fallback

        # Stream it back in small chunks so the UI animates rather than thudding.
        for word in text.split(" "):
            yield word + " "
            await asyncio.sleep(0.01)

        with db.conn() as c:
            c.execute(
                "INSERT INTO messages (session_id, role, body, mode_at_time, answer_level) "
                "VALUES (?, ?, ?, ?, ?)",
                (req.session_id, "assistant", text, s["mode"], chosen),
            )
            c.execute(
                "UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?",
                (req.session_id,),
            )
    finally:
        review_mod.drop_event(review_id)


STEP_WAIT_SECONDS = 540  # under the plugin's 10-minute read timeout


def _save_reply(session_id: str, mode: str, text: str) -> None:
    with db.conn() as c:
        c.execute(
            "INSERT INTO messages (session_id, role, body, mode_at_time) VALUES (?, ?, ?, ?)",
            (session_id, "assistant", text, mode),
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

    check_id = steps.submit(sid, cur, req.message)
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
