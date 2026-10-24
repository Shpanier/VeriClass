"""VeriExam terminal: the policy handed to the plugin, the command log, and the
alert a refused command raises on the dashboard."""
import os
import tempfile

# Same isolation as test_auth: a throwaway DB before backend is imported (if
# test_auth ran first in this process, its DB is reused — codes here differ).
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-terminal-tests")

import pytest
from fastapi.testclient import TestClient

from backend import db, exercises, terminal
from backend.main import app

TEACHER = "TERM-TEACH"
CARMEL = "TERM-CARMEL"
DOV = "TERM-DOVVV"


@pytest.fixture(scope="module")
def client():
    # Connect as 127.0.0.1: instructor logins are local-only, like the real dashboard.
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            for name, code, role in (
                ("Term Teacher", TEACHER, "teacher"),
                ("Carmel Cohen", CARMEL, "student"),
                ("Dov Dahan", DOV, "student"),
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
def carmel(client):
    return _hdr(client, CARMEL)


@pytest.fixture(scope="module")
def dov(client):
    return _hdr(client, DOV)


@pytest.fixture(scope="module")
def session(client, carmel):
    r = client.post("/api/sessions", json={}, headers=carmel)
    assert r.status_code == 200, r.text
    return r.json()


def _student_row(client, teacher, session_id):
    rows = client.get("/api/students", headers=teacher).json()
    return next(s for s in rows if s["session_id"] == session_id)


# --- policy ---------------------------------------------------------------


def test_default_policy():
    p = terminal.policy_for({"exercise_id": "x"})
    assert p["source"] == "default"
    assert p["scripts"] is True
    assert {"grep", "awk", "git"} <= set(p["allow"])
    assert not {"python3", "bash", "curl"} & set(p["allow"])


def test_exercise_policy_replaces_and_extends():
    p = terminal.policy_for({"terminal": {"allow": ["LS", "cat"], "allow_extra": ["python3"], "scripts": False}})
    assert p == {"allow": ["cat", "ls", "python3"], "scripts": False, "source": "exercise", "blocked_hint": None}
    p = terminal.policy_for({"terminal": {"allow_extra": ["python3"]}})
    assert "python3" in p["allow"] and "grep" in p["allow"]


def test_python_lab_allows_pip_by_default():
    # October 2026: six students' `pip install` was refused at the start of a Python lab.
    p = terminal.policy_for({"language": "python"})
    assert {"pip", "pip3", "python", "python3"} <= set(p["allow"])
    # An explicit list wins: the teacher decides.
    p = terminal.policy_for({"language": "python", "terminal": {"allow": ["ls"]}})
    assert p["allow"] == ["ls"]


def test_blocked_hint():
    hint = "Install packages in PyCharm's Terminal tab."
    assert terminal.policy_for({"terminal": {"blocked_hint": hint}})["blocked_hint"] == hint
    terminal.validate({"blocked_hint": hint}, "x")
    with pytest.raises(ValueError):
        terminal.validate({"blocked_hint": "x" * 301}, "x")


@pytest.mark.parametrize(
    "cfg",
    [
        "ls cat",
        {"allow": "ls"},
        {"allow": ["ls", ""]},
        {"allow": ["rm -rf"]},
        {"scripts": "yes"},
        {"alow": ["ls"]},
    ],
)
def test_bad_terminal_block_is_rejected(cfg):
    with pytest.raises(ValueError):
        terminal.validate(cfg, "test")


def test_active_exercise_carries_the_policy(client, carmel, session):
    r = client.get(f"/api/exercises/active?variant={session['variant']}", headers=carmel)
    assert r.status_code == 200, r.text
    assert "grep" in r.json()["terminal"]["allow"]


def test_exercise_edit_keeps_terminal_block(client, teacher):
    ex = dict(exercises.active())
    ex_id = ex["exercise_id"]
    full = client.get(f"/api/exercises/{ex_id}", headers=teacher).json()
    full["terminal"] = {"allow": ["ls", "grep"], "scripts": False}
    assert client.put(f"/api/exercises/{ex_id}", json=full, headers=teacher).status_code == 200
    assert terminal.policy_for(exercises.get(ex_id))["allow"] == ["grep", "ls"]
    # The dashboard form doesn't send `terminal`; a plain edit must not wipe it.
    full.pop("terminal")
    assert client.put(f"/api/exercises/{ex_id}", json=full, headers=teacher).status_code == 200
    assert exercises.get(ex_id)["terminal"] == {"allow": ["ls", "grep"], "scripts": False}
    # Restore the built-in YAML for the other tests.
    with db.conn() as c:
        c.execute("DELETE FROM exercises WHERE exercise_id = ?", (ex_id,))
    exercises.load_all(exercises_dir())
    exercises.load_from_db()


def exercises_dir():
    from backend.main import EXERCISES_DIR
    return EXERCISES_DIR


# --- logging + alerts -------------------------------------------------------


def test_command_log_requires_own_session(client, carmel, dov, session):
    body = {"session_id": session["session_id"], "line": "ls", "allowed": True}
    assert client.post("/api/terminal/command", json=body).status_code == 401
    assert client.post("/api/terminal/command", json=body, headers=dov).status_code == 403
    assert client.post("/api/terminal/command", json=body, headers=carmel).status_code == 200


def test_teacher_only_log(client, carmel, session):
    url = f"/api/terminal/commands?session_id={session['session_id']}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=carmel).status_code == 403


def test_allowed_command_is_logged_without_alert(client, carmel, teacher, session):
    sid = session["session_id"]
    before = _student_row(client, teacher, sid)
    r = client.post(
        "/api/terminal/command",
        json={
            "session_id": sid,
            "line": "grep -c 404 access.log",
            "cwd": "lab01",
            "allowed": True,
            "commands": ["grep"],
            "exit_code": 0,
            "duration_ms": 12,
            "output_tail": "2\n",
        },
        headers=carmel,
    )
    assert r.status_code == 200 and r.json()["alert"] is False
    row = client.get(f"/api/terminal/commands?session_id={sid}", headers=teacher).json()[0]
    assert row["line"] == "grep -c 404 access.log"
    assert row["allowed"] is True and row["commands"] == ["grep"] and row["exit_code"] == 0
    after = _student_row(client, teacher, sid)
    assert after["terminal_count"] == before["terminal_count"] + 1
    assert after["terminal_alerts"] == before["terminal_alerts"]


def test_refused_command_raises_an_alert(client, carmel, teacher, session):
    sid = session["session_id"]
    before = _student_row(client, teacher, sid)
    r = client.post(
        "/api/terminal/command",
        json={
            "session_id": sid,
            "line": "cat x | bash",
            "allowed": False,
            "reason": "starting another shell ('bash') isn't allowed here",
            "commands": ["cat", "bash"],
        },
        headers=carmel,
    )
    assert r.json()["alert"] is True
    after = _student_row(client, teacher, sid)
    assert after["terminal_alerts"] == before["terminal_alerts"] + 1
    # A terminal alert is not "left the IDE".
    assert after["away"] is False
    assert after["focus_alerts"] == before["focus_alerts"]
    events = client.get(f"/api/proctor/events?session_id={sid}", headers=teacher).json()
    assert events[0]["kind"] == "blocked_command"
    assert "cat x | bash" in events[0]["detail"]


def test_syntax_error_is_logged_but_not_alerted(client, carmel, teacher, session):
    sid = session["session_id"]
    before = _student_row(client, teacher, sid)
    r = client.post(
        "/api/terminal/command",
        json={"session_id": sid, "line": "echo 'oops", "allowed": False,
              "reason": "syntax error: a quote ' is never closed", "syntax_error": True},
        headers=carmel,
    )
    assert r.json()["alert"] is False
    after = _student_row(client, teacher, sid)
    assert after["terminal_alerts"] == before["terminal_alerts"]
    assert after["terminal_count"] == before["terminal_count"] + 1


def test_stock_terminal_event_counts_as_terminal_alert(client, carmel, teacher, session):
    sid = session["session_id"]
    before = _student_row(client, teacher, sid)
    r = client.post(
        "/api/proctor/event",
        json={"session_id": sid, "kind": "stock_terminal_opened", "detail": "tried to open the IDE's own Terminal"},
        headers=carmel,
    )
    assert r.status_code == 200
    after = _student_row(client, teacher, sid)
    assert after["terminal_alerts"] == before["terminal_alerts"] + 1
    assert after["away"] is False


def test_client_cannot_forge_blocked_command_kind(client, carmel, session):
    # blocked_command is written by the backend from a refused line, never posted directly.
    r = client.post(
        "/api/proctor/event",
        json={"session_id": session["session_id"], "kind": "blocked_command"},
        headers=carmel,
    )
    assert r.status_code == 422


def test_oversized_fields_are_clipped(client, carmel, teacher, session):
    sid = session["session_id"]
    r = client.post(
        "/api/terminal/command",
        json={"session_id": sid, "line": "x" * 10_000, "allowed": True, "output_tail": "y" * 50_000},
        headers=carmel,
    )
    assert r.status_code == 200
    row = client.get(f"/api/terminal/commands?session_id={sid}", headers=teacher).json()[0]
    assert len(row["line"]) == 2000 and len(row["output_tail"]) == 8000
