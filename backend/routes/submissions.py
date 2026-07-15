import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import db, deps

router = APIRouter()

# Guard rails: a submission is a source file + console dump, not an upload
# channel. Cap both so a runaway paste can't bloat the DB. Generous enough for
# any realistic C file / program output.
_MAX_SOURCE = 200_000
_MAX_CONSOLE = 200_000


class SubmissionRequest(BaseModel):
    session_id: str
    source_code: str = ""
    filename: Optional[str] = None
    console_output: Optional[str] = None
    # Real compile/run result reported by the IDE plugin. Optional so older
    # plugins (source + console only) still work.
    language: Optional[str] = None            # c | cpp | python | other
    compile_ok: Optional[bool] = None         # None when not applicable (Python)
    compile_output: Optional[str] = None
    run_report: Optional[list[dict[str, Any]]] = None  # [{input, expected, actual, passed}]


@router.post("/submissions")
def create_submission(req: SubmissionRequest, user: dict = Depends(deps.current_user)):
    """A student sends their current source file + console output to the teacher.

    Bound to the caller's own session so a student can't submit into a
    classmate's session (teachers may act on any session, as elsewhere).
    """
    deps.require_owns_session(req.session_id, user)
    source = (req.source_code or "")[:_MAX_SOURCE]
    console = ((req.console_output or "")[:_MAX_CONSOLE]) or None
    filename = (req.filename or "").strip()[:255] or None
    if not source and not console:
        raise HTTPException(422, "Nothing to submit (empty source and console).")

    language = (req.language or "").strip()[:16] or None
    compile_ok = None if req.compile_ok is None else int(req.compile_ok)
    compile_output = ((req.compile_output or "")[:_MAX_CONSOLE]) or None
    run_report = json.dumps(req.run_report) if req.run_report else None

    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO submissions (session_id, filename, source_code, console_output, "
            "language, compile_ok, compile_output, run_report) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (req.session_id, filename, source, console,
             language, compile_ok, compile_output, run_report),
        )
    return {"ok": True, "id": cur.lastrowid}


@router.get("/submissions")
def list_submissions(
    session_id: str,
    limit: int = 100,
    teacher: dict = Depends(deps.require_teacher),
):
    """Every submission for one student session, newest first."""
    limit = max(1, min(limit, 500))
    with db.conn() as c:
        rows = c.execute(
            "SELECT id, session_id, filename, source_code, console_output, "
            "language, compile_ok, compile_output, run_report, created_at "
            "FROM submissions WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("run_report"):
            try:
                d["run_report"] = json.loads(d["run_report"])
            except (ValueError, TypeError):
                d["run_report"] = None
        out.append(d)
    return out
