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


# LLM_PROVIDER=anthropic switches every agent to Claude (CLAUDE_MODEL, default Sonnet).
PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")


def _api_key() -> str:
    env = "ANTHROPIC_API_KEY" if PROVIDER == "anthropic" else "GEMINI_API_KEY"
    key = os.environ.get(env, "")
    if not key:
        raise RuntimeError(f"{env} is not set — the agent layer requires it (LLM_PROVIDER={PROVIDER}).")
    return key


def gemini_llm(
    model: str | None = None,
    temperature: float = 0.4,
    timeout: float | None = None,
) -> LLM:
    """Return a CrewAI LLM pinned to Gemini.

    `model` is a bare Gemini model name (e.g. 'gemini-2.5-pro'); the 'gemini/'
    provider prefix is added here so callers never name a provider. `timeout`
    overrides the config default (useful for long generations like writing a full
    program, which can exceed the standard 30s).
    """
    tmo = timeout if timeout is not None else float(_config().get("timeout_sec", 30))
    if PROVIDER == "anthropic":
        # Current Claude models reject `temperature`, so it is not sent.
        return LLM(model=f"anthropic/{CLAUDE_MODEL}", api_key=_api_key(),
                   timeout=tmo, max_tokens=4096)
    name = model or _config().get("model") or DEFAULT_MODEL
    return LLM(
        model=f"gemini/{name}",
        api_key=_api_key(),
        temperature=temperature,
        timeout=tmo,
    )
