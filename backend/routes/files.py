"""Data files that exercises hand to students (e.g. a CSV for a data lab).

Files placed in EXERCISE_FILES_DIR (default ./config/exercise_files) are served
publicly at GET /api/files/<name>, so a brief can tell students to download one
with a line of Python. Public on purpose (no token in the student's script);
only put course material there.
"""
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

FILES_DIR = Path(os.environ.get("EXERCISE_FILES_DIR", "./config/exercise_files"))
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@router.get("/files/{name}")
def get_file(name: str):
    if not _SAFE_NAME.match(name):
        raise HTTPException(404, "Not found")
    path = FILES_DIR / name
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path, filename=name)
