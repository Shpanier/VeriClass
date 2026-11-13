"""The server's own settings, kept in one file: `.env` at the top of the folder.

The dashboard's setup page writes here (the LLM provider and its API key, the
language of the student chat), so a lecturer never has to open the file. A
change is applied to the running server at once: the modules that read these
values at import time are told to read them again (`configure()` in each).

Tests point VERICLASS_ENV_FILE at a throwaway file.
"""
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

import httpx

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.0.0"

PROVIDERS: dict[str, dict[str, str]] = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "key_env": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com/settings/keys",
    },
    "gemini": {
        "label": "Google (Gemini)",
        "key_env": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/apikey",
    },
}
# Written to .env when a provider is chosen for the first time and nothing is set yet.
_FIRST_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {"CLAUDE_MODEL": "claude-haiku-5-5"},
    "gemini": {},
}
CHAT_LANGUAGES = ("auto", "he", "en")


def env_file() -> Path:
    return Path(os.environ.get("VERICLASS_ENV_FILE") or (ROOT / ".env"))


_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def _format(value: str) -> str:
    """A value as it is written after KEY=: quoted only when it has to be."""
    if value == "" or re.fullmatch(r"[A-Za-z0-9_./:@%+,\-]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_env(updates: dict[str, str]) -> Path:
    """Set KEY=value in .env and in this process. Every other line and comment
    of the file stays as it is; the file is created when missing (readable only
    by its owner, since it holds the API key)."""
    path = env_file()
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    left = dict(updates)
    out: list[str] = []
    for line in lines:
        m = _LINE.match(line)
        if m and m.group(1) in left:
            key = m.group(1)
            out.append(f"{key}={_format(left.pop(key))}")
        else:
            out.append(line)
    if left:
        if out and out[-1].strip():
            out.append("")
        out.extend(f"{k}={_format(v)}" for k, v in left.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out) + "\n")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass  # Windows: the folder's own permissions apply
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    for k, v in updates.items():
        os.environ[k] = v
    return path


def reconfigure() -> None:
    """Have the LLM modules read the environment again."""
    from backend import student_llm
    from backend.agents import llm as agent_llm

    student_llm.configure()
    agent_llm.configure()


# --- the LLM ------------------------------------------------------------------------


def provider() -> str:
    p = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    return p if p in PROVIDERS else "gemini"


def _hint(key: str) -> str:
    return f"…{key[-4:]}" if len(key) >= 12 else ""


def llm_status() -> dict[str, Any]:
    """What the dashboard shows about the LLM. Never the key itself."""
    from backend import student_llm
    from backend.agents import llm as agent_llm

    p = provider()
    key = os.environ.get(PROVIDERS[p]["key_env"], "").strip()
    return {
        "provider": p,
        "provider_label": PROVIDERS[p]["label"],
        "ready": bool(key),
        "key_hint": _hint(key),
        "chat_model": student_llm.MODEL,
        "agent_model": agent_llm.default_model_name(),
        "providers": [
            {"id": pid, "label": spec["label"], "key_url": spec["key_url"],
             "key_set": bool(os.environ.get(spec["key_env"], "").strip()),
             "key_hint": _hint(os.environ.get(spec["key_env"], "").strip())}
            for pid, spec in PROVIDERS.items()
        ],
    }


async def test_key(provider_id: str, key: str) -> dict[str, Any]:
    """Ask the provider whether the key works (lists its models: no tokens are
    spent). {ok, message, model_ok}: model_ok is False when the key works but the
    model this server would use isn't offered to it."""
    if provider_id not in PROVIDERS:
        return {"ok": False, "message": "Unknown provider."}
    key = (key or "").strip()
    if not key:
        return {"ok": False, "message": "Paste the API key first."}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if provider_id == "anthropic":
                r = await client.get("https://api.anthropic.com/v1/models", params={"limit": 1000},
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
            else:
                r = await client.get("https://generativelanguage.googleapis.com/v1beta/models",
                                     params={"key": key, "pageSize": 1000})
    except httpx.HTTPError:
        return {"ok": False, "network": True,
                "message": "Couldn't reach the provider. Check this computer's internet connection."}
    if r.status_code in (400, 401, 403):
        return {"ok": False, "message": "The provider refused this key. Copy it again, with no spaces."}
    if r.status_code != 200:
        return {"ok": False, "message": f"The provider answered with an error ({r.status_code}). Try again in a minute."}
    try:
        body = r.json()
        names = ([m.get("id", "") for m in body.get("data", [])] if provider_id == "anthropic"
                 else [m.get("name", "").removeprefix("models/") for m in body.get("models", [])])
    except ValueError:
        names = []
    wanted = _model_for(provider_id)
    model_ok = (not names) or any(n == wanted or n.startswith(wanted + "-") for n in names)
    return {"ok": True, "model": wanted, "model_ok": model_ok,
            "message": "The key works." if model_ok else
            f"The key works, but the model '{wanted}' isn't offered to it. Change the model in .env."}


def _model_for(provider_id: str) -> str:
    if provider_id == "anthropic":
        return os.environ.get("CLAUDE_MODEL", "").strip() or _FIRST_MODELS["anthropic"]["CLAUDE_MODEL"]
    return os.environ.get("STUDENT_CHAT_MODEL", "").strip() or "gemini-2.5-flash-lite"


def save_llm(provider_id: str, key: Optional[str]) -> dict[str, Any]:
    """Choose the provider and (when given) store its key. Applied at once."""
    if provider_id not in PROVIDERS:
        raise ValueError("Unknown provider.")
    spec = PROVIDERS[provider_id]
    key = (key or "").strip()
    if not key and not os.environ.get(spec["key_env"], "").strip():
        raise ValueError("Paste the API key first.")
    updates = {"LLM_PROVIDER": provider_id}
    if key:
        updates[spec["key_env"]] = key
    for name, value in _FIRST_MODELS[provider_id].items():
        if not os.environ.get(name, "").strip():
            updates[name] = value
    save_env(updates)
    reconfigure()
    return llm_status()


# --- the student chat's language ---------------------------------------------------


def chat_language() -> str:
    v = os.environ.get("CHAT_LANGUAGE", "auto").strip().lower()
    return v if v in CHAT_LANGUAGES else "auto"


def save_chat_language(value: str) -> str:
    value = (value or "").strip().lower()
    if value not in CHAT_LANGUAGES:
        raise ValueError("The chat language is one of: auto, he, en.")
    save_env({"CHAT_LANGUAGE": value})
    return value


# --- did the last tutor call work? ----------------------------------------------------
# Kept in memory for the dashboard's status line: a refused key or a spending
# limit shows there (the student is only told to turn to the lecturer).

_LLM_HEALTH: dict[str, Any] = {"ok": None, "error": "", "at": None}


def note_llm(ok: bool, error: str = "") -> None:
    import time

    _LLM_HEALTH.update(ok=ok, error="" if ok else error, at=time.time())


def llm_health() -> dict[str, Any]:
    return dict(_LLM_HEALTH)
