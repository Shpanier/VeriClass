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


def steps_of(ex: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    return list((ex or {}).get("steps") or [])


def parse_done(message: str) -> Optional[int]:
    """0 = 'done' without a number, N = 'done with step N', None = not a done message."""
    m = _DONE_EN.search(message) or _DONE_HE.search(message)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else 0


def current_step(session_id: str) -> int:
    """1-based step the session is working on = highest approved step + 1."""
    with db.conn() as c:
        row = c.execute(
            "SELECT MAX(step) AS s FROM step_checks WHERE session_id = ? AND status = 'approved'",
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


def submit(session_id: str, step: int, answer: str) -> int:
    """Store (or extend) the pending check for this step; returns its id."""
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
            return row["id"]
        cur = c.execute(
            "INSERT INTO step_checks (session_id, step, answer) VALUES (?, ?, ?)",
            (session_id, step, answer),
        )
        return cur.lastrowid


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
