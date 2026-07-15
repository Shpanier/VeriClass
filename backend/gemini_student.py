"""Gemini backend for the direct (non-review) student chat.

Streams token-by-token over httpx (CrewAI is not used here because it does not
stream). The review drafts, probe suggestions and grading go through the CrewAI
agent layer in backend/agents/. All of it is Gemini.
"""
import asyncio
import json
import logging
import os
from typing import AsyncIterator

import httpx

log = logging.getLogger(__name__)

API_KEY_ENV = "GEMINI_API_KEY"
MODEL = os.environ.get("STUDENT_CHAT_MODEL", "gemini-2.5-flash-lite")
BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Google returns these when the model is momentarily overloaded; they are
# transient, so retry a few times with backoff before giving up.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


def _to_gemini(messages: list[dict]) -> list[dict]:
    """Map [{role:user|assistant, content:...}] → Gemini [{role:user|model, parts:[{text:...}]}].

    Gemini rejects empty parts and mishandles a non-alternating history, so we
    defensively (1) drop empty turns, (2) merge consecutive same-role turns, and
    (3) drop any leading model turn — leaving a clean user/model alternation
    that starts with a user turn. Without this, a single empty/failed turn in the
    stored transcript makes the model answer as if it lost the conversation.
    """
    out: list[dict] = []
    for m in messages:
        text = (m.get("content") or "").strip()
        if not text:
            continue
        role = "model" if m["role"] == "assistant" else "user"
        if out and out[-1]["role"] == role:
            out[-1]["parts"][0]["text"] += "\n\n" + text
        else:
            out.append({"role": role, "parts": [{"text": text}]})
    while out and out[0]["role"] == "model":
        out.pop(0)
    return out


def _payload(system_prompt: str, messages: list[dict]) -> dict:
    return {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": _to_gemini(messages),
    }


async def stream_chat(
    system_prompt: str, messages: list[dict], timeout: float = 60.0
) -> AsyncIterator[str]:
    key = os.environ[API_KEY_ENV]
    # Pass the key in a header, not the query string — a URL key lands in proxy
    # and access logs; a header does not.
    url = f"{BASE}/{MODEL}:streamGenerateContent?alt=sse"
    headers = {"x-goog-api-key": key}
    payload = _payload(system_prompt, messages)

    for attempt in range(_MAX_ATTEMPTS):
        emitted = False  # once we've yielded text we can't safely retry (would duplicate)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    # Transient overload → drain, back off, and retry (if attempts left).
                    if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS - 1:
                        await resp.aread()
                        delay = 0.6 * (2 ** attempt)
                        log.warning(
                            "gemini %s (HTTP %s); retry %d/%d in %.1fs",
                            MODEL, resp.status_code, attempt + 1, _MAX_ATTEMPTS - 1, delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    resp.raise_for_status()  # final attempt or non-retryable → raise
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        blob = line[5:].strip()
                        if not blob or blob == "[DONE]":
                            continue
                        try:
                            obj = json.loads(blob)
                        except json.JSONDecodeError:
                            continue
                        for cand in obj.get("candidates", []):
                            for part in cand.get("content", {}).get("parts", []):
                                text = part.get("text")
                                if text:
                                    emitted = True
                                    yield text
            return  # stream finished cleanly
        except (httpx.TransportError, httpx.TimeoutException) as e:
            # Network hiccup: retry only if nothing was emitted and attempts remain.
            if emitted or attempt == _MAX_ATTEMPTS - 1:
                raise
            delay = 0.6 * (2 ** attempt)
            log.warning("gemini network error (%s); retry %d/%d in %.1fs",
                        type(e).__name__, attempt + 1, _MAX_ATTEMPTS - 1, delay)
            await asyncio.sleep(delay)
