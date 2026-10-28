import asyncio
import logging
import os
import re

import chainlit as cl
import httpx
from dotenv import load_dotenv

load_dotenv()

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8010")

# Quiet the chatty libraries chainlit pulls in. Errors/warnings still print.
for noisy in ("httpx", "httpcore", "socketio", "engineio", "asyncio", "watchfiles", "uvicorn.access"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("vericlass.student")


# With CHAINLIT_AUTH_SECRET set (make one with `chainlit create-secret`), Chainlit
# shows its own login page, with a hidden password field. Without it, the chat
# asks for the username and then the password (typed in plain sight).
AUTH_PAGE = bool(os.environ.get("CHAINLIT_AUTH_SECRET", "").strip())

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


async def _prompt(text: str, timeout: int = 600) -> str:
    res = await cl.AskUserMessage(content=text, timeout=timeout).send()
    # After the answer Chainlit marks a task as running again, for the message
    # handler that asked to end. An action (an HTTP call) or the poller never
    # does, and the chat would stay busy with every button disabled.
    await cl.context.emitter.task_end()
    return (res or {}).get("output", "").strip()


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
        code = (await _prompt("🎓 ברוכים הבאים ל־VeriClass. הקלידו את שם המשתמש שלכם.")).upper()
        if not code:
            await cl.Message(content="לא התקבל שם משתמש. רעננו את הדף כדי לנסות שוב.").send()
            return None
        password = await _prompt("עכשיו את הסיסמה. (עד שהמרצה משנה אותה, היא זהה לשם המשתמש.)")
        if not password:
            await cl.Message(content="לא התקבלה סיסמה. רעננו את הדף כדי לנסות שוב.").send()
            return None
    r = await _login(code, password)
    if r is None:
        await cl.Message(content="⚠️ אין חיבור לשרת המעבדה. פנו למרצה.").send()
        return None
    if r.status_code in (401, 429):
        detail = r.json().get("detail", "Wrong username or password.")
        await cl.Message(content=f"❌ {detail} רעננו את הדף כדי לנסות שוב.").send()
        return None
    if r.status_code != 200:
        await cl.Message(content="⚠️ ההתחברות נכשלה. נסו שוב בעוד רגע.").send()
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
        chosen = await _pick("בחרו קורס:", [(c["course_id"], c["name"]) for c in courses])
        if chosen is None:
            return False
        course = next(c for c in courses if c["course_id"] == chosen)
    exercises = course["exercises"]
    if len(exercises) == 1:
        return course["course_id"], exercises[0]["exercise_id"]
    exercises = sorted(exercises, key=lambda e: e["exercise_id"] != course["default_exercise"])
    options = [(e["exercise_id"], (e.get("title_he") or e["title_en"])
                + (" ⭐" if e["exercise_id"] == course["default_exercise"] else "")) for e in exercises]
    chosen = await _pick(f"**{course['name']}**: בחרו תרגיל (⭐ = הבחירה של המרצה):", options)
    if chosen is None:
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

    choice = await _choose(login.get("courses") or [])
    if choice is False:
        await cl.Message(content="לא התקבלה בחירה. רעננו את הדף כדי לנסות שוב.").send()
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
        hint = " התנתקו והתחברו שוב." if AUTH_PAGE else " רעננו את הדף כדי לנסות שוב."
        await cl.Message(content="⚠️ לא הצלחנו לפתוח את המפגש שלכם." + hint).send()
        return

    paced = exercise.get("pacing") == "class"
    cl.user_session.set("token", token)
    cl.user_session.set("session_id", sess["session_id"])
    cl.user_session.set("mode", sess["mode"])
    cl.user_session.set("paced", paced)
    # One thing at a time: the poller and the "done" button both ask questions.
    cl.user_session.set("lock", asyncio.Lock())

    await _send_briefing(exercise, sess["variant"], sess["mode"], paced)
    if paced:
        async with cl.user_session.get("lock"):
            await _show_state()
    # Track the poll task so we can cancel it when the chat session ends —
    # otherwise a page refresh leaks a second forever-running poller that
    # double-prompts the same probe.
    task = asyncio.create_task(_poll(sess["session_id"], token))
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


async def _send_briefing(exercise: dict, variant_id: str, mode: str, paced: bool):
    """The exercise's brief; the variant, its tests and the mode only for an
    exercise that has them (not for a class-paced lab)."""
    v = exercise.get("variant") or {}
    title = exercise.get("title_he") or exercise["title_en"]
    parts = [f"### 📘 {title}", exercise["brief_md"]]
    params_block = _format_params(v.get("params") or {}, exercise.get("param_labels", []))
    if params_block:
        parts.append(f"**Your variant ({variant_id}):**\n{params_block}")
    tests = v.get("test_inputs") or []
    if tests:
        parts.append("**Test inputs you must pass:**\n" + "\n".join(
            f"- `mcalc \"{t['input']}\"` → `{t['expected_output']}`" for t in tests))
    if not paced:
        parts.append(f"**Mode:** `{mode}`")
    actions = [
        # chainlit 2.x: Action carries a `payload` dict instead of `value`.
        cl.Action(name="suggest", payload={"value": s}, label=s)
        for s in exercise.get("welcome_suggestions", [])
    ]
    await cl.Message(content="\n\n".join(parts), actions=actions).send()


@cl.action_callback("suggest")
async def on_suggest(action: cl.Action):
    await _ask(action.payload["value"])


@cl.on_message
async def on_message(msg: cl.Message):
    if cl.user_session.get("paced") and _DONE_TEXT.match(msg.content or ""):
        st = await _get_state()
        if st and st.get("open"):
            await _finish(st["step"]["n"])
            return
    await _ask(msg.content)


async def _ask(text: str):
    token = cl.user_session.get("token")
    session_id = cl.user_session.get("session_id")
    if not token or not session_id:
        await cl.Message(content="המפגש פג. רעננו את הדף.").send()
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
        out.content = "⚠️ החיבור לצ'אט נקטע. נסו שוב."
        await out.update()
        return
    await out.update()


def _ask_error_message(status: int) -> str:
    if status in (401, 403):
        return "⚠️ המפגש פג. רעננו את הדף והתחברו שוב."
    return "⚠️ הצ'אט לא זמין כרגע. נסו שוב בעוד רגע."


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
                text = "⏸️ המרצה עוד לא פתח את השלב הראשון. הוא יופיע כאן ברגע שייפתח."
            else:
                text = (f"⏸️ סיימתם את כל השלבים שפתוחים כרגע. שלב {st['current_label']} יופיע כאן "
                        "כשהמרצה יפתח אותו לכל הכיתה. בינתיים אפשר לשאול כאן שאלות על מה שעשיתם.")
            await cl.Message(content=text).send()
    elif st["finished"] and not cl.user_session.get("finished_note"):
        cl.user_session.set("finished_note", True)
        await cl.Message(content="🎉 סיימתם את כל השלבים של המעבדה. כל הכבוד!").send()


async def _send_step(step: dict, unlocked: bool):
    head = f"🔓 **המרצה פתח את שלב {step['label']}.**\n\n" if unlocked else ""
    how = ("כשסיימתם: לחצו **סיימתי**, והדביקו את כל הפלט שקיבלתם בטרמינל."
           if step["needs_output"] else "כשסיימתם: לחצו **סיימתי**.")
    await cl.Message(
        content=f"{head}{step['markdown']}\n\n---\n{how}",
        actions=[cl.Action(name="finish", payload={"step": step["n"]},
                           label=f"✅ סיימתי את שלב {step['label']}")],
    ).send()


@cl.action_callback("finish")
async def on_finish(action: cl.Action):
    await _finish(action.payload["step"], action)


@cl.action_callback("force")
async def on_force(action: cl.Action):
    """Continue although the pasted output lacked something."""
    n = action.payload["step"]
    last = cl.user_session.get("last_output") or {}
    async with cl.user_session.get("lock"):
        r = await _post_finish(n, last.get(n, ""), force=True)
        await _after_finish(r, n, action)


async def _finish(n: int, action: cl.Action = None):
    """The student says step n is done: ask for the output when the step checks
    one, send it, and go on to the quiz and the next step."""
    async with cl.user_session.get("lock"):
        st = await _get_state()
        if st is None:
            await cl.Message(content="⚠️ אין חיבור לשרת. נסו שוב בעוד רגע.").send()
            return
        if not st.get("open") or st["step"]["n"] != n:
            await _not_this_step(st, n)
            return
        output = ""
        if st["step"]["needs_output"]:
            output = await _prompt(
                f"📋 הדביקו כאן את הפלט של שלב {st['step']['label']}: כל מה שהופיע בטרמינל אחרי "
                "הפקודות (אפשר גם עם הפקודות עצמן). ואז שלחו.", timeout=900)
            if not output:
                await cl.Message(content="לא התקבל פלט. לחצו שוב על «סיימתי» כשתהיו מוכנים.").send()
                return
            last = cl.user_session.get("last_output") or {}
            last[n] = output
            cl.user_session.set("last_output", last)
        r = await _post_finish(n, output, force=False)
        await _after_finish(r, n, action)


async def _post_finish(n: int, output: str, force: bool):
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{BACKEND}/api/steps/finish", headers=_auth(), json={
                "session_id": cl.user_session.get("session_id"), "step": n,
                "output": output, "force": force})
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
        await cl.Message(content="⚠️ לא הצלחנו לשמור את השלב. נסו שוב בעוד רגע.").send()
        return
    if r["status"] == "missing":
        lines = "\n".join(f"- `{h}`" if _looks_like_code(h) else f"- {h}" for h in r["missing"])
        await cl.Message(
            content=(f"🔍 בפלט של שלב {label} חסר:\n{lines}\n\n"
                     "בדקו את «שימו לב» בשלב, הריצו שוב, והדביקו את הפלט החדש. אם אתם בטוחים שהכול "
                     "בסדר, אפשר להמשיך בכל זאת (המרצה יראה את זה)."),
            actions=[cl.Action(name="finish", payload={"step": n}, label="📋 להדביק שוב"),
                     cl.Action(name="force", payload={"step": n}, label="⏭️ להמשיך בכל זאת")],
        ).send()
        return
    if r["status"] != "done":
        await _not_this_step(r["state"], n)
        return
    if action is not None:
        await action.remove()
    note = " הפלט נראה תקין." if r.get("ok") else ""
    if r.get("quiz"):
        note += " לפני השלב הבא, שאלה קצרה."
    await cl.Message(content=f"✅ שלב {label} הושלם.{note}").send()
    await _ask_pending_probes()
    await _show_state()


async def _not_this_step(st: dict, n: int):
    label = (cl.user_session.get("labels") or {}).get(n, str(n))
    if st.get("finished"):
        text = "כבר סיימתם את כל השלבים. 🎉"
    elif st.get("quiz_pending"):
        text = "קודם ענו על השאלה שלמעלה, ואז השלב הבא יופיע."
    elif st.get("waiting_teacher"):
        text = f"שלב {st['current_label']} עוד לא נפתח. הוא יופיע כאן כשהמרצה יפתח אותו."
    else:
        text = f"שלב {label} כבר הושלם. אתם עכשיו בשלב {st.get('current_label')}."
    await cl.Message(content=text).send()


def _looks_like_code(hint: str) -> bool:
    return not re.search(r"[֐-׿]", hint)


async def _poll(session_id: str, token: str):
    """Every 2 seconds: the teacher's questions, and (class-paced) a step the
    teacher just opened."""
    try:
        while True:
            try:
                async with cl.user_session.get("lock"):
                    await _ask_pending_probes()
                    if cl.user_session.get("paced"):
                        await _show_state()
            except Exception as e:
                log.warning("[poll] %s", e)
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        pass  # chat ended; stop polling cleanly


async def _ask_pending_probes():
    """Ask every question waiting for this student. Call with the lock."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{BACKEND}/api/probes/pending/{cl.user_session.get('session_id')}", headers=_auth())
    except httpx.HTTPError as e:
        log.warning("[probes] %s", e)
        return
    if r.status_code == 200:
        for probe in r.json():
            await _handle_probe(probe)


async def _handle_probe(probe: dict):
    if probe.get("source") == "quiz":
        content = f"❓ **שאלת הבנה על שלב {probe.get('quiz_step')}:**\n\n> {probe['body']}\n\nכתבו את התשובה שלכם:"
    else:
        content = f"🎓 **המרצה שואל/ת:**\n\n> {probe['body']}\n\nכתבו את התשובה שלכם:"
    answer = await _prompt(content)
    if not answer:
        return
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{BACKEND}/api/probes/answer",
                json={"probe_id": probe["id"], "answer": answer},
                headers=_auth(),
            )
    except httpx.HTTPError as e:
        log.warning("probe answer failed: %s", e)
        await cl.Message(content="⚠️ התשובה לא נשלחה. נסו שוב.").send()
        return
    if r.status_code == 200:
        data = r.json()
        grade = f" ציון: **{data['auto_grade']}/2**" if data.get("auto_grade") is not None else ""
        why = f" — {data['why']}" if data.get("why") else ""
        await cl.Message(content=f"✅ התשובה נשמרה.{grade}{why}").send()
    else:
        await cl.Message(content="⚠️ התשובה לא נשלחה. נסו שוב.").send()
