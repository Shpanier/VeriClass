"""The lecturer's local tools: the key in the private data folder, and the
anonymized session report they read."""
import os
import stat
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-report-tests")

import pytest
from fastapi.testclient import TestClient

from backend import db, deps, exercises
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        exercises.set_active("ex3-mcalc")
        with db.conn() as c:
            c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES ('Rep T', 'REP-T', 'teacher')")
        yield tc


def test_local_key_is_private_and_works_only_locally(client):
    path = deps.LOCAL_TOKEN_FILE
    assert path.is_file() and stat.S_IMODE(path.stat().st_mode) == 0o600
    key = path.read_text().strip()
    assert client.get("/api/exercises", headers={"X-VeriExam-Local-Token": key}).status_code == 200
    assert client.get("/api/exercises", headers={"X-VeriExam-Local-Token": "wrong"}).status_code == 401
    # Through a tunnel (forwarding headers) the key is refused.
    r = client.get("/api/exercises", headers={"X-VeriExam-Local-Token": key, "X-Forwarded-For": "8.8.8.8"})
    assert r.status_code == 401
    with TestClient(app, client=("10.0.0.7", 50000)) as remote:
        assert remote.get("/api/exercises", headers={"X-VeriExam-Local-Token": key}).status_code == 401


def test_session_report_is_anonymized(client):
    names = []
    for i in range(3):
        code = f"REP-S{i}"
        names.append(f"Secret Name {i}")
        with db.conn() as c:
            c.execute("INSERT INTO users (username, login_code, role) VALUES (?, ?, 'student')", (names[-1], code))
        h = {"Authorization": "Bearer " + client.post("/api/login", json={"code": code, "password": code}).json()["token"]}
        s = client.post("/api/sessions", json={"exercise_id": "ex3-mcalc", "client_os": "Windows 11 amd64"},
                        headers=h).json()
        client.post("/api/terminal/command", headers=h, json={
            "session_id": s["session_id"], "line": "vim x" if i == 0 else "ls", "allowed": i != 0,
            "commands": ["vim" if i == 0 else "ls"], "reason": "'vim' isn't allowed" if i == 0 else None,
            "exit_code": None if i == 0 else 0})
    key = deps.LOCAL_TOKEN_FILE.read_text().strip()
    r = client.get("/api/reports/session?exercise_id=ex3-mcalc", headers={"X-VeriExam-Local-Token": key})
    rep = r.json()
    assert rep["found"] and rep["students"] >= 3
    assert rep["operating_systems"].get("windows", 0) >= 3
    assert rep["terminal"]["blocked"] >= 1 and "ls" in rep["terminal"]["top_programs"]
    assert rep["per_student"][0]["student"] == "S01"
    for n in names + [f"REP-S{i}" for i in range(3)]:
        assert n not in r.text
