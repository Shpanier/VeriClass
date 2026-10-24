import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from backend import db, portability, terminal

logger = logging.getLogger(__name__)

_LOADED: dict[str, dict[str, Any]] = {}
# The ids that came from a bundled YAML file. A DB row with one of these ids is
# an *edit* of a built-in (it overrides the YAML in memory) rather than a
# console-authored exercise.
_YAML_IDS: set[str] = set()

_ACTIVE_SETTING_KEY = "active_exercise_id"
# Stored in place of an id when the teacher switched the active exercise off:
# students outside every course then get no exercise.
_DISABLED = "__none__"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


_DIRECTORY: Optional[Path] = None


def load_all(directory: Path) -> dict[str, dict[str, Any]]:
    """Load the bundled YAML exercises. Clears the cache first, so this is the
    canonical 'start from disk' step. Call load_from_db() afterwards to layer
    teacher edits / console-authored exercises on top."""
    global _DIRECTORY
    _DIRECTORY = directory
    _LOADED.clear()
    _YAML_IDS.clear()
    for path in sorted(directory.glob("*.yaml")):
        with path.open() as f:
            data = yaml.safe_load(f)
        _validate(data, str(path))
        data["source"] = "yaml"
        data["edited"] = False
        data.setdefault("param_labels", [])
        data.setdefault("scaffold_filename", None)
        _check_os(data)
        _LOADED[data["exercise_id"]] = data
        _YAML_IDS.add(data["exercise_id"])
    return _LOADED


def reload_all() -> dict[str, dict[str, Any]]:
    """Start again from disk, then layer the database's edits on top (what the
    server does at startup)."""
    if _DIRECTORY is None:
        raise RuntimeError("load_all() was never called")
    load_all(_DIRECTORY)
    load_from_db()
    return _LOADED


def load_from_db() -> None:
    """Layer DB-stored exercises over the YAML. The DB wins on an id collision:
    a row whose id matches a YAML file is a teacher *edit* of that built-in and
    overrides it (marked edited=True); any other row is a console-authored
    exercise."""
    with db.conn() as c:
        rows = c.execute(
            "SELECT exercise_id, title_en, title_he, default_mode, brief_md, data "
            "FROM exercises"
        ).fetchall()
    for row in rows:
        ex = _row_to_exercise(row)
        _check_os(ex)
        _LOADED[row["exercise_id"]] = ex


def _row_to_exercise(row: Any) -> dict[str, Any]:
    extra = json.loads(row["data"])
    is_yaml = row["exercise_id"] in _YAML_IDS
    return {
        "exercise_id": row["exercise_id"],
        "title_en": row["title_en"],
        "title_he": row["title_he"],
        "default_mode": row["default_mode"],
        "brief_md": row["brief_md"],
        "variants": extra.get("variants", []),
        "welcome_suggestions": extra.get("welcome_suggestions", []),
        "required_error_strings": extra.get("required_error_strings", []),
        "param_labels": extra.get("param_labels", []),
        "scaffold_filename": extra.get("scaffold_filename"),
        "course_name": extra.get("course_name"),
        "language": extra.get("language"),
        "tutor_notes": extra.get("tutor_notes"),
        "steps": extra.get("steps"),
        "terminal": extra.get("terminal"),
        # An edit of a built-in keeps the 'yaml' source but is flagged edited so
        # the dashboard can show "built-in (edited)".
        "source": "yaml" if is_yaml else "console",
        "edited": is_yaml,
    }


def _check_os(ex: dict[str, Any]) -> None:
    """Attach the Windows/macOS differences of the exercise's terminal commands
    (backend/portability.py) as ex["os_warnings"], and log the ones that break."""
    allow = set(terminal.policy_for(ex)["allow"])
    ex["os_warnings"] = portability.lint_exercise(ex, allow)
    for w in ex["os_warnings"]:
        if w["level"] == "error":
            logger.warning("%s step %s: %s — %s", ex["exercise_id"], w["step"], w["line"], w["message"])


def get(exercise_id: str) -> dict[str, Any]:
    return _LOADED[exercise_id]


def active() -> Optional[dict[str, Any]]:
    """The exercise students outside every course get assigned to. Honors the
    teacher's choice stored in system_settings; None when the teacher switched it
    off. Falls back to the first exercise alphabetically (the original
    single-exercise MVP behavior) when unset or stale."""
    if not _LOADED:
        raise RuntimeError("No exercises loaded")
    chosen = _get_setting(_ACTIVE_SETTING_KEY)
    if chosen == _DISABLED:
        return None
    if chosen and chosen in _LOADED:
        return _LOADED[chosen]
    return first()


def first() -> dict[str, Any]:
    """The first exercise alphabetically, for callers that always need one."""
    return next(iter(_LOADED.values()))


def active_id() -> Optional[str]:
    ex = active()
    return ex["exercise_id"] if ex else None


def all() -> list[dict[str, Any]]:
    """Every loaded exercise, for the teacher dashboard list."""
    return list(_LOADED.values())


def variants(exercise_id: str) -> list[dict[str, Any]]:
    return _LOADED[exercise_id]["variants"]


def variant(exercise_id: str, variant_id: str) -> dict[str, Any]:
    for v in variants(exercise_id):
        if v["id"] == variant_id:
            return v
    raise KeyError(f"variant {variant_id} not found in {exercise_id}")


def create(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist a NEW teacher-authored exercise, then add it to
    _LOADED live (no restart). Raises ValueError on a semantic problem,
    DuplicateExercise if the id already exists (built-in or console)."""
    _validate(payload, "console")
    exercise_id = payload["exercise_id"]
    if exercise_id in _LOADED:
        raise DuplicateExercise(exercise_id)
    return _upsert(payload)


def update(exercise_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Overwrite an existing exercise — built-in OR console. Editing a built-in
    writes a DB row that shadows its YAML (flagged edited=True). The id can't be
    changed here (that's what 'duplicate' is for). Raises KeyError if unknown."""
    if exercise_id not in _LOADED:
        raise KeyError(exercise_id)
    payload = {**payload, "exercise_id": exercise_id}
    # Preserve fields the editor UI may not send. The dashboard form has no
    # scaffold_filename input, so a plain edit would otherwise wipe it (and with
    # it the exercise's language) — keep the current value when none is given.
    for key in ("scaffold_filename", "course_name", "language", "tutor_notes", "steps", "terminal"):
        if not payload.get(key):
            existing = _LOADED.get(exercise_id, {}).get(key)
            if existing:
                payload[key] = existing
    _validate(payload, "update")
    return _upsert(payload)


def _upsert(payload: dict[str, Any]) -> dict[str, Any]:
    """Write the exercise to the DB (insert or replace) and refresh _LOADED.
    Shared by create() and update(); the caller is responsible for the
    exists/not-exists policy."""
    exercise_id = payload["exercise_id"]
    is_yaml = exercise_id in _YAML_IDS
    data = {
        "variants": payload["variants"],
        "welcome_suggestions": payload.get("welcome_suggestions", []),
        "required_error_strings": payload.get("required_error_strings", []),
        "param_labels": payload.get("param_labels", []),
        "scaffold_filename": payload.get("scaffold_filename"),
        "course_name": payload.get("course_name"),
        "language": payload.get("language"),
        "tutor_notes": payload.get("tutor_notes"),
        "steps": payload.get("steps"),
        "terminal": payload.get("terminal"),
    }
    with db.conn() as c:
        c.execute(
            "INSERT INTO exercises "
            "(exercise_id, title_en, title_he, default_mode, brief_md, data, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(exercise_id) DO UPDATE SET "
            "  title_en = excluded.title_en, title_he = excluded.title_he, "
            "  default_mode = excluded.default_mode, brief_md = excluded.brief_md, "
            "  data = excluded.data",
            (
                exercise_id,
                payload["title_en"],
                payload.get("title_he"),
                payload["default_mode"],
                payload["brief_md"],
                json.dumps(data),
                "yaml" if is_yaml else "console",
            ),
        )

    stored = {
        "exercise_id": exercise_id,
        "title_en": payload["title_en"],
        "title_he": payload.get("title_he"),
        "default_mode": payload["default_mode"],
        "brief_md": payload["brief_md"],
        "variants": payload["variants"],
        "welcome_suggestions": data["welcome_suggestions"],
        "required_error_strings": data["required_error_strings"],
        "param_labels": data["param_labels"],
        "scaffold_filename": data["scaffold_filename"],
        "course_name": data["course_name"],
        "language": data["language"],
        "tutor_notes": data["tutor_notes"],
        "steps": data["steps"],
        "terminal": data["terminal"],
        "source": "yaml" if is_yaml else "console",
        "edited": is_yaml,
    }
    _check_os(stored)
    _LOADED[exercise_id] = stored
    return stored


def set_active(exercise_id: Optional[str]) -> None:
    """Make an exercise the active one; None switches the active exercise off."""
    if exercise_id is None:
        _set_setting(_ACTIVE_SETTING_KEY, _DISABLED)
        return
    if exercise_id not in _LOADED:
        raise KeyError(exercise_id)
    _set_setting(_ACTIVE_SETTING_KEY, exercise_id)


class DuplicateExercise(Exception):
    """Raised when creating an exercise whose id already exists."""

    def __init__(self, exercise_id: str):
        super().__init__(f"exercise {exercise_id!r} already exists")
        self.exercise_id = exercise_id


def _get_setting(key: str) -> str | None:
    with db.conn() as c:
        row = c.execute(
            "SELECT value FROM system_settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


def _set_setting(key: str, value: str) -> None:
    with db.conn() as c:
        c.execute(
            "INSERT INTO system_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def _validate(data: dict[str, Any], where: str) -> None:
    """Single gate for both YAML and console-authored exercises. Raises
    ValueError on any problem (the route maps this to a 400)."""
    if not isinstance(data, dict):
        raise ValueError(f"{where}: exercise must be a mapping")
    required = ["exercise_id", "title_en", "default_mode", "brief_md", "variants"]
    for k in required:
        if k not in data or data[k] in (None, ""):
            raise ValueError(f"{where}: missing required key '{k}'")
    if not _ID_RE.match(str(data["exercise_id"])):
        raise ValueError(
            f"{where}: exercise_id must match {_ID_RE.pattern} "
            "(lowercase letters, digits, hyphens)"
        )
    if data["default_mode"] not in ("mentor", "coding_partner"):
        raise ValueError(f"{where}: default_mode must be mentor|coding_partner")
    if not isinstance(data["variants"], list) or not data["variants"]:
        raise ValueError(f"{where}: must define at least one variant")

    seen: set[str] = set()
    for i, v in enumerate(data["variants"]):
        if not isinstance(v, dict) or not v.get("id"):
            raise ValueError(f"{where}: variant #{i + 1} is missing an 'id'")
        vid = v["id"]
        if vid in seen:
            raise ValueError(f"{where}: duplicate variant id '{vid}'")
        seen.add(vid)

    # param_labels is optional; if given it must be a list of {key, ...} rows.
    labels = data.get("param_labels")
    if labels is not None:
        if not isinstance(labels, list):
            raise ValueError(f"{where}: param_labels must be a list")
        for i, pl in enumerate(labels):
            if not isinstance(pl, dict) or not pl.get("key"):
                raise ValueError(f"{where}: param_labels #{i + 1} is missing a 'key'")

    # scaffold_filename is optional; if given it selects the starter file (and,
    # via its extension, the language) the IDE plugin scaffolds for this exercise.
    terminal.validate(data.get("terminal"), where)

    sf = data.get("scaffold_filename")
    if sf is not None:
        if not isinstance(sf, str) or not sf.strip() or "." not in sf:
            raise ValueError(f"{where}: scaffold_filename must be a filename with an extension")
