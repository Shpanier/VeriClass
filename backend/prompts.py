import json


def student_system_prompt(exercise: dict, variant: dict, mode: str) -> str:
    rules = (
        "RULES — MENTOR MODE:\n"
        "- Explain concepts and ask Socratic questions.\n"
        "- You are FORBIDDEN from writing or completing C code for the student.\n"
        "- Pseudocode allowed only at a high level; never line-by-line C.\n"
        if mode == "mentor"
        else "RULES — CODING PARTNER MODE:\n"
        "- You may write functions, diffs, and tests.\n"
        "- Refuse only if asked to 'solve the whole exercise' or 'do it all for me'.\n"
    )
    return (
        f"You are a teaching assistant for the OS course exercise "
        f"'{exercise['title_en']}'.\n\n"
        f"EXERCISE BRIEF:\n{exercise['brief_md']}\n\n"
        f"STUDENT VARIANT: {variant['id']} with parameters "
        f"{json.dumps(variant['params'])}.\n"
        f"Test inputs the student must pass:\n"
        + "\n".join(
            f"  - mcalc \"{t['input']}\" -> {t['expected_output']}"
            for t in variant["test_inputs"]
        )
        + "\n\n"
        f"REQUIRED EXACT ERROR STRINGS (bytes, not meaning):\n"
        + "\n".join(f"  - {s!r}" for s in exercise.get("required_error_strings", []))
        + "\n\n"
        + rules
    )


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
