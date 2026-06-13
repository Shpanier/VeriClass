import os

from fastapi import APIRouter

router = APIRouter()

# Single source of truth for which student client behavior is active. The
# CLion plugin can't read the repo's .env (it runs inside the IDE process), so
# the backend reads STUDENT_CLIENT_MODE here and the plugin fetches it at
# session start. Chainlit ignores this endpoint — it always behaves as a
# plain chat client.
_VALID_MODES = ("chat", "ide")


@router.get("/client-config")
def client_config():
    """Tell a rich client (the CLion plugin) how to behave.

    mode:
      chat — faithful chat port: login + briefing + streaming chat + probes.
      ide  — IDE-native: everything in `chat` PLUS scaffold the assigned
             variant's starter C file into the project and show the variant's
             required test inputs as a checklist.
    """
    mode = os.environ.get("STUDENT_CLIENT_MODE", "chat").strip().lower()
    if mode not in _VALID_MODES:
        mode = "chat"
    return {
        "mode": mode,
        "scaffold_filename": os.environ.get("SCAFFOLD_FILENAME", "mcalc.c").strip() or "mcalc.c",
        "poll_interval_ms": 2000,
    }
