import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Must run before any `from backend...` import — submodules read env vars at
# import time (e.g. gemini_student.MODEL, agents.llm.DEFAULT_MODEL), so .env has
# to be in os.environ first or those constants freeze to their defaults.
from dotenv import load_dotenv
load_dotenv(os.environ.get("VERICLASS_ENV_FILE") or Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend import db, deps, exercises, settings, tunnel
from backend.routes import (
    ask,
    broadcast as broadcast_routes,
    client_config,
    courses as course_routes,
    exercises as ex_routes,
    files,
    grade,
    login,
    mode,
    notifications as notification_routes,
    pacing as pacing_routes,
    plugin,
    probes,
    proctor,
    review,
    sessions,
    setup as setup_routes,
    steps as step_routes,
    students,
    submissions,
    terminal as terminal_routes,
    trace as trace_routes,
    transcript as transcript_routes,
    reports as report_routes,
)

# Silence the noisy per-request access log (polling hits /api/students and
# /api/probes/pending every 2-3 seconds and floods the terminal). Warnings
# and errors still surface.
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

EXERCISES_DIR = Path(__file__).parent.parent / "config" / "exercises"
# The lecturer's dashboard, built (dashboard/: npm run build). When it is here
# this server serves it at "/", so nobody needs Node to run a class.
WEB_DIR = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_schema()
    deps.ensure_local_token()
    review.recover()  # answers still being drafted when the server last stopped
    loaded = exercises.load_all(EXERCISES_DIR)
    if not loaded:
        raise RuntimeError(
            f"No exercises found in {EXERCISES_DIR}. "
            "At least one YAML file must exist for the system to boot."
        )
    # Merge in teacher-authored exercises created from the instructor console.
    exercises.load_from_db()
    print(f"[startup] loaded {len(loaded)} exercise(s): {list(loaded)}")
    _banner()
    yield
    tunnel.stop()


def _banner() -> None:
    """What to open, and what is still missing, in plain ASCII (a Windows
    console may not print anything else)."""
    port = tunnel.port()
    chat = tunnel.chat_path()
    lines = ["", "  VeriClass is running. Keep this window open during the class.", ""]
    if (WEB_DIR / "index.html").is_file():
        lines.append(f"    Lecturer's dashboard:  http://localhost:{port}/")
    else:
        lines.append("    Lecturer's dashboard:  not built here; run it with: cd dashboard && npm run dev")
    if chat:
        lines.append(f"    Students' chat:        http://localhost:{port}{chat}/")
        lines.append("                           (for a class: \"Share with students\" in the dashboard)")
    with db.conn() as c:
        teachers = c.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'teacher'").fetchone()["n"]
    notes = []
    if teachers == 0:
        notes.append("No lecturer account yet: the dashboard will ask you to create one.")
    if not settings.llm_status()["ready"]:
        notes.append("No API key yet: the dashboard will ask for it (Settings).")
    if notes:
        lines.append("")
        lines.extend(f"    * {n}" for n in notes)
    lines.append("")
    print("\n".join(lines), flush=True)


# The interactive API pages (/docs) would be public through the tunnel; they are
# for development (API_DOCS=true).
_DOCS = os.environ.get("API_DOCS", "").strip().lower() in ("1", "true", "yes", "on")
app = FastAPI(title="VeriClass Backend", lifespan=lifespan, version=settings.VERSION,
              docs_url="/docs" if _DOCS else None, redoc_url=None,
              openapi_url="/openapi.json" if _DOCS else None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8011"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(login.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(ex_routes.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
app.include_router(probes.router, prefix="/api")
app.include_router(students.router, prefix="/api")
app.include_router(mode.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(client_config.router, prefix="/api")
app.include_router(proctor.router, prefix="/api")
app.include_router(submissions.router, prefix="/api")
app.include_router(plugin.router, prefix="/api")
app.include_router(grade.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(step_routes.router, prefix="/api")
app.include_router(pacing_routes.router, prefix="/api")
app.include_router(transcript_routes.router, prefix="/api")
app.include_router(terminal_routes.router, prefix="/api")
app.include_router(trace_routes.router, prefix="/api")
app.include_router(course_routes.router, prefix="/api")
app.include_router(report_routes.router, prefix="/api")
app.include_router(broadcast_routes.router, prefix="/api")
app.include_router(setup_routes.router, prefix="/api")
app.include_router(notification_routes.router, prefix="/api")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# The students' chat (student_app, Chainlit) inside this server at
# STUDENT_CHAT_PATH (e.g. /chat), so the tunnel that serves the plugin serves the
# chat too. It calls this server's API at BACKEND_URL (its own address, e.g.
# http://127.0.0.1:8010). The start scripts (backend/cli.py) turn it on at /chat;
# without it, run the chat as its own process: chainlit run student_app/app.py.
_CHAT_PATH = os.environ.get("STUDENT_CHAT_PATH", "").strip().rstrip("/")
if _CHAT_PATH:
    from chainlit.utils import mount_chainlit

    mount_chainlit(app=app, target=str(Path(__file__).resolve().parent.parent / "student_app" / "app.py"),
                   path=_CHAT_PATH)
    # The chat's own files (logo, sign-in picture, theme). Chainlit serves them
    # under the chat's path; its sign-in page asks for the picture at /public.
    _PUBLIC = Path(__file__).resolve().parent.parent / "public"
    if _PUBLIC.is_dir():
        app.mount("/public", StaticFiles(directory=_PUBLIC), name="chat-public")


# The lecturer's dashboard at "/". Registered last, so every address above
# (the API, /healthz, the chat) wins over the one-segment file route below.
if (WEB_DIR / "index.html").is_file():
    if (WEB_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="dashboard-assets")

    @app.get("/", include_in_schema=False)
    def dashboard(request: Request):
        # A student who opens the bare address gets the chat: the dashboard is
        # for the lecturer's own computer (TEACHER_LOCAL_ONLY).
        if _CHAT_PATH and deps.TEACHER_LOCAL_ONLY and not deps.is_local_request(request):
            return RedirectResponse(f"{_CHAT_PATH}/")
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/{name}", include_in_schema=False)
    def dashboard_file(name: str):
        """A file next to index.html (the icon). Nothing below that folder's top level."""
        path = WEB_DIR / name
        if name in ("", "index.html") or path.parent != WEB_DIR or not path.is_file():
            raise HTTPException(404, "Not Found")
        return FileResponse(path)
