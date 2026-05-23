import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

from backend import db
from backend.prompts import probe_meta_prompt
from backend.sanitize import sanitize

CONFIG_PATH = Path(__file__).parent.parent / "config" / "cloud_llm.yaml"


@dataclass
class ProbeContext:
    variant_id: str
    variant_params: dict
    recent_chat: str
    latest_code: str
    action_log: str


@dataclass
class ProbeSuggestion:
    kind: str
    body: str
    rationale: str


def _load_config() -> dict[str, Any]:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


async def suggest_probes(ctx: ProbeContext) -> list[ProbeSuggestion]:
    cfg = _load_config()
    sanitized_ctx = ProbeContext(
        variant_id=ctx.variant_id,
        variant_params=ctx.variant_params,
        recent_chat=sanitize(ctx.recent_chat),
        latest_code=sanitize(ctx.latest_code),
        action_log=sanitize(ctx.action_log),
    )
    meta = probe_meta_prompt(sanitized_ctx.__dict__)

    primary = await _call_provider(
        cfg["provider"], cfg["model"], cfg["api_key_env"], meta, cfg["timeout_sec"]
    )
    if primary is not None:
        return _parse_suggestions(primary)

    if "fallback_provider" in cfg:
        secondary = await _call_provider(
            cfg["fallback_provider"],
            cfg["fallback_model"],
            cfg["fallback_api_key_env"],
            meta,
            cfg["timeout_sec"],
        )
        if secondary is not None:
            return _parse_suggestions(secondary)

    return _fallback_suggestions(ctx)


async def _call_provider(
    provider: str, model: str, key_env: str, prompt: str, timeout: int
) -> Optional[str]:
    key = os.environ.get(key_env, "")
    if not key:
        return None
    started = time.time()
    try:
        if provider == "gemini":
            text = await _call_gemini(key, model, prompt, timeout)
        elif provider == "openai":
            text = await _call_openai(key, model, prompt, timeout)
        elif provider == "anthropic":
            text = await _call_anthropic(key, model, prompt, timeout)
        else:
            return None
    except Exception as e:
        print(f"[cloud_llm] {provider} call failed: {e}")
        return None
    finally:
        latency_ms = int((time.time() - started) * 1000)
        _audit(provider, model, prompt, latency_ms)
    return text


async def _call_gemini(key: str, model: str, prompt: str, timeout: int) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def _call_openai(key: str, model: str, prompt: str, timeout: int) -> str:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions", json=payload, headers=headers
        )
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]


async def _call_anthropic(key: str, model: str, prompt: str, timeout: int) -> str:
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages", json=payload, headers=headers
        )
        r.raise_for_status()
        data = r.json()
    return data["content"][0]["text"]


def _parse_suggestions(text: str) -> list[ProbeSuggestion]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        return []
    return [
        ProbeSuggestion(kind=i.get("kind", "?"), body=i.get("body", ""), rationale=i.get("rationale", ""))
        for i in items
    ][:3]


def _fallback_suggestions(ctx: ProbeContext) -> list[ProbeSuggestion]:
    return [
        ProbeSuggestion(
            kind="Trace",
            body=f"Walk through what your code does on input "
            f"'{ctx.variant_params.get('operators', ['+'])[0]} test'. What value does "
            f"your main variable hold at the end?",
            rationale="Local fallback — cloud LLM unavailable.",
        )
    ]


def _audit(provider: str, model: str, sanitized: str, latency_ms: int) -> None:
    with db.conn() as c:
        c.execute(
            "INSERT INTO api_audit_log (provider, model, latency_ms, sanitized_input) "
            "VALUES (?, ?, ?, ?)",
            (provider, model, latency_ms, sanitized[:8000]),
        )
