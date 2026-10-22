import asyncio
import logging
import os

import chainlit as cl
import httpx
from dotenv import load_dotenv

load_dotenv()

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8010")

# Quiet the chatty libraries chainlit pulls in. Errors/warnings still print.
for noisy in ("httpx", "httpcore", "socketio", "engineio", "asyncio", "watchfiles", "uvicorn.access"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("veriexam.student")


# With CHAINLIT_AUTH_SECRET set (make one with `chainlit create-secret`), Chainlit
# shows its own login page, with a hidden password field. Without it, the chat
# asks for the username and then the password (typed in plain sight).
AUTH_PAGE = bool(os.environ.get("CHAINLIT_AUTH_SECRET", "").strip())


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


async def _prompt(text: str, timeout: int = 600) -> str:
    res = await cl.AskUserMessage(content=text, timeout=timeout).send()
    return (res or {}).get("output", "").strip()


async def _chat_login():
    """Login inside the chat (no Chainlit login page). The login response, or None."""
    dev_code = os.environ.get("DEV_AUTO_LOGIN_CODE", "").strip().upper()
    if dev_code:
        await cl.Message(content=f"🛠️ Dev mode: auto-login with `{dev_code}`.").send()
        code, password = dev_code, dev_code  # the default password is the code
    else:
        code = (await _prompt("🎓 Welcome to VeriExam. Enter your username.")).upper()
        if not code:
            await cl.Message(content="No username received. Refresh the page to try again.").send()
            return None
        password = await _prompt("Now your password. (Until your teacher changes it, it is your username.)")
        if not password:
            await cl.Message(content="No password received. Refresh the page to try again.").send()
            return None
    r = await _login(code, password)
    if r is None:
        await cl.Message(content="⚠️ Can't reach the lab server. Ask the instructor.").send()
        return None
    if r.status_code in (401, 429):
        detail = r.json().get("detail", "Wrong username or password.")
        await cl.Message(content=f"❌ {detail} Refresh the page to try again.").send()
        return None
    if r.status_code != 200:
        await cl.Message(content="⚠️ Login failed. Please try again in a moment.").send()
        return None
    return r.json()


async def _pick(question: str, options: list[tuple[str, str]]):
    """One button per (value, label); the chosen value, or None on timeout."""
    res = await cl.AskActionMessage(
        content=question,
        actions=[cl.Action(name="pick", payload={"value": v}, label=label) for v, label in options],
        timeout=600,
    ).send()
    return ((res or {}).get("payload") or {}).get("value")


async def _choose(courses: list[dict]):
    """(course_id, exercise_id) the student opens. (None, None) when they are in
    no course; False when they didn't choose in time. One course with one
    exercise needs no question; the course's default is listed first."""
    if not courses:
        return None, None
    course = courses[0]
    if len(courses) > 1:
        chosen = await _pick("Choose your course:", [(c["course_id"], c["name"]) for c in courses])
        if chosen is None:
            return False
        course = next(c for c in courses if c["course_id"] == chosen)
    exercises = course["exercises"]
    if len(exercises) == 1:
        return course["course_id"], exercises[0]["exercise_id"]
    exercises = sorted(exercises, key=lambda e: e["exercise_id"] != course["default_exercise"])
    options = [(e["exercise_id"], (e.get("title_he") or e["title_en"])
                + (" ⭐" if e["exercise_id"] == course["default_exercise"] else "")) for e in exercises]
    chosen = await _pick(f"**{course['name']}**: choose an exercise (⭐ = your teacher's choice):", options)
    if chosen is None:
        return False
    return course["course_id"], chosen


@cl.on_chat_start
async def on_chat_start():
    """Log in (login page or chat), choose a course and exercise when there is a
    choice, then show the briefing."""
    user = cl.user_session.get("user")
    login = (user.metadata or {}).get("login") if (AUTH_PAGE and user) else await _chat_login()
    if not login:
        return
    token = login["token"]
    auth = {"Authorization": f"Bearer {token}"}

    choice = await _choose(login.get("courses") or [])
    if choice is False:
        await cl.Message(content="No choice received. Refresh the page to try again.").send()
        return
    course_id, exercise_id = choice
    body = {k: v for k, v in (("course_id", course_id), ("exercise_id", exercise_id)) if v}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            s = await client.post(f"{BACKEND}/api/sessions", json=body, headers=auth)
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
        hint = " Log out and in again." if AUTH_PAGE else " Refresh to try again."
        await cl.Message(content="⚠️ Couldn't start your session." + hint).send()
        return

    cl.user_session.set("token", token)
    cl.user_session.set("session_id", sess["session_id"])
    cl.user_session.set("mode", sess["mode"])

    await _send_briefing(exercise, sess["variant"], sess["mode"])
    # Track the poll task so we can cancel it when the chat session ends —
    # otherwise a page refresh leaks a second forever-running poller that
    # double-prompts the same probe.
    task = asyncio.create_task(_poll_probes(sess["session_id"], token))
    cl.user_session.set("probe_task", task)


@cl.on_chat_end
async def on_chat_end():
    task = cl.user_session.get("probe_task")
    if task:
        task.cancel()


def _format_param_value(value) -> str:
    """Render a param value for humans: bools as yes/no, lists comma-joined."""
    if isinstance(value, bool):
        return "yes" if value else "no"
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


async def _send_briefing(exercise: dict, variant_id: str, mode: str):
    v = exercise["variant"]
    test_lines = "\n".join(
        f"- `mcalc \"{t['input']}\"` → `{t['expected_output']}`"
        for t in v["test_inputs"]
    )
    params_block = _format_params(v["params"], exercise.get("param_labels", []))
    body = (
        f"### 📘 Your exercise: {exercise['title_en']} (variant {variant_id})\n\n"
        f"{exercise['brief_md']}\n\n"
        f"**Your variant:**\n{params_block}\n\n"
        f"**Test inputs you must pass:**\n{test_lines}\n\n"
        f"**Mode:** `{mode}`"
    )
    actions = [
        # chainlit 2.x: Action carries a `payload` dict instead of `value`.
        cl.Action(name="suggest", payload={"value": s}, label=s)
        for s in exercise.get("welcome_suggestions", [])
    ]
    await cl.Message(content=body, actions=actions).send()


@cl.action_callback("suggest")
async def on_suggest(action: cl.Action):
    await _ask(action.payload["value"])


@cl.on_message
async def on_message(msg: cl.Message):
    await _ask(msg.content)


async def _ask(text: str):
    token = cl.user_session.get("token")
    session_id = cl.user_session.get("session_id")
    if not token or not session_id:
        await cl.Message(content="Session expired — refresh the page.").send()
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
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status_code != 200:
                    # Read the error body instead of streaming it in as if it
                    # were the tutor's answer.
                    await resp.aread()
                    out.content = _ask_error_message(resp.status_code)
                    await out.update()
                    return
                async for chunk in resp.aiter_text():
                    if chunk:
                        await out.stream_token(chunk)
    except httpx.HTTPError as e:
        log.warning("ask stream failed: %s", e)
        out.content = "⚠️ Lost connection to the tutor. Please try again."
        await out.update()
        return
    await out.update()


def _ask_error_message(status: int) -> str:
    if status in (401, 403):
        return "⚠️ Your session expired. Refresh the page and log in again."
    return "⚠️ The tutor is unavailable right now. Please try again in a moment."


async def _poll_probes(session_id: str, token: str):
    auth = {"Authorization": f"Bearer {token}"}
    try:
        while True:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    r = await client.get(
                        f"{BACKEND}/api/probes/pending/{session_id}", headers=auth
                    )
                if r.status_code == 200 and r.json():
                    for probe in r.json():
                        await _handle_probe(probe, token)
            except Exception as e:
                log.warning("[poll_probes] %s", e)
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        pass  # chat ended; stop polling cleanly


async def _handle_probe(probe: dict, token: str):
    res = await cl.AskUserMessage(
        content=f"🎓 **Your instructor is asking you:**\n\n> {probe['body']}\n\nType your answer:",
        timeout=600,
    ).send()
    answer = (res or {}).get("output", "").strip()
    if not answer:
        return
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{BACKEND}/api/probes/answer",
                json={"probe_id": probe["id"], "answer": answer},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as e:
        log.warning("probe answer failed: %s", e)
        await cl.Message(content="⚠️ Couldn't submit your answer — please try again.").send()
        return
    if r.status_code == 200:
        data = r.json()
        await cl.Message(
            content=f"✅ Answer submitted. Auto-grade: **{data['auto_grade']}/2** — {data['why']}"
        ).send()
    else:
        await cl.Message(content="⚠️ Couldn't submit your answer — please try again.").send()
