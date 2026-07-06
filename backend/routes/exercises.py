from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend import deps, exercises

router = APIRouter()


@router.get("/exercises/active")
def active_exercise(variant: Optional[str] = None, user: dict = Depends(deps.current_user)):
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
    if deps.is_teacher(user):
        # The dashboard needs the whole variant set (or one, if asked).
        if variant:
            response["variant"] = exercises.variant(ex["exercise_id"], variant)
        else:
            response["variants"] = ex["variants"]
        return response

    # Students only ever see their own assigned variant — never the full set,
    # which would hand them every variant's test inputs / expected outputs.
    if not variant:
        raise HTTPException(400, "variant is required")
    if not deps.user_has_variant(user["id"], ex["exercise_id"], variant):
        raise HTTPException(403, "Not your variant")
    response["variant"] = exercises.variant(ex["exercise_id"], variant)
    return response
