"""Single place that builds a Gemini-backed CrewAI LLM.

Everything agent-side talks to Gemini and only Gemini. CrewAI uses LiteLLM
under the hood; the `gemini/<model>` prefix pins it to the Gemini provider, and
LiteLLM reads the key from the GEMINI_API_KEY env var (passed explicitly here so
it also works when the key is loaded late via python-dotenv).
"""
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from crewai import LLM

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "cloud_llm.yaml"

# Default agent model; overridable per-call or via the AGENT_MODEL env var.
DEFAULT_MODEL = os.environ.get("AGENT_MODEL", "gemini-2.5-pro")


@lru_cache(maxsize=1)
def _config() -> dict[str, Any]:
    try:
        with CONFIG_PATH.open() as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set — the agent layer requires a Gemini key."
        )
    return key


def gemini_llm(model: str | None = None, temperature: float = 0.4) -> LLM:
    """Return a CrewAI LLM pinned to Gemini.

    `model` is a bare Gemini model name (e.g. 'gemini-2.5-pro'); the 'gemini/'
    provider prefix is added here so callers never name a provider.
    """
    name = model or _config().get("model") or DEFAULT_MODEL
    timeout = float(_config().get("timeout_sec", 30))
    return LLM(
        model=f"gemini/{name}",
        api_key=_api_key(),
        temperature=temperature,
        timeout=timeout,
    )
