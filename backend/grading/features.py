"""Deterministic feature extraction for the recommended grade.

Everything here is computed straight from SQLite with no LLM call, so it is
cheap, reproducible, and testable. Two families of signals come out:

  * correctness (0-100) — grounded in the submission's actual compile/run result
    (`submissions.run_report`), byte-compared against the variant's expected
    outputs. This is goal #1 ("the solution is correct").
  * wise-use signals — how many hints the student took and at what level, the
    timing/cadence of their questions, how they did on comprehension probes, and
    proctor away-time. These feed the LLM judge that scores goal #2 (did the
    student use the LLM wisely, or plug-and-play).

`extract(session_id)` returns a plain dict; `summarize(features)` renders it as
the compact text block handed to the reviewer agent.
"""
import json
import logging
import statistics
from datetime import datetime
from typing import Any, Optional

from backend import db, exercises
from backend.sanitize import sanitize

log = logging.getLogger(__name__)


# --- helpers ---------------------------------------------------------------

def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """SQLite CURRENT_TIMESTAMP is 'YYYY-MM-DD HH:MM:SS' (UTC). Be tolerant of an
    ISO 'T' separator and fractional seconds too."""
    if not value:
        return None
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _norm(text: str) -> str:
    """Byte-exact comparison of program output vs expected, tolerating exactly
    the trailing newline that printf/puts adds. Everything else must match."""
    return (text or "").rstrip("\n")


# --- correctness -----------------------------------------------------------

def _variant_test_inputs(exercise_id: str, variant_id: str) -> list[dict]:
    try:
        return exercises.variant(exercise_id, variant_id).get("test_inputs", []) or []
    except Exception:
        return []


def _correctness_from_run_report(report: list[dict], compile_ok: Optional[int]) -> tuple[float, dict]:
    """Fraction of test cases whose actual output matches expected, 0-100.

    We recompute pass/fail here (byte-exact) rather than trusting the plugin's
    `passed` flag, so the score is authoritative on the server. A failed compile
    caps correctness at 0 — nothing ran."""
    if compile_ok == 0:
        return 0.0, {"source": "compile_failed", "total": len(report), "passed": 0}
    if not report:
        return 0.0, {"source": "empty_report", "total": 0, "passed": 0}
    passed = 0
    cases = []
    for case in report:
        expected = _norm(str(case.get("expected", "")))
        actual = _norm(str(case.get("actual", "")))
        ok = expected == actual and expected != ""
        passed += 1 if ok else 0
        cases.append({"input": case.get("input", ""), "expected": expected,
                      "actual": actual, "passed": ok})
    total = len(report)
    return round(100.0 * passed / total, 1), {
        "source": "run_report", "total": total, "passed": passed, "cases": cases,
    }


def _correctness_from_console(console: str, test_inputs: list[dict]) -> tuple[float, dict]:
    """Fallback when there's no structured run report (older plugin / manual
    submit): count how many of the variant's expected outputs literally appear
    in the captured console text. Coarser, but better than an LLM guess."""
    if not test_inputs:
        return 0.0, {"source": "no_test_inputs", "total": 0, "passed": 0}
    text = console or ""
    found = sum(1 for t in test_inputs if _norm(str(t.get("expected_output", ""))) in text)
    total = len(test_inputs)
    return round(100.0 * found / total, 1), {
        "source": "console_scan", "total": total, "passed": found,
    }


def _correctness(sub: Optional[dict], exercise_id: str, variant_id: str) -> tuple[float, dict]:
    if not sub:
        return 0.0, {"source": "no_submission", "total": 0, "passed": 0}
    raw = sub.get("run_report")
    if raw:
        try:
            report = json.loads(raw)
            if isinstance(report, list) and report:
                return _correctness_from_run_report(report, sub.get("compile_ok"))
        except (ValueError, TypeError):
            log.warning("submission %s has unparseable run_report", sub.get("id"))
    return _correctness_from_console(
        sub.get("console_output") or "", _variant_test_inputs(exercise_id, variant_id)
    )


# --- extraction ------------------------------------------------------------

def extract(session_id: str) -> dict[str, Any]:
    """All deterministic signals for one session, as a plain dict."""
    with db.conn() as c:
        sess = c.execute(
            "SELECT id, exercise, variant, mode, started_at, last_active_at "
            "FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not sess:
            raise KeyError(f"unknown session {session_id}")
        messages = c.execute(
            "SELECT role, body, answer_level, created_at FROM messages "
            "WHERE session_id = ? ORDER BY created_at ASC, id ASC",
            (session_id,),
        ).fetchall()
        reviews = c.execute(
            "SELECT chosen_level FROM pending_reviews "
            "WHERE session_id = ? AND status = 'answered'",
            (session_id,),
        ).fetchall()
        probes = c.execute(
            "SELECT body, answer, auto_grade, override_grade, status FROM probes "
            "WHERE session_id = ? ORDER BY sent_at ASC",
            (session_id,),
        ).fetchall()
        proctor = c.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(away_ms), 0) AS away "
            "FROM proctor_events WHERE session_id = ? AND away_ms IS NOT NULL",
            (session_id,),
        ).fetchone()
        submissions = c.execute(
            "SELECT id, source_code, console_output, language, compile_ok, "
            "compile_output, run_report, created_at FROM submissions "
            "WHERE session_id = ? ORDER BY id DESC",
            (session_id,),
        ).fetchall()

    exercise_id, variant_id = sess["exercise"], sess["variant"]
    latest_sub = dict(submissions[0]) if submissions else None
    correctness, correctness_detail = _correctness(latest_sub, exercise_id, variant_id)

    # --- hints: assistant turns, split by teacher-chosen level ---
    hint_levels = {"nudge": 0, "normal": 0, "more": 0, "plain": 0}
    user_lens: list[int] = []
    times: list[datetime] = []
    for m in messages:
        ts = _parse_ts(m["created_at"])
        if ts:
            times.append(ts)
        if m["role"] == "assistant":
            level = m["answer_level"] or "plain"
            hint_levels[level] = hint_levels.get(level, 0) + 1
        elif m["role"] == "user":
            user_lens.append(len((m["body"] or "").strip()))
    for r in reviews:  # escalation from the review queue, if used
        if r["chosen_level"] in hint_levels:
            hint_levels[r["chosen_level"]] += 0  # already counted via messages
    hint_total = sum(hint_levels.values())

    # --- timing / cadence ---
    gaps = [
        (times[i] - times[i - 1]).total_seconds()
        for i in range(1, len(times))
        if (times[i] - times[i - 1]).total_seconds() >= 0
    ]
    span_sec = None
    st, la = _parse_ts(sess["started_at"]), _parse_ts(sess["last_active_at"])
    if st and la and la >= st:
        span_sec = (la - st).total_seconds()

    # Time between the last hint the tutor gave and the student's submission —
    # a near-zero gap on a correct answer is the classic copy-paste tell.
    hint_to_submit_sec = None
    if latest_sub and times:
        sub_ts = _parse_ts(latest_sub["created_at"])
        last_assistant = None
        for m in messages:
            if m["role"] == "assistant":
                last_assistant = _parse_ts(m["created_at"])
        if sub_ts and last_assistant and sub_ts >= last_assistant:
            hint_to_submit_sec = (sub_ts - last_assistant).total_seconds()

    # --- probes: average of (override ?? auto), plus the actual Q&A so the
    # reviewer can judge how the student answered the teacher's questions ---
    probe_grades = []
    probe_qa = []
    for p in probes:
        grade = p["override_grade"] if p["override_grade"] is not None else p["auto_grade"]
        if grade is not None:
            probe_grades.append(grade)
        if p["answer"]:  # only answered probes carry a signal
            probe_qa.append({
                "q": sanitize(p["body"] or ""),
                "a": sanitize(p["answer"] or ""),
                "grade": grade,
            })
    avg_probe = round(statistics.mean(probe_grades), 2) if probe_grades else None

    return {
        "session_id": session_id,
        "exercise": exercise_id,
        "variant": variant_id,
        "mode": sess["mode"],
        "correctness": correctness,
        "correctness_detail": correctness_detail,
        "hints": {"total": hint_total, **hint_levels},
        "questions": {
            "count": len(user_lens),
            "avg_len": round(statistics.mean(user_lens), 1) if user_lens else 0,
        },
        "timing": {
            "span_sec": round(span_sec) if span_sec is not None else None,
            "median_gap_sec": round(statistics.median(gaps)) if gaps else None,
            "min_gap_sec": round(min(gaps)) if gaps else None,
            "hint_to_submit_sec": round(hint_to_submit_sec) if hint_to_submit_sec is not None else None,
        },
        "probes": {"count": len(probe_grades), "avg_grade": avg_probe, "qa": probe_qa},
        "proctor": {"alerts": proctor["n"], "away_ms": int(proctor["away"] or 0)},
        "submissions": {"count": len(submissions)},
    }


def summarize(f: dict[str, Any]) -> str:
    """Compact, LLM-friendly rendering of the numeric signals. Kept terse so the
    judge reasons over the numbers rather than drowning in prose."""
    h, q, t, p, pr = f["hints"], f["questions"], f["timing"], f["probes"], f["proctor"]

    def secs(v):
        return f"{v}s" if v is not None else "n/a"

    probe_txt = (
        f"{p['count']} answered, avg {p['avg_grade']}/2" if p["avg_grade"] is not None
        else "none answered"
    )
    # The actual teacher questions + student answers — the strongest read on
    # whether the student understood the code they submitted.
    qa_lines = "".join(
        f"\n  Q: {item['q']}\n  A: {item['a']}  (graded {item['grade']}/2)"
        for item in p.get("qa", [])
    )
    return (
        f"Correctness (actual run): {f['correctness']}/100 "
        f"({f['correctness_detail'].get('passed')}/{f['correctness_detail'].get('total')} "
        f"cases via {f['correctness_detail'].get('source')})\n"
        f"Hints taken: {h['total']} total "
        f"(nudge {h['nudge']}, normal {h['normal']}, more {h['more']}, plain {h['plain']})\n"
        f"Student questions: {q['count']} (avg {q['avg_len']} chars each)\n"
        f"Timing: session span {secs(t['span_sec'])}, median gap between turns "
        f"{secs(t['median_gap_sec'])}, fastest gap {secs(t['min_gap_sec'])}, "
        f"last-hint-to-submit {secs(t['hint_to_submit_sec'])}\n"
        f"Comprehension probes: {probe_txt}{qa_lines}\n"
        f"Proctor: {pr['alerts']} away-events, {round(pr['away_ms'] / 1000)}s outside the IDE\n"
        f"Code submissions: {f['submissions']['count']}"
    )
