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

log = logging.getLogger("oslab.student")


@cl.on_chat_start
async def on_chat_start():
    """Show login prompt, then briefing bubble once authenticated."""
    dev_code = os.environ.get("DEV_AUTO_LOGIN_CODE", "").strip().upper()
    if dev_code:
        code = dev_code
        await cl.Message(content=f"🛠️ Dev mode: auto-login with `{code}`.").send()
    else:
        res = await cl.AskUserMessage(
            content="🎓 Welcome to the OS Lab. Enter your login code to begin.",
            timeout=600,
        ).send()
        code = (res or {}).get("output", "").strip().upper()
        if not code:
            await cl.Message(content="No code received. Refresh the page to try again.").send()
            return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            login = await client.post(f"{BACKEND}/api/login", json={"code": code})
    except httpx.HTTPError as e:
        log.warning("login request failed: %s", e)
        await cl.Message(content="⚠️ Can't reach the lab server. Ask the instructor.").send()
        return
    if login.status_code == 401:
        await cl.Message(content="❌ Code not found. Ask the instructor for your code.").send()
        return
    if login.status_code != 200:
        await cl.Message(content="⚠️ Login failed. Please try again in a moment.").send()
        return
    token = login.json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            s = await client.post(f"{BACKEND}/api/sessions", json={}, headers=auth)
            s.raise_for_status()
            sess = s.json()
            # /exercises/active now requires the token (students only ever get
            # their own assigned variant).
            ex = await client.get(
                f"{BACKEND}/api/exercises/active",
                params={"variant": sess["variant"]},
                headers=auth,
            )
            ex.raise_for_status()
            exercise = ex.json()
    except httpx.HTTPError as e:
        log.warning("session/exercise setup failed: %s", e)
        await cl.Message(content="⚠️ Couldn't start your session. Refresh to try again.").send()
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
