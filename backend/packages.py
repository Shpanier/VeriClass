"""Exercise packages: one folder per exercise, in the lecturer's private data
folder (VERIEXAM_DATA_DIR, default ../VeriExPrivateData next to the code). The
folder is the source of truth: the server loads it, the dashboard writes its
edits back into it, and nothing in it goes to git.

    VeriExPrivateData/exercises/<exercise_id>/
      exercise.yaml   what students and the tutor see (same keys as config/exercises/*.yaml;
                      `variants` is optional)
      teacher.yaml    teacher-only, per step: expected, os_check, evidence, questions; and notes
      faq.yaml        the question bank (backend/bank.py), optional
      files/          what students download: served as one zip (`download:` in exercise.yaml,
                      default <exercise_id>.zip) and file by file, at /api/files/<name>
      solution/       the lecturer's solution; never served
      source.md       where it came from (slides, a Word file); never served

Packages are written in the lecturer's own Claude Code session (the exercise
skill) and installed with the MCP tool push_exercise, or uploaded as a zip in
the dashboard; either way they pass validate_package() first.
"""
import io
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Optional

import yaml

from backend import bank, portability, terminal, textutil

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VERIEXAM_DATA_DIR") or (_REPO.parent / "VeriExPrivateData")).expanduser()

EXERCISE_FILE = "exercise.yaml"
TEACHER_FILE = "teacher.yaml"
FAQ_FILE = "faq.yaml"
FILES_DIR = "files"
# Teacher-only step keys: kept in teacher.yaml, never sent to students or the tutor.
TEACHER_STEP_KEYS = ("expected", "os_check", "evidence", "questions")
# The question bank the exercise skill aims for.
BANK_TARGET = 50
_ZIP_MAX = 50_000_000
_IMPLICIT_VARIANT = {"id": "default", "params": {}, "test_inputs": []}


def exercises_dir() -> Path:
    return DATA_DIR / "exercises"


def package_dirs() -> list[Path]:
    root = exercises_dir()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / EXERCISE_FILE).is_file()
                  and not p.name.startswith("."))


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_package(path: Path) -> dict[str, Any]:
    """The exercise dict of one package folder: exercise.yaml with teacher.yaml's
    step fields merged in and faq.yaml as ex["faq"]. Raises ValueError with a
    readable message on a problem."""
    path = Path(path)
    try:
        data = _read_yaml(path / EXERCISE_FILE)
    except FileNotFoundError:
        raise ValueError(f"{path.name}: no {EXERCISE_FILE}")
    except yaml.YAMLError as e:
        raise ValueError(f"{path.name}/{EXERCISE_FILE}: not valid YAML ({e})")
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}/{EXERCISE_FILE}: must be a mapping of keys")

    teacher = {}
    if (path / TEACHER_FILE).is_file():
        try:
            teacher = _read_yaml(path / TEACHER_FILE) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"{path.name}/{TEACHER_FILE}: not valid YAML ({e})")
        if not isinstance(teacher, dict):
            raise ValueError(f"{path.name}/{TEACHER_FILE}: must be a mapping of keys")
    steps = data.get("steps") or []
    for n, extra in _teacher_steps(teacher, len(steps), path.name).items():
        steps[n - 1] = {**steps[n - 1], **extra}
    if teacher.get("notes"):
        data["teacher_notes"] = teacher["notes"]

    if (path / FAQ_FILE).is_file():
        try:
            data["faq"] = bank.normalize_entries(_read_yaml(path / FAQ_FILE), f"{path.name}/{FAQ_FILE}")
        except yaml.YAMLError as e:
            raise ValueError(f"{path.name}/{FAQ_FILE}: not valid YAML ({e})")

    if not data.get("variants"):
        data["variants"] = [dict(_IMPLICIT_VARIANT)]
        data["implicit_variant"] = True
    files = path / FILES_DIR
    if files.is_dir() and any(files.iterdir()):
        data["files_dir"] = str(files)
        data["download_name"] = data.get("download") or f"{data.get('exercise_id', path.name)}.zip"
    data["source"] = "package"
    data["edited"] = False
    data["package_dir"] = str(path)
    data.setdefault("param_labels", [])
    data.setdefault("scaffold_filename", None)
    return data


def _teacher_steps(teacher: dict, count: int, where: str) -> dict[int, dict]:
    """teacher.yaml's `steps`, as {step number: teacher-only fields}: a list in
    step order, or a mapping keyed by step number."""
    raw = teacher.get("steps") or []
    if isinstance(raw, list):
        items = {i: s for i, s in enumerate(raw, 1)}
    elif isinstance(raw, dict):
        items = {int(k): v for k, v in raw.items()}
    else:
        raise ValueError(f"{where}/{TEACHER_FILE}: steps must be a list or a mapping")
    out = {}
    for n, fields in items.items():
        if not 1 <= n <= count:
            raise ValueError(f"{where}/{TEACHER_FILE}: step {n} doesn't exist (the exercise has {count})")
        if fields is None:
            continue
        if not isinstance(fields, dict):
            raise ValueError(f"{where}/{TEACHER_FILE}: step {n} must be a mapping")
        unknown = set(fields) - set(TEACHER_STEP_KEYS)
        if unknown:
            raise ValueError(f"{where}/{TEACHER_FILE}: step {n} has unknown key(s) {', '.join(sorted(unknown))} "
                             f"(use {', '.join(TEACHER_STEP_KEYS)})")
        out[n] = fields
    return out


# --- validation -----------------------------------------------------------------

_INLINE_CODE = re.compile(r"`[^`]*`")
# A Latin identifier that should be in backticks inside Hebrew prose: snake_case,
# dotted names, calls.
_BARE_IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:_[A-Za-z0-9_]+|\.[A-Za-z_][A-Za-z0-9_]*|\(\))")


def validate_package(path: Path) -> dict[str, Any]:
    """Everything worth knowing before an exercise reaches a class: errors (it
    won't load), warnings (it will, but something is likely wrong) and a summary."""
    from backend import exercises  # the one exercise validator (circular at import time)

    path = Path(path).expanduser()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        ex = load_package(path)
        exercises.validate(ex, path.name)
    except ValueError as e:
        return {"ok": False, "errors": [str(e)], "warnings": [], "summary": {"folder": str(path)}}

    if ex["exercise_id"] != path.name:
        warnings.append(f"the folder is named '{path.name}' but exercise_id is '{ex['exercise_id']}'; "
                        f"it will be installed as '{ex['exercise_id']}'")
    steps = ex.get("steps") or []
    for i, st in enumerate(steps, 1):
        if not str(st.get("expected") or "").strip():
            warnings.append(f"step {i} has no expected answer in {TEACHER_FILE}: the teacher will have "
                            "nothing to compare with")
        for rule in st.get("evidence") or []:
            try:
                re.compile(rule["command"])
                if rule.get("expect"):
                    re.compile(rule["expect"])
            except (re.error, KeyError, TypeError) as e:
                errors.append(f"step {i}: evidence rule is broken ({e})")
        if st.get("minutes") is not None and not isinstance(st.get("minutes"), (int, float)):
            errors.append(f"step {i}: minutes must be a number")
        if textutil.has_hebrew(st.get("text", "")):
            bare = _bare_identifiers(st["text"])
            if bare:
                warnings.append(f"step {i}: put code names in backticks so the chat lays out the Hebrew "
                                f"right-to-left: {', '.join(sorted(bare)[:5])}")
    for w in portability.lint_exercise(ex, set(terminal.policy_for(ex)["allow"])):
        (errors if w["level"] == "error" else warnings).append(
            f"step {w['step']}: `{w['line']}` — {w['message']}")
    if ex.get("check_command") and not str(ex["check_command"]).split()[0] in ("python", "python3", "py"):
        errors.append("check_command must run python (e.g. 'python checks.py'): the plugin runs nothing else")

    faq = ex.get("faq") or []
    files = sorted(p.name for p in (path / FILES_DIR).iterdir()) if (path / FILES_DIR).is_dir() else []
    for f in files:
        if f.endswith(".csv") and _hebrew_in_csv(path / FILES_DIR / f):
            warnings.append(f"files/{f} has Hebrew values: tables printed in PyCharm's console show "
                            "Hebrew rows out of order (seen in class); consider Latin spellings")
    if "checks.py" in files and not ex.get("check_command"):
        warnings.append("files/checks.py exists but no check_command: add `check_command: python checks.py` "
                        "to attach its output to every step submission")
    if steps and len(faq) < BANK_TARGET:
        warnings.append(f"the question bank has {len(faq)} question(s); the exercise skill aims for {BANK_TARGET}")
    minutes = sum(float(s.get("minutes") or 0) for s in steps)
    summary = {
        "folder": str(path),
        "exercise_id": ex["exercise_id"],
        "title_en": ex.get("title_en"),
        "title_he": ex.get("title_he"),
        "course_name": ex.get("course_name"),
        "steps": len(steps),
        "minutes": minutes or None,
        "teacher_answers": sum(1 for s in steps if str(s.get("expected") or "").strip()),
        "bank_questions": len(faq),
        "files": files,
        "download": ex.get("download_name"),
        "variants": 0 if ex.get("implicit_variant") else len(ex["variants"]),
        "check_command": ex.get("check_command"),
    }
    return {"ok": not errors, "errors": errors, "warnings": warnings, "summary": summary}


def _bare_identifiers(text: str) -> set[str]:
    out = set()
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or not textutil.has_hebrew(line):
            continue
        out |= set(_BARE_IDENT.findall(_INLINE_CODE.sub(" ", line)))
    return out


def _hebrew_in_csv(path: Path, sample: int = 20_000) -> bool:
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            return textutil.has_hebrew(f.read(sample))
    except OSError:
        return False


# --- installing -------------------------------------------------------------------

def install_folder(src: Path, replace: bool = True) -> dict[str, Any]:
    """Validate a package folder and copy it into exercises/<exercise_id>
    (nothing to copy when it is already there). The previous version goes to
    exercises/.previous/. Returns the validation result plus `installed_to`."""
    src = Path(src).expanduser().resolve()
    result = validate_package(src)
    if not result["ok"]:
        return result
    target = exercises_dir() / result["summary"]["exercise_id"]
    if src == target.resolve():
        result["installed_to"] = str(target)
        return result
    if target.exists() and not replace:
        result.update(ok=False, errors=[f"an exercise '{target.name}' is already installed"])
        return result
    exercises_dir().mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=exercises_dir()))
    try:
        shutil.copytree(src, staging, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store", "*.pyc"))
        if target.exists():
            keep = exercises_dir() / ".previous" / f"{target.name}-{time.strftime('%Y%m%d-%H%M%S')}"
            keep.parent.mkdir(parents=True, exist_ok=True)
            target.rename(keep)
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    result["installed_to"] = str(target)
    return result


def install_zip(data: bytes, replace: bool = True) -> dict[str, Any]:
    """A zipped package folder (exercise.yaml at the top or inside one folder)."""
    if len(data) > _ZIP_MAX:
        return {"ok": False, "errors": ["the zip is larger than 50 MB"], "warnings": [], "summary": {}}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for name in z.namelist():
                    if name.startswith("/") or ".." in Path(name).parts:
                        return {"ok": False, "errors": [f"unsafe path in the zip: {name}"],
                                "warnings": [], "summary": {}}
                z.extractall(tmp)
        except zipfile.BadZipFile:
            return {"ok": False, "errors": ["not a zip file"], "warnings": [], "summary": {}}
        root = Path(tmp)
        found = [p.parent for p in root.rglob(EXERCISE_FILE) if "__MACOSX" not in p.parts]
        if len(found) != 1:
            return {"ok": False, "errors": [f"the zip must hold exactly one {EXERCISE_FILE} (found {len(found)})"],
                    "warnings": [], "summary": {}}
        return install_folder(found[0], replace)


# --- downloads ---------------------------------------------------------------------

_ZIP_CACHE: dict[str, tuple[float, bytes]] = {}


def download_zip(ex: dict[str, Any]) -> Optional[bytes]:
    """The package's files/ as one zip (cached until a file changes)."""
    if not ex.get("files_dir"):  # (Path("") would be the server's own folder)
        return None
    files = Path(ex["files_dir"])
    if not files.is_dir():
        return None
    entries = sorted(p for p in files.rglob("*") if p.is_file() and p.name != ".DS_Store")
    stamp = max((p.stat().st_mtime for p in entries), default=0.0)
    cached = _ZIP_CACHE.get(str(files))
    if cached and cached[0] == stamp:
        return cached[1]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in entries:
            z.write(p, p.relative_to(files).as_posix())
    data = buf.getvalue()
    _ZIP_CACHE[str(files)] = (stamp, data)
    return data


def export_zip(ex: dict[str, Any]) -> bytes:
    """Any exercise as a package zip: a package's folder as it is (without
    solution/), or a bundled/dashboard exercise split into exercise.yaml and
    teacher.yaml."""
    buf = io.BytesIO()
    eid = ex["exercise_id"]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        folder = Path(ex["package_dir"]) if ex.get("package_dir") else None
        if folder is not None and folder.is_dir():
            for p in sorted(folder.rglob("*")):
                rel = p.relative_to(folder)
                if p.is_file() and rel.parts[0] != "solution" and p.name != ".DS_Store":
                    z.write(p, f"{eid}/{rel.as_posix()}")
        else:
            student, teacher = split_teacher_fields(ex)
            z.writestr(f"{eid}/{EXERCISE_FILE}", yaml.safe_dump(student, allow_unicode=True, sort_keys=False,
                                                                width=100))
            if teacher:
                z.writestr(f"{eid}/{TEACHER_FILE}", yaml.safe_dump(teacher, allow_unicode=True, sort_keys=False,
                                                                   width=100))
    return buf.getvalue()


# --- dashboard edits ---------------------------------------------------------------

# exercise.yaml keys the dashboard's edit form may change.
_EDITABLE = ("title_en", "title_he", "default_mode", "brief_md", "welcome_suggestions",
             "required_error_strings", "param_labels", "tutor_notes", "terminal", "language",
             "course_name", "check_command", "scaffold_filename")
_STEP_KEYS = ("title", "text", "minutes")


def _rt_yaml():
    from ruamel.yaml import YAML  # round-trip: keeps the lecturer's comments and layout
    rt = YAML()
    rt.preserve_quotes = True
    rt.width = 100
    rt.indent(mapping=2, sequence=4, offset=2)
    return rt


def _scalar(value: Any) -> Any:
    """Multi-line text as a YAML block (|), like the files the skill writes."""
    from ruamel.yaml.scalarstring import LiteralScalarString
    if isinstance(value, str) and "\n" in value:
        return LiteralScalarString(value if value.endswith("\n") else value + "\n")
    return value


def write_back(current: dict[str, Any], payload: dict[str, Any]) -> None:
    """Write a dashboard edit into the package's exercise.yaml and teacher.yaml.
    Only the keys the payload carries change; the previous files are kept in
    exercises/.previous/."""
    folder = Path(current["package_dir"])
    rt = _rt_yaml()
    ex_path, t_path = folder / EXERCISE_FILE, folder / TEACHER_FILE
    doc = rt.load(ex_path.read_text(encoding="utf-8"))
    teacher = rt.load(t_path.read_text(encoding="utf-8")) if t_path.is_file() else None
    if teacher is None:
        from ruamel.yaml.comments import CommentedMap
        teacher = CommentedMap()

    for key in _EDITABLE:
        if key in payload and payload[key] is not None:
            if payload[key] in ("", []) and key not in doc:
                continue
            doc[key] = _scalar(payload[key])
    variants = payload.get("variants")
    if variants is not None and not (current.get("implicit_variant") and variants == current["variants"]):
        doc["variants"] = variants

    steps = payload.get("steps")
    if steps is not None:
        old = doc.get("steps") or []
        new_steps = []
        t_old = teacher.get("steps") if isinstance(teacher.get("steps"), list) else []
        t_new = []
        for i, st in enumerate(steps):
            item = old[i] if i < len(old) else {}
            for k in _STEP_KEYS:
                if st.get(k) not in (None, ""):
                    item[k] = _scalar(st[k])
                elif k == "minutes" and k in item and st.get(k) is None:
                    del item[k]
            for k in TEACHER_STEP_KEYS:
                item.pop(k, None)  # teacher-only: never in exercise.yaml
            new_steps.append(item)
            t_item = t_old[i] if i < len(t_old) and t_old[i] else {}
            if "expected" in st:
                t_item["expected"] = _scalar(st.get("expected") or "")
            for k in ("questions", "evidence", "os_check"):
                if st.get(k) not in (None, "", []):
                    t_item[k] = st[k]
            t_new.append(t_item)
        doc["steps"] = new_steps
        teacher["steps"] = t_new

    keep = exercises_dir() / ".previous" / f"{folder.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    keep.mkdir(parents=True, exist_ok=True)
    for p in (ex_path, t_path):
        if p.is_file():
            shutil.copy2(p, keep / p.name)
    with ex_path.open("w", encoding="utf-8") as f:
        rt.dump(doc, f)
    if teacher:
        with t_path.open("w", encoding="utf-8") as f:
            rt.dump(teacher, f)


_RUNTIME_KEYS = {"source", "edited", "package_dir", "files_dir", "download_name", "implicit_variant",
                 "os_warnings", "faq", "teacher_notes"}


def split_teacher_fields(ex: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(exercise.yaml body, teacher.yaml body) of an exercise dict."""
    student = {k: v for k, v in ex.items() if k not in _RUNTIME_KEYS and v not in (None, [], "")}
    if ex.get("implicit_variant"):
        student.pop("variants", None)
    t_steps, s_steps = [], []
    for st in ex.get("steps") or []:
        s_steps.append({k: v for k, v in st.items() if k not in TEACHER_STEP_KEYS})
        t_steps.append({k: st[k] for k in TEACHER_STEP_KEYS if st.get(k) not in (None, "", [])})
    if s_steps:
        student["steps"] = s_steps
    teacher: dict[str, Any] = {}
    if ex.get("teacher_notes"):
        teacher["notes"] = ex["teacher_notes"]
    if any(t_steps):
        teacher["steps"] = t_steps
    return student, teacher
