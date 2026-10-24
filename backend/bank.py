"""Question bank: likely student questions per step, with ready answers.

An exercise package may carry `faq.yaml` (written with the exercise in the
lecturer's Claude Code session, so it costs the server nothing):

    questions:
      - id: q01
        step: 1                      # optional: the step it belongs to
        question: "How do I count missing values in each column?"
        paraphrases: ["איך סופרים ערכים חסרים?"]   # optional, helps matching
        answers:                     # any of nudge / normal / more / direct, each {en, he}
          normal: {en: "...", he: "..."}
        approved: true               # optional, default true

When a student asks something close to a bank question, the teacher's queue
shows the ready answer next to the drafted ones. Matching is plain text
similarity (character trigrams plus words, TF-IDF cosine), so it needs no model
call and works for Hebrew and English alike. With BANK_AUTO_ANSWER=true and
review mode off, a very close match (BANK_AUTO_THRESHOLD) is answered straight
from the bank.
"""
import math
import os
import re
from collections import Counter
from functools import lru_cache
from typing import Any, Optional

from backend import db, exercises, steps

LEVELS = ("nudge", "normal", "more", "direct")

MATCH_THRESHOLD = float(os.environ.get("BANK_MATCH_THRESHOLD", "0.45"))
AUTO_ANSWER = os.environ.get("BANK_AUTO_ANSWER", "false").strip().lower() in ("1", "true", "yes", "on")
AUTO_THRESHOLD = float(os.environ.get("BANK_AUTO_THRESHOLD", "0.8"))
_STEP_BONUS = 0.05

_NIQQUD = re.compile(r"[֑-ׇ]")
_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
_NON_WORD = re.compile(r"[^\w]+")


def normalize_entries(raw: Any, where: str = "faq") -> list[dict[str, Any]]:
    """Validate and normalize a faq.yaml body (a list, or {questions: [...]}).
    Raises ValueError on a malformed entry."""
    items = raw.get("questions") if isinstance(raw, dict) else raw
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError(f"{where}: questions must be a list")
    out, seen = [], set()
    for i, e in enumerate(items, 1):
        if not isinstance(e, dict) or not str(e.get("question") or "").strip():
            raise ValueError(f"{where}: question #{i} has no 'question' text")
        qid = str(e.get("id") or f"q{i:02d}")
        if qid in seen:
            raise ValueError(f"{where}: duplicate question id '{qid}'")
        seen.add(qid)
        answers = {}
        for lvl, val in (e.get("answers") or {}).items():
            if lvl not in LEVELS:
                raise ValueError(f"{where}: question {qid}: unknown answer level '{lvl}' "
                                 f"(use {', '.join(LEVELS)})")
            if isinstance(val, str):
                val = {"en": val, "he": val}
            if not isinstance(val, dict) or not (val.get("en") or val.get("he")):
                raise ValueError(f"{where}: question {qid}: answer '{lvl}' needs en and/or he text")
            answers[lvl] = {"en": str(val.get("en") or val.get("he")), "he": str(val.get("he") or val.get("en"))}
        if not answers:
            raise ValueError(f"{where}: question {qid} has no answers")
        step = e.get("step")
        if step is not None and (not isinstance(step, int) or step < 1):
            raise ValueError(f"{where}: question {qid}: step must be a positive number")
        out.append({
            "id": qid,
            "step": step,
            "question": str(e["question"]).strip(),
            "paraphrases": [str(p).strip() for p in (e.get("paraphrases") or []) if str(p).strip()],
            "answers": answers,
            "approved": bool(e.get("approved", True)),
        })
    return out


def _norm(text: str) -> str:
    text = _NIQQUD.sub("", (text or "").lower()).translate(_FINALS)
    return _NON_WORD.sub(" ", text).strip()


def _features(text: str) -> Counter:
    t = _norm(text)
    padded = f" {t} "
    feats = Counter(padded[i:i + 3] for i in range(len(padded) - 2))
    # Whole words count more than one trigram: they carry the meaning.
    feats.update({f"w:{w}": 2 for w in t.split() if len(w) > 1})
    return feats


@lru_cache(maxsize=64)
def _index(texts: tuple[str, ...]):
    """IDF weights and unit vectors for a tuple of bank texts."""
    feats = [_features(t) for t in texts]
    df = Counter(g for f in feats for g in f)
    n = len(texts)
    idf = {g: math.log((n + 1) / (d + 1)) + 1.0 for g, d in df.items()}
    vecs = [_unit({g: tf * idf[g] for g, tf in f.items()}) for f in feats]
    return idf, vecs


def _unit(v: dict) -> dict:
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {k: x / norm for k, x in v.items()}


def best_match(entries: list[dict[str, Any]], question: str,
               step: Optional[int] = None) -> Optional[dict[str, Any]]:
    """The closest approved entry with its score (0..1), or None if none clears
    MATCH_THRESHOLD. Entries of the student's current step get a small bonus."""
    pool = [(e, t) for e in entries if e["approved"] for t in [e["question"], *e["paraphrases"]]]
    if not pool or not (question or "").strip():
        return None
    idf, vecs = _index(tuple(t for _, t in pool))
    q = _unit({g: tf * idf.get(g, 1.0) for g, tf in _features(question).items()})
    best: dict[str, tuple[float, dict]] = {}
    for (entry, _), vec in zip(pool, vecs):
        score = sum(w * vec.get(g, 0.0) for g, w in q.items())
        if step is not None and entry["step"] is not None:
            score += _STEP_BONUS if entry["step"] == step else -_STEP_BONUS
        if score > best.get(entry["id"], (-1.0, entry))[0]:
            best[entry["id"]] = (score, entry)
    if not best:
        return None
    score, entry = max(best.values(), key=lambda x: x[0])
    if score < MATCH_THRESHOLD:
        return None
    return {"id": entry["id"], "step": entry["step"], "question": entry["question"],
            "score": round(min(score, 1.0), 2), "answers": entry["answers"]}


def match_for_session(session_id: str, question: str) -> Optional[dict[str, Any]]:
    """best_match against the bank of the session's exercise, at its current step."""
    with db.conn() as c:
        row = c.execute("SELECT exercise FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    try:
        ex = exercises.get(row["exercise"])
    except KeyError:
        return None
    entries = ex.get("faq") or []
    if not entries:
        return None
    step = steps.current_step(session_id) if steps.steps_of(ex) else None
    return best_match(entries, question, step)
