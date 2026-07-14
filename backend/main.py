import logging
from contextlib import asynccontextmanager
from pathlib import Path

# Must run before any `from backend...` import — submodules read env vars at
# import time (e.g. gemini_student.MODEL, agents.llm.DEFAULT_MODEL), so .env has
# to be in os.environ first or those constants freeze to their defaults.
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import db, exercises
from backend.routes import (
    ask,
    client_config,
    exercises as ex_routes,
    grade,
    login,
    mode,
    plugin,
    probes,
    proctor,
    review,
    sessions,
    students,
    submissions,
)

# Silence the noisy per-request access log (polling hits /api/students and
# /api/probes/pending every 2-3 seconds and floods the terminal). Warnings
# and errors still surface.
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

EXERCISES_DIR = Path(__file__).parent.parent / "config" / "exercises"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_schema()
    loaded = exercises.load_all(EXERCISES_DIR)
    if not loaded:
        raise RuntimeError(
            f"No exercises found in {EXERCISES_DIR}. "
            "At least one YAML file must exist for the system to boot."
        )
    # Merge in teacher-authored exercises created from the instructor console.
    exercises.load_from_db()
    print(f"[startup] loaded {len(loaded)} exercise(s): {list(loaded)}")
    yield


app = FastAPI(title="OS Lab Backend", lifespan=lifespan)

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


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
