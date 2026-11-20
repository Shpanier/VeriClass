"""The lecturer's notifications (backend/notifications.py): every kind of thing a
student sends shows up in the feed with who and where, what still waits for the
lecturer, the `since` cursor, the settings, and "seen"."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-notification-tests")

import pytest
from fastapi.testclient import TestClient

from backend import db, exercises, notifications
from backend.main import app

_n = iter(range(1, 1000))


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        exercises.set_active("ex3-mcalc")
        with db.conn() as c:
            c.execute("INSERT OR IGNORE INTO users (username, login_code, role) "
                      "VALUES ('Notify Teacher', 'NTF-T', 'teacher')")
        yield tc


def _clean():
    with db.conn() as c:
        c.execute("DELETE FROM system_settings WHERE key LIKE 'notify_%'")
        c.execute("DELETE FROM notification_seen")
        for t in ("pending_reviews", "step_checks", "probes", "submissions", "messages"):
            c.execute(f"DELETE FROM {t}")


@pytest.fixture(autouse=True)
def fresh_settings():
    """Each test starts from the defaults and an empty feed, and leaves nothing behind."""
    _clean()
    yield
    _clean()


def _teacher(tc):
    tok = tc.post("/api/login", json={"code": "NTF-T", "password": "NTF-T"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _student(tc, name=None):
    code = f"NTF-{next(_n)}"
    with db.conn() as c:
        c.execute("INSERT INTO users (username, login_code, role) VALUES (?, ?, 'student')", (name or code, code))
    tok = tc.post("/api/login", json={"code": code, "password": code}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    r = tc.post("/api/sessions", json={"exercise_id": "ex3-mcalc"}, headers=h)
    assert r.status_code == 200, r.text
    return h, r.json()["session_id"]


def _ago(seconds: int) -> str:
    with db.conn() as c:
        return c.execute(f"SELECT datetime('now', '-{seconds} seconds') AS t").fetchone()["t"]


def _rows(sid, at=None):
    """One row of every kind for session `sid`, all at `at` (default now)."""
    at = at or _ago(0)
    with db.conn() as c:
        q = c.execute("INSERT INTO pending_reviews (session_id, question, variant_nudge, variant_normal, variant_more, "
                      "created_at) VALUES (?, 'How do I loop?', '', '', '', ?)", (sid, at)).lastrowid
        k = c.execute("INSERT INTO step_checks (session_id, step, answer, status, created_at) "
                      "VALUES (?, 2, 'my output', 'pending', ?)", (sid, at)).lastrowid
        a = c.execute("INSERT INTO probes (session_id, body, status, answer, quiz_key, quiz_step, review_status, "
                      "answered_at) VALUES (?, 'Why?', 'answered', 'Because', 'q1', 1, 'waiting', ?)",
                      (sid, at)).lastrowid
        p = c.execute("INSERT INTO probes (session_id, body, status, answer, answered_at) "
                      "VALUES (?, 'Explain x', 'answered', 'x is y', ?)", (sid, at)).lastrowid
        b = c.execute("INSERT INTO submissions (session_id, filename, source_code, created_at) "
                      "VALUES (?, 'main.py', 'print(1)', ?)", (sid, at)).lastrowid
        m = c.execute("INSERT INTO messages (session_id, role, body, mode_at_time, created_at) "
                      "VALUES (?, 'user', 'hello tutor', 'mentor', ?)", (sid, at)).lastrowid
        # The same text as the review question: the question notifies, not the chat line too.
        c.execute("INSERT INTO messages (session_id, role, body, mode_at_time, created_at) "
                  "VALUES (?, 'user', 'How do I loop?', 'mentor', ?)", (sid, at))
    return {"question": q, "step": k, "answer": a, "reply": p, "submission": b, "chat": m}


def test_teacher_only(client):
    h, _ = _student(client)
    assert client.get("/api/notifications").status_code == 401
    assert client.get("/api/notifications", headers=h).status_code == 403
    assert client.get("/api/notifications/config", headers=h).status_code == 403
    assert client.post("/api/notifications/seen", json={}, headers=h).status_code == 403


def test_every_kind_with_who_where_and_what_waits(client):
    th = _teacher(client)
    _, sid = _student(client, "Noa Notify")
    ids = _rows(sid)
    r = client.get("/api/notifications", headers=th)
    assert r.status_code == 200, r.text
    body = r.json()
    by_kind = {i["kind"]: i for i in body["items"]}
    # Chat is off by default; the rest are on.
    assert set(by_kind) == {"question", "step", "answer", "reply", "submission"}
    assert body["kinds"] == list(notifications.DEFAULT_KINDS)
    assert body["sound"] is True
    for kind, item in by_kind.items():
        assert item["key"] == f"{kind}:{ids[kind]}"
        assert item["username"] == "Noa Notify"
        assert item["exercise_id"] == "ex3-mcalc"
        assert item["session_id"] == sid
    assert by_kind["question"]["text"] == "How do I loop?"
    assert by_kind["step"]["step"] == 2 and by_kind["step"]["step_label"] == "2"
    assert by_kind["submission"]["text"] == "main.py"
    waits = {k for k, i in by_kind.items() if i["waiting"]}
    assert waits == {"question", "step", "answer"}
    assert set(body["waiting"]) == {f"{k}:{ids[k]}" for k in waits}


def test_handled_items_stop_waiting(client):
    th = _teacher(client)
    _, sid = _student(client)
    ids = _rows(sid)
    with db.conn() as c:
        c.execute("UPDATE pending_reviews SET status = 'answered' WHERE id = ?", (ids["question"],))
        c.execute("UPDATE step_checks SET status = 'approved' WHERE id = ?", (ids["step"],))
        c.execute("UPDATE probes SET review_status = 'approved' WHERE id = ?", (ids["answer"],))
    body = client.get("/api/notifications", headers=th).json()
    kinds = {i["kind"]: i for i in body["items"]}
    assert body["waiting"] == []
    # A handled question and quiz answer stay in the list; a step only notifies while it waits.
    assert kinds["question"]["waiting"] is False and kinds["answer"]["waiting"] is False
    assert "step" not in kinds


def test_since_returns_only_new_items_but_every_waiting_key(client):
    th = _teacher(client)
    _, sid = _student(client)
    old = _rows(sid, at=_ago(600))
    first = client.get("/api/notifications", headers=th).json()
    assert len(first["items"]) == 5
    new = _rows(sid)
    nxt = client.get("/api/notifications", params={"since": _ago(60)}, headers=th).json()
    assert {i["key"] for i in nxt["items"]} == {f"{k}:{new[k]}" for k in notifications.DEFAULT_KINDS}
    # The older questions still wait: their keys keep the pop-ups open.
    for k in ("question", "step", "answer"):
        assert f"{k}:{old[k]}" in nxt["waiting"]
    # Older than the window: gone.
    with db.conn() as c:
        c.execute("UPDATE pending_reviews SET created_at = datetime('now', '-13 hours')")
    body = client.get("/api/notifications", headers=th).json()
    assert not any(i["kind"] == "question" for i in body["items"])
    assert not any(k.startswith("question:") for k in body["waiting"])


def test_settings_pick_the_kinds_and_the_sound(client):
    th = _teacher(client)
    _, sid = _student(client)
    ids = _rows(sid)
    r = client.post("/api/notifications/config", json={"kinds": ["chat", "question"], "sound": False}, headers=th)
    assert r.status_code == 200, r.text
    assert r.json()["kinds"] == ["question", "chat"] and r.json()["sound"] is False
    body = client.get("/api/notifications", headers=th).json()
    assert {i["key"] for i in body["items"]} == {f"question:{ids['question']}", f"chat:{ids['chat']}"}
    assert body["sound"] is False
    assert client.post("/api/notifications/config", json={"kinds": ["nope"]}, headers=th).status_code == 422
    # Nothing at all.
    client.post("/api/notifications/config", json={"kinds": []}, headers=th)
    assert client.get("/api/notifications", headers=th).json()["items"] == []
    assert client.get("/api/notifications/config", headers=th).json()["kinds"] == []


def test_seen_marks_per_lecturer_and_never_goes_back(client):
    th = _teacher(client)
    assert client.get("/api/notifications", headers=th).json()["seen_at"] is None
    late = client.post("/api/notifications/seen", json={}, headers=th).json()["seen_at"]
    assert late
    earlier = client.post("/api/notifications/seen", json={"at": "2020-01-01 00:00:00"}, headers=th).json()
    assert earlier["seen_at"] == late
    assert client.get("/api/notifications", headers=th).json()["seen_at"] == late
