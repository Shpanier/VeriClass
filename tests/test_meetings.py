"""Course meetings: today's meeting opens its exercise, attendance per meeting."""
import datetime
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-meeting-tests")

import pytest
from fastapi.testclient import TestClient

from backend import courses, db
from backend.main import app

TODAY = datetime.date.today().isoformat()


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES ('Meet T', 'MEET-T', 'teacher')")
        if courses.get("meet-c") is None:
            courses.create("meet-c", "Meetings course")
        yield tc


def _login(tc, code, role="student"):
    with db.conn() as c:
        c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES (?, ?, ?)", (code, code, role))
    r = tc.post("/api/login", json={"code": code, "password": code})
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()


def test_today_meeting_opens_its_exercise_and_counts_attendance(client):
    th, _ = _login(client, "MEET-T", "teacher")
    # The course offers two exercises; a meeting today picks one of them.
    c = courses.get("meet-c")
    client.put("/api/courses/meet-c", headers=th, json={
        "name": c["name"], "exercises": ["ex3-mcalc", "ex5-pycalc"], "default_exercise": "ex3-mcalc", "members": []})
    r = client.post("/api/courses/meet-c/meetings", headers=th,
                    json={"date": TODAY, "exercise_id": "ex5-pycalc", "title": "Meeting 3"})
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    assert r.json()["exercise_title"]
    assert client.post("/api/courses/meet-c/meetings", headers=th,
                       json={"date": "2026-02-30", "exercise_id": "ex5-pycalc"}).status_code == 400

    h1, login1 = _login(client, "MEET-S1")
    h2, login2 = _login(client, "MEET-S2")
    with db.conn() as conn:
        ids = [conn.execute("SELECT id FROM users WHERE login_code = ?", (k,)).fetchone()["id"]
               for k in ("MEET-S1", "MEET-S2")]
    courses.add_members("meet-c", ids)
    h1, login1 = _login(client, "MEET-S1")  # log in again to see the course
    course = next(x for x in login1["courses"] if x["course_id"] == "meet-c")
    assert course["today_exercise"] == "ex5-pycalc" and course["default_exercise"] == "ex5-pycalc"
    # No exercise chosen: today's meeting decides.
    s = client.post("/api/sessions", json={"course_id": "meet-c"}, headers=h1).json()
    assert s["exercise_id"] == "ex5-pycalc"

    att = client.get(f"/api/meetings/{mid}/attendance", headers=th).json()
    by = {r["username"]: r for r in att["rows"]}
    assert by["MEET-S1"]["attended"] and not by["MEET-S2"]["attended"]
    assert att["counts"] == {"members": 2, "attended": 1}
    listed = client.get("/api/courses/meet-c/meetings", headers=th).json()
    assert [(m["id"], m["attended"], m["members"]) for m in listed] == [(mid, 1, 2)]

    assert client.delete(f"/api/meetings/{mid}", headers=th).status_code == 200
    assert courses.today_exercise("meet-c") is None
