from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import deps, exercises
from backend import params as param_utils

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
        "param_labels": ex.get("param_labels", []),
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
    v = exercises.variant(ex["exercise_id"], variant)
    response["variant"] = v
    # Expand @-references in the brief to this student's actual variant values.
    response["brief_md"] = param_utils.substitute_brief(
        response["brief_md"], v.get("params", {}), ex.get("param_labels", [])
    )
    return response


# --- teacher-only authoring --------------------------------------------------


def _summary(ex: dict[str, Any], active_id: str) -> dict[str, Any]:
    return {
        "exercise_id": ex["exercise_id"],
        "title_en": ex["title_en"],
        "title_he": ex.get("title_he"),
        "default_mode": ex["default_mode"],
        "variant_count": len(ex.get("variants", [])),
        "source": ex.get("source", "yaml"),
        "edited": ex.get("edited", False),
        "is_active": ex["exercise_id"] == active_id,
    }


def _full(ex: dict[str, Any]) -> dict[str, Any]:
    """The complete exercise, for prefilling the edit / duplicate form."""
    return {
        "exercise_id": ex["exercise_id"],
        "title_en": ex["title_en"],
        "title_he": ex.get("title_he"),
        "default_mode": ex["default_mode"],
        "brief_md": ex["brief_md"],
        "variants": ex.get("variants", []),
        "welcome_suggestions": ex.get("welcome_suggestions", []),
        "required_error_strings": ex.get("required_error_strings", []),
        "param_labels": ex.get("param_labels", []),
        "source": ex.get("source", "yaml"),
        "edited": ex.get("edited", False),
    }


@router.get("/exercises")
def list_exercises(teacher: dict = Depends(deps.require_teacher)):
    active_id = exercises.active_id()
    return [_summary(ex, active_id) for ex in exercises.all()]


@router.get("/exercises/{exercise_id}")
def get_exercise(exercise_id: str, teacher: dict = Depends(deps.require_teacher)):
    try:
        return _full(exercises.get(exercise_id))
    except KeyError:
        raise HTTPException(404, f"Unknown exercise '{exercise_id}'")


class TestInput(BaseModel):
    input: str
    expected_output: str


class VariantPayload(BaseModel):
    id: str
    params: dict[str, Any] = Field(default_factory=dict)
    test_inputs: list[TestInput] = Field(default_factory=list)


class ParamLabel(BaseModel):
    key: str
    label: Optional[str] = None
    note: Optional[str] = None


class ExercisePayload(BaseModel):
    exercise_id: str
    title_en: str
    title_he: Optional[str] = None
    default_mode: str
    brief_md: str
    variants: list[VariantPayload]
    welcome_suggestions: list[str] = Field(default_factory=list)
    required_error_strings: list[str] = Field(default_factory=list)
    param_labels: list[ParamLabel] = Field(default_factory=list)


@router.post("/exercises")
def create_exercise(payload: ExercisePayload, teacher: dict = Depends(deps.require_teacher)):
    try:
        stored = exercises.create(payload.model_dump())
    except exercises.DuplicateExercise as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _summary(stored, exercises.active_id())


@router.put("/exercises/{exercise_id}")
def update_exercise(
    exercise_id: str,
    payload: ExercisePayload,
    teacher: dict = Depends(deps.require_teacher),
):
    # The id in the path is authoritative; edits never rename (duplicate does).
    try:
        stored = exercises.update(exercise_id, payload.model_dump())
    except KeyError:
        raise HTTPException(404, f"Unknown exercise '{exercise_id}'")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _summary(stored, exercises.active_id())


class SetActiveRequest(BaseModel):
    exercise_id: str


@router.post("/exercises/active")
def set_active_exercise(req: SetActiveRequest, teacher: dict = Depends(deps.require_teacher)):
    try:
        exercises.set_active(req.exercise_id)
    except KeyError:
        raise HTTPException(404, f"Unknown exercise '{req.exercise_id}'")
    return {"exercise_id": req.exercise_id}
