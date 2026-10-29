"""Teacher-in-the-loop review queue.

Toggle `review_mode` on; every student /ask is held in `pending_reviews` with
four teacher-pickable answers: three Socratic levels (nudge, normal, more) and a
direct one, each in English and Hebrew. The dashboard polls `/api/reviews/pending`,
can have the four drafted again by a stronger model (`/api/reviews/{id}/regenerate`),
and calls `/api/reviews/{id}/select` with the answer it picked (possibly edited,
or the question bank's). The held /ask request then unblocks and streams it back.

Keeping the queue in step with the students (who is still waiting for what):
- A question is "waiting" while the student's /ask request is open for it
  (in memory: start_waiting / stop_waiting). It stops waiting when the request
  ends for any reason: an answer, a deletion, the timeout, the student closing
  the chat, the connection dropping, a server restart.
- An answer to a question nobody waits for any more is not lost: it goes into
  the session's messages and transcript (backend/transcript.py), and the
  student's chat shows it when they are back, or at once if it is open.
- The teacher can delete a question (status 'deleted'): a waiting student is
  told at once, one who left finds the note in their chat when they are back
  (unless the teacher chose not to tell them).
- A question asked again by the same session replaces its older copy that
  nobody waits for (status 'replaced'), so the queue has no duplicates.
Status: pending | answered | deleted | replaced | expired (an IDE client that
timed out, which can't receive a late answer).

A question in a language the teacher doesn't read (neither Hebrew nor English,
e.g. Arabic or Russian) comes with a translation: the same model call that
drafts the four answers names the question's language and translates it
(question_lang, question_translation). The setting `review_translate_to`
(system_settings, GET/POST /api/reviews/config) picks the language: 'he'
(default), 'en', or 'off'.
"""
import asyncio
import json
import re
import threading
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import bank, db, deps, exercises, prompting, student_llm, textutil, transcript
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


# --- who is waiting --------------------------------------------------------
# The teacher's decision and the student's request ending can happen at the same
# moment (the decision route runs in a worker thread). Both go through _LOCK, so
# exactly one side delivers: the waiting request, or the late delivery.
_WAITING: dict[int, asyncio.AbstractEventLoop] = {}
_LOCK = threading.Lock()


def start_waiting(review_id: int) -> asyncio.Event:
    """Call from the waiting request (in the event loop)."""
    with _LOCK:
        _WAITING[review_id] = asyncio.get_running_loop()
        return event_for(review_id)


def stop_waiting(review_id: int) -> str:
    """The request for this question ends. Returns the question's status at
    that moment; after this, a decision is delivered late (deliver_late)."""
    with _LOCK:
        _WAITING.pop(review_id, None)
        drop_event(review_id)
        with db.conn() as c:
            row = c.execute("SELECT status FROM pending_reviews WHERE id = ?", (review_id,)).fetchone()
    return row["status"] if row else "deleted"


def is_waiting(review_id: int) -> bool:
    return review_id in _WAITING


def _decide(review_id: int, sql: str, args: tuple) -> bool:
    """Apply the teacher's decision to a pending question. True when a request
    waits for it (it delivers the decision); False when it must be delivered
    late. Raises 409 when the question was decided meanwhile."""
    with _LOCK:
        with db.conn() as c:
            cur = c.execute(sql + " WHERE id = ? AND status = 'pending'", (*args, review_id))
            if cur.rowcount == 0:
                raise HTTPException(409, "The question was answered or closed meanwhile.")
        loop = _WAITING.get(review_id)
        if loop is not None:
            # The decision routes run in a worker thread; wake the request in its own loop.
            loop.call_soon_threadsafe(event_for(review_id).set)
            return True
    return False


def _row(review_id: int):
    with db.conn() as c:
        return c.execute(
            "SELECT r.*, s.exercise, s.mode FROM pending_reviews r JOIN sessions s ON s.id = r.session_id "
            "WHERE r.id = ?", (review_id,)).fetchone()


def _quote(question: str) -> str:
    q = " ".join((question or "").split())
    return q if len(q) <= 120 else q[:117] + "…"


def hebrew_for(question: str, exercise_id: Optional[str] = None) -> bool:
    """Write the chat's own lines to this student in Hebrew? When the exercise
    is in Hebrew (its brief, what students read: the chat around them is
    Hebrew) or the question is; English only when both are English."""
    if textutil.detect_lang(question or "") == "he":
        return True
    try:
        ex = exercises.get(exercise_id) if exercise_id else None
    except KeyError:
        ex = None
    return bool(ex) and textutil.has_hebrew(ex.get("brief_md") or "")


def deliver_late(review_id: int) -> None:
    """The teacher answered a question nobody waits for any more: keep the
    answer in the session's messages, and put it in the transcript so the
    student's chat shows it (now if it is open, else after the next login)."""
    r = _row(review_id)
    chosen, text = chosen_text(review_id)
    with db.conn() as c:
        c.execute(
            "INSERT INTO messages (session_id, role, body, mode_at_time, answer_level, model) "
            "VALUES (?, 'assistant', ?, ?, ?, ?)",
            (r["session_id"], text, r["mode"], chosen, model_of(review_id)),
        )
    head = (f"🧑‍🏫 **המרצה ענה על השאלה:** «{_quote(r['question'])}»" if hebrew_for(r["question"], r["exercise"])
            else f"🧑‍🏫 **Your teacher answered your question:** “{_quote(r['question'])}”")
    transcript.record(r["session_id"], "tutor", f"{head}\n\n{text}", kind="text", origin="server")


def deleted_message(question: str, note: Optional[str], exercise_id: Optional[str] = None) -> str:
    """What the student reads when the teacher deleted their question."""
    he = hebrew_for(question, exercise_id)
    text = (f"🗑️ המרצה מחק את השאלה «{_quote(question)}», והיא לא תיענה." if he
            else f"🗑️ Your teacher deleted the question “{_quote(question)}”; it won't be answered.")
    if note and note.strip():
        text += f"\n\n> {note.strip()}"
    return text


def looks_like_noise(question: str) -> bool:
    """A question that was most likely sent by mistake: empty, a few characters,
    or no letters at all."""
    q = (question or "").strip()
    chars = set(q.replace(" ", "").lower())
    return len(q) < 4 or not re.search(r"[^\W\d_]", q) or len(chars) <= 2


def review_mode_enabled() -> bool:
    with db.conn() as c:
        row = c.execute(
            "SELECT value FROM system_settings WHERE key = 'review_mode'"
        ).fetchone()
    return bool(row and row["value"] == "on")


# The languages the teacher's dashboard reads; a question in any other language
# is translated into review_translate_to.
READABLE_LANGS = ("he", "en")
TRANSLATE_TO = ("he", "en", "off")


def translate_to() -> str:
    """The language questions the teacher can't read are translated into, or 'off'."""
    with db.conn() as c:
        row = c.execute("SELECT value FROM system_settings WHERE key = 'review_translate_to'").fetchone()
    return row["value"] if row and row["value"] in TRANSLATE_TO else "he"


def translation_target() -> Optional[str]:
    """translate_to() for the drafting call: None when it's off."""
    to = translate_to()
    return None if to == "off" else to


def _translation(question: str, variants: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(language, translation, translated_to) to keep for a question: a
    translation only when the question is in neither Hebrew nor English and the
    model gave one that isn't just the question again."""
    lang = (variants.get("question_lang") or "").strip().lower() or None
    text = (variants.get("question_translation") or "").strip()
    to = translation_target()
    if not text or not to or lang in READABLE_LANGS or " ".join(text.split()) == " ".join(question.split()):
        return lang, None, None
    return lang, text, to


# --- used by /api/ask ------------------------------------------------------

def enqueue(session_id: str, question: str, variants: dict, plain: bool = False) -> int:
    """Store a question with its drafted answers (and its closest question-bank
    entry, if any) for the teacher. Returns the review id."""
    match = bank.match_for_session(session_id, question)
    same = " ".join(question.split()).lower()
    with db.conn() as c:
        for old in c.execute("SELECT id, question FROM pending_reviews WHERE session_id = ? AND status = 'pending'",
                             (session_id,)).fetchall():
            if " ".join(old["question"].split()).lower() == same and not is_waiting(old["id"]):
                c.execute("UPDATE pending_reviews SET status = 'replaced', closed_at = CURRENT_TIMESTAMP "
                          "WHERE id = ? AND status = 'pending'", (old["id"],))
        cur = c.execute(
            "INSERT INTO pending_reviews(session_id, question, "
            "variant_nudge, variant_normal, variant_more, variant_direct, "
            "variant_nudge_he, variant_normal_he, variant_more_he, variant_direct_he, "
            "model, render_plain, bank_match, question_lang, question_translation, translated_to) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, question,
             *(variants[lvl]["en"] for lvl in LEVELS),
             *(variants[lvl]["he"] for lvl in LEVELS),
             variants.get("model"), int(plain), json.dumps(match, ensure_ascii=False) if match else None,
             *_translation(question, variants)),
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
    drafted again with (CLAUDE_STRONG_MODEL, CLAUDE_BEST_MODEL), and the
    language questions in other languages are translated into."""
    return {"regen_models": student_llm.regen_models(), "translate_to": translate_to()}


class ReviewConfigRequest(BaseModel):
    translate_to: Literal["he", "en", "off"]


@router.post("/reviews/config")
def set_review_config(req: ReviewConfigRequest, teacher: dict = Depends(deps.require_teacher)):
    """Change the translation language (applies to questions asked from now on)."""
    with db.conn() as c:
        c.execute(
            "INSERT INTO system_settings(key, value) VALUES('review_translate_to', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (req.translate_to,),
        )
    return review_config(teacher)


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
        "question_lang", "question_translation", "translated_to",
    )}
    # The language the student wrote in, so the card opens on matching answers.
    item["suggested_lang"] = textutil.detect_lang(r["question"])
    item["bank_match"] = json.loads(r["bank_match"]) if r["bank_match"] else None
    # Is the student's request still open for it? Else an answer reaches them later.
    item["waiting"] = is_waiting(r["id"])
    item["looks_like_noise"] = looks_like_noise(r["question"])
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
    live = _decide(review_id, "UPDATE pending_reviews SET status='answered', chosen_level=?, "
                   "chosen_lang=?, final_text=?, answered_at=CURRENT_TIMESTAMP",
                   (req.chosen, req.lang, final))
    if not live:
        deliver_late(review_id)
    return {"ok": True, "chosen": req.chosen, "lang": req.lang, "delivered": "now" if live else "later"}


# --- deleting questions ------------------------------------------------------

class DeleteRequest(BaseModel):
    notify: bool = True          # tell the student (now, or when they are back)
    note: Optional[str] = None   # a line from the teacher, shown with it


def _delete(review_id: int, notify: bool, note: Optional[str]) -> str:
    """'now' (a waiting request tells the student), 'later' (a note in their
    transcript) or 'silent'."""
    r = _row(review_id)
    if r is None:
        raise HTTPException(404, "Unknown review")
    if r["status"] != "pending":
        raise HTTPException(409, f"Review already {r['status']}")
    live = _decide(review_id, "UPDATE pending_reviews SET status='deleted', closed_at=CURRENT_TIMESTAMP, "
                   "final_text=?", ((note or "").strip() or None,))
    if live:
        return "now"
    if notify:
        transcript.record(r["session_id"], "system", deleted_message(r["question"], note, r["exercise"]),
                          kind="note", origin="server")
        return "later"
    return "silent"


@router.post("/reviews/{review_id}/delete")
def delete_review(review_id: int, req: DeleteRequest, teacher: dict = Depends(deps.require_teacher)):
    """Delete a question (sent by mistake, or no longer relevant)."""
    return {"ok": True, "student_told": _delete(review_id, req.notify, req.note)}


class DeleteStaleRequest(BaseModel):
    exercise_id: Optional[str] = None  # None: every exercise
    notify: bool = False


@router.post("/reviews/delete-stale")
def delete_stale(req: DeleteStaleRequest, teacher: dict = Depends(deps.require_teacher)):
    """Delete every pending question nobody waits for any more."""
    with db.conn() as c:
        rows = c.execute(
            "SELECT r.id FROM pending_reviews r JOIN sessions s ON s.id = r.session_id "
            "WHERE r.status = 'pending'" + (" AND s.exercise = ?" if req.exercise_id else ""),
            (req.exercise_id,) if req.exercise_id else ()).fetchall()
    deleted = 0
    for r in rows:
        if is_waiting(r["id"]):
            continue
        try:
            _delete(r["id"], req.notify, None)
            deleted += 1
        except HTTPException:
            pass  # decided meanwhile
    return {"deleted": deleted}


@router.get("/reviews/open/{session_id}")
def open_questions(session_id: str, user: dict = Depends(deps.current_user)):
    """The session's questions still with the teacher (for a chat that comes back)."""
    deps.require_owns_session(session_id, user)
    with db.conn() as c:
        rows = c.execute("SELECT id, question, created_at FROM pending_reviews WHERE session_id = ? "
                         "AND status = 'pending' ORDER BY id", (session_id,)).fetchall()
    return [{"id": r["id"], "question": r["question"], "created_at": r["created_at"],
             "waiting": is_waiting(r["id"])} for r in rows]


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
            "SELECT r.status, r.question, r.render_plain, s.id, s.user_id, s.exercise, s.mode, s.variant, s.course_id "
            "FROM pending_reviews r JOIN sessions s ON s.id = r.session_id WHERE r.id = ?",
            (review_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Unknown review")
    if row["status"] != "pending":
        raise HTTPException(409, f"Review already {row['status']}")
    session = {k: row[k] for k in ("id", "user_id", "exercise", "mode", "variant", "course_id")}
    try:
        variants = await tutor.generate_variants(
            prompting.system_prompt_for(session, bool(row["render_plain"])),
            session["id"], row["question"],
            course=course_name(exercises.get(session["exercise"])), model=model,
            translate_to=translation_target(),
        )
    except Exception as e:
        raise HTTPException(502, f"{student_llm.model_label(model)} couldn't draft answers: {e}")
    lang, translation, to = _translation(row["question"], variants)
    with db.conn() as c:
        # The question didn't change: a translation the new draft left out stays.
        cur = c.execute(
            "UPDATE pending_reviews SET "
            + ", ".join(f"variant_{lvl} = ?, variant_{lvl}_he = ?" for lvl in LEVELS)
            + ", model = ?, regenerated_at = CURRENT_TIMESTAMP, "
              "question_lang = COALESCE(?, question_lang), "
              "question_translation = COALESCE(?, question_translation), "
              "translated_to = COALESCE(?, translated_to) "
              "WHERE id = ? AND status = 'pending'",
            (*(x for lvl in LEVELS for x in (variants[lvl]["en"], variants[lvl]["he"])),
             variants.get("model"), lang, translation, to, review_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "The question was answered or expired meanwhile.")
        item = c.execute(_ITEM_SQL + " WHERE r.id = ?", (review_id,)).fetchone()
    return _item(item)
