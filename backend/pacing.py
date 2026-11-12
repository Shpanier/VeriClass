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


def set_released(ex: dict[str, Any], course_id: Optional[str], n: int) -> int:
    """Open steps 1..n to the course, closing any later ones; 0 = none open.
    Students past n keep their progress and wait. Returns the value stored."""
    n = max(0, min(int(n), total(ex)))
    with db.conn() as c:
        c.execute(
            "INSERT INTO step_release (course_id, exercise_id, released) VALUES (?, ?, ?) "
            "ON CONFLICT(course_id, exercise_id) DO UPDATE SET released = excluded.released, "
            "updated_at = CURRENT_TIMESTAMP",
            (_course(course_id), ex["exercise_id"], n),
        )
    return n


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
    Raises KeyError for a key the exercise doesn't have."""
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
            if c.execute("SELECT 1 FROM probes WHERE session_id = ? AND quiz_key = ? AND status != 'cancelled'",
                         (r["id"], key)).fetchone():
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
    rel = released(ex, session.get("course_id"))
    quiz = pending_quiz(sid)
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
        # Finished every open step: the teacher opens the next one.
        "waiting_teacher": cur <= n_total and cur > rel and not quiz,
        "open": cur <= n_total and cur <= rel and not quiz,
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
    wrong_step, not_open, quiz_pending, finished."""
    sid = session["id"]
    st_now = state(session, ex)
    cur = st_now["current"]
    if st_now["finished"]:
        return {"status": "finished", "state": st_now}
    if n != cur:
        return {"status": "wrong_step", "state": st_now}
    if st_now["quiz_pending"]:
        return {"status": "quiz_pending", "state": st_now}
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


def _current(c, session_id: str) -> int:
    """steps.current_step inside an open transaction."""
    row = c.execute("SELECT MAX(step) AS s FROM step_checks WHERE session_id = ? AND status = 'approved'",
                    (session_id,)).fetchone()
    return (row["s"] or 0) + 1


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
            for r in sorted(latest.values(), key=lambda r: r["username"].lower()):
                checks = c.execute(
                    "SELECT step, status, auto_ok, forced, missing, answer, created_at FROM step_checks "
                    "WHERE session_id = ? AND status IN ('approved', 'waiting') ORDER BY step, id",
                    (r["id"],)).fetchall()
                quiz_rows = c.execute(
                    "SELECT quiz_key, quiz_step, body, answer, status, auto_grade, override_grade "
                    "FROM probes WHERE session_id = ? AND quiz_key IS NOT NULL ORDER BY id",
                    (r["id"],)).fetchall()
                cur = (max((k["step"] for k in checks if k["status"] == "approved"), default=0)) + 1
                waiting = [k for k in checks if k["status"] == "waiting" and k["step"] == cur]
                students.append({
                    "session_id": r["id"],
                    "username": r["username"],
                    "current": cur,
                    "current_label": label(ex, cur) if cur <= n_total else None,
                    "last_active_at": r["last_active_at"],
                    "quiz_pending": sum(1 for q in quiz_rows if q["status"] == "pending"),
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
                        "key": q["quiz_key"], "step": q["quiz_step"], "body": q["body"],
                        "answer": q["answer"], "status": q["status"],
                        "grade": q["override_grade"] if q["override_grade"] is not None else q["auto_grade"],
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
                # (it wasn't approved yet when they finished the step).
                "quiz_missed": {q["key"]: sum(
                    1 for s in students if s["current"] > q["step"]
                    and not any(a["key"] == q["key"] and a["status"] != "cancelled" for a in s["quiz"])
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
    rel = released(ex, course_id)
    how = ("When the student finishes a step, they click the 'סיימתי' (done) button under the "
           "step in this chat and paste the step's terminal output; the server checks it and "
           "shows the next step. If it doesn't match, the teacher sees it and can let them "
           "continue. Never claim to move them on yourself, and never tell them what the output "
           "should look like.")
    if cur > rel and cur == 1:
        return ("PROGRESS: the teacher has not opened the first step yet. Answer general "
                "questions; never describe or hint at the steps.")
    if cur > rel:
        return (f"PROGRESS: the student finished step {label(ex, cur - 1)} and waits for the "
                "teacher to open the next step for the whole class. Answer questions about the "
                "steps so far; never describe, hint at, or list later steps.\n\n"
                "LAST STEP THEY DID:\n" + step_text(ex, cur - 1) + "\n\n" + how)
    return ("CURRENT STEP — help ONLY with this one:\n" + step_text(ex, cur)
            + "\n\nNever describe, hint at, or list later steps. " + how)
