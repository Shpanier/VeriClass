"""Gemini backend for the student-facing chat. Opt-in via STUDENT_LLM=gemini.

Privacy note: when enabled, student messages leave the local network. Default
remains Ollama. Used during dev for speed; flip off before the pilot.
"""
import asyncio
import json
import logging
import os
from typing import AsyncIterator

import httpx

log = logging.getLogger(__name__)

API_KEY_ENV = "GEMINI_API_KEY"
MODEL = os.environ.get("STUDENT_LLM_MODEL", "gemini-2.5-flash-lite")
BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Google returns these when the model is momentarily overloaded; they are
# transient, so retry a few times with backoff before giving up.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


def _to_gemini(messages: list[dict]) -> list[dict]:
    """Map [{role:user|assistant, content:...}] → Gemini [{role:user|model, parts:[{text:...}]}]"""
    out = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        out.append({"role": role, "parts": [{"text": m["content"]}]})
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
    url = f"{BASE}/{MODEL}:streamGenerateContent?alt=sse&key={key}"
    payload = _payload(system_prompt, messages)

    for attempt in range(_MAX_ATTEMPTS):
        emitted = False  # once we've yielded text we can't safely retry (would duplicate)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
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


async def grade_answer(question: str, answer: str, variant_params: dict) -> tuple[int, str]:
    prompt = (
        "You grade a student's answer to a targeted comprehension question.\n"
        "Score: 0 = wrong/missing, 1 = partially correct, 2 = correct.\n"
        f"Variant params: {json.dumps(variant_params)}\n\n"
        f"Question: {question}\n"
        f"Student answer: {answer}\n\n"
        'Reply with strict JSON: {"score": 0|1|2, "why": "one short line"}'
    )
    text = ""
    async for tok in stream_chat(prompt, [{"role": "user", "content": "Grade now."}]):
        text += tok
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        result = json.loads(text)
        return int(result["score"]), str(result["why"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return 0, "Could not parse grader output"
