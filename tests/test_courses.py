"""Courses and passwords: login needs a password (the login code until the
teacher sets one), and after login a student opens one of the exercises their
courses offer."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-course-tests")

import pytest
from fastapi.testclient import TestClient

from backend import db, exercises, passwords
from backend.main import app

TEACHER = "CRS-TEACH"
ONE = "CRS-ONE"      # one course, one exercise
TWO = "CRS-TWO"      # two courses
NONE = "CRS-NONE"    # no course


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            for name, code, role in (("Crs Teacher", TEACHER, "teacher"), ("Crs One", ONE, "student"),
                                     ("Crs Two", TWO, "student"), ("Crs None", NONE, "student")):
                c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES (?, ?, ?)",
                          (name, code, role))
        yield tc


def _login(tc, code, password=None):
    return tc.post("/api/login", json={"code": code, "password": code if password is None else password})


def _auth(tc, code, password=None):
    r = _login(tc, code, password)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _uid(code):
    with db.conn() as c:
        return c.execute("SELECT id FROM users WHERE login_code = ?", (code,)).fetchone()["id"]


# --- passwords ------------------------------------------------------------------


def test_login_needs_a_password(client):
    r = client.post("/api/login", json={"code": ONE})  # what plugin 0.3.0 sends
    assert r.status_code == 401
    assert "Update the VeriExam plugin" in r.json()["detail"]


def test_default_password_is_the_login_code_in_any_case(client):
    assert _login(client, ONE, ONE.lower()).status_code == 200
    assert _login(client, ONE.lower(), ONE).status_code == 200


def test_wrong_password_and_unknown_code_look_the_same(client):
    wrong = _login(client, ONE, "nope-nope")
    unknown = _login(client, "CRS-NOBODY", "CRS-NOBODY")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Wrong username or password."}


def test_teacher_sets_and_resets_a_password(client):
    h = _auth(client, TEACHER)
    uid = _uid(NONE)
    assert client.post(f"/api/users/{uid}/password", json={"password": "abc"}, headers=h).status_code == 400
    assert client.post(f"/api/users/{uid}/password", json={"password": "Secret-77"}, headers=h).json() == {
        "ok": True, "custom_password": True}
    assert _login(client, NONE).status_code == 401              # the code no longer works
    assert _login(client, NONE, "secret-77").status_code == 401  # a set password is case-sensitive
    assert _login(client, NONE, "Secret-77").status_code == 200
    with db.conn() as c:
        stored = c.execute("SELECT password_hash FROM users WHERE id = ?", (uid,)).fetchone()[0]
    assert stored.startswith("pbkdf2_sha256$") and "Secret-77" not in stored
    users = {u["login_code"]: u for u in client.get("/api/users", headers=h).json()}
    assert users[NONE.lower()]["custom_password"] is True
    client.post(f"/api/users/{uid}/password", json={"password": None}, headers=h)
    assert _login(client, NONE).status_code == 200


def test_students_cannot_set_passwords(client):
    h = _auth(client, ONE)
    assert client.post(f"/api/users/{_uid(ONE)}/password", json={"password": "Secret-77"},
                       headers=h).status_code == 403


def test_verify_rejects_a_damaged_hash():
    assert not passwords.verify("x", "garbage", "CODE")
    assert passwords.verify("Pa55word", passwords.hash_password("Pa55word"), "CODE")


# --- courses -----------------------------------------------------------------------


def test_course_editing_validates(client):
    h = _auth(client, TEACHER)
    assert client.post("/api/courses", json={"course_id": "Bad Id", "name": "x"}, headers=h).status_code == 400
    assert client.post("/api/courses", json={"course_id": "crs-devops", "name": "DevOps"},
                       headers=h).status_code == 201
    assert client.post("/api/courses", json={"course_id": "crs-devops", "name": "again"},
                       headers=h).status_code == 409
    bad_ex = {"name": "DevOps", "exercises": ["no-such-ex"], "default_exercise": "no-such-ex"}
    assert client.put("/api/courses/crs-devops", json=bad_ex, headers=h).status_code == 400
    bad_default = {"name": "DevOps", "exercises": ["ex3-mcalc"], "default_exercise": "ex5-pycalc"}
    assert client.put("/api/courses/crs-devops", json=bad_default, headers=h).status_code == 400
    assert client.get("/api/courses", headers=_auth(client, ONE)).status_code == 403


def _setup_courses(client):
    h = _auth(client, TEACHER)
    client.post("/api/courses", json={"course_id": "crs-devops", "name": "DevOps"}, headers=h)
    client.post("/api/courses", json={"course_id": "crs-dl", "name": "Deep Learning"}, headers=h)
    assert client.put("/api/courses/crs-devops", headers=h, json={
        "name": "DevOps", "exercises": ["ex3-mcalc"], "default_exercise": "ex3-mcalc",
        "members": [_uid(ONE), _uid(TWO)]}).status_code == 200
    assert client.put("/api/courses/crs-dl", headers=h, json={
        "name": "Deep Learning", "exercises": ["ex4-mstat", "ex5-pycalc"], "default_exercise": "ex5-pycalc",
        "members": [_uid(TWO)]}).status_code == 200
    return h


def test_login_lists_the_students_courses(client):
    _setup_courses(client)
    one = _login(client, ONE).json()["courses"]
    assert [(c["course_id"], c["default_exercise"], [e["exercise_id"] for e in c["exercises"]])
            for c in one] == [("crs-devops", "ex3-mcalc", ["ex3-mcalc"])]
    two = {c["course_id"]: c for c in _login(client, TWO).json()["courses"]}
    assert set(two) == {"crs-devops", "crs-dl"}
    assert [e["exercise_id"] for e in two["crs-dl"]["exercises"]] == ["ex4-mstat", "ex5-pycalc"]
    assert two["crs-dl"]["default_exercise"] == "ex5-pycalc"
    assert _login(client, NONE).json()["courses"] == []


def test_one_course_needs_no_choice(client):
    _setup_courses(client)
    h = _auth(client, ONE)
    s = client.post("/api/sessions", json={}, headers=h).json()  # an older client sends nothing
    assert (s["course_id"], s["exercise_id"]) == ("crs-devops", "ex3-mcalc")
    ex = client.get(f"/api/exercises/active?variant={s['variant']}&session_id={s['session_id']}", headers=h)
    assert ex.json()["exercise_id"] == "ex3-mcalc"


def test_several_courses_need_a_choice(client):
    _setup_courses(client)
    h = _auth(client, TWO)
    r = client.post("/api/sessions", json={}, headers=h)
    assert r.status_code == 400 and "Choose a course" in r.json()["detail"]
    s = client.post("/api/sessions", json={"course_id": "crs-dl"}, headers=h).json()
    assert s["exercise_id"] == "ex5-pycalc"  # the course's default
    s2 = client.post("/api/sessions", json={"course_id": "crs-dl", "exercise_id": "ex4-mstat"}, headers=h).json()
    assert s2["exercise_id"] == "ex4-mstat"
    # Without session_id (older clients) the student gets their latest session's exercise.
    assert client.get(f"/api/exercises/active?variant={s2['variant']}", headers=h).json()["exercise_id"] == "ex4-mstat"
    other = client.post("/api/sessions", json={"course_id": "crs-dl", "exercise_id": "ex3-mcalc"}, headers=h)
    assert other.status_code == 403
    one = _auth(client, ONE)
    assert client.post("/api/sessions", json={"course_id": "crs-dl"}, headers=one).status_code == 403


def test_another_students_session_is_refused(client):
    _setup_courses(client)
    s = client.post("/api/sessions", json={}, headers=_auth(client, ONE)).json()
    r = client.get(f"/api/exercises/active?variant={s['variant']}&session_id={s['session_id']}",
                   headers=_auth(client, TWO))
    assert r.status_code == 403


def test_no_course_means_the_global_active_exercise(client):
    h = _auth(client, NONE)
    s = client.post("/api/sessions", json={}, headers=h).json()
    assert s["course_id"] is None and s["exercise_id"] == exercises.active_id()
    other = next(e["exercise_id"] for e in exercises.all() if e["exercise_id"] != exercises.active_id())
    assert client.post("/api/sessions", json={"exercise_id": other}, headers=h).status_code == 403


def test_disabling_the_active_exercise(client):
    teacher = _auth(client, TEACHER)
    active = exercises.active_id()
    try:
        assert client.delete("/api/exercises/active", headers=teacher).json() == {"exercise_id": None}
        assert not any(e["is_active"] for e in client.get("/api/exercises", headers=teacher).json())
        assert client.get("/api/exercises/active", headers=teacher).status_code == 404
        # A student outside every course gets no exercise; course students are unaffected.
        r = client.post("/api/sessions", json={}, headers=_auth(client, NONE))
        assert r.status_code == 403 and "No exercise is open" in r.json()["detail"]
        _setup_courses(client)
        assert client.post("/api/sessions", json={}, headers=_auth(client, ONE)).status_code == 200
    finally:
        client.post("/api/exercises/active", json={"exercise_id": active}, headers=teacher)
    assert exercises.active_id() == active


def test_client_config_follows_the_chosen_exercise(client):
    assert client.get("/api/client-config?exercise_id=ex5-pycalc").json()["scaffold_filename"] == "pycalc.py"


def test_deleting_a_course_keeps_the_students(client):
    h = _setup_courses(client)
    assert client.delete("/api/courses/crs-devops", headers=h).json() == {"ok": True}
    assert _login(client, ONE).json()["courses"] == []
    assert [c["course_id"] for c in _login(client, TWO).json()["courses"]] == ["crs-dl"]
    users = {u["login_code"]: u for u in client.get("/api/users", headers=h).json()}
    assert users[TWO.lower()]["courses"] == ["crs-dl"]
