"""Student lists from CSV (backend/roster.py): Hebrew and Moodle headers, Excel's
Hebrew encoding, preview, import, re-import, and the API."""
import base64
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-roster-tests")

import pytest
from fastapi.testclient import TestClient

from backend import courses, db, roster
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES ('Roster T', 'ROS-T', 'teacher')")
        for cid, name in (("ros-dl", "DL"), ("ros-os", "OS")):
            if courses.get(cid) is None:
                courses.create(cid, name)
        yield tc


def _th(tc):
    tok = tc.post("/api/login", json={"code": "ROS-T", "password": "ROS-T"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_parse_hebrew_headers_and_semicolons():
    rows, cols = roster.parse("שם מלא;דוא״ל;ת.ז;קבוצה\nישראל ישראלי;Israel@Example.ac.il;012345678;א\n")
    assert rows == [{"line": 2, "name": "ישראל ישראלי", "email": "israel@example.ac.il",
                     "student_id": "012345678", "group": "א"}]
    assert cols == ["email", "group", "name", "student_id"]


def test_parse_moodle_export():
    rows, _ = roster.parse("First name,Surname,Email address\nDana,Levi,dana@jce.ac.il\n")
    assert rows[0]["name"] == "Dana Levi" and rows[0]["email"] == "dana@jce.ac.il"


def test_parse_names_only_and_excel_hebrew_encoding():
    data = "יוסי כהן\nשירה לוי\n".encode("cp1255")
    rows, _ = roster.parse(roster.decode(data))
    assert [r["name"] for r in rows] == ["יוסי כהן", "שירה לוי"]


def test_preview_then_import_then_reimport(client):
    th = _th(client)
    csv_text = ("name,email,course\n"
                "Avi One,avi@x.ac.il,ros-dl\n"
                "Bea Two,bea@x.ac.il,\n"
                "Gil Three,gil@x.ac.il,nope\n"
                "Avi One,avi@x.ac.il,ros-dl\n"
                ",nobody@x.ac.il,\n")
    body = {"content_base64": base64.b64encode(csv_text.encode()).decode(), "course_id": "ros-os"}
    r = client.post("/api/students/import", json={**body, "dry_run": True}, headers=th)
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert [x.get("status") or x.get("error") for x in rows] == [
        "new", "new", "unknown course 'nope'", "appears twice in the file", "no name"]
    assert rows[1]["course"] == "ros-os"  # the file's empty course falls back to the chosen one
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM users WHERE email = 'avi@x.ac.il'").fetchone()["n"] == 0

    r = client.post("/api/students/import", json={**body, "dry_run": False}, headers=th)
    out = r.json()
    assert out["counts"] == {"new": 2, "existing": 0, "errors": 3}
    assert "Avi One" in out["codes_csv"] and out["rows"][0]["code"]
    header, first = out["codes_csv"].splitlines()[:2]
    assert header == "name,username,password,email,course,group"
    code = out["rows"][0]["code"]
    assert first.split(",")[1:3] == [code, code]  # the password is the username until it is set
    with db.conn() as c:
        m = {r["course_id"] for r in c.execute(
            "SELECT course_id FROM course_members WHERE user_id = ?", (out["rows"][0]["user_id"],))}
    assert m == {"ros-dl"}

    # Again: the same people are recognized by email, no new accounts.
    again = client.post("/api/students/import", json={**body, "dry_run": False}, headers=th).json()
    assert again["counts"]["new"] == 0 and again["counts"]["existing"] == 2
    assert again["rows"][0]["code"] == out["rows"][0]["code"]


def test_same_name_different_person(client):
    th = _th(client)
    first = "name,email\nNoa Same,noa1@x.ac.il\n"
    second = "name,email\nNoa Same,noa2@x.ac.il\n"
    for text in (first, second):
        r = client.post("/api/students/import", headers=th, json={
            "content_base64": base64.b64encode(text.encode()).decode(), "dry_run": False})
        assert r.json()["counts"]["new"] == 1, r.text
    with db.conn() as c:
        names = sorted(r["username"] for r in c.execute("SELECT username FROM users WHERE username LIKE 'Noa Same%'"))
    assert names == ["Noa Same", "Noa Same (noa2)"]


def test_import_needs_a_teacher_and_a_real_course(client):
    th = _th(client)
    data = base64.b64encode(b"name\nX\n").decode()
    assert client.post("/api/students/import", json={"content_base64": data}).status_code == 401
    assert client.post("/api/students/import", json={"content_base64": data, "course_id": "missing"},
                       headers=th).status_code == 404
    assert client.post("/api/students/import", json={"content_base64": "not base64!"}, headers=th).status_code == 400


def test_a_name_only_row_is_the_student_with_that_name(client):
    """A list of names after a list with emails: the same students, not "Name ()" copies."""
    th = _th(client)
    for text in ("name,email\nRon Late,ron@x.ac.il\n", "Ron Late\n"):
        r = client.post("/api/students/import", headers=th, json={
            "content_base64": base64.b64encode(text.encode()).decode(), "dry_run": False})
        assert r.status_code == 200, r.text
    assert r.json()["counts"] == {"new": 0, "existing": 1, "errors": 0}
    with db.conn() as c:
        assert [x["username"] for x in c.execute("SELECT username FROM users WHERE username LIKE 'Ron Late%'")] == [
            "Ron Late"]


def test_add_one_student(client):
    th = _th(client)
    r = client.post("/api/students", headers=th, json={
        "name": "  Tal   Late ", "student_id": "123456782", "email": "Tal@X.ac.il", "group": "B", "course_id": "ros-dl"})
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["status"] == "new" and row["name"] == "Tal Late" and row["course"] == "ros-dl"
    assert row["code"] and row["password_set"] is False
    with db.conn() as c:
        u = c.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        assert (u["username"], u["login_code"], u["email"], u["student_id"], u["group_name"]) == (
            "Tal Late", row["code"], "tal@x.ac.il", "123456782", "B")
        assert c.execute("SELECT 1 FROM course_members WHERE course_id = 'ros-dl' AND user_id = ?",
                         (row["user_id"],)).fetchone()
    # The student signs in with the code as username and password.
    login = client.post("/api/login", json={"code": row["code"], "password": row["code"]})
    assert login.status_code == 200
    as_student = {"Authorization": f"Bearer {login.json()['token']}"}

    # Again, by ID number, into another course: the same account, now in both courses.
    again = client.post("/api/students", headers=th, json={
        "name": "Tal Late", "student_id": "123456782", "course_id": "ros-os"}).json()
    assert again["status"] == "existing" and again["code"] == row["code"] and again["user_id"] == row["user_id"]
    with db.conn() as c:
        assert {x["course_id"] for x in c.execute(
            "SELECT course_id FROM course_members WHERE user_id = ?", (row["user_id"],))} == {"ros-dl", "ros-os"}
        c.execute("UPDATE users SET password_hash = 'x' WHERE id = ?", (row["user_id"],))
    assert client.post("/api/students", headers=th, json={"name": "Tal Late"}).json()["password_set"] is True

    # Same name, another ID: another person.
    other = client.post("/api/students", headers=th, json={"name": "Tal Late", "student_id": "987654321"}).json()
    assert other["status"] == "new" and other["user_id"] != row["user_id"]
    assert other["username"] == "Tal Late (987654321)"

    assert client.post("/api/students", headers=th, json={"name": "   "}).status_code == 422
    assert client.post("/api/students", headers=th, json={"name": "X Y", "email": "not-an-email"}).status_code == 422
    assert client.post("/api/students", headers=th, json={"name": "X Y", "course_id": "missing"}).status_code == 404
    assert client.post("/api/students", json={"name": "X Y"}).status_code == 401
    assert client.post("/api/students", headers=as_student, json={"name": "X Y"}).status_code == 403
