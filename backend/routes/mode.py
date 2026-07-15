from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import db, deps

router = APIRouter()


class ModeRequest(BaseModel):
    session_id: str
    mode: str  # mentor | coding_partner


@router.post("/mode")
def set_mode(req: ModeRequest, teacher: dict = Depends(deps.require_teacher)):
    if req.mode not in ("mentor", "coding_partner"):
        raise HTTPException(400, "mode must be 'mentor' or 'coding_partner'")
    with db.conn() as c:
        result = c.execute(
            "UPDATE sessions SET mode = ? WHERE id = ?", (req.mode, req.session_id)
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Unknown session")
    return {"ok": True, "mode": req.mode}
