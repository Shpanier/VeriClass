import json

from backend import params as param_utils


# Defaults keep the original OS-course / C behaviour for exercises that don't set
# course_name / language (ex3-mcalc etc.).
_LANG_NAMES = {"c": "C", "cpp": "C++", "python": "Python"}


def course_name(exercise: dict) -> str:
    return exercise.get("course_name") or "Operating Systems"


def code_language(exercise: dict) -> str:
    lang = (exercise.get("language") or "").lower()
    if not lang:
        sf = (exercise.get("scaffold_filename") or "").lower()
        lang = "python" if sf.endswith(".py") else "c"
    return _LANG_NAMES.get(lang, lang)


def student_system_prompt(exercise: dict, variant: dict, mode: str) -> str:
    lang = code_language(exercise)
    rules = (
        "RULES — MENTOR MODE:\n"
        "- Explain concepts and ask Socratic questions.\n"
        f"- You are FORBIDDEN from writing or completing {lang} code for the student.\n"
        f"- Pseudocode allowed only at a high level; never line-by-line {lang}.\n"
        if mode == "mentor"
        else "RULES — CODING PARTNER MODE:\n"
        "- You may write functions, diffs, and tests.\n"
        "- Refuse only if asked to 'solve the whole exercise' or 'do it all for me'.\n"
    )
    brief = param_utils.substitute_brief(
        exercise["brief_md"], variant.get("params", {}), exercise.get("param_labels", [])
    )
    parts = [
        f"You are a teaching assistant for the {course_name(exercise)} course exercise "
        f"'{exercise['title_en']}'.",
        f"EXERCISE BRIEF:\n{brief}",
    ]
    if variant.get("params"):
        parts.append(
            f"STUDENT VARIANT: {variant['id']} with parameters {json.dumps(variant['params'])}."
        )
    tests = variant.get("test_inputs") or []
    if tests:
        cmd = (exercise.get("scaffold_filename") or "mcalc.c").rsplit(".", 1)[0]
        parts.append(
            "Test inputs the student must pass:\n"
            + "\n".join(f"  - {cmd} \"{t['input']}\" -> {t['expected_output']}" for t in tests)
        )
    errors = exercise.get("required_error_strings") or []
    if errors:
        parts.append(
            "REQUIRED EXACT ERROR STRINGS (bytes, not meaning):\n"
            + "\n".join(f"  - {e!r}" for e in errors)
        )
    if exercise.get("tutor_notes"):
        parts.append(f"INSTRUCTOR NOTES (follow these; never show them to the student):\n{exercise['tutor_notes']}")
    return "\n\n".join(parts) + "\n\n" + rules


def probe_meta_prompt(context: dict) -> str:
    """Build the meta-prompt sent to the cloud LLM for question suggestions."""
    return (
        "You help an instructor write ONE targeted question to verify a student "
        "actually understands what they just had an LLM help them with.\n\n"
        "Context (already sanitized):\n"
        f"- Variant: {context['variant_id']} with params {json.dumps(context['variant_params'])}\n"
        f"- Recent student↔LLM exchange (last messages):\n{context['recent_chat']}\n"
        f"- Latest code the student shared:\n{context['latest_code']}\n"
        f"- Action log (last 15 min):\n{context['action_log']}\n\n"
        "Return JSON: a list of 3 suggestions, each with:\n"
        "  - kind: one of [Trace, Why, Counterfactual, Failure-mode, Bug-localization]\n"
        "  - body: the question to ask the student (1-3 sentences)\n"
        "  - rationale: one short line explaining what this question tests\n\n"
        "GOOD vs BAD example:\n"
        "  BAD (generic): 'Explain how recursive descent works.'\n"
        "  GOOD (targeted): 'Your variant V-A2 allows %, and you asked the LLM \"how do I "
        "  add modulo to my parser\". In your current parseTerm, which line would change "
        "  to add %, and why would adding it after * break operator precedence?'\n\n"
        "Reply with ONLY the JSON array, no markdown fence."
    )
