"""Teacher-in-the-loop review queue.

Toggle `review_mode` on; every student /ask is held in `pending_reviews` with
four teacher-pickable answers: three Socratic levels (nudge, normal, more) and a
direct one, each in English and Hebrew. The dashboard polls `/api/reviews/pending`,
can have the four drafted again by a stronger model (`/api/reviews/{id}/regenerate`),
and calls `/api/reviews/{id}/select` with the answer it picked (possibly edited,
or the question bank's). The held /ask request then unblocks and streams it back.
"""
import asyncio
import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import bank, db, deps, exercises, prompting, student_llm, textutil
from backend.agents import tutor
from backend.prompts import course_name

router = APIRouter()

LEVELS = ("nudge", "normal", "more", "direct")

# One event per pending review id. The /ask handler awaits the event; the
# teacher's POST sets it. In-memory because uvicorn is single-process; if you
# ever scale out, move this to Redis pub/sub or a DB-poll loop.
_EVENTS: dict[int, asyncio.Event] = {}


def event_for(review_id: int) -> asyncio.Event:
    ev = _EVENTS.get(review_id)
    if ev is None:
        ev = asyncio.Event()
        _EVENTS[review_id] = ev
    return ev


def drop_event(review_id: int) -> None:
    _EVENTS.pop(review_id, None)


def review_mode_enabled() -> bool:
    with db.conn() as c:
        row = c.execute(
            "SELECT value FROM system_settings WHERE key = 'review_mode'"
        ).fetchone()
    return bool(row and row["value"] == "on")


# --- used by /api/ask ------------------------------------------------------

def enqueue(session_id: str, question: str, variants: dict, plain: bool = False) -> int:
    """Store a question with its drafted answers (and its closest question-bank
    entry, if any) for the teacher. Returns the review id."""
    match = bank.match_for_session(session_id, question)
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO pending_reviews(session_id, question, "
            "variant_nudge, variant_normal, variant_more, variant_direct, "
            "variant_nudge_he, variant_normal_he, variant_more_he, variant_direct_he, "
            "model, render_plain, bank_match) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, question,
             *(variants[lvl]["en"] for lvl in LEVELS),
             *(variants[lvl]["he"] for lvl in LEVELS),
             variants.get("model"), int(plain), json.dumps(match, ensure_ascii=False) if match else None),
        )
        return cur.lastrowid


def chosen_text(review_id: int) -> tuple[str, str]:
    """(level, text) the teacher sent: the exact (maybe edited) text, else the
    stored answer in the chosen language."""
    with db.conn() as c:
        row = c.execute("SELECT * FROM pending_reviews WHERE id = ?", (review_id,)).fetchone()
    chosen = row["chosen_level"]
    if row["final_text"]:
        return chosen, row["final_text"]
    suffix = "_he" if row["chosen_lang"] == "he" else ""
    col = f"variant_{chosen}"
    return chosen, (row[col + suffix] if col + suffix in row.keys() else None) or row[col] or ""


def model_of(review_id: int) -> Optional[str]:
    """Who wrote the answer that was sent: the drafting model, or 'bank'."""
    with db.conn() as c:
        row = c.execute("SELECT chosen_level, model FROM pending_reviews WHERE id = ?", (review_id,)).fetchone()
    if row is None:
        return None
    return "bank" if row["chosen_level"] == "bank" else row["model"]


# --- toggle ---------------------------------------------------------------

class ReviewModeRequest(BaseModel):
    enabled: bool


@router.get("/review_mode")
def get_review_mode(teacher: dict = Depends(deps.require_teacher)):
    return {"enabled": review_mode_enabled()}


@router.post("/review_mode")
def set_review_mode(req: ReviewModeRequest, teacher: dict = Depends(deps.require_teacher)):
    value = "on" if req.enabled else "off"
    with db.conn() as c:
        c.execute(
            "INSERT INTO system_settings(key, value) VALUES('review_mode', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (value,),
        )
    return {"enabled": req.enabled}


@router.get("/reviews/config")
def review_config(teacher: dict = Depends(deps.require_teacher)):
    """What the queue's buttons can do: the models a question's answers can be
    drafted again with (CLAUDE_STRONG_MODEL, CLAUDE_BEST_MODEL)."""
    return {"regen_models": student_llm.regen_models()}


# --- pending queue --------------------------------------------------------

_ITEM_SQL = """
    SELECT r.*, u.username, s.exercise AS exercise_id
    FROM pending_reviews r
    JOIN sessions s ON s.id = r.session_id
    JOIN users u    ON u.id = s.user_id
"""


def _item(r) -> dict:
    item = {k: r[k] for k in (
        "id", "session_id", "username", "exercise_id", "question", "created_at",
        "model", "regenerated_at",
        "variant_nudge", "variant_normal", "variant_more", "variant_direct",
        "variant_nudge_he", "variant_normal_he", "variant_more_he", "variant_direct_he",
    )}
    # The language the student wrote in, so the card opens on matching answers.
    item["suggested_lang"] = textutil.detect_lang(r["question"])
    item["bank_match"] = json.loads(r["bank_match"]) if r["bank_match"] else None
    return item


@router.get("/reviews/pending")
def pending_reviews(teacher: dict = Depends(deps.require_teacher)):
    with db.conn() as c:
        rows = c.execute(
            _ITEM_SQL + " WHERE r.status = 'pending' ORDER BY r.created_at ASC"
        ).fetchall()
    return [_item(r) for r in rows]


class SelectRequest(BaseModel):
    # 'bank': the question bank's answer; `text` then carries it.
    chosen: Literal["nudge", "normal", "more", "direct", "bank"]
    lang: Literal["en", "he"] = "en"
    # The exact text to send the student (the teacher-edited box content). When
    # omitted, the stored variant for (chosen, lang) is used as-is.
    text: Optional[str] = None


# Whitelist: (level, lang) -> column. `chosen`/`lang` are already constrained by
# the Literals above; this dict guarantees we only ever name a real column, so
# interpolating `col` into the SQL below is safe (never user-controlled text).
_VARIANT_COL = {
    (lvl, lang): f"variant_{lvl}" + ("_he" if lang == "he" else "")
    for lvl in LEVELS for lang in ("en", "he")
}


@router.post("/reviews/{review_id}/select")
def select_variant(review_id: int, req: SelectRequest, teacher: dict = Depends(deps.require_teacher)):
    col = _VARIANT_COL.get((req.chosen, req.lang))
    with db.conn() as c:
        row = c.execute(
            f"SELECT status, {col or 'NULL'} AS variant FROM pending_reviews WHERE id = ?",
            (review_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Unknown review")
        if row["status"] != "pending":
            raise HTTPException(409, f"Review already {row['status']}")
        # The student receives exactly this text (edited box, or the variant).
        final = (req.text or "").strip() or (row["variant"] or "").strip()
        if not final:
            raise HTTPException(422, "Nothing to send (empty answer)")
        c.execute(
            "UPDATE pending_reviews SET status='answered', chosen_level=?, "
            "chosen_lang=?, final_text=?, answered_at=CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (req.chosen, req.lang, final, review_id),
        )
    event_for(review_id).set()
    return {"ok": True, "chosen": req.chosen, "lang": req.lang}


class RegenerateRequest(BaseModel):
    # 'strong' = CLAUDE_STRONG_MODEL (Sonnet), 'best' = CLAUDE_BEST_MODEL (Opus).
    model: Literal["strong", "best"]


@router.post("/reviews/{review_id}/regenerate")
async def regenerate(review_id: int, req: RegenerateRequest, teacher: dict = Depends(deps.require_teacher)):
    """Draft the four answers again with a stronger model, from the same point
    in the conversation. The student keeps waiting; nothing is sent until the
    teacher picks."""
    model = next((m["model"] for m in student_llm.regen_models() if m["key"] == req.model), None)
    if model is None:
        raise HTTPException(400, "That model isn't configured (ANTHROPIC_API_KEY, "
                                 "CLAUDE_STRONG_MODEL / CLAUDE_BEST_MODEL).")
    with db.conn() as c:
        row = c.execute(
            "SELECT r.status, r.question, r.render_plain, s.id, s.user_id, s.exercise, s.mode, s.variant "
            "FROM pending_reviews r JOIN sessions s ON s.id = r.session_id WHERE r.id = ?",
            (review_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Unknown review")
    if row["status"] != "pending":
        raise HTTPException(409, f"Review already {row['status']}")
    session = {k: row[k] for k in ("id", "user_id", "exercise", "mode", "variant")}
    try:
        variants = await tutor.generate_variants(
            prompting.system_prompt_for(session, bool(row["render_plain"])),
            session["id"], row["question"],
            course=course_name(exercises.get(session["exercise"])), model=model,
        )
    except Exception as e:
        raise HTTPException(502, f"{student_llm.model_label(model)} couldn't draft answers: {e}")
    with db.conn() as c:
        cur = c.execute(
            "UPDATE pending_reviews SET "
            + ", ".join(f"variant_{lvl} = ?, variant_{lvl}_he = ?" for lvl in LEVELS)
            + ", model = ?, regenerated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'pending'",
            (*(x for lvl in LEVELS for x in (variants[lvl]["en"], variants[lvl]["he"])),
             variants.get("model"), review_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "The question was answered or expired meanwhile.")
        item = c.execute(_ITEM_SQL + " WHERE r.id = ?", (review_id,)).fetchone()
    return _item(item)
