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

    async with httpx.AsyncClient(timeout=10) as client:
        login = await client.post(f"{BACKEND}/api/login", json={"code": code})
    if login.status_code != 200:
        await cl.Message(content="❌ Code not found. Ask the instructor for your code.").send()
        return
    token = login.json()["token"]

    async with httpx.AsyncClient(timeout=10) as client:
        s = await client.post(
            f"{BACKEND}/api/sessions",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
    s.raise_for_status()
    sess = s.json()

    async with httpx.AsyncClient(timeout=10) as client:
        ex = await client.get(
            f"{BACKEND}/api/exercises/active",
            params={"variant": sess["variant"]},
        )
    ex.raise_for_status()
    exercise = ex.json()

    cl.user_session.set("token", token)
    cl.user_session.set("session_id", sess["session_id"])
    cl.user_session.set("mode", sess["mode"])

    await _send_briefing(exercise, sess["variant"], sess["mode"])
    asyncio.create_task(_poll_probes(sess["session_id"]))


async def _send_briefing(exercise: dict, variant_id: str, mode: str):
    v = exercise["variant"]
    test_lines = "\n".join(
        f"- `mcalc \"{t['input']}\"` → `{t['expected_output']}`"
        for t in v["test_inputs"]
    )
    body = (
        f"### 📘 Your exercise: {exercise['title_en']} (variant {variant_id})\n\n"
        f"{exercise['brief_md']}\n\n"
        f"**Your variant parameters:** `{v['params']}`\n\n"
        f"**Test inputs you must pass:**\n{test_lines}\n\n"
        f"**Mode:** `{mode}`"
    )
    actions = [
        cl.Action(name="suggest", value=s, label=s, description="")
        for s in exercise.get("welcome_suggestions", [])
    ]
    await cl.Message(content=body, actions=actions).send()


@cl.action_callback("suggest")
async def on_suggest(action: cl.Action):
    await _ask(action.value)


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
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
        async with client.stream(
            "POST",
            f"{BACKEND}/api/ask",
            json={"session_id": session_id, "message": text},
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            async for chunk in resp.aiter_text():
                if chunk:
                    await out.stream_token(chunk)
    await out.update()


async def _poll_probes(session_id: str):
    while True:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{BACKEND}/api/probes/pending/{session_id}")
            if r.status_code == 200 and r.json():
                for probe in r.json():
                    await _handle_probe(probe)
        except Exception as e:
            print(f"[poll_probes] {e}")
        await asyncio.sleep(2)


async def _handle_probe(probe: dict):
    res = await cl.AskUserMessage(
        content=f"🎓 **Your instructor is asking you:**\n\n> {probe['body']}\n\nType your answer:",
        timeout=600,
    ).send()
    answer = (res or {}).get("output", "").strip()
    if not answer:
        return
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{BACKEND}/api/probes/answer",
            json={"probe_id": probe["id"], "answer": answer},
        )
    if r.status_code == 200:
        data = r.json()
        await cl.Message(
            content=f"✅ Answer submitted. Auto-grade: **{data['auto_grade']}/2** — {data['why']}"
        ).send()
