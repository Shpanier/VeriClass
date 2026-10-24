""""Ask again" with the stronger model, and the cache of its answers."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-reask-tests")

import pytest
from fastapi.testclient import TestClient

from backend import answer_cache, db, exercises, student_llm
from backend.main import app

STRONG = "claude-sonnet-5-5"


@pytest.fixture()
def llm(monkeypatch):
    """Fake both models; records every strong-model call."""
    calls = []

    async def default(system_prompt, messages, timeout=60.0):
        yield "short answer"

    async def strong(system_prompt, messages, timeout=120.0):
        calls.append(messages)
        yield "a long, "
        yield "detailed answer"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(student_llm, "MODEL", "claude-haiku-5-5")
    monkeypatch.setattr(student_llm, "STRONG_MODEL", STRONG)
    monkeypatch.setattr(student_llm, "stream_chat", default)
    monkeypatch.setattr(student_llm, "stream_strong", strong)
    monkeypatch.setattr(answer_cache, "ENABLED", True)
    return calls


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            c.execute("DELETE FROM system_settings WHERE key = 'review_mode'")
            c.execute("DELETE FROM answer_cache")
        exercises.set_active("ex3-mcalc")
        yield tc


_students = iter(range(1, 1000))


def _session(tc, variant=None):
    """A new student's session (a student who logs in again resumes theirs),
    optionally moved to [variant]."""
    code = f"RSK-{next(_students)}"
    with db.conn() as c:
        c.execute("INSERT INTO users (username, login_code, role) VALUES (?, ?, 'student')", (code, code))
    r = tc.post("/api/login", json={"code": code, "password": code})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    s = tc.post("/api/sessions", json={"exercise_id": "ex3-mcalc"}, headers=h)
    assert s.status_code == 200, s.text
    sid = s.json()["session_id"]
    if variant:
        with db.conn() as c:
            c.execute("UPDATE sessions SET variant = ? WHERE id = ?", (variant, sid))
    return h, sid


def _variant(i):
    return exercises.variants("ex3-mcalc")[i]["id"]


def _assistant_rows(sid):
    with db.conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT body, model, cached FROM messages WHERE session_id = ? AND role = 'assistant' ORDER BY id",
            (sid,))]


def test_reply_offers_ask_again_with_the_strong_model(client, llm):
    h, sid = _session(client)
    r = client.post("/api/ask", json={"session_id": sid, "message": "What is a pipe?"}, headers=h)
    assert r.status_code == 200
    assert r.text == "short answer"
    assert r.headers["X-VeriExam-Reask"] == "Sonnet 5.5"
    assert _assistant_rows(sid) == [{"body": "short answer", "model": "claude-haiku-5-5", "cached": 0}]


def test_ask_again_sends_the_question_without_the_first_answer(client, llm):
    h, sid = _session(client)
    client.post("/api/ask", json={"session_id": sid, "message": "How does fork work?"}, headers=h)
    r = client.post("/api/ask", json={"session_id": sid, "message": "How does fork work?", "reask": True},
                    headers=h)
    assert r.status_code == 200
    assert r.text == "a long, detailed answer"
    assert "X-VeriExam-Reask" not in r.headers  # no "ask again" on the strong answer itself
    assert llm[-1] == [{"role": "user", "content": "How does fork work?"}]
    rows = _assistant_rows(sid)
    assert rows[-1] == {"body": "a long, detailed answer", "model": STRONG, "cached": 0}
    with db.conn() as c:  # the question isn't stored twice
        n = c.execute("SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'", (sid,)).fetchone()[0]
    assert n == 1


def test_same_question_in_the_same_context_comes_from_the_cache(client, llm):
    h1, sid1 = _session(client, _variant(0))
    h2, sid2 = _session(client, _variant(0))
    q = "Why does my program print garbage?"
    for h, sid, question in ((h1, sid1, q), (h2, sid2, "  why does my program  print GARBAGE ")):
        client.post("/api/ask", json={"session_id": sid, "message": question}, headers=h)
        r = client.post("/api/ask", json={"session_id": sid, "message": question, "reask": True}, headers=h)
        assert r.text.strip() == "a long, detailed answer"
    assert len(llm) == 1  # the second student got the cached answer
    assert _assistant_rows(sid2)[-1]["cached"] == 1
    with db.conn() as c:
        assert c.execute("SELECT hits FROM answer_cache WHERE question = ?", (q,)).fetchone()["hits"] == 1


def test_another_variant_is_not_served_from_the_cache(client, llm):
    # The variant's parameters are in the tutor's prompt, so its answer may differ.
    for i in (0, 1):
        h, sid = _session(client, _variant(i))
        client.post("/api/ask", json={"session_id": sid, "message": "What should argv[1] be?"}, headers=h)
        client.post("/api/ask", json={"session_id": sid, "message": "What should argv[1] be?", "reask": True},
                    headers=h)
    assert len(llm) == 2


def test_a_different_conversation_is_not_served_from_the_cache(client, llm):
    h, sid = _session(client, _variant(0))
    client.post("/api/ask", json={"session_id": sid, "message": "I use ex3"}, headers=h)
    client.post("/api/ask", json={"session_id": sid, "message": "Explain it again"}, headers=h)
    client.post("/api/ask", json={"session_id": sid, "message": "Explain it again", "reask": True}, headers=h)
    h2, sid2 = _session(client, _variant(0))
    client.post("/api/ask", json={"session_id": sid2, "message": "Explain it again"}, headers=h2)
    client.post("/api/ask", json={"session_id": sid2, "message": "Explain it again", "reask": True}, headers=h2)
    assert len(llm) == 2
    assert llm[0][:2] == [{"role": "user", "content": "I use ex3"}, {"role": "assistant", "content": "short answer"}]


def test_cache_off(client, llm, monkeypatch):
    monkeypatch.setattr(answer_cache, "ENABLED", False)
    for _ in range(2):
        h, sid = _session(client, _variant(0))
        client.post("/api/ask", json={"session_id": sid, "message": "What is errno?"}, headers=h)
        client.post("/api/ask", json={"session_id": sid, "message": "What is errno?", "reask": True}, headers=h)
    assert len(llm) == 2


def test_ask_again_turned_off_or_unknown_question(client, llm, monkeypatch):
    h, sid = _session(client)
    assert client.post("/api/ask", json={"session_id": sid, "message": "never asked", "reask": True},
                       headers=h).status_code == 400
    monkeypatch.setattr(student_llm, "STRONG_MODEL", "")
    r = client.post("/api/ask", json={"session_id": sid, "message": "What is a pipe?"}, headers=h)
    assert "X-VeriExam-Reask" not in r.headers
    assert client.post("/api/ask", json={"session_id": sid, "message": "What is a pipe?", "reask": True},
                       headers=h).status_code == 400


def test_model_label():
    assert student_llm.model_label("claude-sonnet-5-5") == "Sonnet 5.5"
    assert student_llm.model_label("claude-opus-4-1-20250805") == "Opus 4.1"
    assert student_llm.model_label("claude-haiku-5-5") == "Haiku 5.5"


def test_no_ask_again_past_the_teachers_review(client, llm):
    h, sid = _session(client)
    client.post("/api/ask", json={"session_id": sid, "message": "What is a fork bomb?"}, headers=h)
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('review_mode', 'on')")
    try:
        r = client.post("/api/ask", json={"session_id": sid, "message": "What is a fork bomb?", "reask": True},
                        headers=h)
        assert r.status_code == 400
        assert llm == []
    finally:
        with db.conn() as c:
            c.execute("DELETE FROM system_settings WHERE key = 'review_mode'")
