import os

from fastapi import APIRouter

router = APIRouter()

# Single source of truth for which student client behavior is active. The
# CLion plugin can't read the repo's .env (it runs inside the IDE process), so
# the backend reads STUDENT_CLIENT_MODE here and the plugin fetches it at
# session start. Chainlit ignores this endpoint — it always behaves as a
# plain chat client.
_VALID_MODES = ("chat", "ide")


def _envbool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@router.get("/client-config")
def client_config():
    """Tell a rich client (the CLion plugin) how to behave.

    mode:
      chat — faithful chat port: login + briefing + streaming chat + probes.
      ide  — IDE-native: everything in `chat` PLUS scaffold the assigned
             variant's starter C file into the project and show the variant's
             required test inputs as a checklist.

    Exam/proctor controls (the plugin's anti-cheating "exam mode"):
      exam_mode       — when true the plugin reports to POST /api/proctor/event
                        whenever the student leaves the IDE (minimize, switch
                        app, leave fullscreen) so the dashboard can flag it.
                        Defaults ON in `ide` mode, OFF in `chat`; override with
                        EXAM_MODE in .env.
      force_fullscreen — the plugin puts CLion in full screen at exam start and
                        re-asserts it if the student leaves. Defaults to
                        whatever exam_mode is; override with FULLSCREEN.
      heartbeat_ms    — how often the plugin pings the backend to stay on the
                        live grid during a quiet exam.
    """
    mode = os.environ.get("STUDENT_CLIENT_MODE", "chat").strip().lower()
    if mode not in _VALID_MODES:
        mode = "chat"

    exam_mode = _envbool("EXAM_MODE", default=(mode == "ide"))
    force_fullscreen = _envbool("FULLSCREEN", default=exam_mode)

    return {
        "mode": mode,
        "scaffold_filename": os.environ.get("SCAFFOLD_FILENAME", "mcalc.c").strip() or "mcalc.c",
        "poll_interval_ms": 2000,
        "exam_mode": exam_mode,
        "force_fullscreen": force_fullscreen,
        "heartbeat_ms": 30000,
    }
