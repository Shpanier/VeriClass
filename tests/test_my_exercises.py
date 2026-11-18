"""What a student may open now (GET /api/my-exercises, backend/courses.py
choices()): the student chat's exercise menu. The list is read when asked, not
kept from the sign-in, and the server says which exercise opens by itself."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-menu-tests")

import pytest
from fastapi.testclient import TestClient

from backend import courses, db
from backend.main import app

TEACHER = "MYX-T"
STUDENT = "MYX-S"
LONER = "MYX-NONE"  # in no course


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            for name, code, role in (("Myx T", TEACHER, "teacher"), ("Myx S", STUDENT, "student"),
                                     ("Myx None", LONER, "student")):
                c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES (?, ?, ?)",
                          (name, code, role))
        h = _auth(tc, TEACHER)
        tc.post("/api/courses", json={"course_id": "myx-a", "name": "Course A"}, headers=h)
        _offer(tc, h, ["ex3-mcalc", "ex4-mstat"])
        yield tc


def _auth(tc, code):
    r = tc.post("/api/login", json={"code": code, "password": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _uid(code):
    with db.conn() as c:
        return c.execute("SELECT id FROM users WHERE login_code = ?", (code,)).fetchone()["id"]


def _offer(tc, h, exercise_ids):
    r = tc.put("/api/courses/myx-a", headers=h, json={
        "name": "Course A", "exercises": exercise_ids, "default_exercise": "ex4-mstat",
        "members": [_uid(STUDENT)]})
    assert r.status_code == 200, r.text


def _mine(tc, h):
    r = tc.get("/api/my-exercises", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_list_is_read_now_not_kept_from_the_sign_in(client):
    student = _auth(client, STUDENT)  # signed in while the course offers two exercises
    _offer(client, _auth(client, TEACHER), ["ex3-mcalc", "ex4-mstat", "ex5-pycalc"])
    mine = _mine(client, student)
    [course] = mine["courses"]
    assert [e["exercise_id"] for e in course["exercises"]] == ["ex3-mcalc", "ex4-mstat", "ex5-pycalc"]
    assert all(e["last_active_at"] is None for e in course["exercises"])
    # Nothing opened yet: the course's default.
    assert mine["suggested"] == {"course_id": "myx-a", "exercise_id": "ex4-mstat"}


def test_the_exercise_just_worked_on_opens_again_then_todays_meeting(client):
    student = _auth(client, STUDENT)
    s = client.post("/api/sessions", json={"course_id": "myx-a", "exercise_id": "ex3-mcalc"}, headers=student)
    assert s.status_code == 200, s.text
    mine = _mine(client, student)
    assert mine["suggested"] == {"course_id": "myx-a", "exercise_id": "ex3-mcalc"}
    worked = {e["exercise_id"]: e["last_active_at"] for e in mine["courses"][0]["exercises"]}
    assert worked["ex3-mcalc"] and worked["ex4-mstat"] is None

    # Hours later it is the course's default again ...
    with db.conn() as c:
        c.execute("UPDATE sessions SET last_active_at = datetime('now', ?) WHERE user_id = ?",
                  (f"-{courses.KEEP_LAST_HOURS + 1} hours", _uid(STUDENT)))
    assert _mine(client, student)["suggested"]["exercise_id"] == "ex4-mstat"
    # ... or, on a meeting day, the meeting's exercise.
    courses.add_meeting("myx-a", courses._today(), "ex5-pycalc")
    assert _mine(client, student)["suggested"] == {"course_id": "myx-a", "exercise_id": "ex5-pycalc"}


def test_an_exercise_no_longer_offered_is_not_suggested(client):
    h = _auth(client, TEACHER)
    student = _auth(client, STUDENT)
    client.post("/api/sessions", json={"course_id": "myx-a", "exercise_id": "ex3-mcalc"}, headers=student)
    _offer(client, h, ["ex4-mstat", "ex5-pycalc"])
    mine = _mine(client, student)
    assert "ex3-mcalc" not in [e["exercise_id"] for e in mine["courses"][0]["exercises"]]
    assert mine["suggested"]["exercise_id"] != "ex3-mcalc"
    # Opening it from a menu read before the change is refused.
    r = client.post("/api/sessions", json={"course_id": "myx-a", "exercise_id": "ex3-mcalc"}, headers=student)
    assert r.status_code == 403


def test_no_course_means_no_menu(client):
    assert _mine(client, _auth(client, LONER)) == {"courses": [], "suggested": None}


def test_it_needs_a_sign_in(client):
    assert client.get("/api/my-exercises").status_code == 401
    assert client.get("/api/my-exercises", headers={"Authorization": "Bearer nope"}).status_code == 401
