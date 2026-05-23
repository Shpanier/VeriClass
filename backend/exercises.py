from pathlib import Path
from typing import Any

import yaml

_LOADED: dict[str, dict[str, Any]] = {}


def load_all(directory: Path) -> dict[str, dict[str, Any]]:
    _LOADED.clear()
    for path in sorted(directory.glob("*.yaml")):
        with path.open() as f:
            data = yaml.safe_load(f)
        _validate(data, path)
        _LOADED[data["exercise_id"]] = data
    return _LOADED


def get(exercise_id: str) -> dict[str, Any]:
    return _LOADED[exercise_id]


def active() -> dict[str, Any]:
    """The MVP has a single active exercise: the first one alphabetically."""
    if not _LOADED:
        raise RuntimeError("No exercises loaded")
    return next(iter(_LOADED.values()))


def variants(exercise_id: str) -> list[dict[str, Any]]:
    return _LOADED[exercise_id]["variants"]


def variant(exercise_id: str, variant_id: str) -> dict[str, Any]:
    for v in variants(exercise_id):
        if v["id"] == variant_id:
            return v
    raise KeyError(f"variant {variant_id} not found in {exercise_id}")


def _validate(data: dict[str, Any], path: Path) -> None:
    required = ["exercise_id", "title_en", "default_mode", "brief_md", "variants"]
    for k in required:
        if k not in data:
            raise ValueError(f"{path}: missing required key '{k}'")
    if data["default_mode"] not in ("mentor", "coding_partner"):
        raise ValueError(f"{path}: default_mode must be mentor|coding_partner")
    if not data["variants"]:
        raise ValueError(f"{path}: must define at least one variant")
