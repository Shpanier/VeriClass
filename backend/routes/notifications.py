"""The lecturer's notifications (backend/notifications.py): the feed the
dashboard polls for its pop-ups and bell, "seen", and the settings."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend import deps, notifications

router = APIRouter()


@router.get("/notifications")
def feed(since: Optional[str] = Query(None, max_length=32), teacher: dict = Depends(deps.require_teacher)):
    """New notifications after `since` (the `now` of the previous call; omit
    for the last 12 hours), the keys still waiting for the lecturer, this
    lecturer's "seen up to", and the kinds and sound in use."""
    return notifications.feed(teacher["id"], since)


class SeenRequest(BaseModel):
    # Up to when (a `created_at` or `now` from the feed); default: now.
    at: Optional[str] = Field(None, max_length=32)


@router.post("/notifications/seen")
def seen(req: SeenRequest, teacher: dict = Depends(deps.require_teacher)):
    return {"seen_at": notifications.mark_seen(teacher["id"], req.at)}


@router.get("/notifications/config")
def get_config(teacher: dict = Depends(deps.require_teacher)):
    return notifications.config()


class ConfigRequest(BaseModel):
    kinds: Optional[list[str]] = Field(None, max_length=len(notifications.KINDS))
    sound: Optional[bool] = None


@router.post("/notifications/config")
def set_config(req: ConfigRequest, teacher: dict = Depends(deps.require_teacher)):
    try:
        return notifications.save_config(req.kinds, req.sound)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
