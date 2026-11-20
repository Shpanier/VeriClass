"""The lecturer's notifications: what students sent that the lecturer should
see, for the dashboard's pop-ups and its bell (GET /api/notifications).

Nothing is written when a student acts: the feed reads the rows the platform
already keeps, so every client (web chat, IDE plugin) and every exercise is
covered, and a notification can't get out of step with what it points at.

Kinds (each can be turned off; `chat` is off by default):
  question    a question in the review queue (review mode on): the student
              waits for the lecturer's answer           (pending_reviews)
  step        a step answer or a pasted output that waits for the lecturer's
              check; only while it waits                 (step_checks pending | waiting)
  answer      a quiz answer graded too low: waits for the lecturer's decision
                                                         (probes review_status 'waiting')
  reply       a student answered the lecturer's own question ("Ask them")
                                                         (probes without quiz_key, answered)
  submission  "Send to teacher" in the IDE plugin       (submissions)
  chat        any message a student writes in the chat, also the ones the
              tutor answers by itself                    (messages, role 'user')

An item "waits" while the lecturer still has to act on it (question, step,
answer); the dashboard keeps its pop-up open until then. Every item has a key
"<kind>:<row id>", unique across kinds.

Settings (system_settings, GET/POST /api/notifications/config):
  notify_kinds   comma-separated kinds that notify (default all but chat)
  notify_sound   on | off: a short chime with each new notification (default on)
Each lecturer's "seen up to" (the bell's unread count) is in notification_seen.
"""
from __future__ import annotations

from typing import Any, Optional

from backend import db, exercises, pacing

KINDS = ("question", "step", "answer", "reply", "submission", "chat")
DEFAULT_KINDS = ("question", "step", "answer", "reply", "submission")
# How far back the feed reaches; also the bell's list.
HOURS = 12
LIMIT = 100
SNIPPET = 240


def _setting(key: str) -> Optional[str]:
    with db.conn() as c:
        row = c.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_setting(key: str, value: str) -> None:
    with db.conn() as c:
        c.execute("INSERT INTO system_settings(key, value) VALUES(?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def kinds() -> list[str]:
    raw = _setting("notify_kinds")
    if raw is None:
        return list(DEFAULT_KINDS)
    picked = {k.strip() for k in raw.split(",")}
    return [k for k in KINDS if k in picked]


def sound() -> bool:
    return (_setting("notify_sound") or "on") != "off"


def config() -> dict[str, Any]:
    return {"kinds": kinds(), "all_kinds": list(KINDS), "default_kinds": list(DEFAULT_KINDS),
            "sound": sound(), "hours": HOURS}


def save_config(new_kinds: Optional[list[str]] = None, new_sound: Optional[bool] = None) -> dict[str, Any]:
    if new_kinds is not None:
        unknown = [k for k in new_kinds if k not in KINDS]
        if unknown:
            raise ValueError(f"unknown kinds: {', '.join(unknown)}")
        _set_setting("notify_kinds", ",".join(k for k in KINDS if k in new_kinds))
    if new_sound is not None:
        _set_setting("notify_sound", "on" if new_sound else "off")
    return config()


def seen_at(user_id: int) -> Optional[str]:
    with db.conn() as c:
        row = c.execute("SELECT seen_at FROM notification_seen WHERE user_id = ?", (user_id,)).fetchone()
    return row["seen_at"] if row else None


def mark_seen(user_id: int, at: Optional[str] = None) -> str:
    """Everything up to `at` (default: now) counts as seen for this lecturer.
    Never moves the mark back."""
    with db.conn() as c:
        now = at or c.execute("SELECT CURRENT_TIMESTAMP AS t").fetchone()["t"]
        c.execute("INSERT INTO notification_seen(user_id, seen_at) VALUES(?, ?) "
                  "ON CONFLICT(user_id) DO UPDATE SET seen_at = MAX(seen_at, excluded.seen_at)", (user_id, now))
        return c.execute("SELECT seen_at FROM notification_seen WHERE user_id = ?", (user_id,)).fetchone()["seen_at"]


def _snip(text: Optional[str]) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= SNIPPET else t[: SNIPPET - 1] + "…"


# One SELECT per kind, all with the same columns: id, session_id, at, text,
# step, waiting. `{since}` is the lower bound on `at`.
_SQL = {
    "question": """
        SELECT r.id, r.session_id, r.created_at AS at, r.question AS text, NULL AS step,
               r.status = 'pending' AS waiting
        FROM pending_reviews r WHERE r.created_at > ? AND r.status != 'replaced'""",
    "step": """
        SELECT k.id, k.session_id, k.created_at AS at, k.answer AS text, k.step,
               k.status IN ('pending', 'waiting') AS waiting
        FROM step_checks k
        WHERE k.created_at > ? AND k.status IN ('pending', 'waiting')""",
    "answer": """
        SELECT p.id, p.session_id, p.answered_at AS at, p.answer AS text, p.quiz_step AS step,
               p.review_status = 'waiting' AS waiting
        FROM probes p
        WHERE p.answered_at > ? AND p.quiz_key IS NOT NULL AND p.review_status IS NOT NULL
              AND p.review_status != 'reset'""",
    "reply": """
        SELECT p.id, p.session_id, p.answered_at AS at, p.answer AS text, NULL AS step, 0 AS waiting
        FROM probes p
        WHERE p.answered_at > ? AND p.quiz_key IS NULL AND p.status = 'answered'""",
    "submission": """
        SELECT b.id, b.session_id, b.created_at AS at, COALESCE(b.filename, '') AS text, NULL AS step, 0 AS waiting
        FROM submissions b WHERE b.created_at > ?""",
    "chat": """
        SELECT m.id, m.session_id, m.created_at AS at, m.body AS text, NULL AS step, 0 AS waiting
        FROM messages m
        WHERE m.created_at > ? AND m.role = 'user' AND m.via = 'live'
          AND NOT EXISTS (SELECT 1 FROM pending_reviews r
                          WHERE r.session_id = m.session_id AND r.question = m.body)""",
}


def feed(user_id: int, since: Optional[str] = None, only: Optional[list[str]] = None) -> dict[str, Any]:
    """The notifications after `since` (at most HOURS back), newest first, at
    most LIMIT; `waiting`: the keys of every item in the window still waiting
    for the lecturer, so the dashboard closes a pop-up once it is handled."""
    picked = [k for k in (only if only is not None else kinds()) if k in KINDS]
    with db.conn() as c:
        now = c.execute("SELECT CURRENT_TIMESTAMP AS t").fetchone()["t"]
        floor = c.execute(f"SELECT datetime('now', '-{HOURS} hours') AS t").fetchone()["t"]
        lower = max(since, floor) if since else floor
        rows: list[tuple[str, Any]] = []
        waiting: list[str] = []
        for kind in picked:
            for r in c.execute(_SQL[kind], (lower,)).fetchall():
                rows.append((kind, r))
            if since and kind in ("question", "step", "answer"):
                # Still waiting, although older than `since`: for the pop-ups.
                for r in c.execute(_SQL[kind], (floor,)).fetchall():
                    if r["waiting"]:
                        waiting.append(f"{kind}:{r['id']}")
        rows.sort(key=lambda kr: (kr[1]["at"] or "", kr[1]["id"]), reverse=True)
        rows = rows[:LIMIT]
        sids = sorted({r["session_id"] for _, r in rows})
        who: dict[str, Any] = {}
        if sids:
            marks = ",".join("?" * len(sids))
            for s in c.execute(
                    f"SELECT s.id, s.exercise, s.course_id, u.username FROM sessions s JOIN users u ON u.id = s.user_id "
                    f"WHERE s.id IN ({marks})", sids):
                who[s["id"]] = s
    items = []
    labels: dict[str, Any] = {}
    for kind, r in rows:
        s = who.get(r["session_id"])
        if s is None:
            continue
        key = f"{kind}:{r['id']}"
        if r["waiting"] and key not in waiting:
            waiting.append(key)
        step_label = None
        if r["step"] is not None:
            eid = s["exercise"]
            if eid not in labels:
                try:
                    labels[eid] = exercises.get(eid)
                except KeyError:
                    labels[eid] = None
            step_label = pacing.label(labels[eid], int(r["step"])) if labels[eid] else str(r["step"])
        items.append({
            "key": key, "kind": kind, "id": r["id"], "session_id": r["session_id"],
            "username": s["username"], "exercise_id": s["exercise"], "course_id": s["course_id"],
            "text": _snip(r["text"]), "step": r["step"], "step_label": step_label,
            "created_at": r["at"], "waiting": bool(r["waiting"]),
        })
    return {"now": now, "seen_at": seen_at(user_id), "kinds": picked, "sound": sound(),
            "items": items, "waiting": waiting}
