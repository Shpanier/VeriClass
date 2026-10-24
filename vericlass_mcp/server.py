"""VeriClass MCP server: the lecturer's Claude Code session talks to their own
VeriClass server through these tools. Each lecturer runs their own server; the
model doing the work is the lecturer's Claude Code session, so nothing here
spends the VeriClass server's API tokens.

Exercises are written as package folders (backend/packages.py) in the private
data folder's drafts/, checked with validate_exercise, and installed with
push_exercise. Students come from a CSV (import_students). Class sessions come
back as anonymized numbers (session_report).

Register it with Claude Code once (scripts/install_mcp.sh does this):

    claude mcp add vericlass --scope local -- <repo>/.venv/bin/python <repo>/vericlass_mcp/server.py

It reaches the server at VERICLASS_URL (default http://127.0.0.1:8010) with the
local key the server keeps in the private data folder (.local-token).
"""
import io
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import httpx  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from backend import packages  # noqa: E402

URL = os.environ.get("VERICLASS_URL", "http://127.0.0.1:8010").rstrip("/")
TIMEOUT = float(os.environ.get("VERICLASS_MCP_TIMEOUT", "120"))

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

mcp = FastMCP(
    "vericlass",
    instructions=(
        "Tools for the lecturer's own VeriClass server: exercises (package folders: exercise.yaml, "
        "teacher.yaml, faq.yaml, files/), courses and meetings, students from CSV, and anonymized "
        "class reports. Write new exercises in drafts/ (new_exercise_folder), check them with "
        "validate_exercise until there are no errors, show the lecturer, and only then push_exercise. "
        "Never put student names or login codes in replies."
    ),
)


# --- talking to the VeriClass server -------------------------------------------------

def _key() -> str:
    try:
        return (packages.DATA_DIR / ".local-token").read_text(encoding="utf-8").strip()
    except OSError:
        raise RuntimeError(
            f"No local key in {packages.DATA_DIR}. Start the VeriClass server once on this computer; "
            "it creates the key.")


def _call(method: str, path: str, **kwargs) -> Any:
    try:
        r = httpx.request(method, URL + path, headers={"X-VeriClass-Local-Token": _key()},
                          timeout=TIMEOUT, **kwargs)
    except httpx.ConnectError:
        raise RuntimeError(
            f"The VeriClass server isn't running at {URL}. Start it (scripts/dev_up.sh, or "
            ".venv/bin/uvicorn backend.main:app --port 8010) and try again.")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except Exception:
            detail = r.text[:300]
        raise RuntimeError(f"VeriClass server: HTTP {r.status_code}: {detail}")
    ctype = r.headers.get("content-type", "")
    return r.json() if "json" in ctype else r.content


def _drafts() -> Path:
    d = packages.DATA_DIR / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- overview ------------------------------------------------------------------------

@mcp.tool(annotations=READ)
def status() -> dict:
    """Is the VeriClass server running; where the private data folder and drafts are;
    the installed exercises, the courses, and any exercise that failed to load."""
    out: dict[str, Any] = {"server": URL, "data_folder": str(packages.DATA_DIR),
                           "drafts_folder": str(_drafts()), "exercises_folder": str(packages.exercises_dir())}
    try:
        st = _call("GET", "/api/exercises-status")
        out["running"] = True
        out["load_errors"] = st["load_errors"]
        out["exercises"] = [
            {k: e.get(k) for k in ("exercise_id", "title_en", "source", "steps", "bank_questions", "is_active")}
            for e in _call("GET", "/api/exercises")]
        out["courses"] = [{"course_id": c["course_id"], "name": c["name"], "students": len(c["members"]),
                           "exercises": c["exercises"], "default_exercise": c["default_exercise"]}
                          for c in _call("GET", "/api/courses")]
        out["review_mode"] = _call("GET", "/api/review_mode")["enabled"]
    except RuntimeError as e:
        out["running"] = False
        out["problem"] = str(e)
    return out


@mcp.tool(annotations=READ)
def list_exercises() -> list:
    """Every installed exercise: id, titles, source (package / yaml / console), steps,
    question-bank size, folder."""
    return _call("GET", "/api/exercises")


@mcp.tool(annotations=READ)
def get_exercise(exercise_id: str) -> dict:
    """One exercise in full, including the teacher-only expected answers of its steps."""
    return _call("GET", f"/api/exercises/{exercise_id}")


# --- writing and installing exercises ------------------------------------------------

_TEMPLATE_EXERCISE = """\
# {title}
# Written with the exercise skill. Students and the tutor see this file;
# answers go in teacher.yaml. Keys: see VeriClassPrivateData/README.md and
# backend/packages.py. `variants` is optional (leave it out: everyone gets the
# same exercise).
exercise_id: {eid}
course_name: ""
language: {language}
title_he: "{title_he}"
title_en: "{title}"
default_mode: mentor
# download: {eid}.zip        # files/ as one zip at /api/files/<name>
# check_command: python checks.py   # run on each step submission, output to the teacher
brief_md: |
  **Welcome.** ...
welcome_suggestions:
  - "סיימתי שלב 1. התשובות שלי:"
  - "נתקעתי. אפשר רמז?"
  - "איך מריצים קובץ פייתון ב־PyCharm?"
tutor_notes: |
  What the tutor must never reveal, and the known traps of this exercise.
# terminal:
#   allow_extra: [python3]
#   blocked_hint: "Run Python files with PyCharm's green Run button."
steps:
  - title: "..."
    minutes: 10
    text: |
      ...
      ענו:
      - ...
"""

_TEMPLATE_TEACHER = """\
# Teacher-only: the expected answer and checks of each step, in step order.
# Never sent to students or to the tutor model.
notes: |
  ...
steps:
  - expected: |
      ...
    # questions: 3            # how many questions the step asks (else counted from its text)
    # evidence:               # terminal labs: what to look for in the student's log
    #   - label: "the log has 2000 lines"
    #     command: "wc -l"
    #     expect: "^\\\\s*2000\\\\b"
"""

_TEMPLATE_FAQ = """\
# Question bank: likely student questions per step, with ready answers in four
# levels (nudge / normal / more / direct), English and Hebrew. The exercise
# skill aims for 50, found by simulating students working through the steps.
questions: []
#  - id: q01
#    step: 1
#    question: "..."
#    paraphrases: ["..."]
#    answers:
#      nudge:  {en: "...", he: "..."}
#      normal: {en: "...", he: "..."}
#      more:   {en: "...", he: "..."}
#      direct: {en: "...", he: "..."}
"""


@mcp.tool(annotations=WRITE)
def new_exercise_folder(exercise_id: str, title_en: str = "", title_he: str = "", language: str = "python") -> dict:
    """Start a new exercise in the private drafts folder from the package template
    (exercise.yaml, teacher.yaml, faq.yaml, files/, solution/, source.md)."""
    import re
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", exercise_id):
        raise RuntimeError("exercise_id: lowercase letters, digits and hyphens, e.g. dl3-lab-cnn")
    folder = _drafts() / exercise_id
    if folder.exists():
        raise RuntimeError(f"{folder} already exists")
    (folder / "files").mkdir(parents=True)
    (folder / "solution").mkdir()
    title = title_en or exercise_id
    (folder / packages.EXERCISE_FILE).write_text(
        _TEMPLATE_EXERCISE.format(eid=exercise_id, title=title, title_he=title_he, language=language), "utf-8")
    (folder / packages.TEACHER_FILE).write_text(_TEMPLATE_TEACHER, "utf-8")
    (folder / packages.FAQ_FILE).write_text(_TEMPLATE_FAQ, "utf-8")
    (folder / "source.md").write_text(f"# Source\n\nWhere {exercise_id} came from (slides, a Word file).\n", "utf-8")
    return {"folder": str(folder), "files": sorted(p.name for p in folder.iterdir())}


@mcp.tool(annotations=READ)
def validate_exercise(folder: str) -> dict:
    """Check a package folder without installing it: errors (it won't load),
    warnings (likely mistakes: missing answers, Windows/macOS differences, code
    names outside backticks in Hebrew, Hebrew in CSV output, a small question
    bank) and a summary. Works without the server."""
    path = Path(folder).expanduser()
    if not (path / packages.EXERCISE_FILE).is_file():
        raise RuntimeError(f"No {packages.EXERCISE_FILE} in {path}")
    return packages.validate_package(path)


@mcp.tool(annotations=WRITE)
def push_exercise(folder: str, course_id: Optional[str] = None, make_default: bool = False,
                  meeting_date: Optional[str] = None, meeting_title: Optional[str] = None) -> dict:
    """Install (or update) a package folder on the server, with no restart, after
    checking it. Optionally offer it in a course (make_default: preselect it) or
    hold it as that course's meeting on meeting_date (YYYY-MM-DD). The previous
    version is kept in exercises/.previous/."""
    path = Path(folder).expanduser().resolve()
    result = _call("POST", "/api/exercises/install", json={"path": str(path), "replace": True})
    if result.get("ok") and course_id:
        result["course"] = assign_exercise(course_id, result["summary"]["exercise_id"], make_default,
                                           meeting_date, meeting_title)
    return result


@mcp.tool(annotations=WRITE)
def export_exercise(exercise_id: str) -> dict:
    """Copy an installed exercise into drafts/ (a new folder) to edit it there,
    then push_exercise it again."""
    data = _call("GET", f"/api/exercises/{exercise_id}/export")
    target = packages.stamped(_drafts(), f"{exercise_id}-edit")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(target)
    inner = target / exercise_id
    if inner.is_dir():  # the zip holds <exercise_id>/...
        for p in inner.iterdir():
            shutil.move(str(p), target / p.name)
        inner.rmdir()
    return {"folder": str(target), "files": sorted(p.name for p in target.iterdir())}


@mcp.tool(annotations=WRITE)
def reload_exercises() -> dict:
    """Read every exercise from disk again (after editing an installed package by hand)."""
    r = _call("POST", "/api/exercises/reload")
    return {"exercises": [e["exercise_id"] for e in r["exercises"]], "load_errors": r["load_errors"]}


# --- courses, meetings, students ------------------------------------------------------

@mcp.tool(annotations=READ)
def list_courses() -> list:
    """Courses with their exercises, default exercise, number of students and meetings."""
    out = []
    for c in _call("GET", "/api/courses"):
        meetings = _call("GET", f"/api/courses/{c['course_id']}/meetings")
        out.append({"course_id": c["course_id"], "name": c["name"], "students": len(c["members"]),
                    "exercises": c["exercises"], "default_exercise": c["default_exercise"],
                    "meetings": [{k: m[k] for k in ("id", "meeting_date", "exercise_id", "title", "attended",
                                                     "members")} for m in meetings]})
    return out


@mcp.tool(annotations=WRITE)
def create_course(course_id: str, name: str) -> dict:
    """A new course (id: lowercase letters, digits, hyphens, e.g. dl-2026)."""
    return _call("POST", "/api/courses", json={"course_id": course_id, "name": name})


@mcp.tool(annotations=WRITE)
def assign_exercise(course_id: str, exercise_id: str, make_default: bool = False,
                    meeting_date: Optional[str] = None, meeting_title: Optional[str] = None) -> dict:
    """Offer an exercise in a course; make_default preselects it; meeting_date
    (YYYY-MM-DD) makes it that day's meeting, which students open without choosing."""
    if meeting_date:
        m = _call("POST", f"/api/courses/{course_id}/meetings",
                  json={"date": meeting_date, "exercise_id": exercise_id, "title": meeting_title})
        if not make_default:
            return {"meeting": m}
    course = next((c for c in _call("GET", "/api/courses") if c["course_id"] == course_id), None)
    if course is None:
        raise RuntimeError(f"No course '{course_id}' (create_course first)")
    ex_ids = list(dict.fromkeys(course["exercises"] + [exercise_id]))
    default = exercise_id if make_default or not course["default_exercise"] else course["default_exercise"]
    updated = _call("PUT", f"/api/courses/{course_id}", json={
        "name": course["name"], "exercises": ex_ids, "default_exercise": default, "members": course["members"]})
    return {"course_id": course_id, "exercises": updated["exercises"], "default_exercise": updated["default_exercise"]}


@mcp.tool(annotations=WRITE)
def import_students(csv_path: str, course_id: Optional[str] = None, dry_run: bool = True) -> dict:
    """Students from a CSV file (name or first+last name; optional email, student
    id, course, group; Moodle exports and Hebrew Excel files work). Start with
    dry_run=True to see what would happen. The new login codes are written to a
    file in the private codes/ folder; this tool never returns names or codes."""
    import base64
    data = Path(csv_path).expanduser().read_bytes()
    r = _call("POST", "/api/students/import", json={
        "content_base64": base64.b64encode(data).decode(), "course_id": course_id, "dry_run": dry_run})
    out: dict[str, Any] = {
        "dry_run": dry_run, "counts": r["counts"], "columns_recognized": r["columns"],
        "problems": [{"line": row["line"], "problem": row["error"]} for row in r["rows"] if row.get("error")],
    }
    if not dry_run and r.get("codes_csv"):
        codes = packages.DATA_DIR / "codes"
        codes.mkdir(parents=True, exist_ok=True)
        path = packages.stamped(codes, f"login-codes-{course_id or 'students'}", ".csv")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
            f.write(r["codes_csv"])
        out["codes_file"] = str(path)
    return out


# --- reports ---------------------------------------------------------------------------

@mcp.tool(annotations=WRITE)  # (save writes a file in the private reports/ folder)
def session_report(exercise_id: Optional[str] = None, course_id: Optional[str] = None,
                   date: Optional[str] = None, include_questions: bool = False, save: bool = True) -> dict:
    """One class session in numbers (default: the latest day with sessions):
    students numbered S01, S02, …, no names; operating systems, the review
    queue's waits and answer levels, step decisions, terminal lines and blocks,
    per student. include_questions adds the students' questions as written.
    save writes it to the private reports/ folder too."""
    params = {k: v for k, v in {"exercise_id": exercise_id, "course_id": course_id, "date": date,
                                "include_questions": str(include_questions).lower()}.items() if v}
    rep = _call("GET", "/api/reports/session", params=params)
    if save and rep.get("found"):
        reports = packages.DATA_DIR / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        name = f"{exercise_id or course_id or 'session'}-{rep['date']}.json"
        (reports / name).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        rep["saved_to"] = str(reports / name)
    return rep


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
