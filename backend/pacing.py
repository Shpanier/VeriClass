"""Class-paced labs: the teacher opens steps for the whole class, and students
move on their own inside what is open. Made for the chat-only setup: students
work in a GitHub Codespace and the student chat (student_app) is the only chat
they use.

An exercise opts in with `pacing: class` in exercise.yaml. Steps 1..open_steps
are open from the start (the setup part, done at each student's own pace) until
the teacher sets a course's marker in the dashboard: open up to any step, part
of the setup included (e.g. stop everyone after A5), or open several at once.

A student finishes a step by pasting its output into the chat. The server
checks it against the step's `expect_output` patterns (teacher.yaml) and moves
the student on. An output that doesn't match waits for the teacher, who sees it
next to the step's `expected_output` in the dashboard and either lets the
student continue or sends it back (with a note) to try again; meanwhile the
student may paste again. A step without patterns needs no output.

A finished step's `quiz` questions (teacher.yaml) are asked as probes, but only
the ones the teacher approved in the dashboard, and the next step waits until
they are answered. A question approved after some students already finished its
step can be asked of them at once (ask_finished). Approvals are keyed by the
question's text, so a question changed in the package needs a new approval.

A question marked `always: true` in the package is approved by its author: it
is asked without waiting for the dashboard (e.g. "what does the code you just
pasted do?" after every paste step). The dashboard can still switch it off,
and its choice then wins.

Only a quiz answer the grader gave 2/2 moves the student on by itself. One
graded 0/2 or 1/2 waits for the teacher, who sees it in the dashboard next to
the model answer and either lets the student continue (correcting the grade if
the grader was wrong) or asks them to answer again; either way with a text for
the student (the grader's feedback, the model answer, or the teacher's own).
The student is told so in their chat and can still ask questions meanwhile;
the grader's reason for the grade is shown to the teacher only, since it tends
to give the answer away. exercise.yaml `quiz_review` sets which grades wait:
'partial' (0/2 and 1/2, the default), 'zero' (0/2 only), 'off'.

The teacher can move a student to any step (move_to): back (their work from
there on no longer counts and is done again), forward (the steps between are
skipped and the target step is opened for that student, even beyond what the
class has open), or the step they are on (start it over). Withdrawing a
question that students were asked tells each of them, quoting the question and
their own answer, and the answer no longer counts. Every such change reaches
the student's chat as a note in the transcript, which interrupts whatever the
chat was waiting for.
"""
import hashlib
import json
import re
from typing import Any, Optional

from backend import db, steps, textutil

# Stored size of a pasted output (the teacher sees the end of a long one).
_OUTPUT_MAX = 50_000


def is_paced(ex: Optional[dict[str, Any]]) -> bool:
    return (ex or {}).get("pacing") == "class"


def total(ex: dict[str, Any]) -> int:
    return len(steps.steps_of(ex))


def open_from_start(ex: dict[str, Any]) -> int:
    """Steps open before the teacher opens anything (open_steps, at most all)."""
    return max(0, min(int(ex.get("open_steps") or 0), total(ex)))


def label(ex: dict[str, Any], n: int) -> str:
    """The step's name in messages: its `label` (e.g. "B3"), else its number."""
    st = steps.steps_of(ex)
    if 1 <= n <= len(st) and st[n - 1].get("label"):
        return str(st[n - 1]["label"])
    return str(n)


def hebrew(ex: dict[str, Any]) -> bool:
    """Write the chat's own lines (headers, buttons) in Hebrew?"""
    st = steps.steps_of(ex)
    return textutil.has_hebrew((st[0].get("title", "") if st else "") + ex.get("brief_md", ""))


# --- what is open ------------------------------------------------------------------

def _course(course_id: Optional[str]) -> str:
    return course_id or ""


def released(ex: dict[str, Any], course_id: Optional[str]) -> int:
    """Steps 1..N are open to this course's students: the teacher's marker for
    the course, or open_steps while the teacher hasn't set one."""
    with db.conn() as c:
        row = c.execute(
            "SELECT released FROM step_release WHERE course_id = ? AND exercise_id = ?",
            (_course(course_id), ex["exercise_id"]),
        ).fetchone()
    return max(0, min(row["released"], total(ex))) if row else open_from_start(ex)


def released_for(ex: dict[str, Any], session_id: str, course_id: Optional[str]) -> int:
    """Steps open to this student: the course's, or more when the teacher moved
    the student forward past them (sessions.released_to)."""
    with db.conn() as c:
        row = c.execute("SELECT released_to FROM sessions WHERE id = ?", (session_id,)).fetchone()
    own = (row["released_to"] or 0) if row else 0
    return max(released(ex, course_id), min(own, total(ex)))


def set_released(ex: dict[str, Any], course_id: Optional[str], n: int) -> int:
    """Open steps 1..n to the course, closing any later ones; 0 = none open.
    Students past n keep their progress and wait. Closing steps closes them
    for the students they were opened for alone (moved forward, move_to) as
    well. Returns the value stored."""
    n = max(0, min(int(n), total(ex)))
    closing = n < released(ex, course_id)
    with db.conn() as c:
        c.execute(
            "INSERT INTO step_release (course_id, exercise_id, released) VALUES (?, ?, ?) "
            "ON CONFLICT(course_id, exercise_id) DO UPDATE SET released = excluded.released, "
            "updated_at = CURRENT_TIMESTAMP",
            (_course(course_id), ex["exercise_id"], n),
        )
        if closing:
            c.execute("UPDATE sessions SET released_to = NULL WHERE exercise = ? AND COALESCE(course_id, '') = ? "
                      "AND released_to > ?", (ex["exercise_id"], _course(course_id), n))
    return n


def limit_own(session_id: str, n: int) -> None:
    """The student is sent back (or reset) to step n: the steps opened for them
    alone (sessions.released_to, move_to) no longer reach past it. Step n
    itself stays open to them when their course hasn't opened it (they were
    put there); otherwise nothing is left open for them alone."""
    from backend import exercises  # exercises -> packages -> bank -> steps; avoids a cycle at import

    with db.conn() as c:
        row = c.execute("SELECT exercise, course_id, released_to FROM sessions WHERE id = ?",
                        (session_id,)).fetchone()
    if row is None or not row["released_to"] or row["released_to"] <= n:
        return
    try:
        course = released(exercises.get(row["exercise"]), row["course_id"])
    except KeyError:
        course = 0
    with db.conn() as c:
        c.execute("UPDATE sessions SET released_to = ? WHERE id = ?", (n if n > course else None, session_id))


# --- checking a pasted output ----------------------------------------------------------

def output_rules(step: dict[str, Any]) -> list[dict[str, str]]:
    """The step's expect_output as [{match, hint}]: a bare string is a pattern
    whose hint is the pattern itself."""
    out = []
    for r in step.get("expect_output") or []:
        if isinstance(r, str):
            r = {"match": r}
        out.append({"match": r["match"], "hint": r.get("hint") or r["match"]})
    return out


def check_output(step: dict[str, Any], output: str) -> list[str]:
    """Hints of the patterns the output doesn't match (empty: all match).
    Patterns are regular expressions, searched line by line (re.M)."""
    text = (output or "").replace("\r\n", "\n").replace(" ", " ")
    return [r["hint"] for r in output_rules(step) if not re.search(r["match"], text, re.M)]


# --- a chat message while a step is open -------------------------------------------------
# Students often type or paste into the chat instead of clicking "Done": the
# message may be the step's answer or a question. exercise.yaml `output_in_chat`
# decides what happens (the student chat asks the student when it says "maybe"):
#   confirm (default): an output that passes every check of the student's
#     current step finishes it; any other message asks the student first:
#     "a question, or your answer for step X?".
#   accept: the same for a full match; a partial match asks; any other message
#     is a question.
#   ask: every message with at least one matching check asks, a full match too.
#   off: chat messages are always questions.
# A student with no open step (waiting for the teacher, finished) only asks questions.
OUTPUT_IN_CHAT = ("confirm", "accept", "ask", "off")


def output_in_chat(ex: dict[str, Any]) -> str:
    value = ex.get("output_in_chat")
    return value if value in OUTPUT_IN_CHAT else "confirm"


def detect_output(session: dict[str, Any], ex: dict[str, Any], text: str) -> dict[str, Any]:
    """Is this chat message the current step's answer? `kind`: output (finish
    the step with it), maybe (ask the student), or question. `needs_output`:
    the step checks a pasted output (else finishing needs no text). The
    checks' hints are never returned: they would give the expected output away."""
    question = {"kind": "question"}
    mode = output_in_chat(ex)
    if mode == "off" or not (text or "").strip():
        return question
    st = state(session, ex)
    if not st["open"]:
        return question
    cur = st["current"]
    rules = output_rules(steps.steps_of(ex)[cur - 1])
    found = {"step": cur, "label": label(ex, cur), "needs_output": bool(rules)}
    if not rules:
        return {"kind": "maybe", **found} if mode == "confirm" else question
    matched = len(rules) - len(check_output({"expect_output": rules}, text))
    found.update(matched=matched, checks=len(rules))
    if matched == len(rules) and mode in ("confirm", "accept"):
        return {"kind": "output", **found}
    if matched > 0 or mode == "confirm":
        return {"kind": "maybe", **found}
    return question


# --- quiz questions ------------------------------------------------------------------

def quiz_key(question: str) -> str:
    return hashlib.sha1(" ".join(question.split()).encode("utf-8")).hexdigest()[:12]


def _approvals(exercise_id: str) -> dict[str, dict[str, Any]]:
    with db.conn() as c:
        return {r["quiz_key"]: dict(r) for r in c.execute(
            "SELECT quiz_key, approved, body FROM quiz_approvals WHERE exercise_id = ?", (exercise_id,))}


def quiz_items(ex: dict[str, Any]) -> list[dict[str, Any]]:
    """Every quiz question of the exercise, in step order, with the teacher's
    approval and wording. A question marked `always` counts as approved until
    the teacher decides otherwise in the dashboard."""
    approvals = _approvals(ex["exercise_id"])
    items = []
    for n, st in enumerate(steps.steps_of(ex), 1):
        for q in st.get("quiz") or []:
            if isinstance(q, str):
                q = {"q": q}
            key = quiz_key(q["q"])
            a = approvals.get(key)
            always = q.get("always") is True
            items.append({
                "key": key, "step": n, "label": label(ex, n), "q": q["q"],
                "answer": q.get("answer") or "",
                "always": always,
                "approved": bool(a["approved"]) if a else always,
                "body": (a or {}).get("body") or q["q"],
            })
    return items


def set_quiz(ex: dict[str, Any], key: str, approved: bool, body: Optional[str] = None) -> dict[str, Any]:
    """Approve (or withdraw) a quiz question, optionally with new wording.
    Raises KeyError for a key the exercise doesn't have. Withdrawing changes
    only what is asked from now on; withdraw_asked() takes it back from the
    students already asked."""
    item = next((i for i in quiz_items(ex) if i["key"] == key), None)
    if item is None:
        raise KeyError(key)
    body = (body or "").strip() or None
    if body == item["q"]:
        body = None
    with db.conn() as c:
        c.execute(
            "INSERT INTO quiz_approvals (exercise_id, quiz_key, approved, body) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(exercise_id, quiz_key) DO UPDATE SET approved = excluded.approved, "
            "body = COALESCE(excluded.body, quiz_approvals.body), updated_at = CURRENT_TIMESTAMP",
            (ex["exercise_id"], key, int(approved), body),
        )
    return next(i for i in quiz_items(ex) if i["key"] == key)


# Statuses of a quiz probe that no longer counts: withdrawn before the answer
# (cancelled), after it (withdrawn), or done again after a reset (reset).
GONE = ("cancelled", "withdrawn", "reset")


def withdraw_asked(ex: dict[str, Any], key: str, course_id: Optional[str]) -> int:
    """The teacher withdrew a question: take it back from the course's students
    who were asked it. A question still open is cancelled (its next step no
    longer waits for it); an answer no longer counts (status 'withdrawn', kept
    for the record), and one that waited for the teacher no longer holds the
    student back. Each student's chat says so, quoting that question and the
    student's own answer to it. Returns how many students were told."""
    from backend import transcript  # transcript doesn't import pacing; avoids a cycle at import

    item = next((i for i in quiz_items(ex) if i["key"] == key), None)
    if item is None:
        raise KeyError(key)
    he = hebrew(ex)
    told = 0
    with db.conn() as c:
        sessions = [r["id"] for r in _latest_sessions(c, ex["exercise_id"], _course(course_id))]
    for sid in sessions:
        with db.conn() as c:
            rows = c.execute(
                "SELECT id, body, answer, status, quiz_step FROM probes WHERE session_id = ? AND quiz_key = ? "
                "AND status IN ('pending', 'answered') ORDER BY id", (sid, key)).fetchall()
            if not rows:
                continue
            c.execute("UPDATE probes SET status = 'cancelled' WHERE session_id = ? AND quiz_key = ? "
                      "AND status = 'pending'", (sid, key))
            c.execute("UPDATE probes SET status = 'withdrawn', "
                      "review_status = CASE WHEN review_status = 'waiting' THEN 'withdrawn' ELSE review_status END "
                      "WHERE session_id = ? AND quiz_key = ? AND status = 'answered'", (sid, key))
            c.execute("UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (sid,))
        # The latest one is what the student last saw: still open, or answered.
        last = rows[-1]
        lbl = label(ex, last["quiz_step"])
        question = _quote(last["body"])
        if last["status"] == "pending":
            text = (f"🚫 **המרצה ביטל את השאלה על שלב {lbl}.** אין צורך לענות עליה:\n\n{question}" if he else
                    f"🚫 **Your teacher cancelled the question about step {lbl}.** No need to answer it:\n\n{question}")
        else:
            answer = _quote(last["answer"] or "")
            text = (f"🚫 **המרצה ביטל את השאלה על שלב {lbl}:**\n\n{question}\n\nהתשובה שלכם הייתה:\n\n"
                    f"{answer}\n\nהיא לא נחשבת בציון." if he else
                    f"🚫 **Your teacher cancelled the question about step {lbl}:**\n\n{question}\n\n"
                    f"Your answer was:\n\n{answer}\n\nIt doesn't count in your grade.")
        transcript.record(sid, "system", text, kind="cancelled", step=last["quiz_step"], origin="server")
        told += 1
    return told


def _quote(text: str) -> str:
    """Markdown quote of a (multi-line) text."""
    return "\n".join("> " + line for line in (text or "").strip().splitlines()) or ">"


def ask_finished(ex: dict[str, Any], key: str, course_id: Optional[str]) -> int:
    """Ask an approved question now of the course's students who already
    finished its step without being asked it. Their next step waits for the
    answer, as after any question. Returns how many were asked."""
    item = next((i for i in quiz_items(ex) if i["key"] == key), None)
    if item is None:
        raise KeyError(key)
    if not item["approved"]:
        return 0
    asked = 0
    with db.conn() as c:
        for r in _latest_sessions(c, ex["exercise_id"], _course(course_id)):
            if _current(c, r["id"]) <= item["step"]:
                continue  # not there yet: asked when they finish the step
            if item["step"] in _skipped(c, r["id"]):
                continue  # moved past the step without doing it: nothing to ask about
            if c.execute("SELECT 1 FROM probes WHERE session_id = ? AND quiz_key = ? "
                         "AND status NOT IN ('cancelled', 'withdrawn', 'reset')", (r["id"], key)).fetchone():
                continue
            c.execute("INSERT INTO probes (session_id, body, source, quiz_key, quiz_step) "
                      "VALUES (?, ?, 'quiz', ?, ?)", (r["id"], item["body"], key, item["step"]))
            asked += 1
    return asked


def quiz_reference(ex: dict[str, Any], key: str) -> Optional[str]:
    """The teacher's model answer of a quiz question, for the grader."""
    item = next((i for i in quiz_items(ex) if i["key"] == key), None)
    return (item or {}).get("answer") or None


def pending_quiz(session_id: str) -> list[dict[str, Any]]:
    with db.conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, body, quiz_step FROM probes WHERE session_id = ? AND status = 'pending' "
            "AND quiz_key IS NOT NULL ORDER BY id", (session_id,))]


# --- a quiz answer that waits for the teacher ------------------------------------------
# exercise.yaml `quiz_review`: which grades (0..2, by the grader) keep the
# student from moving on until the teacher decides:
#   partial (default): an answer graded 0/2 or 1/2; only 2/2 moves on by itself.
#   zero: an answer graded 0/2.
#   off: none; the grade is only recorded (as it was before November 2026).
# An answer the grader couldn't grade (an LLM outage) never waits.
QUIZ_REVIEW = ("zero", "partial", "off")


def quiz_review(ex: Optional[dict[str, Any]]) -> str:
    value = (ex or {}).get("quiz_review")
    return value if value in QUIZ_REVIEW else "partial"


def needs_review(ex: Optional[dict[str, Any]], grade: Optional[int]) -> bool:
    """Does a quiz answer with this grade wait for the teacher?"""
    mode = quiz_review(ex)
    if grade is None or mode == "off" or not is_paced(ex):
        return False
    return grade <= (1 if mode == "partial" else 0)


def held_quiz(session_id: str) -> list[dict[str, Any]]:
    """The session's quiz answers that wait for the teacher, oldest first."""
    with db.conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, body, quiz_step FROM probes WHERE session_id = ? AND review_status = 'waiting' "
            "AND quiz_key IS NOT NULL ORDER BY id", (session_id,))]


def review_answer(ex: dict[str, Any], probe_id: int, approve: bool, note: Optional[str] = None,
                  grade: Optional[int] = None) -> bool:
    """The teacher decides about a quiz answer that waits for them. Approve:
    the student continues; `grade` (0..2), when given, replaces the grader's.
    Otherwise the answer is kept as 'returned' and the question is asked again.
    Either way the student's chat says so (the transcript), with `note`: the
    text the teacher chose for the student (the grader's feedback, the model
    answer, or their own). False when the answer doesn't wait (decided already, or the
    student was sent back meanwhile) or isn't of this exercise."""
    from backend import transcript  # transcript doesn't import pacing; avoids a cycle at import

    note = (note or "").strip() or None
    with db.conn() as c:
        p = c.execute(
            "SELECT p.id, p.session_id, p.body, p.quiz_key, p.quiz_step FROM probes p "
            "JOIN sessions s ON s.id = p.session_id "
            "WHERE p.id = ? AND s.exercise = ? AND p.review_status = 'waiting' AND p.quiz_key IS NOT NULL",
            (probe_id, ex["exercise_id"])).fetchone()
        if p is None:
            return False
        if approve:
            c.execute(
                "UPDATE probes SET review_status = 'approved', teacher_note = ?, reviewed_at = CURRENT_TIMESTAMP, "
                "override_grade = COALESCE(?, override_grade) WHERE id = ?", (note, grade, probe_id))
        else:
            c.execute(
                "UPDATE probes SET review_status = 'returned', teacher_note = ?, "
                "reviewed_at = CURRENT_TIMESTAMP WHERE id = ?", (note, probe_id))
            c.execute(
                "INSERT INTO probes (session_id, body, source, quiz_key, quiz_step) VALUES (?, ?, 'quiz', ?, ?)",
                (p["session_id"], p["body"], p["quiz_key"], p["quiz_step"]))
        c.execute("UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (p["session_id"],))
    lbl = label(ex, p["quiz_step"])
    he = hebrew(ex)
    if approve:
        text = (f"✅ המרצה קרא את התשובה שלכם לשאלה על שלב {lbl} ואישר לכם להמשיך." if he else
                f"✅ Your teacher read your answer to the question about step {lbl}: you can continue.")
        if grade is not None:
            text += f" הציון עודכן ל־{grade}/2." if he else f" The grade is now {grade}/2."
        if note:
            text += "\n\n" + _quote(note)
        transcript.record(p["session_id"], "system", text, kind="result", step=p["quiz_step"], origin="server")
    else:
        text = (f"↩️ המרצה קרא את התשובה שלכם לשאלה על שלב {lbl} וביקש שתענו עליה שוב. "
                "השאלה מופיעה כאן שוב." if he else
                f"↩️ Your teacher read your answer to the question about step {lbl} and asks you to "
                "answer it again. The question is shown here again.")
        if note:
            text += "\n\n" + _quote(note)
        transcript.record(p["session_id"], "system", text, kind="note", origin="server")
    return True


# --- a student's progress ----------------------------------------------------------------

def step_text(ex: dict[str, Any], n: int) -> str:
    """The step as the chat shows it: a header line, then the step's text."""
    st = steps.steps_of(ex)[n - 1]
    he = hebrew(ex)
    head = f"### {'שלב' if he else 'Step'} {label(ex, n)} · {st['title']}"
    if st.get("minutes"):
        head += f"\n_{'זמן' if he else 'Time'}: {st['minutes']} {'דקות' if he else 'minutes'}_"
    return head + "\n\n" + st["text"].strip()


def state(session: dict[str, Any], ex: dict[str, Any]) -> dict[str, Any]:
    """Where the student is: the step they work on (when it is open to them),
    or what they are waiting for."""
    sid = session["id"]
    n_total = total(ex)
    cur = steps.current_step(sid)
    rel = released_for(ex, sid, session.get("course_id"))
    quiz = pending_quiz(sid)
    held = held_quiz(sid)
    with db.conn() as c:
        review = c.execute(
            "SELECT 1 FROM step_checks WHERE session_id = ? AND step = ? AND status = 'waiting'",
            (sid, cur)).fetchone() is not None
    out: dict[str, Any] = {
        "total": n_total,
        "current": cur,
        "current_label": label(ex, cur) if cur <= n_total else None,
        "released": rel,
        "finished": cur > n_total,
        "quiz_pending": len(quiz),
        # Quiz answers graded too low: the teacher lets them continue or asks again.
        "quiz_review": len(held),
        # Finished every open step: the teacher opens the next one.
        "waiting_teacher": cur <= n_total and cur > rel and not quiz and not held,
        "open": cur <= n_total and cur <= rel and not quiz and not held,
        # Their last output didn't match; the teacher can let them continue.
        "waiting_review": review,
    }
    if out["open"]:
        st = steps.steps_of(ex)[cur - 1]
        out["step"] = {
            "n": cur, "label": label(ex, cur), "title": st["title"],
            "markdown": step_text(ex, cur),
            "needs_output": bool(output_rules(st)),
        }
    return out


def _complete(c, ex: dict[str, Any], sid: str, n: int) -> int:
    """Step n is done: ask its approved quiz questions. Returns how many."""
    approved_quiz = [q for q in quiz_items(ex) if q["step"] == n and q["approved"]]
    for q in approved_quiz:
        c.execute(
            "INSERT INTO probes (session_id, body, source, quiz_key, quiz_step) "
            "VALUES (?, ?, 'quiz', ?, ?)",
            (sid, q["body"], q["key"], n),
        )
    c.execute("UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (sid,))
    return len(approved_quiz)


def finish(session: dict[str, Any], ex: dict[str, Any], n: int, output: str) -> dict[str, Any]:
    """The student says step n is done. `status` is one of:
    done, missing (the output lacks something; it waits for the teacher),
    wrong_step, not_open, quiz_pending, quiz_review (a quiz answer of theirs
    waits for the teacher), finished."""
    sid = session["id"]
    st_now = state(session, ex)
    cur = st_now["current"]
    if st_now["finished"]:
        return {"status": "finished", "state": st_now}
    if n != cur:
        return {"status": "wrong_step", "state": st_now}
    if st_now["quiz_pending"]:
        return {"status": "quiz_pending", "state": st_now}
    if st_now["quiz_review"]:
        return {"status": "quiz_review", "state": st_now}
    if cur > st_now["released"]:
        return {"status": "not_open", "state": st_now}

    step = steps.steps_of(ex)[cur - 1]
    rules = output_rules(step)
    missing = check_output(step, output) if rules else []
    answer = (output or "")[-_OUTPUT_MAX:]
    with db.conn() as c:
        # Only the latest attempt at a step waits for the teacher.
        c.execute("DELETE FROM step_checks WHERE session_id = ? AND step = ? AND status = 'waiting'",
                  (sid, cur))
        if missing:
            c.execute(
                "INSERT INTO step_checks (session_id, step, answer, status, delivered, auto_ok, missing) "
                "VALUES (?, ?, ?, 'waiting', 1, 0, ?)",
                (sid, cur, answer, json.dumps(missing, ensure_ascii=False)),
            )
            c.execute("UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (sid,))
            quiz = None
        else:
            c.execute(
                "INSERT INTO step_checks (session_id, step, answer, status, delivered, decided_at, auto_ok) "
                "VALUES (?, ?, ?, 'approved', 1, CURRENT_TIMESTAMP, ?)",
                (sid, cur, answer, None if not rules else 1),
            )
            quiz = _complete(c, ex, sid, cur)
    if missing:
        return {"status": "missing", "missing": missing, "state": state(session, ex)}
    return {"status": "done", "ok": None if not rules else True, "missing": [],
            "quiz": quiz, "state": state(session, ex)}


def let_through(ex: dict[str, Any], session_id: str, n: int) -> bool:
    """The teacher lets a student continue past step n although their output
    didn't match. False when nothing of theirs waits at that step."""
    with db.conn() as c:
        row = c.execute(
            "SELECT id FROM step_checks WHERE session_id = ? AND step = ? AND status = 'waiting' "
            "ORDER BY id DESC LIMIT 1", (session_id, n)).fetchone()
        if row is None or _current(c, session_id) != n:
            return False
        c.execute("UPDATE step_checks SET status = 'approved', forced = 1, decided_at = CURRENT_TIMESTAMP "
                  "WHERE id = ?", (row["id"],))
        _complete(c, ex, session_id, n)
    return True


def decline(ex: dict[str, Any], session_id: str, n: int, note: Optional[str] = None) -> bool:
    """The teacher sends a student's non-matching output for step n back: the
    student stays on the step and is told so in their chat (the transcript),
    with the teacher's note. The output is kept (status 'returned'). False when
    nothing of theirs waits at that step."""
    from backend import transcript  # transcript doesn't import pacing; avoids a cycle at import

    note = (note or "").strip() or None
    with db.conn() as c:
        row = c.execute(
            "SELECT id FROM step_checks WHERE session_id = ? AND step = ? AND status = 'waiting' "
            "ORDER BY id DESC LIMIT 1", (session_id, n)).fetchone()
        if row is None or _current(c, session_id) != n:
            return False
        c.execute("UPDATE step_checks SET status = 'returned', teacher_note = ?, decided_at = CURRENT_TIMESTAMP "
                  "WHERE id = ?", (note, row["id"]))
    lbl = label(ex, n)
    text = (f"↩️ המרצה בדק את הפלט ששלחתם לשלב {lbl}, והוא עוד לא תקין. בדקו את השלב, הריצו שוב, "
            "והדביקו את הפלט החדש." if hebrew(ex) else
            f"↩️ Your teacher checked the output you sent for step {lbl}: it isn't right yet. Check the "
            "step, run it again, and paste the new output.")
    if note:
        text += f"\n\n> {note}"
    transcript.record(session_id, "system", text, kind="returned", step=n, origin="server")
    return True


# --- the teacher moves a student ------------------------------------------------------------

def move_note(ex: dict[str, Any], n: int, how: str) -> str:
    """The note the student's chat shows when the teacher moves them to step n.
    how: back, forward, or again (the step they are on, from its start)."""
    lbl = label(ex, n)
    if hebrew(ex):
        head = "⏸️ **המרצה עצר אתכם.**"
        if how == "forward":
            return f"{head} המרצה העביר אתכם קדימה לשלב {lbl}. השלבים שבדרך דולגו; ממשיכים מכאן."
        if how == "again":
            return f"{head} מתחילים את שלב {lbl} מההתחלה (פלט שהדבקתם לשלב הזה, אם היה, לא נשמר). השלב מופיע כאן שוב."
        where = "להתחלה (שלב 1)" if n == 1 and lbl == "1" else f"לשלב {lbl}"
        return (f"{head} המרצה החזיר אתכם {where}. מה שעשיתם מהשלב הזה והלאה (פלטים ותשובות) "
                "לא נחשב, ועושים אותו שוב: השלב מופיע כאן שוב.")
    head = "⏸️ **Your teacher stopped you here.**"
    if how == "forward":
        return f"{head} They moved you ahead to step {lbl}; the steps in between were skipped. Carry on from here."
    if how == "again":
        return f"{head} Start step {lbl} over (an output you sent for it, if any, wasn't kept). The step is shown again."
    return (f"{head} They sent you back to step {lbl}. Your work from that step on (outputs and answers) "
            "no longer counts, and you do it again: the step is shown again.")


def move_to(ex: dict[str, Any], session_id: str, course_id: Optional[str], n: int) -> dict[str, Any]:
    """Move a student to step n (1..total) and interrupt their chat (a note in
    the transcript). Back: steps.reset_to; their work from n on no longer
    counts, and steps opened for them alone no longer reach past n
    (limit_own). Forward: steps.skip_to, and the steps up to n are opened for this
    student (sessions.released_to) when the course hasn't opened them. The step
    they are on: it starts over (a pending output is dropped). Returns from, to
    and how ('back' | 'forward' | 'again')."""
    n = max(1, min(int(n), total(ex)))
    cur = steps.current_step(session_id)
    # The step they are moved to is shown to them, open to the class or not.
    if is_paced(ex) and n > released_for(ex, session_id, course_id):
        with db.conn() as c:
            c.execute("UPDATE sessions SET released_to = ? WHERE id = ?", (n, session_id))
    if n > cur:
        out = steps.skip_to(session_id, n, move_note(ex, n, "forward"))
        how = "forward"
    elif n < cur:
        out = steps.reset_to(session_id, n, move_note(ex, n, "back"))
        how = "back"
    else:
        out = steps.reset_to(session_id, n, move_note(ex, n, "again"), again=True)
        how = "again"
    return {**out, "how": how}


def _current(c, session_id: str) -> int:
    """steps.current_step inside an open transaction."""
    row = c.execute("SELECT MAX(step) AS s FROM step_checks WHERE session_id = ? "
                    f"AND status IN {steps.PASSED_SQL}", (session_id,)).fetchone()
    return (row["s"] or 0) + 1


def _skipped_steps(checks) -> set[int]:
    """The steps of these step_checks rows the student skipped (moved past by
    the teacher, steps.skip_to) and didn't do."""
    return ({k["step"] for k in checks if k["status"] == "skipped"}
            - {k["step"] for k in checks if k["status"] == "approved"})


def _skipped(c, session_id: str) -> set[int]:
    """_skipped_steps of a session, inside an open transaction."""
    return _skipped_steps(c.execute(
        f"SELECT step, status FROM step_checks WHERE session_id = ? AND status IN {steps.PASSED_SQL}",
        (session_id,)).fetchall())


# --- the teacher's view ---------------------------------------------------------------------

def _latest_sessions(c, exercise_id: str, course_id: str) -> list:
    """Each student's latest session in this exercise and course ('' = none)."""
    rows = c.execute(
        "SELECT s.id, s.user_id, u.username, s.last_active_at FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.exercise = ? AND COALESCE(s.course_id, '') = ? "
        "AND u.role = 'student' ORDER BY s.last_active_at", (exercise_id, course_id)).fetchall()
    return list({r["user_id"]: r for r in rows}.values())


def _courses_of(c, exercise_id: str) -> list[tuple[str, str]]:
    """(course_id, name) of the courses that offer the exercise or have a session
    in it; '' = students outside every course."""
    names = {r["course_id"]: r["name"] for r in c.execute("SELECT course_id, name FROM courses")}
    ids = [r["course_id"] for r in c.execute(
        "SELECT course_id FROM course_exercises WHERE exercise_id = ? ORDER BY course_id", (exercise_id,))]
    for r in c.execute("SELECT DISTINCT COALESCE(course_id, '') AS cid FROM sessions WHERE exercise = ?",
                       (exercise_id,)):
        if r["cid"] not in ids:
            ids.append(r["cid"])
    return [(cid, names.get(cid, "")) for cid in ids]


def overview(ex: dict[str, Any]) -> dict[str, Any]:
    """Everything the dashboard's class-pacing panel shows for one exercise."""
    eid = ex["exercise_id"]
    n_total = total(ex)
    quiz = quiz_items(ex)
    step_meta = [{
        "n": n, "label": label(ex, n), "title": st["title"], "minutes": st.get("minutes"),
        "checked": bool(output_rules(st)),
        # What the teacher compares a pasted output with (teacher.yaml).
        "expected": str(st.get("expected") or ""),
        "expected_output": str(st.get("expected_output") or ""),
        "hints": [r["hint"] for r in output_rules(st)],
        "quiz": sum(1 for q in quiz if q["step"] == n),
        "quiz_approved": sum(1 for q in quiz if q["step"] == n and q["approved"]),
    } for n, st in enumerate(steps.steps_of(ex), 1)]

    courses = []
    with db.conn() as c:
        for cid, name in _courses_of(c, eid):
            latest = {r["user_id"]: r for r in _latest_sessions(c, eid, cid)}
            members = (c.execute("SELECT COUNT(*) AS n FROM course_members WHERE course_id = ?",
                                 (cid,)).fetchone()["n"] if cid else None)
            students = []
            skipped: dict[str, set[int]] = {}  # session id -> the steps it skipped
            for r in sorted(latest.values(), key=lambda r: r["username"].lower()):
                checks = c.execute(
                    "SELECT step, status, auto_ok, forced, missing, answer, created_at FROM step_checks "
                    "WHERE session_id = ? AND status IN ('approved', 'skipped', 'waiting') ORDER BY step, id",
                    (r["id"],)).fetchall()
                skipped[r["id"]] = _skipped_steps(checks)
                own = c.execute("SELECT released_to FROM sessions WHERE id = ?", (r["id"],)).fetchone()
                quiz_rows = c.execute(
                    "SELECT id, quiz_key, quiz_step, body, answer, status, auto_grade, override_grade, "
                    "review_status, auto_why, answered_at "
                    "FROM probes WHERE session_id = ? AND quiz_key IS NOT NULL ORDER BY id",
                    (r["id"],)).fetchall()
                cur = (max((k["step"] for k in checks if k["status"] in steps.PASSED), default=0)) + 1
                waiting = [k for k in checks if k["status"] == "waiting" and k["step"] == cur]
                students.append({
                    "session_id": r["id"],
                    "username": r["username"],
                    "current": cur,
                    "current_label": label(ex, cur) if cur <= n_total else None,
                    "last_active_at": r["last_active_at"],
                    # Opened for this student beyond the course (moved forward): up to this step.
                    "released_to": (own["released_to"] or None) if own else None,
                    # Steps the teacher moved them past without doing them.
                    "skipped": [label(ex, k["step"]) for k in checks if k["status"] == "skipped"],
                    "quiz_pending": sum(1 for q in quiz_rows if q["status"] == "pending"),
                    # Quiz answers graded too low: the teacher decides (review_answer).
                    "quiz_review": sum(1 for q in quiz_rows if q["review_status"] == "waiting"),
                    # Their output for the current step didn't match: the teacher decides.
                    "waiting": [{
                        "step": k["step"], "label": label(ex, k["step"]),
                        "missing": json.loads(k["missing"]) if k["missing"] else [],
                        "output": (k["answer"] or "")[-4000:],
                        "created_at": k["created_at"],
                    } for k in waiting[-1:]],
                    # Steps the teacher let them past although the output didn't match.
                    "flags": [{
                        "step": k["step"], "label": label(ex, k["step"]),
                        "missing": json.loads(k["missing"]) if k["missing"] else [],
                        "output": (k["answer"] or "")[-2000:],
                    } for k in checks if k["status"] == "approved" and k["auto_ok"] == 0],
                    "quiz": [{
                        "id": q["id"],
                        "key": q["quiz_key"], "step": q["quiz_step"], "body": q["body"],
                        "answer": q["answer"], "status": q["status"],
                        "grade": q["override_grade"] if q["override_grade"] is not None else q["auto_grade"],
                        # waiting | approved | returned | reset | skipped | withdrawn; None: needed no review.
                        "review": q["review_status"],
                        "why": q["auto_why"],
                        "answered_at": q["answered_at"],
                    } for q in quiz_rows],
                })
            courses.append({
                "course_id": cid,
                "name": name,
                "released": released(ex, cid),
                "members": members,
                "students": students,
                # Per step: finished it / working on it now.
                "done": {n: sum(1 for s in students if s["current"] > n) for n in range(1, n_total + 1)},
                "here": {n: sum(1 for s in students if s["current"] == n) for n in range(1, n_total + 1)},
                # Per question: students past its step who were never asked it
                # (it wasn't approved yet when they finished the step). Not the
                # ones moved past the step without doing it.
                "quiz_missed": {q["key"]: sum(
                    1 for s in students if s["current"] > q["step"]
                    and q["step"] not in skipped[s["session_id"]]
                    and not any(a["key"] == q["key"] and a["status"] not in GONE for a in s["quiz"])
                ) for q in quiz},
            })
    return {
        "exercise_id": eid,
        "total": n_total,
        "open_steps": open_from_start(ex),
        "steps": step_meta,
        "quiz": quiz,
        "courses": courses,
    }


def tutor_context(ex: dict[str, Any], session_id: str, course_id: Optional[str]) -> str:
    """System-prompt block for a class-paced lab: the step the student works on
    (or the last one they finished), and nothing later."""
    n_total = total(ex)
    cur = steps.current_step(session_id)
    if cur > n_total:
        return ("PROGRESS: the student finished all the steps. Help with questions about "
                "their work; there is nothing more to hand out.")
    rel = released_for(ex, session_id, course_id)
    how = ("When the student finishes a step, they click the 'סיימתי' (done) button under the "
           "step in this chat and paste the step's terminal output; the server checks it and "
           "shows the next step. If it doesn't match, the teacher sees it and can let them "
           "continue. Never claim to move them on yourself, and never tell them what the output "
           "should look like.")
    if cur > rel and cur == 1:
        return ("PROGRESS: the teacher has not opened the first step yet. Answer general "
                "questions; never describe or hint at the steps.")
    if cur > 1 and held_quiz(session_id):
        return (f"PROGRESS: the student finished step {label(ex, cur - 1)}. Their answer to a "
                "question about it waits for the teacher, who will let them continue or ask them "
                "to answer again; the next step appears only then. Answer questions about the "
                "steps so far; never describe, hint at, or list later steps.\n\n"
                "LAST STEP THEY DID:\n" + step_text(ex, cur - 1) + "\n\n" + how)
    if cur > rel:
        return (f"PROGRESS: the student finished step {label(ex, cur - 1)} and waits for the "
                "teacher to open the next step for the whole class. Answer questions about the "
                "steps so far; never describe, hint at, or list later steps.\n\n"
                "LAST STEP THEY DID:\n" + step_text(ex, cur - 1) + "\n\n" + how)
    return ("CURRENT STEP — help ONLY with this one:\n" + step_text(ex, cur)
            + "\n\nNever describe, hint at, or list later steps. " + how)
