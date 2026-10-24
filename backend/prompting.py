"""The tutor's full system prompt for one session: the exercise and variant
(backend/prompts.py), the step the student is on (backend/steps.py) and the
student's environment. Shared by /api/ask and the teacher's "regenerate"
buttons, so a regenerated answer sees exactly what the first one saw."""
from typing import Any

from backend import environment, exercises, steps
from backend.prompts import student_system_prompt


def system_prompt_for(session: dict[str, Any], plain: bool = False) -> str:
    """[session]: a sessions row with id, exercise, variant, mode. [plain]: the
    student's client shows plain text only (older IDE plugins)."""
    ex = exercises.get(session["exercise"])
    variant = exercises.variant(session["exercise"], session["variant"])
    prompt = student_system_prompt(ex, variant, session["mode"])
    env = environment.tutor_block(session["id"], ex)
    if env:
        prompt += "\n\n" + env
    if steps.steps_of(ex):
        prompt += "\n\n" + steps.tutor_context(ex, session["id"], plain)
    return prompt
