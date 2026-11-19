"""Teacher-in-the-loop review queue.

Toggle `review_mode` on; every student /ask is held in `pending_reviews` and
shown to the teacher at once, with its answers drafted meanwhile, one model
call each, all at the same time (table review_answers): three Socratic levels
(nudge, normal, more) and a direct one by the default model, plus an extra
answer by the best model (slot 'best', CLAUDE_BEST_MODEL, Opus; its level is a
setting, direct by default). Each answer is in English and Hebrew. The
dashboard polls `/api/reviews/pending` and shows every answer as soon as it is
ready, the first that finished on top; a failed draft says so and can be
drafted again (`/api/reviews/{id}/regenerate`, also "redo with" a stronger
model). The teacher sends one (possibly edited), the question bank's answer,
or their own text with `/api/reviews/{id}/select`; the held /ask request then
unblocks and streams it back. Two options go with a send: save the answer
into the exercise's question bank (backend/bank.py save_answer), and send it
to every student active on the exercise as a class note (backend/broadcast.py).

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
e.g. Arabic or Russian) comes with a translation: the nudge draft (the
quickest) also names the question's language and translates it
(question_lang, question_translation). The setting `review_translate_to`
(system_settings, GET/POST /api/reviews/config) picks the language: 'he'
(default), 'en', or 'off'.

Settings (system_settings, GET/POST /api/reviews/config):
  review_translate_to   he | en | off
  review_best_answer    on | off: the extra answer by the best model (default on)
  review_best_level     nudge | normal | more | direct (default direct)
  review_save_to_bank   on | off: the "save to the question bank" box's default (on)
"""
import asyncio
import json
import logging
import os
import re
import threading
import time
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend import (bank, broadcast, claude_student, db, deps, exercises, prompting, steps, student_llm, textutil,
                     transcript, whereabouts)
from backend.agents import llm as agent_llm
from backend.agents import tutor
from backend.prompts import course_name

log = logging.getLogger("vericlass.review")

router = APIRouter()

LEVELS = ("nudge", "normal", "more", "direct")
BEST_SLOT = "best"
SLOTS = (*LEVELS, BEST_SLOT)
ANSWER_STATUSES = ("drafting", "ready", "failed", "replaced")

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
            "SELECT r.*, s.exercise, s.mode, s.course_id FROM pending_reviews r JOIN sessions s ON s.id = r.session_id "
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


def class_note(question: str, text: str, exercise_id: Optional[str] = None) -> str:
    """What the other students read when the teacher sends an answer to the class."""
    if hebrew_for(question, exercise_id):
        return f"🧑‍🏫 **המרצה ענה על שאלה ששאלו בכיתה:** «{_quote(question)}»\n\n{text}"
    return f"🧑‍🏫 **Your teacher answered a question asked in class:** “{_quote(question)}”\n\n{text}"


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


# --- settings ----------------------------------------------------------------

def _setting(key: str) -> Optional[str]:
    with db.conn() as c:
        row = c.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_setting(key: str, value: str) -> None:
    with db.conn() as c:
        c.execute("INSERT INTO system_settings(key, value) VALUES(?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def review_mode_enabled() -> bool:
    return _setting("review_mode") == "on"


# The languages the teacher's dashboard reads; a question in any other language
# is translated into review_translate_to.
READABLE_LANGS = ("he", "en")
TRANSLATE_TO = ("he", "en", "off")


def translate_to() -> str:
    """The language questions the teacher can't read are translated into, or 'off'."""
    value = _setting("review_translate_to")
    return value if value in TRANSLATE_TO else "he"


def translation_target() -> Optional[str]:
    """translate_to() for the drafting call: None when it's off."""
    to = translate_to()
    return None if to == "off" else to


def best_answer() -> dict[str, Any]:
    """The extra answer by the best model: {available, enabled, model, label,
    level}. available = CLAUDE_BEST_MODEL is set with ANTHROPIC_API_KEY;
    enabled = available and the setting isn't off."""
    model = student_llm.BEST_MODEL
    available = bool(model and os.environ.get(claude_student.API_KEY_ENV))
    level = _setting("review_best_level")
    return {
        "available": available,
        "enabled": available and _setting("review_best_answer") != "off",
        "model": model or None,
        "label": student_llm.model_label(model) if model else None,
        "level": level if level in LEVELS else "direct",
    }


def save_to_bank_default() -> bool:
    return _setting("review_save_to_bank") != "off"


def plan_slots() -> list[dict[str, Any]]:
    """The answers to draft for a new question: the four levels by the default
    model, plus the best model's answer when it is on."""
    slots = [{"slot": lvl, "level": lvl, "model": None} for lvl in LEVELS]
    best = best_answer()
    if best["enabled"]:
        slots.append({"slot": BEST_SLOT, "level": best["level"], "model": best["model"]})
    return slots


# --- drafting ----------------------------------------------------------------

def _translation(question: str, out: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(language, translation, translated_to) to keep for a question: a
    translation only when the question is in neither Hebrew nor English and the
    model gave one that isn't just the question again."""
    lang = (out.get("question_lang") or "").strip().lower() or None
    text = (out.get("question_translation") or "").strip()
    to = translation_target()
    if not text or not to or lang in READABLE_LANGS or " ".join(text.split()) == " ".join(question.split()):
        return lang, None, None
    return lang, text, to


def _model_name(model: Optional[str]) -> str:
    return model or agent_llm.default_model_name()


def _add_answer_rows(c, review_id: int, slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for s in slots:
        cur = c.execute(
            "INSERT INTO review_answers (review_id, slot, level, model) VALUES (?, ?, ?, ?)",
            (review_id, s["slot"], s["level"], _model_name(s.get("model"))))
        rows.append({"id": cur.lastrowid, **s})
    return rows


def enqueue(session_id: str, question: str, plain: bool = False,
            slots: Optional[list[dict[str, Any]]] = None) -> int:
    """Store a question for the teacher at once (with its closest question-bank
    entry, if any) and the rows of the answers about to be drafted. Returns the
    review id; draft the answers with start_drafting."""
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
            "model, render_plain, bank_match) "
            "VALUES(?, ?, '', '', '', '', ?, ?, ?)",
            (session_id, question, _model_name(None), int(plain),
             json.dumps(match, ensure_ascii=False) if match else None),
        )
        review_id = cur.lastrowid
        _add_answer_rows(c, review_id, slots if slots is not None else plan_slots())
        return review_id


def _pending_answer_rows(review_id: int) -> list[dict[str, Any]]:
    with db.conn() as c:
        rows = c.execute("SELECT id, slot, level, model FROM review_answers WHERE review_id = ? "
                         "AND status = 'drafting' ORDER BY id", (review_id,)).fetchall()
    return [dict(r) for r in rows]


# The drafting tasks, kept so the event loop doesn't drop them half-way; they
# outlive the student's request (a teacher may still answer later).
_TASKS: set[asyncio.Task] = set()


def start_drafting(review_id: int, session: dict[str, Any], system_prompt: str, question: str,
                   rows: Optional[list[dict[str, Any]]] = None) -> list[asyncio.Task]:
    """Draft every answer row of the question still 'drafting' (or `rows`),
    one task each, all at once. Each task stores its answer the moment it is
    done, so the queue shows it while the others are still being written.
    Call from the event loop."""
    if rows is None:
        rows = _pending_answer_rows(review_id)
    try:
        course = course_name(exercises.get(session["exercise"]))
    except KeyError:
        course = "Operating Systems"
    tasks = []
    # The quickest draft (nudge) also names the question's language and translates it.
    translator = next((r["id"] for r in rows if r["slot"] == "nudge"), rows[0]["id"] if rows else None)
    for r in rows:
        t = asyncio.create_task(_draft_one(review_id, r, system_prompt, session["id"], question, course,
                                           translate=r["id"] == translator))
        _TASKS.add(t)
        t.add_done_callback(_TASKS.discard)
        tasks.append(t)
    return tasks


async def _draft_one(review_id: int, row: dict[str, Any], system_prompt: str, session_id: str,
                     question: str, course: str, translate: bool) -> None:
    started = time.monotonic()
    # The default model is named by its provider (None); any other is a Claude model by name.
    model = row.get("model") if row.get("model") != _model_name(None) else None
    try:
        out = await tutor.draft(system_prompt, session_id, question, row["level"], course=course, model=model,
                                translate_to=translation_target() if translate else None)
    except Exception as e:  # the model, the network, a schema mismatch: the row says so
        log.warning("review %s: drafting %s with %s failed: %s", review_id, row["slot"], row.get("model"), e)
        with db.conn() as c:
            c.execute("UPDATE review_answers SET status = 'failed', error = ?, seconds = ?, ready_at = strftime('%Y-%m-%d %H:%M:%f', 'now') "
                      "WHERE id = ? AND status = 'drafting'",
                      (str(e)[:500] or type(e).__name__, round(time.monotonic() - started, 1), row["id"]))
        return
    answer_ready(review_id, row, out, time.monotonic() - started)
    if translate:
        lang, translation, to = _translation(question, out)
        with db.conn() as c:
            c.execute("UPDATE pending_reviews SET question_lang = COALESCE(?, question_lang), "
                      "question_translation = COALESCE(?, question_translation), "
                      "translated_to = COALESCE(?, translated_to) WHERE id = ?",
                      (lang, translation, to, review_id))


def answer_ready(review_id: int, row: dict[str, Any], out: dict[str, Any], seconds: float) -> None:
    """Store a finished draft. The four level answers are mirrored into the
    question's variant_* columns too (older readers of the table)."""
    with db.conn() as c:
        c.execute("UPDATE review_answers SET status = 'ready', text_en = ?, text_he = ?, model = ?, seconds = ?, "
                  "ready_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ? AND status = 'drafting'",
                  (out.get("en") or "", out.get("he") or "", out.get("model") or row.get("model"),
                   round(seconds, 1), row["id"]))
        if row["slot"] in LEVELS:
            c.execute(f"UPDATE pending_reviews SET variant_{row['slot']} = ?, variant_{row['slot']}_he = ? WHERE id = ?",
                      (out.get("en") or "", out.get("he") or "", review_id))


def recover() -> int:
    """At startup: answers that were still being drafted when the server
    stopped are marked failed, so the queue doesn't wait for them forever."""
    with db.conn() as c:
        cur = c.execute("UPDATE review_answers SET status = 'failed', error = 'the server restarted while drafting', "
                        "ready_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE status = 'drafting'")
    return cur.rowcount


def answers_of(review_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(finished, drafting): the ready and failed answers in the order they
    finished, and the ones still being written."""
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, slot, level, model, status, text_en, text_he, error, seconds, ready_at FROM review_answers "
            "WHERE review_id = ? AND status IN ('drafting', 'ready', 'failed') ORDER BY ready_at, id",
            (review_id,)).fetchall()
    finished, drafting = [], []
    for r in rows:
        d = dict(r)
        d["label"] = student_llm.model_label(d["model"]) if d["model"] and d["model"].startswith("claude-") else d["model"]
        (drafting if d["status"] == "drafting" else finished).append(d)
    return finished, drafting


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
    """Who wrote the answer that was sent: the drafting model, 'bank', or None
    for the teacher's own text."""
    with db.conn() as c:
        row = c.execute("SELECT chosen_level, chosen_slot, model FROM pending_reviews WHERE id = ?",
                        (review_id,)).fetchone()
        if row is None:
            return None
        slot = row["chosen_slot"] or row["chosen_level"]
        if slot == "bank":
            return "bank"
        if slot == "own":
            return None
        a = c.execute("SELECT model FROM review_answers WHERE review_id = ? AND slot = ? AND status = 'ready' "
                      "ORDER BY id DESC LIMIT 1", (review_id, slot)).fetchone()
    return a["model"] if a else row["model"]


# --- toggle ---------------------------------------------------------------

class ReviewModeRequest(BaseModel):
    enabled: bool


@router.get("/review_mode")
def get_review_mode(teacher: dict = Depends(deps.require_teacher)):
    return {"enabled": review_mode_enabled()}


@router.post("/review_mode")
def set_review_mode(req: ReviewModeRequest, teacher: dict = Depends(deps.require_teacher)):
    _set_setting("review_mode", "on" if req.enabled else "off")
    return {"enabled": req.enabled}


@router.get("/reviews/config")
def review_config(teacher: dict = Depends(deps.require_teacher)):
    """What the queue does: the models a question's answers can be drafted
    again with (CLAUDE_STRONG_MODEL, CLAUDE_BEST_MODEL), the extra answer by
    the best model, the language questions in other languages are translated
    into, the default of the "save to the question bank" box, and how many
    minutes back "all students" reaches."""
    return {
        "regen_models": student_llm.regen_models(),
        "translate_to": translate_to(),
        "best_answer": best_answer(),
        "save_to_bank": save_to_bank_default(),
        "class_minutes": broadcast.active_minutes(),
    }


class ReviewConfigRequest(BaseModel):
    translate_to: Optional[Literal["he", "en", "off"]] = None
    best_answer: Optional[bool] = None
    best_level: Optional[Literal["nudge", "normal", "more", "direct"]] = None
    save_to_bank: Optional[bool] = None


@router.post("/reviews/config")
def set_review_config(req: ReviewConfigRequest, teacher: dict = Depends(deps.require_teacher)):
    """Change a setting (applies to questions asked from now on)."""
    if req.translate_to is not None:
        _set_setting("review_translate_to", req.translate_to)
    if req.best_answer is not None:
        _set_setting("review_best_answer", "on" if req.best_answer else "off")
    if req.best_level is not None:
        _set_setting("review_best_level", req.best_level)
    if req.save_to_bank is not None:
        _set_setting("review_save_to_bank", "on" if req.save_to_bank else "off")
    return review_config(teacher)


# --- pending queue --------------------------------------------------------

_ITEM_SQL = """
    SELECT r.*, u.username, s.exercise AS exercise_id, s.course_id
    FROM pending_reviews r
    JOIN sessions s ON s.id = r.session_id
    JOIN users u    ON u.id = s.user_id
"""


def _item(r) -> dict:
    item = {k: r[k] for k in (
        "id", "session_id", "username", "exercise_id", "course_id", "question", "created_at",
        "model", "regenerated_at",
        "question_lang", "question_translation", "translated_to",
    )}
    # The language the student wrote in, so the card opens on matching answers.
    item["suggested_lang"] = textutil.detect_lang(r["question"])
    item["bank_match"] = json.loads(r["bank_match"]) if r["bank_match"] else None
    # Is the student's request still open for it? Else an answer reaches them later.
    item["waiting"] = is_waiting(r["id"])
    item["looks_like_noise"] = looks_like_noise(r["question"])
    item["answers"], item["drafting"] = answers_of(r["id"])
    # Where the student is (the step and its status) and the chat just before
    # the question: a one-line question means little without them.
    try:
        ex = exercises.get(r["exercise_id"])
    except KeyError:
        ex = None
    session = {"id": r["session_id"], "exercise": r["exercise_id"], "course_id": r["course_id"]}
    item["step"] = whereabouts.step_of(session, ex)
    item["before"] = whereabouts.before(r["session_id"], ex, r["question"], r["created_at"])
    if not item["answers"] and not item["drafting"]:
        # A question from before answers had rows of their own: its four columns.
        for lvl in LEVELS:
            if (r[f"variant_{lvl}"] or "").strip():
                item["answers"].append({"id": None, "slot": lvl, "level": lvl, "model": r["model"],
                                        "label": r["model"], "status": "ready", "text_en": r[f"variant_{lvl}"],
                                        "text_he": r[f"variant_{lvl}_he"], "error": None, "seconds": None,
                                        "ready_at": r["created_at"]})
    return item


@router.get("/reviews/pending")
def pending_reviews(teacher: dict = Depends(deps.require_teacher)):
    with db.conn() as c:
        rows = c.execute(
            _ITEM_SQL + " WHERE r.status = 'pending' ORDER BY r.created_at ASC"
        ).fetchall()
    return [_item(r) for r in rows]


class SelectRequest(BaseModel):
    # A drafted answer's slot ('nudge' | 'normal' | 'more' | 'direct' | 'best'),
    # 'bank' (the question bank's answer; `text` then carries it) or 'own' (the
    # teacher's own text in `text`).
    chosen: str = Field(max_length=16)
    lang: Literal["en", "he"] = "en"
    # The exact text to send the student (the teacher-edited box content). When
    # omitted, the stored answer for (chosen, lang) is used as-is.
    text: Optional[str] = None
    # Save the answer into the exercise's question bank (backend/bank.py). For
    # 'bank' and 'own', `level` says which level it is saved as (default normal).
    save_to_bank: bool = False
    level: Optional[Literal["nudge", "normal", "more", "direct"]] = None
    # Send it to every other student active on the exercise too (backend/broadcast.py).
    send_to_class: bool = False


def _answer_for(review_id: int, slot: str, lang: str) -> tuple[str, Optional[str], Optional[str]]:
    """(level, text, model) of a drafted answer the teacher picked. 404 for a
    slot that has no finished answer."""
    with db.conn() as c:
        a = c.execute("SELECT level, model, text_en, text_he FROM review_answers WHERE review_id = ? AND slot = ? "
                      "AND status = 'ready' ORDER BY id DESC LIMIT 1", (review_id, slot)).fetchone()
        if a is None and slot in LEVELS:  # a question from before answers had rows
            r = c.execute("SELECT * FROM pending_reviews WHERE id = ?", (review_id,)).fetchone()
            if r is not None and (r[f"variant_{slot}"] or "").strip():
                return slot, (r[f"variant_{slot}_he"] if lang == "he" else None) or r[f"variant_{slot}"], r["model"]
    if a is None:
        raise HTTPException(404, f"No finished answer '{slot}' for this question")
    text = (a["text_he"] if lang == "he" else a["text_en"]) or a["text_en"] or a["text_he"]
    return a["level"], text, a["model"]


@router.post("/reviews/{review_id}/select")
def select_variant(review_id: int, req: SelectRequest, teacher: dict = Depends(deps.require_teacher)):
    r = _row(review_id)
    if not r:
        raise HTTPException(404, "Unknown review")
    if r["status"] != "pending":
        raise HTTPException(409, f"Review already {r['status']}")
    if req.chosen in ("bank", "own"):
        level, stored, model = req.chosen, None, None
    elif req.chosen in SLOTS:
        level, stored, model = _answer_for(review_id, req.chosen, req.lang)
    else:
        raise HTTPException(422, f"chosen must be one of {', '.join(SLOTS)}, bank or own")
    # The student receives exactly this text (edited box, or the answer).
    final = (req.text or "").strip() or (stored or "").strip()
    if not final:
        raise HTTPException(422, "Nothing to send (empty answer)")
    live = _decide(review_id, "UPDATE pending_reviews SET status='answered', chosen_level=?, chosen_slot=?, "
                   "chosen_lang=?, final_text=?, answered_at=CURRENT_TIMESTAMP",
                   (level, req.chosen, req.lang, final))
    if not live:
        deliver_late(review_id)
    out: dict[str, Any] = {"ok": True, "chosen": req.chosen, "lang": req.lang,
                           "delivered": "now" if live else "later", "saved_to_bank": False, "sent_to_class": 0}
    if req.save_to_bank:
        try:
            ex = exercises.get(r["exercise"])
            step = steps.current_step(r["session_id"]) if steps.steps_of(ex) else None
            match = json.loads(r["bank_match"]) if r["bank_match"] else None
            bank.save_answer(r["exercise"], r["question"],
                             level if level in LEVELS else (req.level or "normal"), req.lang, final,
                             step=step, model=model if req.chosen in SLOTS else req.chosen,
                             # The bank's own answer, sent again: it goes back into that entry.
                             merge_into=match["id"] if req.chosen == "bank" and match else None)
            with db.conn() as c:
                c.execute("UPDATE pending_reviews SET saved_to_bank = 1 WHERE id = ?", (review_id,))
            out["saved_to_bank"] = True
        except Exception as e:  # the answer was sent; only the saving failed
            log.warning("review %s: saving to the question bank failed: %s", review_id, e)
            out["bank_error"] = str(e)
    if req.send_to_class:
        try:
            sent = broadcast.send(r["exercise"], class_note(r["question"], final, r["exercise"]),
                                  r["course_id"], exclude_session=r["session_id"])
            with db.conn() as c:
                c.execute("UPDATE pending_reviews SET sent_to_class = ? WHERE id = ?", (sent["sent"], review_id))
            out["sent_to_class"] = sent["sent"]
            out["class_skipped"] = sent["skipped"]
        except Exception as e:
            log.warning("review %s: sending to the class failed: %s", review_id, e)
            out["class_error"] = str(e)
    return out


# --- answered questions: sending one to the class later ---------------------

@router.get("/reviews/answered")
def answered_reviews(exercise_id: Optional[str] = None, hours: int = Query(12, ge=1, le=24 * 14),
                     limit: int = Query(30, ge=1, le=200), teacher: dict = Depends(deps.require_teacher)):
    """The questions answered in the last `hours` (newest first), with the text the
    student got and how many other students it was also sent to: the review
    queue's "Answered recently", where an answer can still go to the whole class."""
    where = ["r.status = 'answered'", "r.final_text IS NOT NULL",
             "COALESCE(r.answered_at, r.created_at) >= datetime('now', ?)"]
    args: list[Any] = [f"-{hours} hours"]
    if exercise_id:
        where.append("s.exercise = ?")
        args.append(exercise_id)
    with db.conn() as c:
        rows = c.execute(
            _ITEM_SQL + " WHERE " + " AND ".join(where)
            + " ORDER BY COALESCE(r.answered_at, r.created_at) DESC, r.id DESC LIMIT ?", (*args, limit)).fetchall()
    return [{
        "id": r["id"], "session_id": r["session_id"], "username": r["username"],
        "exercise_id": r["exercise_id"], "course_id": r["course_id"], "question": r["question"],
        "text": r["final_text"], "lang": r["chosen_lang"], "slot": r["chosen_slot"], "level": r["chosen_level"],
        "created_at": r["created_at"], "answered_at": r["answered_at"],
        "sent_to_class": r["sent_to_class"] or 0, "saved_to_bank": bool(r["saved_to_bank"]),
    } for r in rows]


class SendToClassRequest(BaseModel):
    # The text to send; omitted: the answer the student got.
    text: Optional[str] = Field(default=None, max_length=20_000)


@router.post("/reviews/{review_id}/send-to-class")
def send_answered_to_class(review_id: int, req: SendToClassRequest, teacher: dict = Depends(deps.require_teacher)):
    """Send an answer already given to one student to every other student active
    on the exercise (the same class note as "send to all students" when answering)."""
    r = _row(review_id)
    if not r:
        raise HTTPException(404, "Unknown review")
    if r["status"] != "answered":
        raise HTTPException(409, "Only an answered question can be sent to the class")
    text = (req.text or "").strip() or (r["final_text"] or "").strip()
    if not text:
        raise HTTPException(422, "Nothing to send (empty answer)")
    sent = broadcast.send(r["exercise"], class_note(r["question"], text, r["exercise"]),
                          r["course_id"], exclude_session=r["session_id"])
    with db.conn() as c:
        c.execute("UPDATE pending_reviews SET sent_to_class = ? WHERE id = ?",
                  ((r["sent_to_class"] or 0) + sent["sent"], review_id))
    return {"ok": True, "sent_to_class": sent["sent"], "class_skipped": sent["skipped"]}


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
    # 'strong' = CLAUDE_STRONG_MODEL (Sonnet), 'best' = CLAUDE_BEST_MODEL (Opus);
    # None: each answer's own model again (a failed draft, tried again).
    model: Optional[Literal["strong", "best"]] = None
    # Which answers: default the four levels (with a model), or the failed ones (without).
    slots: Optional[list[Literal["nudge", "normal", "more", "direct", "best"]]] = None


@router.post("/reviews/{review_id}/regenerate")
async def regenerate(review_id: int, req: RegenerateRequest, teacher: dict = Depends(deps.require_teacher)):
    """Draft answers again, from the same point in the conversation: the four
    levels with a stronger model, or the failed ones with their own model. The
    earlier answers of those slots are replaced; the new ones appear in the
    queue as they finish. The student keeps waiting; nothing is sent until the
    teacher picks."""
    model = None
    if req.model:
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
    finished, drafting = answers_of(review_id)
    busy = {a["slot"] for a in drafting}
    if req.slots:
        wanted = [s for s in req.slots if s not in busy]
    elif model:
        wanted = [lvl for lvl in LEVELS if lvl not in busy]
    else:
        wanted = [a["slot"] for a in finished if a["status"] == "failed" and a["slot"] not in busy]
    if not wanted:
        raise HTTPException(409, "Nothing to draft again (still drafting, or no failed answer).")
    best = best_answer()
    slots = []
    for s in wanted:
        level = best["level"] if s == BEST_SLOT else s
        own = best["model"] if s == BEST_SLOT else None
        slots.append({"slot": s, "level": level, "model": model or own})
    with db.conn() as c:
        c.execute("UPDATE review_answers SET status = 'replaced' WHERE review_id = ? AND slot IN (%s) "
                  "AND status IN ('ready', 'failed')" % ",".join("?" * len(wanted)), (review_id, *wanted))
        rows = _add_answer_rows(c, review_id, slots)
        c.execute("UPDATE pending_reviews SET regenerated_at = CURRENT_TIMESTAMP WHERE id = ?", (review_id,))
    session = {k: row[k] for k in ("id", "user_id", "exercise", "mode", "variant", "course_id")}
    start_drafting(review_id, session, prompting.system_prompt_for(session, bool(row["render_plain"])),
                   row["question"], rows)
    with db.conn() as c:
        item = c.execute(_ITEM_SQL + " WHERE r.id = ?", (review_id,)).fetchone()
    return _item(item)
