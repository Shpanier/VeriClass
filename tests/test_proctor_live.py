"""Exam proctoring beyond leave-the-IDE: the live status on the grid, panels and
windows that aren't allowed, pastes, full terminal output with retries, and the
student's signed trace export."""
import json
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-proctor-tests")

import pytest
from fastapi.testclient import TestClient

from backend import db, trace
from backend.main import app

TEACHER = "LIVE-TEACH"
NOA = "LIVE-NOAAA"
ELI = "LIVE-ELIII"


@pytest.fixture(scope="module")
def client():
    # 127.0.0.1: instructor logins are local-only, like the real dashboard.
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            for name, code, role in (
                ("Live Teacher", TEACHER, "teacher"),
                ("Noa Levi", NOA, "student"),
                ("Eli Mor", ELI, "student"),
            ):
                c.execute(
                    "INSERT OR IGNORE INTO users(username, login_code, role) VALUES(?,?,?)",
                    (name, code, role),
                )
        yield tc


def _hdr(tc, code):
    r = tc.post("/api/login", json={"code": code, "password": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def teacher(client):
    return _hdr(client, TEACHER)


@pytest.fixture(scope="module")
def noa(client):
    return _hdr(client, NOA)


@pytest.fixture(scope="module")
def eli(client):
    return _hdr(client, ELI)


@pytest.fixture(scope="module")
def session(client, noa):
    r = client.post("/api/sessions", json={}, headers=noa)
    assert r.status_code == 200, r.text
    return r.json()


def _row(client, teacher, session_id):
    rows = client.get("/api/students", headers=teacher).json()
    return next(s for s in rows if s["session_id"] == session_id)


def _beat(client, hdr, sid, **status):
    base = {"focused": True, "fullscreen": True, "fullscreen_supported": True,
            "tool_windows": ["VeriExam", "VeriExam Terminal"], "forbidden_tool_windows": [],
            "other_windows": [], "open_files": ["main.py"], "active_file": "main.py"}
    base.update(status)
    r = client.post("/api/proctor/heartbeat", json={"session_id": sid, "status": base}, headers=hdr)
    assert r.status_code == 200, r.text


# --- session key ---------------------------------------------------------------


def test_session_carries_a_stable_trace_key(client, noa, session):
    assert len(session["trace_key"]) == 64
    again = client.post("/api/sessions", json={}, headers=noa).json()
    assert again["session_id"] == session["session_id"]
    assert again["trace_key"] == session["trace_key"]


# --- live state ---------------------------------------------------------------


def test_live_state_follows_the_snapshot(client, teacher, noa, session):
    sid = session["session_id"]
    _beat(client, noa, sid)
    row = _row(client, teacher, sid)
    assert row["exam_state"] == "ok"
    assert row["live"]["open_files"] == ["main.py"]

    _beat(client, noa, sid, fullscreen=False)
    assert _row(client, teacher, sid)["exam_state"] == "not_fullscreen"

    _beat(client, noa, sid, other_windows=["Settings"])
    row = _row(client, teacher, sid)
    assert (row["exam_state"], row["exam_state_detail"]) == ("other_window", "Settings")

    _beat(client, noa, sid, focused=False, other_windows=["Settings"])
    row = _row(client, teacher, sid)
    assert row["exam_state"] == "away" and row["away"] is True

    _beat(client, noa, sid)
    assert _row(client, teacher, sid)["exam_state"] == "ok"


def test_stale_snapshot_is_no_signal(client, teacher, noa, session):
    sid = session["session_id"]
    _beat(client, noa, sid)
    with db.conn() as c:
        c.execute("UPDATE live_status SET updated_at = datetime('now', '-2 minutes') WHERE session_id = ?", (sid,))
    assert _row(client, teacher, sid)["exam_state"] == "no_signal"
    _beat(client, noa, sid)


def test_old_plugin_without_snapshot_uses_events(client, teacher, eli):
    sid = client.post("/api/sessions", json={}, headers=eli).json()["session_id"]
    assert _row(client, teacher, sid)["exam_state"] is None
    for kind, state in (("exam_started", "ok"), ("fullscreen_exited", "not_fullscreen"),
                        ("fullscreen_restored", "ok"), ("focus_lost", "away"), ("focus_regained", "ok")):
        r = client.post("/api/proctor/event", json={"session_id": sid, "kind": kind}, headers=eli)
        assert r.status_code == 200, r.text
        assert _row(client, teacher, sid)["exam_state"] == state, kind
    # One-off events don't change the state.
    client.post("/api/proctor/event", json={"session_id": sid, "kind": "file_opened", "detail": "a.py"}, headers=eli)
    assert _row(client, teacher, sid)["exam_state"] == "ok"


def test_status_bound_to_own_session(client, eli, session):
    r = client.post("/api/proctor/heartbeat", json={"session_id": session["session_id"], "status": {}}, headers=eli)
    assert r.status_code == 403


# --- panels, windows, retries -----------------------------------------------------


def test_forbidden_panel_is_an_alert_with_how(client, teacher, noa, session):
    sid = session["session_id"]
    before = _row(client, teacher, sid)["ide_alerts"]
    body = {"session_id": sid, "kind": "tool_window_opened",
            "detail": "Project — keyboard ⌘1", "client_id": "tw-1", "client_at": "2026-10-22 09:00:00"}
    assert client.post("/api/proctor/event", json=body, headers=noa).json()["duplicate"] is False
    # The outbox retried a report that had got through: stored once.
    assert client.post("/api/proctor/event", json=body, headers=noa).json()["duplicate"] is True
    row = _row(client, teacher, sid)
    assert row["ide_alerts"] == before + 1
    assert row["last_alert_kind"] == "tool_window_opened"
    assert row["last_alert_detail"] == "Project — keyboard ⌘1"
    assert row["last_alert_at"] == "2026-10-22 09:00:00"
    ev = client.get(f"/api/proctor/events?session_id={sid}", headers=teacher).json()[0]
    assert ev["client_at"] == "2026-10-22 09:00:00" and ev["via"] == "live"


def test_unknown_kind_rejected(client, noa, session):
    r = client.post("/api/proctor/event", json={"session_id": session["session_id"], "kind": "made_up"}, headers=noa)
    assert r.status_code == 422


# --- pastes -------------------------------------------------------------------


def test_paste_from_outside_is_an_alert(client, teacher, noa, session):
    sid = session["session_id"]
    before = _row(client, teacher, sid)
    text = "def solve():\n    return 42\n"
    body = {"session_id": sid, "target": "editor", "source": "outside", "text": text,
            "file": "main.py", "client_id": "p-1"}
    assert client.post("/api/proctor/paste", json=body, headers=noa).status_code == 200
    assert client.post("/api/proctor/paste", json=body, headers=noa).json()["duplicate"] is True
    client.post("/api/proctor/paste", json={"session_id": sid, "target": "terminal", "source": "ide",
                                            "text": "ls -l", "client_id": "p-2"}, headers=noa)
    row = _row(client, teacher, sid)
    assert row["paste_count"] == before["paste_count"] + 2
    assert row["ide_alerts"] == before["ide_alerts"] + 1  # only the outside one
    pastes = client.get(f"/api/proctor/pastes?session_id={sid}", headers=teacher).json()
    assert pastes[1]["text"] == text and pastes[1]["lines"] == 3 and pastes[1]["source"] == "outside"
    kinds = [e["kind"] for e in client.get(f"/api/proctor/events?session_id={sid}", headers=teacher).json()[:2]]
    assert kinds == ["paste_internal", "paste_external"]


def test_pastes_list_is_teacher_only(client, noa, session):
    assert client.get(f"/api/proctor/pastes?session_id={session['session_id']}", headers=noa).status_code == 403


# --- terminal: full output in pieces ------------------------------------------------


def test_full_output_reassembled_and_retry_safe(client, teacher, noa, session):
    sid = session["session_id"]
    output = "".join(f"line {i}\n" for i in range(5000))  # ~49 KB → 4 pieces
    pieces = [output[i:i + 16000] for i in range(0, len(output), 16000)]
    cmd = {"session_id": sid, "line": "seq 5000", "allowed": True, "exit_code": 0,
           "output_tail": output[-4000:], "client_id": "cmd-1", "client_at": "2026-10-22 09:01:00",
           "output_chars": len(output), "output_chunks": len(pieces)}
    first = client.post("/api/terminal/command", json=cmd, headers=noa).json()
    assert client.post("/api/terminal/command", json=cmd, headers=noa).json()["duplicate"] is True
    for i, p in enumerate(pieces[:-1]):
        body = {"session_id": sid, "client_id": "cmd-1", "seq": i, "text": p}
        assert client.post("/api/terminal/output", json=body, headers=noa).json()["stored"] is True
    partial = client.get(f"/api/terminal/commands/{first['id']}/output", headers=teacher).json()
    assert partial["complete"] is False and "was not received" in partial["output"]
    last = {"session_id": sid, "client_id": "cmd-1", "seq": len(pieces) - 1, "text": pieces[-1]}
    client.post("/api/terminal/output", json=last, headers=noa)
    assert client.post("/api/terminal/output", json=last, headers=noa).json()["stored"] is False
    full = client.get(f"/api/terminal/commands/{first['id']}/output", headers=teacher).json()
    assert full["complete"] is True and full["output"] == output


def test_output_bound_to_own_session(client, eli, session):
    body = {"session_id": session["session_id"], "client_id": "x", "seq": 0, "text": "hi"}
    assert client.post("/api/terminal/output", json=body, headers=eli).status_code == 403


# --- signed export --------------------------------------------------------------------


def _export(session, rows):
    """Build an export the way the plugin does (see backend/trace.py)."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(trace.COLUMNS)
    prev = ""
    rows = rows + [("export_end", "end", {"rows": len(rows)})]
    for seq, (kind, cid, payload) in enumerate(rows, start=1):
        p = json.dumps(payload)
        at = f"2026-10-22 09:{seq:02d}:00"
        mac = trace.row_mac(session["trace_key"], prev, str(seq), cid, at, session["session_id"], kind, p)
        w.writerow([seq, at, at, session["session_id"], "Noa Levi", kind, "", "", "", "", "no", cid, p, mac])
        prev = mac
    return "﻿" + buf.getvalue()


def _sample_rows(sid):
    return [
        ("chat_user", "c-1", {"text": "How do I count lines?"}),
        ("terminal", "cmd-exp", {"session_id": sid, "line": "wc -l data.txt", "allowed": True,
                                 "exit_code": 0, "output": "12 data.txt\n" * 3000}),
        ("proctor", "ev-exp", {"session_id": sid, "kind": "focus_lost", "detail": "You switched away."}),
        ("paste", "p-exp", {"session_id": sid, "target": "editor", "source": "outside", "text": "x = 1"}),
    ]


def test_export_verifies_and_imports_missing(client, teacher, session):
    sid = session["session_id"]
    csv_text = _export(session, _sample_rows(sid))
    r = client.post("/api/trace/verify", json={"csv": csv_text}, headers=teacher).json()
    assert r["ok"] is True and r["complete"] is True and r["student"] == "Noa Levi"
    assert r["missing_on_server"] == 4 and r["imported"] == 0

    r = client.post("/api/trace/verify", json={"csv": csv_text, "import_missing": True}, headers=teacher).json()
    assert r["imported"] == 4
    cmds = client.get(f"/api/terminal/commands?session_id={sid}", headers=teacher).json()
    imported = next(c for c in cmds if c["line"] == "wc -l data.txt")
    assert imported["via"] == "export"
    full = client.get(f"/api/terminal/commands/{imported['id']}/output", headers=teacher).json()
    assert full["complete"] is True and full["output"] == "12 data.txt\n" * 3000

    # Importing again changes nothing.
    r = client.post("/api/trace/verify", json={"csv": csv_text, "import_missing": True}, headers=teacher).json()
    assert r["missing_on_server"] == 0 and r["imported"] == 0


def test_edited_export_is_caught(client, teacher, session):
    sid = session["session_id"]
    csv_text = _export(session, _sample_rows(sid))
    edited = csv_text.replace("How do I count lines?", "I did it myself")
    r = client.post("/api/trace/verify", json={"csv": edited, "import_missing": True}, headers=teacher).json()
    assert r["ok"] is False and r["first_bad_seq"] == 1 and r["valid_rows"] == 0 and r["imported"] == 0


def test_cut_export_is_caught(client, teacher, session):
    lines = _export(session, _sample_rows(session["session_id"])).split("\r\n")
    cut = "\r\n".join(lines[:-2]) + "\r\n"  # drop the end marker
    r = client.post("/api/trace/verify", json={"csv": cut}, headers=teacher).json()
    assert r["ok"] is False and r["complete"] is False and r["first_bad_seq"] is None


def test_not_an_export(client, teacher):
    r = client.post("/api/trace/verify", json={"csv": "a,b\n1,2\n"}, headers=teacher)
    assert r.status_code == 422


def test_verify_is_teacher_only(client, noa, session):
    r = client.post("/api/trace/verify", json={"csv": _export(session, [])}, headers=noa)
    assert r.status_code == 403


def test_token_survives_a_backend_restart(client, noa, session):
    from backend import auth
    auth._SESSION_TOKENS.clear()  # what a restart does to the in-memory cache
    r = client.post("/api/proctor/heartbeat", json={"session_id": session["session_id"]}, headers=noa)
    assert r.status_code == 200, r.text
