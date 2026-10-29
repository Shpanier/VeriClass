"""A session's chat transcript (backend/transcript.py): the student's chat
appends what it shows and what the student writes, and reads it all back after
a new login. Teachers can read any session's transcript."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import deps, exercises, transcript

router = APIRouter()


def _exercise(session: dict) -> Optional[dict]:
    try:
        return exercises.get(session["exercise"])
    except KeyError:
        return None


@router.get("/transcript/{session_id}")
def read(session_id: str, after: int = 0, origin: Optional[Literal["client", "server"]] = None,
         exclude_client: Optional[str] = None, user: dict = Depends(deps.current_user)):
    """Entries after id `after` (0 = from the start, the latest CHAT_HISTORY_REPLAY_MAX
    of them); origin 'server' = only the server's own notes; exclude_client =
    leave out what this chat wrote itself."""
    s = deps.require_owns_session(session_id, user)
    if not transcript.enabled(_exercise(s)):
        return {"enabled": False, "entries": [], "truncated": False, "last_id": 0}
    out = transcript.entries(session_id, after=after, origin=origin, exclude_client=exclude_client)
    return {"enabled": True, **out, "last_id": transcript.last_id(session_id)}


class Entry(BaseModel):
    author: Literal["student", "tutor", "system"]
    content: str
    kind: str = "text"
    step: Optional[int] = None


class AppendRequest(BaseModel):
    entries: list[Entry] = Field(max_length=50)
    client: Optional[str] = Field(default=None, max_length=80)  # the writing chat's id


@router.post("/transcript/{session_id}")
def append(session_id: str, req: AppendRequest, user: dict = Depends(deps.current_user)):
    """Append entries (the chat's own messages and the student's). Only the
    session's student writes here."""
    s = deps.require_owns_session(session_id, user)
    if s["user_id"] != user["id"]:
        raise HTTPException(403, "Only the session's own chat writes its transcript")
    if not transcript.enabled(_exercise(s)):
        return {"enabled": False, "ids": []}
    try:
        ids = [transcript.record(session_id, e.author, e.content, e.kind, e.step, client=req.client)
               for e in req.entries]
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"enabled": True, "ids": ids}
