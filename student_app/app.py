import asyncio
import datetime
import logging
import os
import re
import sys
import uuid
import warnings

import chainlit as cl
import httpx
from chainlit.session import WebsocketSession
from dotenv import load_dotenv

load_dotenv()

# The chat's own lines, in Hebrew and English (this folder isn't a package:
# Chainlit loads this file by its path).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chat_texts import text as _text  # noqa: E402

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8010")

# Quiet the chatty libraries chainlit pulls in. Errors/warnings still print.
for noisy in ("httpx", "httpcore", "socketio", "engineio", "asyncio", "watchfiles", "uvicorn.access"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("vericlass.student")


# With CHAINLIT_AUTH_SECRET set (make one with `chainlit create-secret`), Chainlit
# shows its own login page, with a hidden password field. Without it, the chat
# asks for the username and then the password (typed in plain sight).
AUTH_PAGE = bool(os.environ.get("CHAINLIT_AUTH_SECRET", "").strip())

_HEBREW = re.compile(r"[֐-׿]")


def _lang() -> str:
    """The language of the chat's own lines for this student: "he" or "en"
    (student_app/chat_texts.py). The lecturer's setting CHAT_LANGUAGE=he|en
    fixes it. On "auto" it is the lab's language once a lab is open
    (_follow_lab), and the browser's language before that (signing in,
    choosing a course)."""
    forced = os.environ.get("CHAT_LANGUAGE", "auto").strip().lower()
    if forced in ("he", "en"):
        return forced
    try:
        chosen = cl.user_session.get("lang")
        browser = cl.user_session.get("languages") or ""
    except Exception:  # no chat session yet
        return "en"
    if chosen:
        return chosen
    return "he" if re.search(r"(?:^|[\s,;])he\b", browser, re.I) else "en"


def _follow_lab(exercise: dict) -> None:
    """From here on the chat speaks the lab's language: Hebrew when the lab's
    brief is written in Hebrew (the rule the server's own notes follow,
    backend/pacing.py), otherwise English."""
    steps = exercise.get("steps") or []
    sample = f"{steps[0].get('title', '') if steps else ''} {exercise.get('brief_md') or ''}"
    cl.user_session.set("lang", "he" if _HEBREW.search(sample) else "en")


def _t(key: str, **values) -> str:
    return _text(key, _lang(), **values)


def _title(item: dict, lang: str = None) -> str:
    """An exercise's title in the chat's language (or in `lang`)."""
    return (item.get("title_he") or item["title_en"]) if (lang or _lang()) == "he" else item["title_en"]


# --- the exercise menu at the top of the page ------------------------------------------
# With the sign-in page, the header holds a menu of the exercises the student may
# open: one Chainlit chat profile per (course, exercise). It is read from the
# server on every page load (GET /api/my-exercises), so an exercise the teacher
# offered after the student signed in is there too. Choosing an entry starts the
# chat again in that exercise. Each exercise keeps its own session on the server,
# so going back to one continues from where the student was. The server also
# says which entry opens by itself (backend/courses.py, choices()): the exercise
# the student was just in, else today's meeting's, else the course's default.

# Chainlit looks for per-profile settings by running the menu's callback outside
# the event loop, which can't work inside the server; it ignores the failure, and
# only a warning about the never-awaited coroutine is left. The menu sets none.
warnings.filterwarnings("ignore", message=r"coroutine .*wrapper.* was never awaited", category=RuntimeWarning)


async def _my_exercises(token: str):
    """GET /api/my-exercises: {courses, suggested}; None when it can't be read
    (no server, or a sign-in the server no longer knows)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{BACKEND}/api/my-exercises", headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200:
            return r.json()
        log.warning("my-exercises: HTTP %s", r.status_code)
    except httpx.HTTPError as e:
        log.warning("my-exercises failed: %s", e)
    return None


def _when(value: str) -> str:
    """A server time (UTC) as the class's local date and time, 12.11.2026 14:05."""
    try:
        t = datetime.datetime.fromisoformat(value.replace("Z", "")).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return value
    return t.astimezone().strftime("%d.%m.%Y %H:%M")


def _menu(data: dict, lang: str) -> list:
    """The menu's entries: one per exercise of each course, in the course's order.
    An entry's name is "course_id/exercise_id" (what on_chat_start gets back);
    the student sees the exercise's title (with the course when two titles are
    the same), ⭐ on the lecturer's pick, and, beside it, the course and when
    they last worked on it."""
    suggested = data.get("suggested") or {}
    entries = [(c, e) for c in data.get("courses") or [] for e in c["exercises"]]
    titles = [_title(e, lang) for _, e in entries]
    menu = []
    for (course, ex), title in zip(entries, titles):
        if titles.count(title) > 1:
            title = f"{title} · {course['name']}"
        pick = ex["exercise_id"] == course.get("default_exercise")
        lines = [_text("menu_course", lang, course=course["name"])]
        if pick:
            lines.append(_text("menu_pick", lang))
        lines.append(_text("menu_last", lang, when=_when(ex["last_active_at"])) if ex.get("last_active_at")
                     else _text("menu_new", lang))
        menu.append(cl.ChatProfile(
            name=f"{course['course_id']}/{ex['exercise_id']}",
            display_name=f"{title} ⭐" if pick else title,
            markdown_description="\n\n".join(lines),
            default=(suggested.get("course_id"), suggested.get("exercise_id"))
            == (course["course_id"], ex["exercise_id"]),
        ))
    return menu


# A short message that means "I finished this step" in a class-paced lab: the
# typed form of the step's button.
_DONE_TEXT = re.compile(r"^\s*(סיימתי|סיימנו|גמרתי|גמרנו|הבא|השלב הבא|done|next)\s*[.!]*\s*$", re.I)


async def _login(code: str, password: str):
    """POST /api/login. The dev launcher starts the backend, this app, and the
    browser at once, so on a fresh boot our first request can beat uvicorn to
    the port: retry a few times with backoff. None when the server is unreachable."""
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                return await client.post(f"{BACKEND}/api/login", json={"code": code, "password": password})
        except httpx.HTTPError as e:
            log.warning("login request failed (attempt %d/5): %s", attempt + 1, e)
            await asyncio.sleep(1.5)
    return None


if AUTH_PAGE:
    @cl.password_auth_callback
    async def auth_callback(username: str, password: str):
        r = await _login(username.strip().upper(), password)
        if r is None or r.status_code != 200:
            return None
        return cl.User(identifier=username.strip().lower(), metadata={"login": r.json()})

    @cl.set_chat_profiles
    async def exercise_menu(current_user: cl.User = None, language: str = None):
        """The exercise menu for this student, read from the server now. None (no
        menu) when they are in no course, or the server can't say."""
        login = ((current_user.metadata or {}).get("login") or {}) if current_user else {}
        data = await _my_exercises(login["token"]) if login.get("token") else None
        if not data:
            return None
        forced = os.environ.get("CHAT_LANGUAGE", "auto").strip().lower()
        lang = forced if forced in ("he", "en") else ("he" if (language or "").lower().startswith("he") else "en")
        return _menu(data, lang) or None


async def _prompt(text: str, timeout: int = 600, kind: str = "", step: int = None) -> str:
    """Ask the student and wait for the answer. With `kind` (e.g. "output",
    "answer"), the question and the answer go into the transcript; login
    prompts pass none, so a password is never recorded."""
    res = await cl.AskUserMessage(content=text, timeout=timeout).send()
    # After the answer Chainlit marks a task as running again, for the message
    # handler that asked to end. An action (an HTTP call) or the poller never
    # does, and the chat would stay busy with every button disabled.
    await cl.context.emitter.task_end()
    answer = (res or {}).get("output", "").strip()
    if kind:
        await _record({"author": "tutor", "kind": "quiz" if kind == "answer" else "text",
                       "step": step, "content": text},
                      *([{"author": "student", "kind": kind, "step": step, "content": answer}] if answer else []))
    return answer


# --- the transcript (backend/transcript.py) ----------------------------------------
# Everything this chat shows after login, and everything the student writes,
# is appended to the session's transcript on the server, tagged with this
# chat's id. A new login replays it and carries on from the same place. While
# the chat is open it shows what it didn't write itself: the server's notes
# (the teacher sent the student back, deleted a question, answered one the
# student no longer waited for) and what another open chat of the same session
# wrote (a second tab, or the chat before a reload).

async def _record(*entries: dict) -> None:
    """Append entries to the transcript; a failure only costs the replay."""
    sid = cl.user_session.get("session_id")
    if not sid or not cl.user_session.get("history") or not entries:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{BACKEND}/api/transcript/{sid}", headers=_auth(),
                                  json={"entries": list(entries), "client": _client_id()})
        if r.status_code != 200:
            log.warning("transcript: HTTP %s %s", r.status_code, r.text[:200])
    except httpx.HTTPError as e:
        log.warning("transcript failed: %s", e)


async def _say(content: str, kind: str = "text", step: int = None, actions=None, record: bool = True):
    """Show a message (and record it). Every message after login goes through here."""
    msg = cl.Message(content=content, actions=actions or [])
    await msg.send()
    if record:
        await _record({"author": "tutor", "kind": kind, "step": step, "content": content})
    return msg


def _client_id() -> str:
    """This open chat's id (one per browser tab and login)."""
    cid = cl.user_session.get("client_id")
    if not cid:
        cid = uuid.uuid4().hex
        cl.user_session.set("client_id", cid)
    return cid


async def _transcript(after: int = 0, others_only: bool = False, from_restart: bool = False,
                      before: int = None):
    """GET the transcript (entries after id `after`; others_only: not what this
    chat wrote; from_restart: only since the latest fresh start; before: only
    the entries before that id). None when it can't be read."""
    params = {"after": after, **({"exclude_client": _client_id()} if others_only else {})}
    if from_restart:
        params["from_restart"] = "true"
    if before is not None:
        params["before"] = before
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{BACKEND}/api/transcript/{cl.user_session.get('session_id')}",
                                 headers=_auth(), params=params)
        if r.status_code == 200:
            return r.json()
        log.warning("transcript read: HTTP %s", r.status_code)
    except httpx.HTTPError as e:
        log.warning("transcript read failed: %s", e)
    return None


def _earlier_button(restart_id: int) -> cl.Action:
    """Opens the conversation from before a fresh start."""
    return cl.Action(name="earlier_chat", payload={"before": restart_id}, label=_t("earlier_button"))


async def _replay() -> list[dict]:
    """Show the session's earlier conversation. Returns its entries ([] = a new
    session, or a fresh start with nothing after it yet). After a fresh start
    (the lecturer sent the student back to the first step) only what came after
    it, under the lecturer's note and a button that opens the earlier chat."""
    t = await _transcript(from_restart=True)
    if not t or not t.get("enabled"):
        cl.user_session.set("history", bool(t and t.get("enabled")))
        return []
    cl.user_session.set("history", True)
    cl.user_session.set("seen", t.get("last_id") or 0)
    entries = t.get("entries") or []
    restart = t.get("restart")
    if restart:
        actions = [_earlier_button(restart["id"])] if t.get("earlier") else []
        await cl.Message(content=restart["content"], actions=actions).send()
    if not entries:
        return []
    if t.get("truncated"):
        await cl.Message(content=_t("older_hidden")).send()
    for e in entries:
        if e["author"] == "student":
            await cl.Message(content=e["content"], author="student", type="user_message").send()
        else:
            await cl.Message(content=e["content"]).send()
    await cl.Message(content=_t("resumed", title=cl.user_session.get("title") or "")).send()
    return entries


async def _sync_others() -> None:
    """Show what this chat didn't write: the server's notes and another open
    chat's messages. Call with the lock."""
    if not cl.user_session.get("history"):
        return
    t = await _transcript(after=cl.user_session.get("seen") or 0, others_only=True)
    for e in (t or {}).get("entries") or []:
        cl.user_session.set("seen", e["id"])
        if e["author"] != "student" and e["kind"] in ("reset", "restart"):
            # The teacher moved the student (back, forward, or the same step over):
            # stop whatever the chat was waiting for. The note says so.
            cl.user_session.set("awaiting_output", None)
            _interrupt_pick()
        elif e["author"] != "student" and e["kind"] == "cancelled":
            # A question was withdrawn: "your answer, or a question?" about it is void.
            _interrupt_pick("probe")
        if e["author"] == "student":
            await cl.Message(content=e["content"], author="student", type="user_message").send()
        elif e["kind"] == "returned" and e.get("step"):
            # The teacher sent the step's output back: paste again from here.
            cl.user_session.set("in_review", None)
            await cl.Message(content=e["content"], actions=[_paste_again(e["step"])]).send()
        elif e["kind"] == "restart":
            # Back to the first step: the lab starts over, as for a new student.
            await cl.Message(content=e["content"] + "\n\n" + _t("restart_reload"),
                             actions=[_earlier_button(e["id"])]).send()
        else:
            await cl.Message(content=e["content"]).send()
        if e["kind"] in ("reset", "restart"):
            _forget_shown()
            cl.user_session.set("reset_shown", True)
        if e["kind"] == "restart" and cl.user_session.get("exercise"):
            # (Recorded as this chat's own entry: the next poll leaves it out.)
            await _send_briefing(cl.user_session.get("exercise"), cl.user_session.get("variant"),
                                 cl.user_session.get("mode"), bool(cl.user_session.get("paced")))


async def _open_questions() -> None:
    """After a new login: the questions still with the teacher."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{BACKEND}/api/reviews/open/{cl.user_session.get('session_id')}",
                                 headers=_auth())
        open_q = r.json() if r.status_code == 200 else []
    except httpx.HTTPError as e:
        log.warning("open questions failed: %s", e)
        return
    if open_q:
        lines = "\n".join(f"- «{' '.join(q['question'].split())[:120]}»" for q in open_q)
        await _say(_t("still_with_lecturer", lines=lines), record=False)


def _since_reset(entries: list[dict]) -> list[dict]:
    """The entries after the last time the teacher moved the student."""
    since = entries
    for i, e in enumerate(entries):
        if e["kind"] in ("reset", "restart"):
            since = entries[i + 1:]
    return since


async def _shown_probe(entries: list[dict]) -> None:
    """After a new login: the open question the replayed conversation already
    shows is not asked again. (It was, at every login, and piled up in the
    transcript, one more copy each time.)"""
    probes = await _pending_probes()
    if probes and any(e["kind"] == "quiz" and probes[0]["body"] in e["content"] for e in _since_reset(entries)):
        cl.user_session.set("probe_shown", probes[0]["id"])


def _forget_shown() -> None:
    """After a reset: show the step the student is on again, as if new."""
    for key in ("shown_step", "waiting_for", "in_review", "awaiting_output"):
        cl.user_session.set(key, None)
    cl.user_session.set("finished_note", False)
    cl.user_session.set("quiz_held", False)


def _resume_marks(entries: list[dict], st: dict) -> None:
    """What the replayed conversation already shows, since the last reset: the
    current step's text, the note that the student waits for the teacher, the
    end of the lab. So a new login doesn't repeat them."""
    since = _since_reset(entries)
    cur = st["current"]
    if st.get("open") and any(e["kind"] == "step" and e["step"] == cur for e in since):
        cl.user_session.set("shown_step", cur)
        cl.user_session.set("resume_button", True)
    if st.get("waiting_teacher") and any(e["kind"] == "note" and e["step"] == cur for e in since):
        cl.user_session.set("waiting_for", cur)
    if st.get("finished") and any(e["kind"] == "note" and e["step"] == st["total"] + 1 for e in since):
        cl.user_session.set("finished_note", True)
    if st.get("waiting_review"):
        cl.user_session.set("in_review", cur)
    if st.get("quiz_review"):
        cl.user_session.set("quiz_held", True)


async def _chat_login():
    """Login inside the chat (no Chainlit login page). The login response, or None."""
    dev_code = os.environ.get("DEV_AUTO_LOGIN_CODE", "").strip().upper()
    # Served by the class server (STUDENT_CHAT_PATH): every student would be
    # logged in as the dev account, so the dev shortcut is off there.
    if dev_code and os.environ.get("STUDENT_CHAT_PATH", "").strip():
        log.warning("DEV_AUTO_LOGIN_CODE ignored: the chat is served to students at STUDENT_CHAT_PATH")
        dev_code = ""
    if dev_code:
        await cl.Message(content=f"🛠️ Dev mode: auto-login with `{dev_code}`.").send()
        code, password = dev_code, dev_code  # the default password is the code
    else:
        code = (await _prompt(_t("ask_username"))).upper()
        if not code:
            await cl.Message(content=_t("no_username")).send()
            return None
        password = await _prompt(_t("ask_password"))
        if not password:
            await cl.Message(content=_t("no_password")).send()
            return None
    r = await _login(code, password)
    if r is None:
        await cl.Message(content=_t("no_server")).send()
        return None
    if r.status_code in (401, 429):
        await cl.Message(content=_t("wrong_login" if r.status_code == 401 else "too_many_logins")).send()
        return None
    if r.status_code != 200:
        await cl.Message(content=_t("login_failed")).send()
        return None
    return r.json()


# What _pick returns when the teacher's change (a reset, a withdrawn question)
# or a reconnect made the question void (_interrupt_pick).
_INTERRUPTED = "__interrupted__"


async def _pick(question: str, options: list[tuple[str, str]], about: str = ""):
    """One button per (value, label); the chosen value, None on timeout, or
    _INTERRUPTED when it was cancelled meanwhile. `about`: what it is about
    ("step", "probe"), so a change can cancel only the questions it makes void."""
    ask = cl.AskActionMessage(
        content=question,
        actions=[cl.Action(name="pick", payload={"value": v}, label=label) for v, label in options],
        timeout=600,
    )
    task = asyncio.ensure_future(ask.send())
    cl.user_session.set("open_pick", {"task": task, "about": about})
    try:
        res = await task
    except asyncio.CancelledError:
        if cl.user_session.get("interrupted_pick") is not task:
            raise  # the chat itself is being stopped
        for action in ask.actions:
            try:
                await action.remove()
            except Exception:  # the browser may be gone; nothing to tidy then
                pass
        ask.content = f"{question}\n\n{_t('stopped')}"
        await ask.update()
        await cl.context.emitter.clear("clear_ask")
        await cl.context.emitter.task_end()
        return _INTERRUPTED
    finally:
        if (cl.user_session.get("open_pick") or {}).get("task") is task:
            cl.user_session.set("open_pick", None)
    # Chainlit then replaces the question with "Selected: …" in English; keep
    # the question, with the answer under it, in the chat's language.
    ask.content = f"{question}\n\n**{res['label']}**" if res else f"{question}\n\n{_t('nothing_chosen')}"
    await ask.update()
    return ((res or {}).get("payload") or {}).get("value")


def _interrupt_pick(about: str = None) -> bool:
    """Cancel the open button question (only one about `about`, when given)."""
    op = cl.user_session.get("open_pick")
    if not op or op["task"].done() or (about is not None and op["about"] != about):
        return False
    cl.user_session.set("interrupted_pick", op["task"])
    op["task"].cancel()
    return True


async def _choose(courses: list[dict]):
    """(course_id, exercise_id) the student opens. (None, None) when they are in
    no course; False when they didn't choose in time. One course with one
    exercise needs no question; the course's default is listed first."""
    if not courses:
        return None, None
    course = courses[0]
    if len(courses) > 1:
        chosen = await _pick(_t("choose_course"), [(c["course_id"], c["name"]) for c in courses])
        if chosen in (None, _INTERRUPTED):
            return False
        course = next(c for c in courses if c["course_id"] == chosen)
    exercises = course["exercises"]
    if len(exercises) == 1:
        return course["course_id"], exercises[0]["exercise_id"]
    exercises = sorted(exercises, key=lambda e: e["exercise_id"] != course["default_exercise"])
    options = [(e["exercise_id"], _title(e)
                + (" ⭐" if e["exercise_id"] == course["default_exercise"] else "")) for e in exercises]
    chosen = await _pick(_t("choose_exercise", course=course["name"]), options)
    if chosen in (None, _INTERRUPTED):
        return False
    return course["course_id"], chosen


@cl.on_chat_start
async def on_chat_start():
    """Log in (login page or chat), choose a course and exercise when there is a
    choice, then show the briefing (and, in a class-paced lab, the open step)."""
    user = cl.user_session.get("user")
    login = (user.metadata or {}).get("login") if (AUTH_PAGE and user) else await _chat_login()
    if not login:
        return
    token = login["token"]
    auth = {"Authorization": f"Bearer {token}"}

    # The exercise: the one chosen in the menu at the top of the page; without a
    # menu (the chat signs in by itself, or the student is in no course) the chat
    # asks, from the list the server gives now (the sign-in page's list is as old
    # as the sign-in, which lasts days).
    profile = cl.user_session.get("chat_profile") if AUTH_PAGE else None
    fresh = await _my_exercises(token) if AUTH_PAGE else None
    courses = fresh["courses"] if fresh else login.get("courses") or []
    if profile and "/" in profile:
        course_id, exercise_id = profile.split("/", 1)
    else:
        choice = await _choose(courses)
        if choice is False:
            await cl.Message(content=_t("no_choice")).send()
            return
        course_id, exercise_id = choice
    # More than one exercise in the menu: say how to switch.
    switchable = bool(profile) and sum(len(c["exercises"]) for c in courses) > 1
    body = {k: v for k, v in (("course_id", course_id), ("exercise_id", exercise_id)) if v}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            s = await client.post(f"{BACKEND}/api/sessions", json=body, headers=auth)
            if s.status_code in (403, 404) and profile:
                # Chosen in a menu read earlier: the teacher stopped offering it since.
                await cl.Message(content=_t("exercise_gone")).send()
                return
            s.raise_for_status()
            sess = s.json()
            # Students only ever get their own session's exercise and variant.
            ex = await client.get(
                f"{BACKEND}/api/exercises/active",
                params={"variant": sess["variant"], "session_id": sess["session_id"]},
                headers=auth,
            )
            ex.raise_for_status()
            exercise = ex.json()
    except httpx.HTTPError as e:
        log.warning("session/exercise setup failed: %s", e)
        hint = _t("hint_relogin" if AUTH_PAGE else "hint_reload")
        await cl.Message(content=_t("session_failed") + hint).send()
        return

    _follow_lab(exercise)
    cl.user_session.set("title", _title(exercise))
    paced = exercise.get("pacing") == "class"
    cl.user_session.set("token", token)
    cl.user_session.set("session_id", sess["session_id"])
    # For a fresh start while the chat is open (the briefing is shown again).
    cl.user_session.set("exercise", exercise)
    cl.user_session.set("variant", sess["variant"])
    cl.user_session.set("mode", sess["mode"])
    cl.user_session.set("paced", paced)
    # One thing at a time: the poller and the "done" button both ask questions.
    cl.user_session.set("lock", asyncio.Lock())

    async with cl.user_session.get("lock"):
        history = await _replay()
        if not history:
            await _send_briefing(exercise, sess["variant"], sess["mode"], paced)
        else:
            await _open_questions()
            await _shown_probe(history)
        if switchable:
            await _say(_t("switch_hint"), record=False)
        if paced:
            st = await _get_state()
            if st and history:
                _resume_marks(history, st)
            cl.user_session.set("last_current", st["current"] if st else None)
            if cl.user_session.get("resume_button") and st and st.get("open"):
                cl.user_session.set("resume_button", False)
                await _send_finish_button(st["step"])
            await _show_state()
    # Track the poll task so we can cancel it when the chat session ends —
    # otherwise a page refresh leaks a second forever-running poller that
    # double-prompts the same probe.
    task = asyncio.create_task(_poll(sess["session_id"], token))
    cl.user_session.set("probe_task", task)


@cl.on_chat_end
async def on_chat_end():
    # Chainlit calls this on every disconnect, a short one too (Wi-Fi, a laptop
    # lid), and restores the same session when the browser reconnects, without
    # on_chat_start. Cancelling the poller here left a reconnected chat deaf to
    # the teacher (steps opened, students moved, questions) in November 2026.
    # So the poller only pauses until the browser is back, and stops when
    # Chainlit drops the session (_poll).
    cl.user_session.set("dead_socket", cl.context.session.socket_id)


def _format_param_value(value) -> str:
    """Render a param value for humans: bools as yes/no, lists comma-joined."""
    if isinstance(value, bool):
        return _t("yes" if value else "no")
    if isinstance(value, (list, tuple)):
        return ", ".join(str(x) for x in value)
    return str(value)


def _prettify_key(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").strip().capitalize()


def _format_params(params: dict, labels: list[dict]) -> str:
    """A labeled markdown list connecting each variant param to its meaning.
    `labels` (exercise-level param_labels) sets the order + friendly labels;
    any params not covered fall back to a prettified key."""
    lines: list[str] = []
    covered: set[str] = set()
    for pl in labels or []:
        key = pl.get("key")
        if key is None or key not in params:
            continue
        covered.add(key)
        label = pl.get("label") or _prettify_key(key)
        note = pl.get("note")
        suffix = f" — _{note}_" if note else ""
        lines.append(f"- **{label}:** {_format_param_value(params[key])}{suffix}")
    for key, value in params.items():
        if key in covered:
            continue
        lines.append(f"- **{_prettify_key(key)}:** {_format_param_value(value)}")
    return "\n".join(lines)


async def _send_briefing(exercise: dict, variant_id: str, mode: str, paced: bool):
    """The exercise's brief; the variant, its tests and the mode only for an
    exercise that has them (not for a class-paced lab)."""
    v = exercise.get("variant") or {}
    parts = [f"### {_title(exercise)}", exercise["brief_md"]]
    params_block = _format_params(v.get("params") or {}, exercise.get("param_labels", []))
    if params_block:
        parts.append(f"{_t('variant_head', variant=variant_id)}\n{params_block}")
    tests = v.get("test_inputs") or []
    if tests:
        parts.append(_t("tests_head") + "\n" + "\n".join(
            _t("test_line", input=t["input"], output=t["expected_output"]) for t in tests))
    if not paced:
        parts.append(_t(f"mode_{mode}") if mode in ("mentor", "coding_partner") else _t("mode_other", mode=mode))
    actions = [
        # chainlit 2.x: Action carries a `payload` dict instead of `value`.
        cl.Action(name="suggest", payload={"value": s}, label=s)
        for s in exercise.get("welcome_suggestions", [])
    ]
    await _say("\n\n".join(parts), kind="brief", actions=actions)


@cl.action_callback("earlier_chat")
async def on_earlier_chat(action: cl.Action):
    """The conversation from before a fresh start, shown on demand (not recorded)."""
    t = await _transcript(before=int(action.payload.get("before") or 0))
    entries = (t or {}).get("entries") or []
    if not entries:
        await cl.Message(content=_t("earlier_none")).send()
        return
    await cl.Message(content=_t("earlier_head")).send()
    if t.get("truncated"):
        await cl.Message(content=_t("older_hidden")).send()
    for e in entries:
        if e["author"] == "student":
            await cl.Message(content=e["content"], author="student", type="user_message").send()
        else:
            await cl.Message(content=e["content"]).send()
    await cl.Message(content=_t("earlier_end")).send()


@cl.action_callback("suggest")
async def on_suggest(action: cl.Action):
    await _record({"author": "student", "kind": "text", "content": action.payload["value"]})
    await _ask(action.payload["value"])


@cl.on_message
async def on_message(msg: cl.Message):
    awaiting = cl.user_session.get("awaiting_output") if cl.user_session.get("paced") else None
    if awaiting is not None:
        # Asked for after "Done": this message is the step's output.
        cl.user_session.set("awaiting_output", None)
        await _record({"author": "student", "kind": "output", "step": awaiting, "content": msg.content or ""})
        await _send_output(awaiting, msg.content or "")
        return
    await _record({"author": "student", "kind": "text", "content": msg.content or ""})
    # "Done" finishes the open step, even while a question of ours is open.
    if cl.user_session.get("paced") and _DONE_TEXT.match(msg.content or ""):
        st = await _get_state()
        if st and st.get("open"):
            await _finish(st["step"]["n"])
            return
    reply = await _probe_answer(msg.content or "")
    if reply == "answered":
        return
    if reply == "question":
        # Asked while a question of ours is open: answer it, then remind them.
        await _ask(msg.content)
        await _remind_probe()
        return
    if cl.user_session.get("paced") and await _pasted_output(msg.content or ""):
        return
    await _ask(msg.content)


async def _pasted_output(text: str) -> bool:
    """A message while a step is open may be the step's answer rather than a
    question (students often type or paste instead of clicking "Done"). The
    server decides (POST /api/steps/detect, exercise.yaml output_in_chat): it is
    the step's output, a question, or "maybe", and then the student is asked
    first, before anything goes to the teacher. Finishes the step and returns
    True when it is the answer; False = treat it as a question."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{BACKEND}/api/steps/detect", headers=_auth(),
                                  json={"session_id": cl.user_session.get("session_id"), "text": text})
        d = r.json() if r.status_code == 200 else None
    except httpx.HTTPError as e:
        log.warning("detect output failed: %s", e)
        d = None
    if not d or d["kind"] == "question":
        return False
    n, label, needs_output = d["step"], d["label"], d.get("needs_output", True)
    if d["kind"] == "maybe":
        question = _t("maybe_step_q", label=label)
        answer_label = _t("opt_output" if needs_output else "opt_done", label=label)
        chosen = await _pick(question, [("answer", answer_label), ("question", _t("opt_question"))], about="step")
        if chosen == _INTERRUPTED:
            return True  # the teacher moved the student meanwhile; their note says where
        await _record({"author": "tutor", "kind": "text", "step": n, "content": question},
                      *([{"author": "student", "kind": "text", "step": n,
                          "content": answer_label if chosen == "answer" else _t("opt_question")}] if chosen else []))
        if chosen != "answer":
            return False
    async with cl.user_session.get("lock"):
        st = await _get_state()
        if not st or not st.get("open") or st["step"]["n"] != n:
            return False
        if d["kind"] == "output":
            await _say(_t("detected_output", label=label), kind="result", step=n)
        await _after_finish(await _post_finish(n, text if needs_output else ""), n)
    return True


async def _ask(text: str):
    token = cl.user_session.get("token")
    session_id = cl.user_session.get("session_id")
    if not token or not session_id:
        await cl.Message(content=_t("expired")).send()
        return

    out = cl.Message(content="")
    await out.send()
    # 10 min — large enough to cover teacher-review mode (server holds the
    # response until the teacher picks a variant).
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                f"{BACKEND}/api/ask",
                json={"session_id": session_id, "message": text},
                # This chat shows the transcript: an answer the teacher sends after
                # the wait ended still reaches the student (backend/routes/review.py).
                headers={"Authorization": f"Bearer {token}", "X-VeriClass-Transcript": "1"},
            ) as resp:
                if resp.status_code != 200:
                    # Read the error body instead of streaming it in as if it
                    # were the tutor's answer.
                    await resp.aread()
                    out.content = _ask_error_message(resp.status_code)
                    await out.update()
                    return
                if resp.headers.get("X-VeriClass-Review"):
                    # The answer waits for the teacher, maybe for minutes. Meanwhile the
                    # chat isn't busy: the student can answer a question, finish a step,
                    # or ask something else.
                    await cl.context.emitter.task_end()
                async for chunk in resp.aiter_text():
                    if chunk:
                        await out.stream_token(chunk)
    except httpx.HTTPError as e:
        log.warning("ask stream failed: %s", e)
        out.content = _t("cut")
        await out.update()
        return
    await out.update()
    await _record({"author": "tutor", "kind": "text", "content": out.content})


def _ask_error_message(status: int) -> str:
    if status in (401, 403):
        return _t("expired_login")
    return _t("unavailable")


# --- class-paced labs (backend/pacing.py) --------------------------------------------
# The server says which step is open to this student; the chat shows each step
# once, with a "done" button. The teacher opens later steps from the dashboard,
# and the poller shows them here when they open.

def _auth() -> dict:
    return {"Authorization": f"Bearer {cl.user_session.get('token')}"}


async def _get_state():
    """GET /api/steps/state: where the student is. None when it can't be read."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{BACKEND}/api/steps/state/{cl.user_session.get('session_id')}",
                                 headers=_auth())
        if r.status_code == 200:
            st = r.json()
            if st.get("step"):
                labels = cl.user_session.get("labels") or {}
                labels[st["step"]["n"]] = st["step"]["label"]
                cl.user_session.set("labels", labels)
            return st
        log.warning("step state: HTTP %s", r.status_code)
    except httpx.HTTPError as e:
        log.warning("step state failed: %s", e)
    return None


async def _show_state():
    """Show what changed since the last look: a newly open step, the note that
    the student waits for the teacher, or the end of the lab. Call with the lock."""
    st = await _get_state()
    if st is None:
        return
    last = cl.user_session.get("last_current")
    cl.user_session.set("last_current", st["current"])
    awaiting = cl.user_session.get("awaiting_output")
    if awaiting is not None and not (st.get("open") and st["step"]["n"] == awaiting):
        # Waiting for this step's output, but it isn't open any more (a question
        # was added, the teacher moved the student): stop waiting, and say why.
        cl.user_session.set("awaiting_output", None)
        label = (cl.user_session.get("labels") or {}).get(awaiting, str(awaiting))
        why = _t("why_question" if st.get("quiz_pending") else "why_changed")
        await _say(_t("paste_stopped", label=label, why=why), kind="note", step=awaiting)
    if last is not None and st["current"] < last:
        # The teacher sent the student back. The server's note normally came
        # through the transcript already; without a transcript, say it here.
        if not cl.user_session.get("reset_shown") and not cl.user_session.get("history"):
            await _say(_t("sent_back", label=st.get("current_label") or st["current"]), kind="note")
        _forget_shown()
    cl.user_session.set("reset_shown", False)
    review = cl.user_session.get("in_review")
    if (review is not None and st["current"] == review and st.get("open") and not st.get("waiting_review")
            and not cl.user_session.get("history")):
        # Sent back by the teacher; without a transcript its note can't arrive, so say it here.
        cl.user_session.set("in_review", None)
        await _say(_t("output_returned", label=st["current_label"]), kind="returned", step=review,
                   actions=[_paste_again(review)])
    if review is not None and st["current"] > review:
        # The teacher let them past the step whose output didn't match.
        cl.user_session.set("in_review", None)
        label = (cl.user_session.get("labels") or {}).get(review, str(review))
        await _say(_t("step_approved", label=label), kind="result", step=review)
    if cl.user_session.get("quiz_held") and not st.get("quiz_review"):
        # The teacher decided about the quiz answer that waited. The server's note
        # says what (the transcript); without a transcript, say it here.
        cl.user_session.set("quiz_held", False)
        if not cl.user_session.get("history"):
            await _say(_t("answer_read"), kind="note")
    if st["open"]:
        step = st["step"]
        if cl.user_session.get("shown_step") != step["n"]:
            unlocked = cl.user_session.get("waiting_for") == step["n"]
            cl.user_session.set("shown_step", step["n"])
            cl.user_session.set("waiting_for", None)
            await _send_step(step, unlocked)
    elif st["waiting_teacher"]:
        if cl.user_session.get("waiting_for") != st["current"]:
            cl.user_session.set("waiting_for", st["current"])
            if st["current"] == 1:
                text = _t("first_not_open")
            else:
                text = _t("wait_next", label=st["current_label"])
            await _say(text, kind="note", step=st["current"])
    elif st["finished"] and not cl.user_session.get("finished_note"):
        cl.user_session.set("finished_note", True)
        await _say(_t("lab_done"), kind="note", step=st["total"] + 1)


async def _send_step(step: dict, unlocked: bool):
    head = _t("step_opened", label=step["label"]) if unlocked else ""
    how = _t("how_output" if step["needs_output"] else "how_done")
    await _say(f"{head}{step['markdown']}\n\n---\n{how}", kind="step", step=step["n"],
               actions=[_finish_action(step)])


def _paste_again(n: int) -> cl.Action:
    return cl.Action(name="finish", payload={"step": n}, label=_t("btn_paste_again"))


def _finish_action(step: dict) -> cl.Action:
    return cl.Action(name="finish", payload={"step": step["n"]}, label=_t("btn_done", label=step["label"]))


async def _send_finish_button(step: dict):
    """After a new login: the step's text is in the replayed conversation; only
    its button needs to come back."""
    how = _t("resume_how_output" if step["needs_output"] else "resume_how_done")
    await _say(_t("where_you_are", label=step["label"], how=how), record=False,
               actions=[_finish_action(step)])


@cl.action_callback("finish")
async def on_finish(action: cl.Action):
    await _finish(action.payload["step"], action)


async def _finish(n: int, action: cl.Action = None):
    """The student says step n is done: ask for the output when the step checks
    one, send it, and go on to the quiz and the next step."""
    async with cl.user_session.get("lock"):
        st = await _get_state()
        if st is None:
            await cl.Message(content=_t("no_server_retry")).send()
            return
        if not st.get("open") or st["step"]["n"] != n:
            await _not_this_step(st, n)
            return
        if st["step"]["needs_output"]:
            # The next message is the output (on_message). Nothing waits here, so
            # the poller can still interrupt: the teacher may move the student
            # or ask a question meanwhile.
            cl.user_session.set("awaiting_output", n)
            cl.user_session.set("awaiting_action", action)
            await _say(_t("paste_here", label=st["step"]["label"]), step=n)
            return
        r = await _post_finish(n, "")
        await _after_finish(r, n, action)


async def _send_output(n: int, text: str):
    """The message after "Done" (and its paste request) is step n's output."""
    async with cl.user_session.get("lock"):
        action = cl.user_session.get("awaiting_action")
        cl.user_session.set("awaiting_action", None)
        await _after_finish(await _post_finish(n, text), n, action)


async def _post_finish(n: int, output: str):
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{BACKEND}/api/steps/finish", headers=_auth(), json={
                "session_id": cl.user_session.get("session_id"), "step": n,
                "output": output})
        if r.status_code == 200:
            return r.json()
        log.warning("finish step: HTTP %s %s", r.status_code, r.text[:200])
    except httpx.HTTPError as e:
        log.warning("finish step failed: %s", e)
    return None


async def _after_finish(r, n: int, action: cl.Action = None):
    """Tell the student how it went; on success, the quiz and the next step.
    Call with the lock."""
    label = (cl.user_session.get("labels") or {}).get(n, str(n))
    if r is None:
        await cl.Message(content=_t("save_failed")).send()
        return
    if r["status"] == "missing":
        # The hints would give the expected output away; the teacher sees them.
        cl.user_session.set("in_review", n)
        await _say(_t("output_mismatch", label=label), kind="result", step=n,
                   actions=[_paste_again(n)])
        return
    if r["status"] != "done":
        await _not_this_step(r["state"], n)
        await _show_state()  # e.g. moved meanwhile: show the step they are on
        return
    if action is not None:
        await action.remove()
    cl.user_session.set("in_review", None)
    note = _t("output_ok") if r.get("ok") else ""
    if r.get("quiz"):
        note += _t("quiz_next")
    await _say(_t("step_done", label=label, note=note), kind="result", step=n)
    await _ask_pending_probes()
    await _show_state()


async def _not_this_step(st: dict, n: int):
    label = (cl.user_session.get("labels") or {}).get(n, str(n))
    if st.get("finished"):
        text = _t("all_done")
    elif st.get("quiz_pending"):
        text = _t("answer_first")
    elif st.get("quiz_review"):
        text = _t("answer_waiting")
    elif st.get("waiting_teacher"):
        text = _t("not_open_yet", label=st["current_label"])
    else:
        text = _t("already_done", label=label, current=st.get("current_label"))
    await _say(text)


async def _poll(session_id: str, token: str):
    """Every 2 seconds: the server's notes (the teacher moved the student,
    withdrew a question, answered one), the questions asked, and (class-paced)
    a step the teacher just opened. Pauses while the browser is disconnected
    and ends when Chainlit drops the session (a reload starts a new one)."""
    session = cl.context.session
    try:
        while True:
            if WebsocketSession.get_by_id(session.id) is None:
                return
            dead = cl.user_session.get("dead_socket")
            if dead is not None:
                if session.socket_id == dead:
                    await asyncio.sleep(2)
                    continue
                # Reconnected: Chainlit cleared any open question on screen.
                cl.user_session.set("dead_socket", None)
                _interrupt_pick()
            try:
                async with cl.user_session.get("lock"):
                    await _sync_others()
                    if cl.user_session.get("in_review") is not None:
                        await _show_state()  # "the teacher approved" before that step's quiz
                    await _ask_pending_probes()
                    if cl.user_session.get("paced"):
                        await _show_state()
            except Exception as e:
                log.warning("[poll] %s", e)
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        pass  # chat ended; stop polling cleanly


# --- questions the chat asks the student (backend/open_questions.py) ----------------
# A quiz question after a step, or one the teacher sent. It is shown once and
# stays open without locking the chat: the student answers in the chat when
# ready, and can still ask the teacher something meanwhile. The server says
# whether a message is the answer (exercise.yaml answer_in_chat); when unsure,
# the student is asked. One question at a time, oldest first.

async def _pending_probes() -> list:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{BACKEND}/api/probes/pending/{cl.user_session.get('session_id')}", headers=_auth())
    except httpx.HTTPError as e:
        log.warning("[probes] %s", e)
        return []
    return r.json() if r.status_code == 200 else []


async def _ask_pending_probes():
    """Show the oldest question waiting for the student's answer, once. Call with the lock."""
    probes = await _pending_probes()
    if probes and cl.user_session.get("probe_shown") != probes[0]["id"]:
        cl.user_session.set("probe_shown", probes[0]["id"])
        await _say(_probe_text(probes[0]), kind="quiz")


def _probe_text(probe: dict) -> str:
    head = (_t("quiz_head", step=probe.get("quiz_step")) if probe.get("source") == "quiz"
            else _t("lecturer_asks"))
    return f"{head}\n\n> {probe['body']}\n\n{_t('answer_here')}"


async def _probe_answer(text: str):
    """A message while a question of ours is open: "answered" (sent as its
    answer), "question" (the student's own question), or None (no question is
    open, or it is the open step's output). POST /api/probes/classify decides;
    on "maybe" the student picks."""
    if not cl.user_session.get("probe_shown"):
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{BACKEND}/api/probes/classify", headers=_auth(),
                                  json={"session_id": cl.user_session.get("session_id"), "text": text})
        d = r.json() if r.status_code == 200 else None
    except httpx.HTTPError as e:
        log.warning("classify answer failed: %s", e)
        d = None
    if not d or d["kind"] in ("none", "step"):
        return None
    if d["kind"] == "maybe":
        question = _t("maybe_answer_q")
        options = [("answer", _t("opt_my_answer")), ("question", _t("opt_my_question"))]
        chosen = await _pick(question, options, about="probe")
        if chosen == _INTERRUPTED:
            return "answered"  # the question was withdrawn (or the student moved); nothing more to do
        await _record({"author": "tutor", "kind": "text", "content": question},
                      *([{"author": "student", "kind": "text", "content": dict(options)[chosen]}] if chosen else []))
        if chosen != "answer":
            return "question"
    async with cl.user_session.get("lock"):
        await _answer_probe(d["probe"], text)
        await _ask_pending_probes()
        if cl.user_session.get("paced"):
            await _show_state()
    return "answered"


async def _remind_probe():
    """After answering the student's own question: the question of ours is still open."""
    probes = await _pending_probes()
    if probes and probes[0]["id"] == cl.user_session.get("probe_shown"):
        await _say(_t("remind", body=probes[0]["body"]))


async def _answer_probe(probe: dict, answer: str):
    """Send the student's answer and show how it went."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{BACKEND}/api/probes/answer",
                json={"probe_id": probe["id"], "answer": answer},
                headers=_auth(),
            )
    except httpx.HTTPError as e:
        log.warning("probe answer failed: %s", e)
        await _say(_t("answer_not_sent"), record=False)
        return
    if r.status_code == 200:
        data = r.json()
        grade = _t("grade", grade=data["auto_grade"]) if data.get("auto_grade") is not None else ""
        why = f" — {data['why']}" if data.get("why") else ""
        if data.get("review"):
            # Graded too low to move on by itself (exercise.yaml quiz_review): the
            # teacher lets them continue or asks again; the server's note says which.
            cl.user_session.set("quiz_held", True)
            await _say(_t("answer_saved_review", grade=grade, why=why), kind="result")
        else:
            await _say(_t("answer_saved", grade=grade, why=why), kind="result")
    elif r.status_code == 409:
        await _say(_t("question_closed"), record=False)
    else:
        await _say(_t("answer_not_sent"), record=False)
