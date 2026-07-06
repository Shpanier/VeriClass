"""Authorization contract for every /api route.

This suite is the executable definition of the trust boundary:
  * no token            -> 401
  * student on a teacher route -> 403
  * a student acting on another student's session -> 403
  * a student can act on their own session

Auth is enforced in a FastAPI dependency that runs before any LLM work, so
these tests need no Gemini key and never make a network call.
"""
import os
import tempfile
from pathlib import Path

# Point the DB at a throwaway file BEFORE importing backend (backend.db freezes
# DB_PATH at import time). A dummy key keeps agent imports happy; it's unused.
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.setdefault("GEMINI_API_KEY", "unused-in-auth-tests")

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.main import app

REPO = Path(__file__).resolve().parent.parent

TEACHER_CODE = "TEACH-001"
ALICE_CODE = "STU-ALICE"
BOB_CODE = "STU-BOBBB"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as tc:  # lifespan runs init_schema + load exercises
        with db.conn() as c:
            c.execute(
                "INSERT INTO users(username, login_code, role) VALUES(?,?,?)",
                ("Teacher One", TEACHER_CODE, "teacher"),
            )
            c.execute(
                "INSERT INTO users(username, login_code, role) VALUES(?,?,?)",
                ("Alice Alpha", ALICE_CODE, "student"),
            )
            c.execute(
                "INSERT INTO users(username, login_code, role) VALUES(?,?,?)",
                ("Bob Beta", BOB_CODE, "student"),
            )
        yield tc


def _token(tc, code):
    r = tc.post("/api/login", json={"code": code})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def teacher(client):
    return _token(client, TEACHER_CODE)


@pytest.fixture(scope="module")
def alice(client):
    return _token(client, ALICE_CODE)


@pytest.fixture(scope="module")
def bob(client):
    return _token(client, BOB_CODE)


@pytest.fixture(scope="module")
def alice_session(client, alice):
    r = client.post("/api/sessions", json={}, headers=_hdr(alice))
    assert r.status_code == 200, r.text
    return r.json()  # {session_id, variant, mode, exercise_id}


# --- teacher-only endpoints: 401 without a token, 403 for a student --------

# (method, path, body) with schema-valid bodies so we isolate auth (not 422).
TEACHER_ROUTES = [
    ("get", "/api/students", None),
    ("post", "/api/mode", {"session_id": "x", "mode": "mentor"}),
    ("post", "/api/probe/suggest", {"session_id": "x"}),
    ("post", "/api/probe/send", {"session_id": "x", "bodies": ["q"]}),
    ("post", "/api/probe/override", {"probe_id": 1, "grade": 2}),
    ("get", "/api/review_mode", None),
    ("post", "/api/review_mode", {"enabled": True}),
    ("get", "/api/reviews/pending", None),
    ("post", "/api/reviews/1/select", {"chosen": "nudge"}),
    ("get", "/api/proctor/events", None),
]


def _call(tc, method, path, body, headers=None):
    kwargs = {"headers": headers} if headers else {}
    if method != "get":
        kwargs["json"] = body
    return getattr(tc, method)(path, **kwargs)


@pytest.mark.parametrize("method,path,body", TEACHER_ROUTES)
def test_teacher_route_requires_token(client, method, path, body):
    r = _call(client, method, path, body)
    assert r.status_code == 401, f"{path} gave {r.status_code}, expected 401"


@pytest.mark.parametrize("method,path,body", TEACHER_ROUTES)
def test_teacher_route_forbids_student(client, alice, method, path, body):
    r = _call(client, method, path, body, headers=_hdr(alice))
    assert r.status_code == 403, f"{path} gave {r.status_code}, expected 403"


def test_teacher_can_list_students(client, teacher):
    r = client.get("/api/students", headers=_hdr(teacher))
    assert r.status_code == 200


def test_student_messages_requires_teacher(client, alice, teacher, alice_session):
    sid = alice_session["session_id"]
    assert client.get(f"/api/students/{sid}/messages").status_code == 401
    assert client.get(f"/api/students/{sid}/messages", headers=_hdr(alice)).status_code == 403
    assert client.get(f"/api/students/{sid}/messages", headers=_hdr(teacher)).status_code == 200


# --- student endpoints: 401 without token, 403 across users, 200 for owner --

def test_probes_pending_ownership(client, alice, bob, alice_session):
    sid = alice_session["session_id"]
    assert client.get(f"/api/probes/pending/{sid}").status_code == 401
    assert client.get(f"/api/probes/pending/{sid}", headers=_hdr(bob)).status_code == 403
    assert client.get(f"/api/probes/pending/{sid}", headers=_hdr(alice)).status_code == 200


def test_proctor_heartbeat_ownership(client, alice, bob, alice_session):
    sid = alice_session["session_id"]
    body = {"session_id": sid}
    assert client.post("/api/proctor/heartbeat", json=body).status_code == 401
    assert client.post("/api/proctor/heartbeat", json=body, headers=_hdr(bob)).status_code == 403
    assert client.post("/api/proctor/heartbeat", json=body, headers=_hdr(alice)).status_code == 200


def test_proctor_event_ownership(client, alice, bob, alice_session):
    sid = alice_session["session_id"]
    body = {"session_id": sid, "kind": "focus_lost"}
    assert client.post("/api/proctor/event", json=body).status_code == 401
    assert client.post("/api/proctor/event", json=body, headers=_hdr(bob)).status_code == 403
    assert client.post("/api/proctor/event", json=body, headers=_hdr(alice)).status_code == 200


def test_ask_rejects_cross_user_session(client, bob, alice_session):
    sid = alice_session["session_id"]
    body = {"session_id": sid, "message": "hi"}
    assert client.post("/api/ask", json=body).status_code == 401
    # Bob may not post into Alice's session — rejected before any LLM call.
    assert client.post("/api/ask", json=body, headers=_hdr(bob)).status_code == 403


# --- variant answer-key gating on /exercises/active ------------------------

def test_active_exercise_requires_token(client):
    assert client.get("/api/exercises/active").status_code == 401


def test_student_needs_own_variant(client, alice, alice_session):
    variant = alice_session["variant"]
    # No variant -> 400; a variant the student wasn't assigned -> 403.
    assert client.get("/api/exercises/active", headers=_hdr(alice)).status_code == 400
    bogus = "ZZZ-not-a-real-variant"
    assert client.get(
        f"/api/exercises/active?variant={bogus}", headers=_hdr(alice)
    ).status_code == 403
    ok = client.get(f"/api/exercises/active?variant={variant}", headers=_hdr(alice))
    assert ok.status_code == 200
    # A student must never receive the full variant set (the answer key).
    assert "variants" not in ok.json()


def test_teacher_sees_all_variants(client, teacher):
    r = client.get("/api/exercises/active", headers=_hdr(teacher))
    assert r.status_code == 200
    assert "variants" in r.json()


# --- grade override validation --------------------------------------------

def test_override_validates_grade_and_probe(client, teacher):
    # Out-of-range grade -> 422.
    r = client.post("/api/probe/override", json={"probe_id": 1, "grade": 9}, headers=_hdr(teacher))
    assert r.status_code == 422
    # Valid grade but unknown probe -> 404 (no silent success).
    r = client.post("/api/probe/override", json={"probe_id": 999999, "grade": 2}, headers=_hdr(teacher))
    assert r.status_code == 404
