"""Gemini backend for the student-facing chat. Opt-in via STUDENT_LLM=gemini.

Privacy note: when enabled, student messages leave the local network. Default
remains Ollama. Used during dev for speed; flip off before the pilot.
"""
import json
import os
from typing import AsyncIterator

import httpx

API_KEY_ENV = "GEMINI_API_KEY"
MODEL = os.environ.get("STUDENT_LLM_MODEL", "gemini-2.5-flash-lite")
BASE = "https://generativelanguage.googleapis.com/v1beta/models"


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
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=_payload(system_prompt, messages)) as resp:
            resp.raise_for_status()
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
                            yield text


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
