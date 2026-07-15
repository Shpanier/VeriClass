import os

from fastapi import APIRouter

from backend import exercises

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
             variant's starter file into the project (the active exercise's
             `scaffold_filename` picks the language, e.g. mcalc.c / pycalc.py)
             and show the variant's required test inputs as a checklist.

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

    # The active exercise's scaffold_filename wins (so activating a Python
    # exercise scaffolds pycalc.py without any .env change); fall back to the
    # global SCAFFOLD_FILENAME env, then the original mcalc.c default.
    try:
        chosen = (exercises.active().get("scaffold_filename") or "").strip()
    except Exception:
        chosen = ""
    scaffold_filename = chosen or os.environ.get("SCAFFOLD_FILENAME", "mcalc.c").strip() or "mcalc.c"

    return {
        "mode": mode,
        "scaffold_filename": scaffold_filename,
        "poll_interval_ms": 2000,
        "exam_mode": exam_mode,
        "force_fullscreen": force_fullscreen,
        "heartbeat_ms": 30000,
        # Dev convenience: hand the plugin a code to auto-login with, so it needs
        # no per-machine setup — the same DEV_AUTO_LOGIN_CODE the Chainlit student
        # app uses. Empty (the default) in exam/production, so auto-login is off
        # there. Only ever a student code; never a teacher one.
        "dev_auto_login_code": os.environ.get("DEV_AUTO_LOGIN_CODE", "").strip(),
    }
