"""Class-session reports for the lecturer's tools (backend/reports.py)."""
from typing import Optional

from fastapi import APIRouter, Depends

from backend import deps, reports

router = APIRouter()


@router.get("/reports/session")
def session_report(exercise_id: Optional[str] = None, course_id: Optional[str] = None,
                   date: Optional[str] = None, include_questions: bool = False,
                   teacher: dict = Depends(deps.require_teacher)):
    """One class session in numbers, students numbered, no names (date:
    YYYY-MM-DD, default the latest day with sessions)."""
    return reports.session_report(exercise_id, course_id, date, include_questions)
