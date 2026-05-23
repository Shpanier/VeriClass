from typing import Optional

from fastapi import APIRouter

from backend import exercises

router = APIRouter()


@router.get("/exercises/active")
def active_exercise(variant: Optional[str] = None):
    ex = exercises.active()
    response = {
        "exercise_id": ex["exercise_id"],
        "title_en": ex["title_en"],
        "title_he": ex.get("title_he"),
        "default_mode": ex["default_mode"],
        "brief_md": ex["brief_md"],
        "welcome_suggestions": ex.get("welcome_suggestions", []),
        "required_error_strings": ex.get("required_error_strings", []),
    }
    if variant:
        response["variant"] = exercises.variant(ex["exercise_id"], variant)
    else:
        response["variants"] = ex["variants"]
    return response
