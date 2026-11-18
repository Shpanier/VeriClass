"""Each exercise's dates in the dashboard's list (backend/exercises.py, dates()):
when it came to this server and when it last changed, which the Exercises tab
sorts and filters by."""
import os
import re
import tempfile
import time

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-date-tests")

import pytest
from fastapi.testclient import TestClient

from backend import db, exercises, packages
from backend.main import app

TEACHER = "DATES-T"
PKG = "pkg-demo"
ISO = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES ('Dates T', ?, 'teacher')",
                      (TEACHER,))
        yield tc


def _th(tc):
    tok = tc.post("/api/login", json={"code": TEACHER, "password": TEACHER}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _listed(tc, h):
    return {e["exercise_id"]: e for e in tc.get("/api/exercises", headers=h).json()}


def test_packages_have_both_dates_and_samples_none(client):
    listed = _listed(client, _th(client))
    for e in listed.values():
        if e["source"] == "yaml":
            # A bundled sample's file time is only when VeriClass was installed.
            assert e["added_at"] is None and e["changed_at"] is None, e
        else:
            assert ISO.fullmatch(e["added_at"]) and ISO.fullmatch(e["changed_at"]), e
            assert e["added_at"] <= e["changed_at"], e
    assert listed[PKG]["source"] == "package" and listed["ex3-mcalc"]["source"] == "yaml"


def test_a_package_changed_when_its_newest_file_did(client):
    h = _th(client)
    folder = packages.exercises_dir() / PKG
    month_ago = time.time() - 30 * 86400
    for f in folder.rglob("*"):
        if f.is_file():
            os.utime(f, (month_ago, month_ago))
    before = _listed(client, h)[PKG]
    assert before["changed_at"] == exercises._iso(month_ago)
    # A folder copied after its files were written is no newer than them.
    assert before["added_at"] == before["changed_at"]

    os.utime(folder / "exercise.yaml")  # edited now
    after = _listed(client, h)[PKG]
    assert after["changed_at"] > before["changed_at"]
    assert after["added_at"] <= after["changed_at"]
    # Hidden files (macOS's .DS_Store, kept old versions) don't count.
    (folder / ".DS_Store").write_bytes(b"")
    os.utime(folder / ".DS_Store", (time.time() + 86400,) * 2)
    assert _listed(client, h)[PKG]["changed_at"] == after["changed_at"]
    (folder / ".DS_Store").unlink()


def test_a_dashboard_exercise_has_its_database_times(client):
    h = _th(client)
    payload = {"exercise_id": "dates-console", "title_en": "Dates", "default_mode": "mentor",
               "brief_md": "b", "variants": [{"id": "v1"}]}
    assert client.post("/api/exercises", json=payload, headers=h).status_code in (200, 201)
    try:
        with db.conn() as c:
            c.execute("UPDATE exercises SET created_at = '2026-01-02 03:04:05', updated_at = NULL "
                      "WHERE exercise_id = 'dates-console'")
        e = _listed(client, h)["dates-console"]
        assert e["added_at"] == e["changed_at"] == "2026-01-02T03:04:05Z"

        r = client.put("/api/exercises/dates-console", json={**payload, "title_en": "Dates, again"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["changed_at"] > "2026-01-02T03:04:05Z"
        e = _listed(client, h)["dates-console"]
        assert e["added_at"] == "2026-01-02T03:04:05Z" and e["changed_at"] > e["added_at"]
    finally:
        with db.conn() as c:
            c.execute("DELETE FROM exercises WHERE exercise_id = 'dates-console'")
        exercises.reload_all()


def test_an_edited_sample_changed_when_it_was_edited(client):
    h = _th(client)
    full = client.get("/api/exercises/ex4-mstat", headers=h).json()
    payload = {k: full[k] for k in ("exercise_id", "title_en", "title_he", "default_mode", "brief_md", "variants",
                                    "welcome_suggestions", "required_error_strings", "param_labels")}
    try:
        assert client.put("/api/exercises/ex4-mstat", json={**payload, "title_en": "mstat, edited"},
                          headers=h).status_code == 200
        e = _listed(client, h)["ex4-mstat"]
        assert e["added_at"] is None and ISO.fullmatch(e["changed_at"])
    finally:
        with db.conn() as c:
            c.execute("DELETE FROM exercises WHERE exercise_id = 'ex4-mstat'")
        exercises.reload_all()


def test_the_reloaded_list_has_the_dates_too(client):
    r = client.post("/api/exercises/reload", headers=_th(client)).json()
    assert all(ISO.fullmatch(e["added_at"]) for e in r["exercises"] if e["source"] != "yaml")
