"""Generate three teacher-reviewable answer variants for a student question.

Levels:
  nudge  — a one-line Socratic hint, no answer
  normal — guidance and partial reasoning, no full solution
  more   — normal + extra explanation/examples, still no full solution

Used by /api/ask when review mode is on. The teacher picks one variant in the
dashboard; the chosen one is sent to the student and `answer_level` is logged.
"""
import json
import re

from backend import student_llm

_LEVELS = ("nudge", "normal", "more")

_INSTRUCTION = """\
You generate THREE candidate answers a teacher will choose from before sending
to a student in an OS lab. NEVER include the full working solution. Tailor each
answer to its label:

  nudge   — single short Socratic hint (≤ 2 sentences). No code blocks.
  normal  — guided reasoning with a small targeted pointer. May reference a
            relevant function or syscall by name, but do NOT write the answer
            for them. Short code fragments only (≤ 3 lines) if essential.
  more    — same as normal plus one extra explanation or analogy. Still NO full
            solution, NO complete function body.

Reply with STRICT JSON only, no prose, no markdown fences:
{"nudge": "...", "normal": "...", "more": "..."}
"""


async def generate(system_prompt: str, history: list[dict], student_question: str) -> dict:
    """Return {'nudge': str, 'normal': str, 'more': str}."""
    msgs = list(history) + [
        {"role": "user", "content": student_question},
        {"role": "user", "content": _INSTRUCTION},
    ]
    chunks: list[str] = []
    async for tok in student_llm.stream_chat(system_prompt, msgs):
        chunks.append(tok)
    raw = "".join(chunks).strip()
    return _parse(raw, student_question)


def _parse(raw: str, fallback_question: str) -> dict:
    text = raw.strip()
    # Strip ```json ... ``` fences if the model added them anyway.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Pluck the outermost JSON object if there's extra prose.
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        obj = json.loads(text)
        return {lvl: str(obj.get(lvl, "")).strip() or _placeholder(lvl) for lvl in _LEVELS}
    except (json.JSONDecodeError, AttributeError):
        # Fall back so the teacher still sees *something* and can pick.
        return {lvl: _placeholder(lvl, raw=raw) for lvl in _LEVELS}


def _placeholder(level: str, raw: str = "") -> str:
    hint = {
        "nudge":  "What part of the input are you having trouble parsing?",
        "normal": "Think about how each token in the input maps to an operation. Try printing them in order first.",
        "more":   "Walk through one test input by hand on paper. Which token is the operator? Which are the operands?",
    }[level]
    return hint + (f"\n\n(model output was not valid JSON; raw: {raw[:200]})" if raw else "")
