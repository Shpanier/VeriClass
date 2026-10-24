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
