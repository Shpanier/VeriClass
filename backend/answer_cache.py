"""Cache for the "ask again" (strong model) answers, to save LLM spend.

Only answers from the strong model are cached (student_llm.STRONG_MODEL); the
default model's answers are cheap and never cached.

A cached answer is reused only for the same question in the same context: the
key hashes the model, the full system prompt (exercise brief, variant, mentor or
partner rules, current lab step) and the earlier turns of the conversation. So
two students who open the same exercise and ask the same first question share
one answer, while "explain that again" after different conversations never
collides. The question is compared after normalizing case, spaces and trailing
punctuation; other rewordings are a different question.

Settings (.env):
  ANSWER_CACHE=true        false turns the cache off
  ANSWER_CACHE_DAYS=30     how long an answer is reused; 0 = until cleared
Clear it: sqlite3 vericlass.db "DELETE FROM answer_cache"
"""
import hashlib
import json
import os
import re
from typing import Optional

from backend import db

ENABLED = os.environ.get("ANSWER_CACHE", "true").strip().lower() not in ("0", "false", "no", "off")


def _days() -> int:
    try:
        return max(0, int(os.environ.get("ANSWER_CACHE_DAYS", "30").strip()))
    except ValueError:
        return 30


def normalize(question: str) -> str:
    q = re.sub(r"\s+", " ", question).strip().casefold()
    return q.rstrip(" ?!.;:,׃")


def key(model: str, system_prompt: str, history: list[dict], question: str) -> str:
    turns = [[m["role"], (m.get("content") or "").strip()] for m in history]
    blob = json.dumps([model, system_prompt, turns, normalize(question)], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def get(cache_key: str) -> Optional[str]:
    """The cached answer, or None. Counts the hit."""
    if not ENABLED:
        return None
    days = _days()
    with db.conn() as c:
        row = c.execute(
            "SELECT answer FROM answer_cache WHERE key = ?"
            + (" AND created_at >= datetime('now', ?)" if days else ""),
            (cache_key, f"-{days} days") if days else (cache_key,),
        ).fetchone()
        if row is None:
            return None
        c.execute(
            "UPDATE answer_cache SET hits = hits + 1, last_hit_at = CURRENT_TIMESTAMP WHERE key = ?",
            (cache_key,),
        )
    return row["answer"]


def put(cache_key: str, model: str, exercise: str, question: str, answer: str) -> None:
    if not ENABLED or not answer.strip():
        return
    with db.conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO answer_cache (key, model, exercise, question, answer) "
            "VALUES (?, ?, ?, ?, ?)",
            (cache_key, model, exercise, question, answer),
        )
