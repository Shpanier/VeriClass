"""Files that exercises hand to students (starter code, data, checks).

Served publicly at GET /api/files/<name>, so a step can tell students to
download one with a line of Python (no token in the student's script). Looked
up in order:
  1. EXERCISE_FILES_DIR (default ./config/exercise_files), the older place;
  2. an exercise package's download zip (`download:` in exercise.yaml, default
     <exercise_id>.zip), built from its files/ folder;
  3. a single file in some package's files/ folder.
Only course material belongs in files/: anyone with the server's address can
download it. A package's solution/ and teacher files are never served.
"""
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from backend import exercises, packages

router = APIRouter()

FILES_DIR = Path(os.environ.get("EXERCISE_FILES_DIR", "./config/exercise_files"))
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@router.get("/files/{name}")
def get_file(name: str):
    if not _SAFE_NAME.match(name):
        raise HTTPException(404, "Not found")
    path = FILES_DIR / name
    if path.is_file():
        return FileResponse(path, filename=name)
    for ex in exercises.all():
        if ex.get("download_name") == name:
            data = packages.download_zip(ex)
            if data is not None:
                return Response(data, media_type="application/zip",
                                headers={"Content-Disposition": f'attachment; filename="{name}"'})
    for ex in exercises.all():
        if not ex.get("files_dir"):  # (Path("") would be the server's own folder)
            continue
        files = Path(ex["files_dir"])
        if (files / name).is_file() and (files / name).resolve().parent == files.resolve():
            return FileResponse(files / name, filename=name)
    raise HTTPException(404, "Not found")
