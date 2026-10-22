"""Exam window lock: the IDE window stays maximized, and on Windows the plugin
reports another app in front. The server must accept the new events and show
the new live state."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-exam-window-tests")

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.main import app
from backend.routes.students import exam_state

TEACHER = "WIN-TEACH"
STUDENT = "WIN-STUDY"


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            for name, code, role in (("Win Teacher", TEACHER, "teacher"), ("Win Student", STUDENT, "student")):
                c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES (?, ?, ?)",
                          (name, code, role))
        yield tc


def _h(tc, code):
    r = tc.post("/api/login", json={"code": code, "password": code})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_new_events_are_accepted_and_count_as_alerts(client):
    hs = _h(client, STUDENT)
    sid = client.post("/api/sessions", json={}, headers=hs).json()["session_id"]
    for kind in ("other_app_in_front", "window_unmaximized", "window_maximized"):
        r = client.post("/api/proctor/event", headers=hs,
                        json={"session_id": sid, "kind": kind, "detail": "chrome.exe — \"ChatGPT\""})
        assert r.status_code == 200, r.text
    rows = {s["session_id"]: s for s in client.get("/api/students", headers=_h(client, TEACHER)).json()}
    assert rows[sid]["focus_alerts"] == 2  # the two leaves; "maximized again" is not an alert


def test_live_state_not_maximized():
    base = {"focused": True, "fullscreen": False, "fullscreen_supported": False}
    assert exam_state(None, {**base, "maximized": False}, 1.0) == ("not_maximized", "window not maximized")
    assert exam_state(None, {**base, "maximized": True}, 1.0) == ("ok", None)
    assert exam_state(None, base, 1.0) == ("ok", None)  # older plugins don't send "maximized"


def test_last_event_decides_without_a_live_status():
    assert exam_state("other_app_in_front", None, None) == ("away", "outside the IDE")
    assert exam_state("window_unmaximized", None, None) == ("not_maximized", "window not maximized")
    assert exam_state("window_maximized", None, None) == ("ok", None)


def test_client_config_asks_for_a_maximized_window(client, monkeypatch):
    monkeypatch.setenv("STUDENT_CLIENT_MODE", "ide")
    monkeypatch.delenv("EXAM_MODE", raising=False)
    monkeypatch.delenv("EXAM_MAXIMIZED", raising=False)
    assert client.get("/api/client-config").json()["exam_maximized"] is True
    monkeypatch.setenv("EXAM_MAXIMIZED", "false")
    assert client.get("/api/client-config").json()["exam_maximized"] is False
    monkeypatch.setenv("EXAM_MODE", "false")
    monkeypatch.delenv("EXAM_MAXIMIZED")
    assert client.get("/api/client-config").json()["exam_maximized"] is False
