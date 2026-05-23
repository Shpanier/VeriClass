import json
import os
from typing import AsyncIterator

import httpx

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")


async def stream_chat(
    system_prompt: str, messages: list[dict], timeout: float = 60.0
) -> AsyncIterator[str]:
    """Yield tokens as they arrive from Ollama."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system_prompt}, *messages],
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", f"{OLLAMA_HOST}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                obj = json.loads(line)
                token = obj.get("message", {}).get("content")
                if token:
                    yield token
                if obj.get("done"):
                    break


async def grade_answer(question: str, answer: str, variant_params: dict) -> tuple[int, str]:
    """Returns (score 0–2, one-line justification)."""
    prompt = (
        "You grade a student's answer to a targeted comprehension question.\n"
        "Score: 0 = wrong/missing, 1 = partially correct, 2 = correct.\n"
        f"Variant params: {json.dumps(variant_params)}\n\n"
        f"Question: {question}\n"
        f"Student answer: {answer}\n\n"
        "Reply with strict JSON: {\"score\": 0|1|2, \"why\": \"one short line\"}"
    )
    text = ""
    async for tok in stream_chat(prompt, [{"role": "user", "content": "Grade now."}]):
        text += tok
    try:
        result = json.loads(text)
        return int(result["score"]), str(result["why"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return 0, "Could not parse grader output"
