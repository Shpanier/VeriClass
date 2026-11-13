"""First run, settings and the students' link: what a lecturer needs to get a
class going without a terminal.

  GET  /api/setup/status          is there a lecturer account yet? (public)
  POST /api/setup/teacher         create the first one (only while there is none,
                                  and only from this computer)
  GET  /api/settings              the LLM, the chat language, folders, version
  POST /api/settings/llm          choose the provider and store its API key (.env)
  POST /api/settings/llm/test     does this key work? (nothing is saved)
  POST /api/settings/chat-language
  GET  /api/share                 the students' link(s) and the tunnel's state
  POST /api/share/tunnel          start / stop the tunnel; download cloudflared
  GET  /api/overview              counts for the dashboard's first-steps checklist
"""
import asyncio
import os
import re
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend import auth, courses, db, deps, exercises, packages, passwords, settings, tunnel

router = APIRouter()

_USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")


def _teacher_count() -> int:
    with db.conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'teacher'").fetchone()["n"]


@router.get("/setup/status")
def setup_status(request: Request):
    """Public, and says nothing sensitive: whether the first lecturer account
    still has to be created, and whether this browser may create it."""
    return {"needs_teacher": _teacher_count() == 0, "local": deps.is_local_request(request),
            "version": settings.VERSION}


class FirstTeacher(BaseModel):
    name: str
    username: str
    password: str


@router.post("/setup/teacher", status_code=201)
def create_first_teacher(req: FirstTeacher, request: Request):
    """The first lecturer account. Refused once any lecturer exists, and from
    any computer but this one, so a student can't claim a fresh server."""
    if not deps.is_local_request(request):
        raise HTTPException(403, "The first account is created on the lecturer's computer.")
    if _teacher_count() > 0:
        raise HTTPException(409, "A lecturer account already exists. Sign in with it.")
    name = " ".join(req.name.split())
    username = req.username.strip()
    if not name:
        raise HTTPException(422, "Enter your name.")
    if not _USERNAME.match(username):
        raise HTTPException(422, "A username is 3 to 32 letters, digits, dots, dashes or underscores.")
    problem = passwords.check_new(req.password)
    if problem:
        raise HTTPException(422, problem)
    code = username.upper()
    try:
        with db.conn() as c:
            c.execute("INSERT INTO users (username, login_code, role, password_hash) VALUES (?, ?, 'teacher', ?)",
                      (name, code, passwords.hash_password(req.password)))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That name or username is already taken. Choose another.")
    result = auth.login_with_code(code, req.password, deps.client_ip(request), rate_limit=False)
    if not result or "token" not in result:
        raise HTTPException(500, "The account was created, but signing in failed. Sign in with it.")
    result["courses"] = courses.for_user(result["user_id"], result["role"])
    return result


# --- settings --------------------------------------------------------------------------


def _plugin_ui() -> bool:
    """Show the dashboard's IDE-plugin screens (exam monitoring, terminal log,
    submissions)? PLUGIN_UI=on|off decides; otherwise they show once a plugin
    was published to this server or a student ever worked from the IDE."""
    v = os.environ.get("PLUGIN_UI", "auto").strip().lower()
    if v in ("on", "true", "1", "yes"):
        return True
    if v in ("off", "false", "0", "no"):
        return False
    from backend.routes import plugin

    try:
        if any(plugin.DIST_DIR.glob("latest*.json")):
            return True
    except OSError:
        pass
    with db.conn() as c:
        for table in ("proctor_events", "terminal_commands", "submissions"):
            if c.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                return True
    return False


@router.get("/settings")
def get_settings(teacher: dict = Depends(deps.require_teacher)):
    return {
        "version": settings.VERSION,
        "user": {"name": teacher.get("username"), "via": teacher.get("via", "login")},
        "llm": {**settings.llm_status(), "health": settings.llm_health()},
        "chat_language": settings.chat_language(),
        "plugin_ui": _plugin_ui(),
        "paths": {"env_file": str(settings.env_file()), "data_dir": str(packages.DATA_DIR),
                  "database": str(db.DB_PATH.resolve())},
    }


class LlmRequest(BaseModel):
    provider: str
    # None or empty: keep the key already stored for this provider.
    api_key: Optional[str] = None


@router.post("/settings/llm/test")
async def test_llm(req: LlmRequest, teacher: dict = Depends(deps.require_teacher)):
    spec = settings.PROVIDERS.get(req.provider)
    if spec is None:
        raise HTTPException(422, "Unknown provider.")
    key = (req.api_key or "").strip() or os.environ.get(spec["key_env"], "")
    return await settings.test_key(req.provider, key)


@router.post("/settings/llm")
async def save_llm(req: LlmRequest, teacher: dict = Depends(deps.require_teacher)):
    """Store the provider and key in .env and use them from now on. The key is
    checked first; a key the provider refuses is not saved (a network failure
    doesn't block saving: the lecturer may be offline while setting up)."""
    spec = settings.PROVIDERS.get(req.provider)
    if spec is None:
        raise HTTPException(422, "Unknown provider.")
    key = (req.api_key or "").strip()
    check = await settings.test_key(req.provider, key or os.environ.get(spec["key_env"], ""))
    if not check["ok"] and not check.get("network"):
        raise HTTPException(422, check["message"])
    try:
        status = settings.save_llm(req.provider, key or None)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if check["ok"]:
        settings.note_llm(True)
    return {"llm": {**status, "health": settings.llm_health()}, "check": check}


class ChatLanguage(BaseModel):
    language: str


@router.post("/settings/chat-language")
def save_chat_language(req: ChatLanguage, teacher: dict = Depends(deps.require_teacher)):
    try:
        return {"chat_language": settings.save_chat_language(req.language)}
    except ValueError as e:
        raise HTTPException(422, str(e))


# --- the students' link ------------------------------------------------------------------


@router.get("/share")
def share(teacher: dict = Depends(deps.require_teacher)):
    return tunnel.status()


class TunnelRequest(BaseModel):
    action: str  # start | stop | download
    provider: Optional[str] = None


@router.post("/share/tunnel")
async def share_tunnel(req: TunnelRequest, teacher: dict = Depends(deps.require_teacher)):
    if req.action == "stop":
        await asyncio.to_thread(tunnel.stop)
    elif req.action == "download":
        try:
            await asyncio.to_thread(tunnel.download_cloudflared)
        except Exception as e:
            raise HTTPException(502, f"The download failed: {e}. You can install it yourself: {tunnel.install_hint()}")
    elif req.action == "start":
        try:
            tunnel.start(req.provider)
        except FileNotFoundError as e:
            raise HTTPException(409, f"{e} isn't installed on this computer.")
        except ValueError as e:
            raise HTTPException(422, str(e))
    else:
        raise HTTPException(422, "action is one of: start, stop, download.")
    return tunnel.status()


# --- first steps ----------------------------------------------------------------------------


@router.get("/overview")
def overview(teacher: dict = Depends(deps.require_teacher)):
    """How far the setup is, for the dashboard's first-steps checklist."""
    with db.conn() as c:
        students = c.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'student'").fetchone()["n"]
        n_courses = c.execute("SELECT COUNT(*) AS n FROM courses").fetchone()["n"]
        offered = c.execute("SELECT COUNT(*) AS n FROM course_exercises").fetchone()["n"]
        members = c.execute("SELECT COUNT(*) AS n FROM course_members").fetchone()["n"]
        sessions = c.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    return {
        "llm_ready": settings.llm_status()["ready"],
        "students": students,
        "courses": n_courses,
        "courses_with_exercise": offered > 0,
        "courses_with_students": members > 0,
        "exercises": len(exercises.all()),
        "own_exercises": sum(1 for e in exercises.all() if e.get("source") != "yaml"),
        "sessions": sessions,
    }
