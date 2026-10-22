"""Claude backend for the direct (non-review) student chat.

Mirrors gemini_student: streams token-by-token over httpx against the Anthropic
Messages API (SSE). Selected with LLM_PROVIDER=anthropic; the model comes from
CLAUDE_MODEL (default Sonnet).
"""
import asyncio
import json
import logging
import os
from typing import AsyncIterator

import httpx

log = logging.getLogger(__name__)

API_KEY_ENV = "ANTHROPIC_API_KEY"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
URL = "https://api.anthropic.com/v1/messages"
MAX_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", "2048"))

# 429 = rate limited, 529 = overloaded; both transient.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}
_MAX_ATTEMPTS = 3


def _to_claude(messages: list[dict]) -> list[dict]:
    """Clean user/assistant alternation starting with a user turn (same rules as
    gemini_student._to_gemini: drop empty turns, merge same-role neighbours)."""
    out: list[dict] = []
    for m in messages:
        text = (m.get("content") or "").strip()
        if not text:
            continue
        role = "assistant" if m["role"] == "assistant" else "user"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + text
        else:
            out.append({"role": role, "content": text})
    while out and out[0]["role"] == "assistant":
        out.pop(0)
    return out


async def stream_chat(
    system_prompt: str, messages: list[dict], timeout: float = 60.0, model: str | None = None
) -> AsyncIterator[str]:
    """[model] overrides CLAUDE_MODEL (the "ask again" model, see student_llm)."""
    model = model or MODEL
    headers = {
        "x-api-key": os.environ[API_KEY_ENV],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt,
        "messages": _to_claude(messages),
        "stream": True,
    }

    for attempt in range(_MAX_ATTEMPTS):
        emitted = False
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", URL, json=payload, headers=headers) as resp:
                    if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS - 1:
                        await resp.aread()
                        delay = 0.6 * (2 ** attempt)
                        log.warning("claude %s (HTTP %s); retry %d/%d in %.1fs",
                                    model, resp.status_code, attempt + 1, _MAX_ATTEMPTS - 1, delay)
                        await asyncio.sleep(delay)
                        continue
                    if resp.is_error:
                        await resp.aread()
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            obj = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        if obj.get("type") == "content_block_delta":
                            text = obj.get("delta", {}).get("text")
                            if text:
                                emitted = True
                                yield text
                        elif obj.get("type") == "error":
                            raise RuntimeError(obj.get("error", {}).get("message", "Claude stream error"))
            return
        except (httpx.TransportError, httpx.TimeoutException) as e:
            if emitted or attempt == _MAX_ATTEMPTS - 1:
                raise
            delay = 0.6 * (2 ** attempt)
            log.warning("claude network error (%s); retry %d/%d in %.1fs",
                        type(e).__name__, attempt + 1, _MAX_ATTEMPTS - 1, delay)
            await asyncio.sleep(delay)
