"""Step-by-step labs with teacher sign-off.

An exercise may define `steps:` (title, text for students, expected answer for
the teacher only). Students see one step at a time. When a pair writes
"Done with step N", their answer is stored in `step_checks` and their /ask
request waits while the teacher compares it with the expected answer in the
dashboard. Approving releases the next step into the chat; sending it back
returns the teacher's note. The tutor model never sees `expected` and never
hands out steps itself.
"""
import asyncio
import re
from typing import Any, Optional

from backend import db

# "Done with step 2", "finished step 2", "we completed step 2", "סיימנו שלב 2"
_DONE_EN = re.compile(r"\b(?:done|finished|completed)\b[^\n]{0,25}?\bstep\b\s*(\d+)?", re.I)
_DONE_HE = re.compile(r"סיימ\S*\s+(?:את\s+)?שלב\s*(\d+)?")

# One event per step_check id; the /ask handler awaits it, the teacher's
# decision sets it. In-memory, like the review queue (single uvicorn process).
_EVENTS: dict[int, asyncio.Event] = {}


def event_for(check_id: int) -> asyncio.Event:
    return _EVENTS.setdefault(check_id, asyncio.Event())


def drop_event(check_id: int) -> None:
    _EVENTS.pop(check_id, None)


def _wake(check_ids: list[int]) -> None:
    """Wake the /ask requests waiting for these checks (as the teacher's
    decision does): each reads its row again, finds it delivered, and ends."""
    for check_id in check_ids:
        event_for(check_id).set()


def steps_of(ex: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    return list((ex or {}).get("steps") or [])


def parse_done(message: str) -> Optional[int]:
    """0 = 'done' without a number, N = 'done with step N', None = not a done message."""
    m = _DONE_EN.search(message) or _DONE_HE.search(message)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else 0


# A step_checks status that counts as past the step: done, or skipped (the
# teacher moved the student past it, skip_to). The session works on the step
# after the highest such row.
PASSED = ("approved", "skipped")
PASSED_SQL = "(" + ", ".join(f"'{s}'" for s in PASSED) + ")"


def current_step(session_id: str) -> int:
    """1-based step the session is working on = highest approved (or skipped) step + 1."""
    with db.conn() as c:
        row = c.execute(
            f"SELECT MAX(step) AS s FROM step_checks WHERE session_id = ? AND status IN {PASSED_SQL}",
            (session_id,),
        ).fetchone()
    return (row["s"] or 0) + 1


def current_step_for_user(user_id: int, exercise_id: str) -> int:
    with db.conn() as c:
        row = c.execute(
            "SELECT id FROM sessions WHERE user_id = ? AND exercise = ? "
            "ORDER BY last_active_at DESC LIMIT 1",
            (user_id, exercise_id),
        ).fetchone()
    return current_step(row["id"]) if row else 1


CODE_START = "▼▼▼ code: select these lines and copy (Cmd+C / Ctrl+C) ▼▼▼"
CODE_END = "▲▲▲ end of code ▲▲▲"


def to_plain(md: str) -> str:
    """Markdown -> readable plain text, for the IDE plugin's chat (a plain text
    pane that shows ** and ``` literally). Code fences become a block between
    two marker lines, NOT indented, so a select + copy pastes as valid Python."""
    out, in_code = [], False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append(CODE_START if in_code else CODE_END)
            continue
        if in_code:
            out.append(line)
            continue
        line = line.replace("**", "").replace("`", "")
        if line.lstrip().startswith("- "):
            indent = len(line) - len(line.lstrip())
            line = " " * indent + "• " + line.lstrip()[2:]
        out.append(line)
    return "\n".join(out)


def step_banner(ex: dict[str, Any], n: int) -> str:
    """Plain-text version of a step with a banner, for the plugin chat."""
    steps = steps_of(ex)
    st = steps[n - 1]
    bar = "━" * 34
    return (f"{bar}\nSTEP {n} OF {len(steps)}: {st['title'].upper()}\n{bar}\n\n"
            + to_plain(st["text"].strip()))


def step_markdown(ex: dict[str, Any], n: int) -> str:
    steps = steps_of(ex)
    st = steps[n - 1]
    return f"**Step {n} of {len(steps)}: {st['title']}**\n\n{st['text'].strip()}"


def undelivered_decision(session_id: str) -> Optional[dict[str, Any]]:
    with db.conn() as c:
        row = c.execute(
            "SELECT * FROM step_checks WHERE session_id = ? AND status != 'pending' "
            "AND delivered = 0 ORDER BY id LIMIT 1",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def decision_message(ex: dict[str, Any], check: dict[str, Any], plain: bool = False) -> str:
    n, total = check["step"], len(steps_of(ex))
    note = (check.get("teacher_note") or "").strip()
    if check["status"] == "returned":
        msg = f"↩️ Your teacher asks you to look again at step {n}."
        if note:
            msg += f"\n\n{'Teacher: ' if plain else '> '}{note}"
        return msg + f"\n\nFix it, then write \"Done with step {n}\" again."
    msg = f"✅ Your teacher approved step {n}."
    if note:
        msg += f"\n\n{'Teacher: ' if plain else '> '}{note}"
    if n < total:
        nxt = step_banner(ex, n + 1) if plain else step_markdown(ex, n + 1)
        return msg + "\n\n" + nxt
    return msg + "\n\n🎉 You finished all the steps of this lab. Well done!"


def mark_delivered(check_id: int) -> None:
    with db.conn() as c:
        c.execute("UPDATE step_checks SET delivered = 1 WHERE id = ?", (check_id,))


# What a step submission may carry from the plugin (0.4.3+): the open file, the
# Run console, and the output of the exercise's check command. Stored sizes.
_CODE_MAX = 200_000
_CONSOLE_MAX = 50_000
_CHECK_MAX = 20_000


def submit(session_id: str, step: int, answer: str,
           attachment: Optional[dict[str, Any]] = None) -> int:
    """Store (or extend) the pending check for this step; returns its id. The
    newest attachment replaces an earlier one."""
    with db.conn() as c:
        row = c.execute(
            "SELECT id, answer FROM step_checks WHERE session_id = ? AND step = ? "
            "AND status = 'pending' ORDER BY id DESC LIMIT 1",
            (session_id, step),
        ).fetchone()
        if row:
            c.execute(
                "UPDATE step_checks SET answer = ? WHERE id = ?",
                (row["answer"] + "\n\n" + answer, row["id"]),
            )
            check_id = row["id"]
        else:
            check_id = c.execute(
                "INSERT INTO step_checks (session_id, step, answer) VALUES (?, ?, ?)",
                (session_id, step, answer),
            ).lastrowid
        a = attachment or {}
        if any((a.get(k) or "").strip() for k in ("source", "console", "check_output")):
            c.execute(
                "UPDATE step_checks SET code_filename = ?, code_text = ?, console_text = ?, "
                "check_output = ? WHERE id = ?",
                ((a.get("filename") or "")[:200] or None, (a.get("source") or "")[:_CODE_MAX] or None,
                 (a.get("console") or "")[-_CONSOLE_MAX:] or None,
                 (a.get("check_output") or "")[-_CHECK_MAX:] or None, check_id),
            )
        return check_id


# --- helping the teacher decide ----------------------------------------------
# In October 2026, 7 of 8 approvals in one class went to pairs whose log file was
# broken, and 2 of 4 in another to answers covering one question of six. These
# give the teacher the facts next to each submission.

_ITEM = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+")
_ASK_LINE = re.compile(r"^\s*(?:\*\*)?(?:ענו|answer)\b", re.I)


def question_count(step: dict[str, Any]) -> Optional[int]:
    """How many questions a step asks: `questions: N` in the exercise (teacher
    file), else the items of the last list in its text (after a line starting
    "Answer"/"ענו", when there is one). None when it can't tell."""
    if isinstance(step.get("questions"), int) and step["questions"] > 0:
        return step["questions"]
    lines, in_code = [], False
    for line in (step.get("text") or "").splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            lines.append(line)
    start = max((i for i, ln in enumerate(lines) if _ASK_LINE.match(ln)), default=None)
    seg = lines[start + 1:] if start is not None else lines
    blocks: list[int] = []
    in_block = False
    for line in seg:
        if _ITEM.match(line):
            if not in_block:
                blocks.append(0)
                in_block = True
            blocks[-1] += 1
        elif not line.strip() or (in_block and line[:1] in (" ", "\t")):
            continue  # a blank line, or an item's continuation line
        else:
            in_block = False
    if blocks:
        return blocks[-1]
    if start is not None:
        return max(1, lines[start].count("?"))
    return None


# An answer's numbering: "1.", "2)", "q3 -", "שאלה 4:", "סעיף 5", or a number
# glued to the text right after the colon ("1רשומה…").
_MARK = re.compile(
    r"(?:^|[\s:;,])(?:[qQ]\s*|שאלה\s*|סעיף\s*)?(\d{1,2})(?:\s*[.):\-–]|(?=[֐-׿A-Za-z]))"
)
_DONE_PREFIX = re.compile(
    r"^.*?(?:" + _DONE_EN.pattern + "|" + _DONE_HE.pattern + r")[^\n:]*:?", re.I | re.S
)
_ANSWERS_WORD = re.compile(r"^\s*(?:התשובות שלנו|התשובות שלי|our answers|my answers|answers)\s*:?", re.I)


def answered_count(answer: str, questions: Optional[int]) -> Optional[int]:
    """Roughly how many of the step's questions the submission answers: the
    distinct question numbers it uses, else its non-empty lines. An estimate."""
    if not questions:
        return None
    body = _DONE_PREFIX.sub("", answer or "", count=1)
    body = _ANSWERS_WORD.sub("", body.strip(), count=1).strip()
    if not body:
        return 0
    marks = {int(m) for m in _MARK.findall(body) if 1 <= int(m) <= questions}
    if marks:
        return len(marks)
    lines = [ln for ln in body.splitlines() if ln.strip()]
    return min(len(lines), questions)


_EVIDENCE_RECENT = 6
_EVIDENCE_OUTPUT = 400


def evidence(session_id: str, step: dict[str, Any]) -> dict[str, Any]:
    """Terminal facts for a step submission: the step's `evidence` rules (teacher
    file: the last command matching `command`, and whether its output matches
    `expect`), and the session's last few terminal lines since its previous
    decided step."""
    with db.conn() as c:
        since = c.execute(
            "SELECT MAX(decided_at) AS t FROM step_checks WHERE session_id = ? AND status != 'pending'",
            (session_id,),
        ).fetchone()["t"]
        recent = c.execute(
            "SELECT line, allowed, exit_code, output_tail, created_at FROM terminal_commands "
            "WHERE session_id = ? AND created_at >= COALESCE(?, '') ORDER BY id DESC LIMIT ?",
            (session_id, since, _EVIDENCE_RECENT),
        ).fetchall()
        rules = []
        for rule in step.get("evidence") or []:
            try:
                pattern = re.compile(rule["command"])
                expect = re.compile(rule["expect"], re.M) if rule.get("expect") else None
            except (re.error, KeyError, TypeError):
                continue
            hit = None
            for r in c.execute(
                "SELECT line, exit_code, output_tail, created_at FROM terminal_commands "
                "WHERE session_id = ? AND allowed = 1 ORDER BY id DESC LIMIT 400", (session_id,),
            ):
                if pattern.search(r["line"]):
                    hit = r
                    break
            rules.append({
                "label": rule.get("label") or rule["command"],
                "found": hit is not None,
                "line": hit["line"] if hit else None,
                "output": (hit["output_tail"] or "")[-_EVIDENCE_OUTPUT:] if hit else None,
                "ok": (bool(expect.search(hit["output_tail"] or "")) if expect else None) if hit else False,
            })
    return {
        "rules": rules,
        "recent": [
            {"line": r["line"], "allowed": bool(r["allowed"]), "exit_code": r["exit_code"],
             "output": (r["output_tail"] or "")[-_EVIDENCE_OUTPUT:], "at": r["created_at"]}
            for r in reversed(recent)
        ],
    }


def get(check_id: int) -> Optional[dict[str, Any]]:
    with db.conn() as c:
        row = c.execute("SELECT * FROM step_checks WHERE id = ?", (check_id,)).fetchone()
    return dict(row) if row else None


def tutor_context(ex: dict[str, Any], session_id: str, plain: bool = False) -> str:
    """Extra system-prompt block: the step the students are on, and nothing later."""
    steps = steps_of(ex)
    n = current_step(session_id)
    if n > len(steps):
        return ("PROGRESS: the students finished all steps. Help them with the bonus "
                "or with questions about their work.")
    fmt = ("\n\nFORMAT: the students' chat shows plain text only. Do NOT use Markdown: "
           "no **, no backticks, no ``` fences, no # headings. Put any code of more "
           f"than a few words on its own lines between a line '{CODE_START}' and a "
           f"line '{CODE_END}', with no extra indentation, so the students can copy "
           "and paste it. Use short paragraphs and '•' for lists.") if plain else ""
    return (
        "CURRENT STEP — help ONLY with this one:\n"
        + step_markdown(ex, n)
        + "\n\nThe server releases the next step after the TEACHER approves the "
        "students' answer. Never describe, hint at, or list later steps. If the "
        "students think they are done, tell them to write "
        f"\"Done with step {n}\" followed by their answers, so the teacher can check it."
        + fmt
    )


def reset_to(session_id: str, n: int, note: Optional[str] = None, again: bool = False) -> dict[str, Any]:
    """Send a session back to step n (1 = from the beginning), for any
    step-by-step lab. Its records of step n and later are kept for the record
    (status 'reset') but no longer count: the outputs, and the answers to the
    quiz questions about those steps, which are asked again when the student
    does the steps again; questions still open about them are withdrawn.
    `note`, when given, goes into the session's transcript, so the student's
    chat shows it (and stops whatever the student was doing there). `again`:
    also when n is the step the student is on (start that step over); without
    it a student already at or before n is left alone. Returns the step the
    session was on (`from`) and the step it is on now (`to`)."""
    from backend import pacing, transcript  # both import steps; avoids a cycle at import

    before = current_step(session_id)
    asked = max(1, int(n))
    n = min(asked, before)
    moved = n < before or again or _has_open_rows(session_id, n)
    waiting: list[int] = []
    if moved:
        with db.conn() as c:
            # A sign-off request still waiting for the teacher is woken below.
            waiting = _pending_ids(c, session_id, n)
            c.execute(
                "UPDATE step_checks SET status = 'reset', delivered = 1, decided_at = CURRENT_TIMESTAMP "
                "WHERE session_id = ? AND step >= ? "
                "AND status IN ('approved', 'skipped', 'waiting', 'pending', 'returned')",
                (session_id, n),
            )
            c.execute(
                "UPDATE probes SET status = 'cancelled' WHERE session_id = ? AND status = 'pending' "
                "AND quiz_step IS NOT NULL AND quiz_step >= ?",
                (session_id, n),
            )
            # Their answers about those steps no longer count (asked again on the way).
            c.execute(
                "UPDATE probes SET status = 'reset', "
                "review_status = CASE WHEN review_status = 'waiting' THEN 'reset' ELSE review_status END "
                "WHERE session_id = ? AND status = 'answered' AND quiz_step IS NOT NULL AND quiz_step >= ?",
                (session_id, n),
            )
            c.execute("UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))
    # Steps the teacher opened for this student alone (a move forward) no
    # longer reach past the step they are sent back to.
    pacing.limit_own(session_id, asked)
    if moved:
        _wake(waiting)
        if note:
            transcript.record(session_id, "system", note, kind="reset", step=n, origin="server")
    return {"session_id": session_id, "from": before, "to": current_step(session_id)}


def skip_to(session_id: str, n: int, note: Optional[str] = None) -> dict[str, Any]:
    """Move a session forward to step n: the steps from the one it is on up to
    n - 1 are marked skipped (status 'skipped': passed, not done; their quiz
    questions are not asked), and the questions it still had to answer, or
    answers of its that waited for the teacher, no longer hold it back. `note`
    goes into the transcript (the chat stops what the student was doing and
    shows step n). n at or before the current step changes nothing.

    Only the records of the steps it skips (the one it is on and later) are
    touched, and each skipped step gets one 'skipped' row: an output or a
    sign-off request of its still open there no longer counts (status
    'reset', kept for the record, as reset_to does; a request waiting for it
    is woken), and a decision about it not shown yet is not shown any more.
    The records of the steps it did stay as they are."""
    from backend import transcript  # transcript doesn't import steps; avoids a cycle at import

    before = current_step(session_id)
    n = int(n)
    if n <= before:
        return {"session_id": session_id, "from": before, "to": before}
    with db.conn() as c:
        waiting = _pending_ids(c, session_id, before, n)
        c.execute(
            "UPDATE step_checks SET status = 'reset', delivered = 1, decided_at = CURRENT_TIMESTAMP "
            "WHERE session_id = ? AND step >= ? AND step < ? AND status IN ('waiting', 'pending')",
            (session_id, before, n))
        c.execute(
            "UPDATE step_checks SET delivered = 1 "
            "WHERE session_id = ? AND step >= ? AND step < ? AND status = 'returned'",
            (session_id, before, n))
        for k in range(before, n):
            c.execute(
                "INSERT INTO step_checks (session_id, step, answer, status, delivered, decided_at, forced) "
                "VALUES (?, ?, '', 'skipped', 1, CURRENT_TIMESTAMP, 1)", (session_id, k))
        c.execute("UPDATE probes SET status = 'cancelled' WHERE session_id = ? AND status = 'pending' "
                  "AND quiz_step IS NOT NULL", (session_id,))
        c.execute("UPDATE probes SET review_status = 'skipped' WHERE session_id = ? AND review_status = 'waiting'",
                  (session_id,))
        c.execute("UPDATE sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))
    _wake(waiting)
    if note:
        transcript.record(session_id, "system", note, kind="reset", step=n, origin="server")
    return {"session_id": session_id, "from": before, "to": current_step(session_id)}


def _pending_ids(c, session_id: str, start: int, end: Optional[int] = None) -> list[int]:
    """Ids of the session's sign-off requests waiting for the teacher at steps start..end - 1."""
    sql = "SELECT id FROM step_checks WHERE session_id = ? AND step >= ? AND status = 'pending'"
    args: list[Any] = [session_id, start]
    if end is not None:
        sql += " AND step < ?"
        args.append(end)
    return [r["id"] for r in c.execute(sql, args)]


def _has_open_rows(session_id: str, n: int) -> bool:
    """Anything at step n or later that still counts (an output waiting for the teacher)."""
    with db.conn() as c:
        return c.execute(
            "SELECT 1 FROM step_checks WHERE session_id = ? AND step >= ? "
            "AND status IN ('waiting', 'pending')", (session_id, n)).fetchone() is not None
