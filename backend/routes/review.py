"""Teacher-in-the-loop review queue.

Toggle `review_mode` on; every student /ask is held in `pending_reviews` with
three teacher-pickable variants. The dashboard polls `/api/reviews/pending`,
calls `/api/reviews/{id}/select` with one of {nudge, normal, more}, and the
held /ask request unblocks and streams the chosen text back to the student.
"""
import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import db

router = APIRouter()

# One event per pending review id. The /ask handler awaits the event; the
# teacher's POST sets it. In-memory because uvicorn is single-process; if you
# ever scale out, move this to Redis pub/sub or a DB-poll loop.
_EVENTS: dict[int, asyncio.Event] = {}


def event_for(review_id: int) -> asyncio.Event:
    ev = _EVENTS.get(review_id)
    if ev is None:
        ev = asyncio.Event()
        _EVENTS[review_id] = ev
    return ev


def drop_event(review_id: int) -> None:
    _EVENTS.pop(review_id, None)


def review_mode_enabled() -> bool:
    with db.conn() as c:
        row = c.execute(
            "SELECT value FROM system_settings WHERE key = 'review_mode'"
        ).fetchone()
    return bool(row and row["value"] == "on")


# --- toggle ---------------------------------------------------------------

class ReviewModeRequest(BaseModel):
    enabled: bool


@router.get("/review_mode")
def get_review_mode():
    return {"enabled": review_mode_enabled()}


@router.post("/review_mode")
def set_review_mode(req: ReviewModeRequest):
    value = "on" if req.enabled else "off"
    with db.conn() as c:
        c.execute(
            "INSERT INTO system_settings(key, value) VALUES('review_mode', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (value,),
        )
    return {"enabled": req.enabled}


# --- pending queue --------------------------------------------------------

@router.get("/reviews/pending")
def pending_reviews():
    with db.conn() as c:
        rows = c.execute(
            """
            SELECT r.id, r.session_id, u.username, r.question,
                   r.variant_nudge, r.variant_normal, r.variant_more,
                   r.created_at
            FROM pending_reviews r
            JOIN sessions s ON s.id = r.session_id
            JOIN users u    ON u.id = s.user_id
            WHERE r.status = 'pending'
            ORDER BY r.created_at ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


class SelectRequest(BaseModel):
    chosen: Literal["nudge", "normal", "more"]


@router.post("/reviews/{review_id}/select")
def select_variant(review_id: int, req: SelectRequest):
    with db.conn() as c:
        row = c.execute(
            "SELECT status FROM pending_reviews WHERE id = ?", (review_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Unknown review")
        if row["status"] != "pending":
            raise HTTPException(409, f"Review already {row['status']}")
        c.execute(
            "UPDATE pending_reviews SET status='answered', chosen_level=?, "
            "answered_at=CURRENT_TIMESTAMP WHERE id = ?",
            (req.chosen, review_id),
        )
    event_for(review_id).set()
    return {"ok": True, "chosen": req.chosen}
