import asyncio
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend import auth, db, exercises, student_llm
from backend.agents import tutor
from backend.prompts import student_system_prompt
from backend.routes import review as review_mod

REVIEW_TIMEOUT_SECONDS = 600  # how long the student request waits for the teacher

log = logging.getLogger("oslab.ask")

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
async def ask(req: AskRequest, authorization: str = Header(None)):
    _user_or_401(authorization)
    if any(p in req.message.lower() for p in _DENYLIST_PHRASES):
        raise HTTPException(400, "Request looks like prompt injection — refused.")

    with db.conn() as c:
        s = c.execute(
            "SELECT exercise, mode, variant FROM sessions WHERE id = ?", (req.session_id,)
        ).fetchone()
        if not s:
            raise HTTPException(404, "Unknown session")
        history = c.execute(
            "SELECT role, body FROM messages WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT 20",
            (req.session_id,),
        ).fetchall()

    ex = exercises.get(s["exercise"])
    variant = exercises.variant(s["exercise"], s["variant"])
    sys_prompt = student_system_prompt(ex, variant, s["mode"])
    msgs = [{"role": h["role"], "body": h["body"]} for h in reversed(history)]
    msgs = [{"role": m["role"], "content": m["body"]} for m in msgs]
    msgs.append({"role": "user", "content": req.message})

    with db.conn() as c:
        c.execute(
            "INSERT INTO messages (session_id, role, body, mode_at_time) VALUES (?, ?, ?, ?)",
            (req.session_id, "user", req.message, s["mode"]),
        )

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
            log.warning("Student LLM (gemini) HTTP %s: %s",
                        e.response.status_code if e.response else "?", detail)
            yield f"\n\n_⚠️ Student LLM (gemini) error: {detail or e}_\n"
        except httpx.RequestError as e:
            log.warning("Student LLM (gemini) unreachable: %s", e)
            yield "\n\n_⚠️ Student LLM (gemini) unreachable. Check network / GEMINI_API_KEY._\n"
        finally:
            with db.conn() as c:
                c.execute(
                    "INSERT INTO messages (session_id, role, body, mode_at_time) VALUES (?, ?, ?, ?)",
                    (req.session_id, "assistant", "".join(collected), s["mode"]),
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
        variants = await tutor.generate_variants(sys_prompt, req.session_id, req.message)
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


def _user_or_401(authorization: Optional[str]) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    user_id = auth.user_id_for_token(authorization.removeprefix("Bearer ").strip())
    if user_id is None:
        raise HTTPException(401, "Invalid token")
    return user_id
