"""Recommended-grade service — blends deterministic correctness with the LLM's
wise-use judgment and persists one recommendation per session.

  recommended = 0.30 * correctness + 0.70 * wise_use

Correctness comes from the real compile/run (grading.features), wise_use from
the reviewer agent. The 0.30/0.70 split is applied HERE in Python so the weight
is guaranteed regardless of what the LLM returns.

Like the probe auto-grade flow, the LLM step is best-effort: a transient Gemini
outage stores the correctness score with a "wise-use unavailable" note instead
of failing the whole request.
"""
import json
import logging

from backend import db, exercises
from backend.agents import reviewer
from backend.grading import features

log = logging.getLogger(__name__)

CORRECTNESS_WEIGHT = 0.30
WISE_USE_WEIGHT = 0.70


def blended(correctness: float, wise_use: float) -> int:
    return round(CORRECTNESS_WEIGHT * correctness + WISE_USE_WEIGHT * wise_use)


def derive_band(recommended: float, correctness: float, wise_use: float) -> str:
    """Map the numbers to a teacher-facing band.

    The special case first: a correct-but-plug-and-play submission (high
    correctness, low wise-use) is always `flagged`, no matter the blend — that
    is precisely the student the teacher needs to look at, and a heavy
    correctness component could otherwise float them into 'review'.
    """
    if correctness >= 80 and wise_use < 40:
        return "flagged"
    if recommended >= 85:
        return "excellent"
    if recommended >= 70:
        return "good"
    if recommended >= 55:
        return "review"
    if recommended >= 40:
        return "flagged"
    return "fail"


def _variant_params(exercise_id: str, variant_id: str) -> dict:
    try:
        return exercises.variant(exercise_id, variant_id).get("params", {})
    except Exception:
        return {}


def _latest_submission(session_id: str) -> dict | None:
    with db.conn() as c:
        row = c.execute(
            "SELECT id, source_code FROM submissions WHERE session_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def _upsert(session_id: str, submission_id, correctness, wise_use, recommended,
            band, rationale, components) -> None:
    """Insert or refresh the recommendation, PRESERVING any teacher override."""
    with db.conn() as c:
        c.execute(
            """
            INSERT INTO grade_recommendations
              (session_id, submission_id, correctness, wise_use, recommended,
               band, rationale, components, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id) DO UPDATE SET
              submission_id = excluded.submission_id,
              correctness   = excluded.correctness,
              wise_use      = excluded.wise_use,
              recommended   = excluded.recommended,
              band          = excluded.band,
              rationale     = excluded.rationale,
              components    = excluded.components,
              updated_at    = CURRENT_TIMESTAMP
            """,
            (session_id, submission_id, correctness, wise_use, recommended,
             band, rationale, json.dumps(components)),
        )


def get(session_id: str) -> dict | None:
    with db.conn() as c:
        row = c.execute(
            "SELECT * FROM grade_recommendations WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["components"] = json.loads(d["components"]) if d["components"] else None
    except (ValueError, TypeError):
        d["components"] = None
    return d


async def compute(session_id: str, lang: str = "en") -> dict:
    """Compute (or recompute) the recommended grade for a session and persist it.

    Raises KeyError if the session is unknown (via features.extract). The LLM
    step is best-effort; correctness is always stored. `lang` (en | he) sets the
    language of the rationale + signals written by the reviewer."""
    feats = features.extract(session_id)
    correctness = feats["correctness"]
    exercise_id, variant_id = feats["exercise"], feats["variant"]
    sub = _latest_submission(session_id)
    submission_id = sub["id"] if sub else None
    summary = features.summarize(feats)

    wise_use = None
    rationale = None
    signals: list[str] = []
    try:
        rec = await reviewer.recommend(
            session_id, exercise_id, variant_id,
            _variant_params(exercise_id, variant_id), summary,
            (sub or {}).get("source_code", ""), lang,
        )
        wise_use = int(rec.wise_use)
        rationale = rec.rationale
        signals = list(rec.signals or [])
    except Exception:
        log.exception("wise-use judgment failed for session %s; storing correctness only", session_id)
        rationale = "Wise-use judgment is temporarily unavailable — correctness was still measured."

    if wise_use is None:
        recommended, band = None, "review"
    else:
        recommended = blended(correctness, wise_use)
        band = derive_band(recommended, correctness, wise_use)

    components = {"features": feats, "signals": signals}
    _upsert(session_id, submission_id, correctness, wise_use, recommended,
            band, rationale, components)
    return get(session_id)


def override(session_id: str, grade: float) -> bool:
    """Teacher sets the final grade. Returns False if there's no recommendation
    row yet (compute one first)."""
    with db.conn() as c:
        result = c.execute(
            "UPDATE grade_recommendations SET override_grade = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (grade, session_id),
        )
    return result.rowcount > 0
