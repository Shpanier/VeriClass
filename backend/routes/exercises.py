import base64
import binascii
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend import db, deps, exercises, packages, steps, terminal
from backend import params as param_utils

router = APIRouter()


def _students_exercise(user: dict, session_id: Optional[str]) -> dict[str, Any]:
    """The exercise a student is working on: their session's (session_id, from
    plugin 0.4.0), else their latest session's (older clients start a session
    and then ask here), else the global active one."""
    if session_id:
        session = deps.require_owns_session(session_id, user)
        return exercises.get(session["exercise"])
    with db.conn() as c:
        row = c.execute(
            "SELECT exercise FROM sessions WHERE user_id = ? ORDER BY last_active_at DESC, started_at DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
    if row:
        try:
            return exercises.get(row["exercise"])
        except KeyError:
            pass
    ex = exercises.active()
    if ex is None:
        raise HTTPException(404, "No exercise is open right now. Ask your teacher.")
    return ex


@router.get("/exercises/active")
def active_exercise(
    variant: Optional[str] = None,
    session_id: Optional[str] = None,
    user: dict = Depends(deps.current_user),
):
    """Teachers: the global active exercise. Students: the exercise of their own
    session (see _students_exercise)."""
    if deps.is_teacher(user):
        ex = exercises.active()
        if ex is None:
            raise HTTPException(404, "No active exercise")
    else:
        ex = _students_exercise(user, session_id)
    response = {
        "exercise_id": ex["exercise_id"],
        "title_en": ex["title_en"],
        "title_he": ex.get("title_he"),
        "default_mode": ex["default_mode"],
        "brief_md": ex["brief_md"],
        "welcome_suggestions": ex.get("welcome_suggestions", []),
        "required_error_strings": ex.get("required_error_strings", []),
        "param_labels": ex.get("param_labels", []),
        # What the plugin's VeriExam terminal lets this exercise run.
        "terminal": terminal.policy_for(ex),
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
    # Step-by-step labs: append only the step this student is on (step 1 for a
    # new pair; later steps after a re-login). Teacher-only `expected` never leaves.
    if steps.steps_of(ex):
        n = (steps.current_step(session_id) if session_id
             else steps.current_step_for_user(user["id"], ex["exercise_id"]))
        if n <= len(steps.steps_of(ex)):
            response["brief_md"] += "\n\n" + steps.step_markdown(ex, n)
        # The plugin (0.4.3+) offers to send answers as a submission of this step.
        response["steps_total"] = len(steps.steps_of(ex))
        response["step_current"] = n
    # Run by the plugin on a step submission, its output attached for the teacher.
    if ex.get("check_command"):
        response["check_command"] = ex["check_command"]
    return response


# --- teacher-only authoring --------------------------------------------------


def _summary(ex: dict[str, Any], active_id: Optional[str]) -> dict[str, Any]:
    return {
        "exercise_id": ex["exercise_id"],
        "title_en": ex["title_en"],
        "title_he": ex.get("title_he"),
        "default_mode": ex["default_mode"],
        "variant_count": len(ex.get("variants", [])),
        "source": ex.get("source", "yaml"),
        "edited": ex.get("edited", False),
        "is_active": ex["exercise_id"] == active_id,
        # Terminal commands that break on Windows or macOS (see os_warnings).
        "os_errors": sum(w["level"] == "error" for w in ex.get("os_warnings", [])),
        "steps": len(ex.get("steps") or []),
        "bank_questions": len(ex.get("faq") or []),
        # A package's folder in the private data folder (teacher only).
        "folder": ex.get("package_dir"),
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
        "scaffold_filename": ex.get("scaffold_filename"),
        "terminal": ex.get("terminal"),
        "source": ex.get("source", "yaml"),
        "edited": ex.get("edited", False),
        # Terminal commands that behave differently on Windows and macOS.
        "os_warnings": ex.get("os_warnings", []),
        "tutor_notes": ex.get("tutor_notes"),
        "language": ex.get("language"),
        "course_name": ex.get("course_name"),
        "check_command": ex.get("check_command"),
        # Steps with their teacher-only fields (this view is for the teacher).
        "steps": [
            {k: st.get(k) for k in ("title", "text", "minutes", "expected", "questions")}
            for st in ex.get("steps") or []
        ],
        "implicit_variant": bool(ex.get("implicit_variant")),
        "bank_questions": len(ex.get("faq") or []),
        "download_name": ex.get("download_name"),
        "folder": ex.get("package_dir"),
    }


@router.get("/exercises")
def list_exercises(teacher: dict = Depends(deps.require_teacher)):
    active_id = exercises.active_id()
    return [_summary(ex, active_id) for ex in exercises.all()]


# --- packages: the private data folder (backend/packages.py) ----------------------


@router.get("/exercises-status")
def exercises_status(teacher: dict = Depends(deps.require_teacher)):
    """Where packages live, and the ones that failed to load."""
    return {"data_dir": str(packages.DATA_DIR), "exercises_dir": str(packages.exercises_dir()),
            "load_errors": exercises.load_errors()}


class ZipRequest(BaseModel):
    zip_base64: str
    # Replace an installed exercise with the same id (the old one is kept in .previous/).
    replace: bool = True


class FolderRequest(BaseModel):
    # A package folder on this computer (the server runs on the lecturer's machine).
    path: str
    replace: bool = True


def _zip_bytes(b64: str) -> bytes:
    try:
        return base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "The upload couldn't be read (expected a base64 zip).")


def _installed(result: dict[str, Any]) -> dict[str, Any]:
    if result["ok"]:
        try:
            ex = exercises.reload_package(result["summary"]["exercise_id"])
        except ValueError as e:
            result.update(ok=False, errors=[str(e)])
            return result
        result["exercise"] = _summary(ex, exercises.active_id())
    return result


@router.post("/exercises/import")
def import_package(req: ZipRequest, teacher: dict = Depends(deps.require_teacher)):
    """The dashboard's "Upload exercise": a zipped package folder."""
    return _installed(packages.install_zip(_zip_bytes(req.zip_base64), req.replace))


@router.post("/exercises/install")
def install_package(req: FolderRequest, teacher: dict = Depends(deps.require_teacher)):
    """Install a package folder from this computer (the MCP tool push_exercise)."""
    folder = Path(req.path).expanduser()
    if not (folder / packages.EXERCISE_FILE).is_file():
        raise HTTPException(404, f"No {packages.EXERCISE_FILE} in {folder}")
    return _installed(packages.install_folder(folder, req.replace))


@router.post("/exercises/validate")
def validate_package(req: FolderRequest, teacher: dict = Depends(deps.require_teacher)):
    """Check a package folder without installing it."""
    folder = Path(req.path).expanduser()
    if not (folder / packages.EXERCISE_FILE).is_file():
        raise HTTPException(404, f"No {packages.EXERCISE_FILE} in {folder}")
    return packages.validate_package(folder)


@router.post("/exercises/reload")
def reload_exercises(teacher: dict = Depends(deps.require_teacher)):
    """Read every exercise from disk again (after editing a package by hand)."""
    exercises.reload_all()
    active_id = exercises.active_id()
    return {"exercises": [_summary(ex, active_id) for ex in exercises.all()],
            "load_errors": exercises.load_errors()}


@router.get("/exercises/{exercise_id}/export")
def export_package(exercise_id: str, teacher: dict = Depends(deps.require_teacher)):
    """Any exercise as a package zip (exercise.yaml + teacher.yaml + files/)."""
    try:
        ex = exercises.get(exercise_id)
    except KeyError:
        raise HTTPException(404, f"Unknown exercise '{exercise_id}'")
    return Response(packages.export_zip(ex), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{exercise_id}.zip"'})


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


class StepPayload(BaseModel):
    title: str
    text: str
    minutes: Optional[float] = None
    # Teacher-only (teacher.yaml in a package).
    expected: Optional[str] = None
    questions: Optional[int] = None


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
    scaffold_filename: Optional[str] = None
    # Optional VeriExam-terminal rules (see backend/terminal.py).
    terminal: Optional[dict[str, Any]] = None
    # None: keep what the exercise has (older dashboards don't send these).
    tutor_notes: Optional[str] = None
    steps: Optional[list[StepPayload]] = None
    language: Optional[str] = None
    course_name: Optional[str] = None
    check_command: Optional[str] = None


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
    # None switches the active exercise off (students outside a course get none).
    exercise_id: Optional[str] = None


@router.post("/exercises/active")
def set_active_exercise(req: SetActiveRequest, teacher: dict = Depends(deps.require_teacher)):
    try:
        exercises.set_active(req.exercise_id)
    except KeyError:
        raise HTTPException(404, f"Unknown exercise '{req.exercise_id}'")
    return {"exercise_id": req.exercise_id}


@router.delete("/exercises/active")
def disable_active_exercise(teacher: dict = Depends(deps.require_teacher)):
    """Switch the active exercise off. Course exercises are not affected."""
    exercises.set_active(None)
    return {"exercise_id": None}
