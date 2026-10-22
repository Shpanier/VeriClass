import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend import db, deps, exercises
from backend.grading import service as grade_service
from backend.routes.proctor import ALERT_KINDS, FOCUS_STATE_KINDS, IDE_ALERT_KINDS, TERMINAL_ALERT_KINDS

router = APIRouter()


def _ph(kinds: tuple) -> str:
    """"?, ?, ?" for an IN (...) over these kinds."""
    return ", ".join("?" for _ in kinds)


_ANY_ALERT_KINDS = ALERT_KINDS + TERMINAL_ALERT_KINDS + IDE_ALERT_KINDS

# No live status for this long means the exam client stopped reporting: IDE
# closed or crashed, laptop asleep, network or tunnel down.
NO_SIGNAL_AFTER_S = 45


def _variant_params(exercise_id: str, variant_id: str) -> dict:
    """This session's variant parameters, for the dashboard to render. Empty if
    the exercise/variant no longer exists (e.g. an edit removed the variant)."""
    try:
        return exercises.variant(exercise_id, variant_id).get("params", {})
    except Exception:
        return {}


def exam_state(last_focus_kind: Optional[str], live: Optional[dict], live_age_s: Optional[float]) -> tuple[Optional[str], Optional[str]]:
    """(state, detail) for the live grid:

      no_signal       the exam client stopped sending its status
      away            outside the IDE (another app, minimized)
      other_window    a dialog, another project window, or a panel that isn't allowed
      not_fullscreen  in the IDE but out of full screen
      ok              in the IDE, full screen, only the allowed panels
      None            this student isn't running the exam client

    The live snapshot wins when there is one; plugins too old to send it fall
    back to the last focus event.
    """
    if live is not None and live_age_s is not None:
        if live_age_s > NO_SIGNAL_AFTER_S:
            return "no_signal", f"no status for {int(live_age_s)} s"
        if live.get("focused") is False:
            return "away", "outside the IDE"
        others = [str(w) for w in (live.get("other_windows") or [])]
        panels = [str(w) for w in (live.get("forbidden_tool_windows") or [])]
        if others or panels:
            return "other_window", ", ".join(others + panels)
        if live.get("fullscreen") is False and live.get("fullscreen_supported", True):
            return "not_fullscreen", "not in full screen"
        return "ok", None
    if last_focus_kind is None:
        return None, None
    if last_focus_kind in ("focus_lost", "minimized"):
        return "away", "outside the IDE"
    if last_focus_kind == "fullscreen_exited":
        return "not_fullscreen", "not in full screen"
    return "ok", None


@router.get("/students")
def list_students(teacher: dict = Depends(deps.require_teacher)):
    """Returns one row per active session (last_active_at within 30 min),
    enriched with the exam/proctor signals the dashboard flags on:

      focus_alerts    how many times the student left the IDE or full screen
      last_focus_kind the most recent focus event ('focus_lost', 'minimized',
                      'focus_regained', …) or None
      last_focus_at   when that event happened
      away            True if the student is currently outside the IDE
      terminal_alerts refused VeriExam-terminal commands + attempts to open
                      the IDE's own Terminal during an exam
      ide_alerts      panels/windows that aren't allowed + pastes from outside
      terminal_count  lines entered in the VeriExam terminal
      paste_count     every paste the exam client saw
      exam_state, exam_state_detail   see exam_state()
      live            the exam client's latest snapshot (open panels, tabs, …)
      live_age_s      how old that snapshot is
      last_alert_kind, last_alert_detail, last_alert_at   the newest alert
    """
    with db.conn() as c:
        rows = c.execute(
            f"""
            SELECT s.id AS session_id, u.username, s.exercise, s.variant,
                   s.mode, s.started_at, s.last_active_at,
                   (SELECT COUNT(*) FROM probes p WHERE p.session_id = s.id) AS probe_count,
                   (SELECT COUNT(*) FROM submissions sub WHERE sub.session_id = s.id) AS submission_count,
                   (SELECT COUNT(*) FROM proctor_events e
                      WHERE e.session_id = s.id
                        AND e.kind IN ({_ph(ALERT_KINDS)})) AS focus_alerts,
                   (SELECT e.kind FROM proctor_events e
                      WHERE e.session_id = s.id
                        AND e.kind IN ({_ph(FOCUS_STATE_KINDS)})
                      ORDER BY e.id DESC LIMIT 1) AS last_focus_kind,
                   (SELECT e.created_at FROM proctor_events e
                      WHERE e.session_id = s.id
                        AND e.kind IN ({_ph(FOCUS_STATE_KINDS)})
                      ORDER BY e.id DESC LIMIT 1) AS last_focus_at,
                   (SELECT COUNT(*) FROM proctor_events e
                      WHERE e.session_id = s.id
                        AND e.kind IN ({_ph(TERMINAL_ALERT_KINDS)})) AS terminal_alerts,
                   (SELECT COUNT(*) FROM proctor_events e
                      WHERE e.session_id = s.id
                        AND e.kind IN ({_ph(IDE_ALERT_KINDS)})) AS ide_alerts,
                   (SELECT e.id || char(31) || e.kind || char(31) || COALESCE(e.detail, '')
                           || char(31) || COALESCE(e.client_at, e.created_at)
                      FROM proctor_events e
                      WHERE e.session_id = s.id
                        AND e.kind IN ({_ph(_ANY_ALERT_KINDS)})
                      ORDER BY e.id DESC LIMIT 1) AS last_alert,
                   (SELECT COUNT(*) FROM terminal_commands t
                      WHERE t.session_id = s.id) AS terminal_count,
                   (SELECT COUNT(*) FROM pastes pa
                      WHERE pa.session_id = s.id) AS paste_count,
                   ls.data AS live_data,
                   CAST(strftime('%s', 'now') AS INTEGER) - CAST(strftime('%s', ls.updated_at) AS INTEGER)
                       AS live_age_s,
                   g.recommended AS recommended_grade,
                   g.override_grade AS grade_override,
                   g.band AS grade_band
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            LEFT JOIN live_status ls ON ls.session_id = s.id
            LEFT JOIN grade_recommendations g ON g.session_id = s.id
            WHERE s.last_active_at >= datetime('now', '-30 minutes')
            ORDER BY s.last_active_at DESC
            """,
            ALERT_KINDS + FOCUS_STATE_KINDS * 2 + TERMINAL_ALERT_KINDS + IDE_ALERT_KINDS + _ANY_ALERT_KINDS,
        ).fetchall()

    students = []
    for r in rows:
        d = dict(r)
        live = None
        if d.pop("live_data"):
            try:
                live = json.loads(r["live_data"])
            except ValueError:
                live = None
        d["live"] = live if isinstance(live, dict) else None
        if d["live"] is None:
            d["live_age_s"] = None
        d["exam_state"], d["exam_state_detail"] = exam_state(d["last_focus_kind"], d["live"], d["live_age_s"])
        d["away"] = d["exam_state"] == "away"
        last = d.pop("last_alert")
        if last:
            _, kind, detail, at = last.split("\x1f", 3)
            d["last_alert_kind"], d["last_alert_detail"], d["last_alert_at"] = kind, detail or None, at
        else:
            d["last_alert_kind"] = d["last_alert_detail"] = d["last_alert_at"] = None
        d["variant_params"] = _variant_params(d["exercise"], d["variant"])
        students.append(d)
    return students


@router.get("/students/{session_id}/messages")
def session_messages(session_id: str, teacher: dict = Depends(deps.require_teacher)):
    """Full chat transcript + probes for one student session."""
    with db.conn() as c:
        sess = c.execute(
            """
            SELECT s.id AS session_id, u.username, s.exercise, s.variant, s.mode,
                   s.started_at, s.last_active_at
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()
        if not sess:
            raise HTTPException(404, "Unknown session")
        messages = c.execute(
            "SELECT id, role, body, mode_at_time, created_at FROM messages "
            "WHERE session_id = ? ORDER BY created_at ASC, id ASC",
            (session_id,),
        ).fetchall()
        probes = c.execute(
            "SELECT id, body, status, answer, auto_grade, override_grade, source, "
            "sent_at, answered_at FROM probes WHERE session_id = ? ORDER BY sent_at ASC",
            (session_id,),
        ).fetchall()
    session = dict(sess)
    session["variant_params"] = _variant_params(session["exercise"], session["variant"])
    return {
        "session": session,
        "messages": [dict(m) for m in messages],
        "probes": [dict(p) for p in probes],
        "grade": grade_service.get(session_id),
    }
