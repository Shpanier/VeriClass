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

# A schema-valid exercise payload, reused by the gating table and the happy path.
def _sample_exercise(exercise_id="auth-probe-ex"):
    return {
        "exercise_id": exercise_id,
        "title_en": "Auth Probe Exercise",
        "title_he": "תרגיל בדיקה",
        "default_mode": "mentor",
        "brief_md": "Do the thing.",
        "variants": [
            {
                "id": "V-1",
                "params": {"max_number": 100},
                "test_inputs": [{"input": "1+1", "expected_output": "2"}],
            },
            {
                "id": "V-2",
                "params": {"max_number": 200},
                "test_inputs": [{"input": "2+2", "expected_output": "4"}],
            },
        ],
    }


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
    ("get", "/api/exercises", None),
    ("get", "/api/exercises/ex3-mcalc", None),
    ("post", "/api/exercises", _sample_exercise("gating-probe-ex")),
    ("put", "/api/exercises/ex3-mcalc", _sample_exercise("ex3-mcalc")),
    ("post", "/api/exercises/active", {"exercise_id": "gating-probe-ex"}),
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


# --- exercise authoring (teacher creates + activates from the console) ------
# These run last so mutating the active exercise doesn't disturb the tests above.

def test_create_exercise_validation(client, teacher):
    # Missing a required field -> 422 (Pydantic).
    bad = _sample_exercise("no-brief-ex")
    del bad["brief_md"]
    assert client.post("/api/exercises", json=bad, headers=_hdr(teacher)).status_code == 422
    # Schema-valid but semantically wrong default_mode -> 400 (_validate).
    bad = _sample_exercise("bad-mode-ex")
    bad["default_mode"] = "wizard"
    assert client.post("/api/exercises", json=bad, headers=_hdr(teacher)).status_code == 400
    # An id that isn't a safe slug -> 400.
    bad = _sample_exercise("Bad_ID")
    assert client.post("/api/exercises", json=bad, headers=_hdr(teacher)).status_code == 400
    # Duplicate variant ids -> 400.
    bad = _sample_exercise("dup-variant-ex")
    bad["variants"][1]["id"] = bad["variants"][0]["id"]
    assert client.post("/api/exercises", json=bad, headers=_hdr(teacher)).status_code == 400


def test_exercise_authoring_flow(client, teacher, bob):
    ex_id = "console-authored-ex"
    payload = _sample_exercise(ex_id)

    # Create -> 200 and appears in the list marked source=console.
    r = client.post("/api/exercises", json=payload, headers=_hdr(teacher))
    assert r.status_code == 200, r.text
    assert r.json()["exercise_id"] == ex_id

    listing = client.get("/api/exercises", headers=_hdr(teacher)).json()
    mine = next(e for e in listing if e["exercise_id"] == ex_id)
    assert mine["source"] == "console"
    assert mine["variant_count"] == 2

    # Re-creating the same id -> 409.
    assert client.post("/api/exercises", json=payload, headers=_hdr(teacher)).status_code == 409

    # Activate it -> the active exercise now reflects the new one.
    r = client.post("/api/exercises/active", json={"exercise_id": ex_id}, headers=_hdr(teacher))
    assert r.status_code == 200
    active = client.get("/api/exercises/active", headers=_hdr(teacher)).json()
    assert active["exercise_id"] == ex_id

    # Activating an unknown exercise -> 404.
    assert client.post(
        "/api/exercises/active", json={"exercise_id": "does-not-exist"}, headers=_hdr(teacher)
    ).status_code == 404

    # A student starting a session is assigned a variant of the new exercise —
    # no server restart involved.
    r = client.post("/api/sessions", json={}, headers=_hdr(bob))
    assert r.status_code == 200, r.text
    sess = r.json()
    assert sess["exercise_id"] == ex_id
    assert sess["variant"] in {"V-1", "V-2"}


# --- edit + duplicate (built-in AND console) --------------------------------
# Ordered: read/duplicate the pristine built-in first, THEN mutate it.

def test_get_full_exercise(client, teacher):
    r = client.get("/api/exercises/ex3-mcalc", headers=_hdr(teacher))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exercise_id"] == "ex3-mcalc"
    assert len(body["variants"]) == 8      # the full answer key, teacher-only
    assert body["source"] == "yaml"
    assert body["edited"] is False
    # The bundled YAML ships param_labels connecting each param to the exercise.
    assert len(body["param_labels"]) == 3
    assert any(pl["key"] == "max_number" for pl in body["param_labels"])
    assert client.get("/api/exercises/no-such-ex", headers=_hdr(teacher)).status_code == 404


def test_duplicate_builtin_via_create(client, teacher):
    # "Duplicate" = fetch the full exercise, POST it under a new id.
    src = client.get("/api/exercises/ex3-mcalc", headers=_hdr(teacher)).json()
    dup = {**src, "exercise_id": "ex3-mcalc-copy"}
    r = client.post("/api/exercises", json=dup, headers=_hdr(teacher))
    assert r.status_code == 200, r.text
    assert r.json()["exercise_id"] == "ex3-mcalc-copy"
    assert r.json()["source"] == "console"          # a copy is a console exercise
    assert r.json()["variant_count"] == 8
    # Same id again -> 409.
    assert client.post("/api/exercises", json=dup, headers=_hdr(teacher)).status_code == 409


def test_edit_builtin_overrides_yaml(client, teacher):
    payload = _sample_exercise("ex3-mcalc")     # id must match the path
    payload["title_en"] = "Edited mcalc"
    payload["variants"] = [payload["variants"][0]]   # collapse to a single variant
    r = client.put("/api/exercises/ex3-mcalc", json=payload, headers=_hdr(teacher))
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["source"] == "yaml"        # still a built-in...
    assert s["edited"] is True          # ...but now flagged as overridden
    assert s["variant_count"] == 1
    full = client.get("/api/exercises/ex3-mcalc", headers=_hdr(teacher)).json()
    assert full["title_en"] == "Edited mcalc"
    assert full["edited"] is True


def test_update_unknown_and_invalid(client, teacher):
    # Unknown id -> 404.
    assert client.put(
        "/api/exercises/ghost", json=_sample_exercise("ghost"), headers=_hdr(teacher)
    ).status_code == 404
    # Known id but invalid body -> 400.
    bad = _sample_exercise("ex3-mcalc")
    bad["default_mode"] = "wizard"
    assert client.put("/api/exercises/ex3-mcalc", json=bad, headers=_hdr(teacher)).status_code == 400


# --- readable param labels + variant_params surfacing ----------------------

def test_param_labels_roundtrip_and_variant_params(client, teacher):
    # Create with param_labels -> they round-trip on GET full.
    payload = _sample_exercise("labeled-ex")
    payload["param_labels"] = [
        {"key": "max_number", "label": "Maximum result", "note": "too big = out of range"},
        {"key": "operators", "label": "Operators"},
    ]
    assert client.post("/api/exercises", json=payload, headers=_hdr(teacher)).status_code == 200
    full = client.get("/api/exercises/labeled-ex", headers=_hdr(teacher)).json()
    assert full["param_labels"][0]["label"] == "Maximum result"
    assert full["param_labels"][0]["note"] == "too big = out of range"

    # Active-exercise response carries param_labels too.
    assert client.post(
        "/api/exercises/active", json={"exercise_id": "labeled-ex"}, headers=_hdr(teacher)
    ).status_code == 200
    active = client.get("/api/exercises/active", headers=_hdr(teacher)).json()
    assert any(pl["key"] == "max_number" for pl in active["param_labels"])

    # /api/students rows expose each session's raw variant_params for rendering.
    rows = client.get("/api/students", headers=_hdr(teacher)).json()
    assert all("variant_params" in r for r in rows)


def test_brief_at_refs_substituted_for_student(client, teacher, bob):
    # An exercise whose brief references a param with @key.
    payload = _sample_exercise("atref-ex")
    payload["brief_md"] = "Results must not exceed @max_number for this variant."
    payload["param_labels"] = [{"key": "max_number", "label": "Maximum result"}]
    payload["variants"] = [
        {"id": "V-1", "params": {"max_number": 42}, "test_inputs": [{"input": "1", "expected_output": "1"}]}
    ]
    assert client.post("/api/exercises", json=payload, headers=_hdr(teacher)).status_code == 200
    assert client.post(
        "/api/exercises/active", json={"exercise_id": "atref-ex"}, headers=_hdr(teacher)
    ).status_code == 200

    # The teacher (authoring view) sees the RAW brief with the @-reference.
    raw = client.get("/api/exercises/active", headers=_hdr(teacher)).json()
    assert "@max_number" in raw["brief_md"]

    # A student assigned this variant sees the reference expanded to "Label: value".
    sess = client.post("/api/sessions", json={}, headers=_hdr(bob)).json()
    assert sess["exercise_id"] == "atref-ex"
    seen = client.get(
        f"/api/exercises/active?variant={sess['variant']}", headers=_hdr(bob)
    ).json()
    assert "@max_number" not in seen["brief_md"]
    assert "Maximum result: 42" in seen["brief_md"]
