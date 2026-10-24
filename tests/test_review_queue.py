"""The teacher's review queue: four answers (three Socratic levels and a direct
one), the student's language preselected, regenerating with a stronger model,
the question bank, and an approved answer that survives a dropped connection."""
import asyncio
import os
import tempfile
import threading
import time

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-review-tests")

import pytest
from fastapi.testclient import TestClient

from backend import bank, db, environment, exercises, textutil
from backend.agents import tutor
from backend.main import app
from backend.routes import ask as ask_mod
from backend.routes import review as review_mod


def _variants(tag="", model="fake-haiku"):
    out = {lvl: {"en": f"{lvl} en {tag}".strip(), "he": f"{lvl} he {tag}".strip()}
           for lvl in ("nudge", "normal", "more", "direct")}
    out["model"] = model
    return out


@pytest.fixture()
def drafts(monkeypatch):
    calls = []

    async def fake(system_prompt, session_id, question, course="", model=None):
        calls.append({"model": model, "prompt": system_prompt})
        return _variants("regen" if model else "", model or "fake-haiku")

    monkeypatch.setattr(tutor, "generate_variants", fake)
    return calls


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        exercises.set_active("ex3-mcalc")
        with db.conn() as c:
            c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES ('Rev Teacher', 'REV-T', 'teacher')")
            c.execute("INSERT INTO system_settings(key, value) VALUES('review_mode', 'on') "
                      "ON CONFLICT(key) DO UPDATE SET value = 'on'")
        yield tc
        with db.conn() as c:
            c.execute("DELETE FROM system_settings WHERE key = 'review_mode'")


_n = iter(range(1, 1000))


def _student(tc):
    code = f"REV-{next(_n)}"
    with db.conn() as c:
        c.execute("INSERT INTO users (username, login_code, role) VALUES (?, ?, 'student')", (code, code))
    tok = tc.post("/api/login", json={"code": code, "password": code}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    sid = tc.post("/api/sessions", json={"exercise_id": "ex3-mcalc"}, headers=h).json()["session_id"]
    return h, sid


def _teacher(tc):
    tok = tc.post("/api/login", json={"code": "REV-T", "password": "REV-T"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _ask_in_background(tc, h, sid, message):
    """The student's /ask blocks until the teacher picks; run it on a thread."""
    box = {}

    def run():
        box["r"] = tc.post("/api/ask", json={"session_id": sid, "message": message}, headers=h)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


def _wait_pending(tc, th, sid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        items = [r for r in tc.get("/api/reviews/pending", headers=th).json() if r["session_id"] == sid]
        if items:
            return items[0]
        time.sleep(0.05)
    raise AssertionError("no pending review appeared")


def test_four_answers_language_and_direct_pick(client, drafts):
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_in_background(client, h, sid, "How do I parse argv in C?")
    item = _wait_pending(client, th, sid)
    assert item["variant_direct"] == "direct en" and item["variant_direct_he"] == "direct he"
    assert item["suggested_lang"] == "en"
    assert item["model"] == "fake-haiku"
    r = client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "direct", "lang": "en"}, headers=th)
    assert r.status_code == 200, r.text
    t.join(10)
    assert "direct en" in box["r"].text
    with db.conn() as c:
        row = c.execute("SELECT answer_level, model FROM messages WHERE session_id = ? AND role = 'assistant'",
                        (sid,)).fetchone()
    assert (row["answer_level"], row["model"]) == ("direct", "fake-haiku")


def test_regenerate_with_a_stronger_model(client, drafts, monkeypatch):
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_in_background(client, h, sid, "איך מפרקים את argv?")
    item = _wait_pending(client, th, sid)
    assert item["suggested_lang"] == "he"

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/api/reviews/config", headers=th).json() == {"regen_models": []}
    assert client.post(f"/api/reviews/{item['id']}/regenerate", json={"model": "best"}, headers=th).status_code == 400

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    models = client.get("/api/reviews/config", headers=th).json()["regen_models"]
    assert [m["key"] for m in models] == ["strong", "best"]
    r = client.post(f"/api/reviews/{item['id']}/regenerate", json={"model": "best"}, headers=th)
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "claude-opus-5-5" and r.json()["variant_normal_he"] == "normal he regen"
    assert drafts[-1]["model"] == "claude-opus-5-5"
    # The regenerated draft saw the same prompt as the first one.
    assert drafts[-1]["prompt"] == drafts[0]["prompt"]

    client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "normal", "lang": "he"}, headers=th)
    t.join(10)
    assert "normal he regen" in box["r"].text
    # A decided question can't be regenerated any more.
    assert client.post(f"/api/reviews/{item['id']}/regenerate", json={"model": "strong"},
                       headers=th).status_code == 409


def test_bank_answer_can_be_sent(client, drafts, monkeypatch):
    match = {"id": "q01", "step": None, "question": "How do I count?", "score": 0.91,
             "answers": {"normal": {"en": "bank en", "he": "bank he"}}}
    monkeypatch.setattr(bank, "match_for_session", lambda sid, q: match)
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_in_background(client, h, sid, "how do i count things")
    item = _wait_pending(client, th, sid)
    assert item["bank_match"]["score"] == 0.91
    r = client.post(f"/api/reviews/{item['id']}/select",
                    json={"chosen": "bank", "lang": "en", "text": "bank en"}, headers=th)
    assert r.status_code == 200, r.text
    t.join(10)
    assert "bank en" in box["r"].text
    with db.conn() as c:
        row = c.execute("SELECT answer_level, model FROM messages WHERE session_id = ? AND role = 'assistant'",
                        (sid,)).fetchone()
    assert (row["answer_level"], row["model"]) == ("bank", "bank")


def test_approved_answer_survives_a_dropped_stream(client, drafts):
    """The answer is stored before it streams: dropping the connection after the
    first words keeps it (two approved answers were lost this way in class)."""
    h, sid = _student(client)
    s = {"id": sid, "exercise": "ex3-mcalc", "mode": "mentor", "variant": "x"}
    req = ask_mod.AskRequest(session_id=sid, message="q?")

    async def run():
        gen = ask_mod._gen_review(req, s, "prompt", [])
        await gen.__anext__()                      # "your teacher is reviewing…"
        task = asyncio.ensure_future(gen.__anext__())
        for _ in range(100):                       # wait for the review row
            await asyncio.sleep(0.02)
            with db.conn() as c:
                row = c.execute("SELECT id FROM pending_reviews WHERE session_id = ?", (sid,)).fetchone()
            if row:
                break
        with db.conn() as c:
            c.execute("UPDATE pending_reviews SET status='answered', chosen_level='more', chosen_lang='en', "
                      "final_text='a long approved answer' WHERE id = ?", (row["id"],))
        review_mod.event_for(row["id"]).set()
        first = await task                         # one word streamed…
        await gen.aclose()                         # …then the student disappears
        return first

    assert asyncio.run(run()).startswith("a")
    with db.conn() as c:
        body = c.execute("SELECT body FROM messages WHERE session_id = ? AND role = 'assistant'",
                         (sid,)).fetchone()["body"]
    assert body == "a long approved answer"


def test_bank_auto_answer_without_review(client, monkeypatch):
    with db.conn() as c:
        c.execute("UPDATE system_settings SET value = 'off' WHERE key = 'review_mode'")
    try:
        monkeypatch.setattr(bank, "AUTO_ANSWER", True)
        monkeypatch.setattr(bank, "match_for_session", lambda sid, q: {
            "id": "q1", "step": None, "question": "q", "score": 0.95,
            "answers": {"normal": {"en": "ready answer", "he": "תשובה מוכנה"}}})
        h, sid = _student(client)
        r = client.post("/api/ask", json={"session_id": sid, "message": "איך סופרים?"}, headers=h)
        assert "תשובה מוכנה" in r.text
    finally:
        with db.conn() as c:
            c.execute("UPDATE system_settings SET value = 'on' WHERE key = 'review_mode'")


@pytest.mark.parametrize("text,lang", [
    ("How do I count missing values?", "en"),
    ("איך סופרים ערכים חסרים בעמודה?", "he"),
    ("איך משתמשים ב-df.isna().sum() ?", "he"),
    ("fix RTL printing. Reply in English only. Make no mistakes.", "en"),
    ("מה זה? Reply in English please", "en"),
    ("grep -c 'ERROR' app.log", "en"),
])
def test_detect_lang(text, lang):
    assert textutil.detect_lang(text) == lang


def test_bank_matching_hebrew_and_english():
    entries = bank.normalize_entries({"questions": [
        {"id": "q1", "step": 1, "question": "איך סופרים ערכים חסרים בכל עמודה?",
         "paraphrases": ["how do I count missing values per column"],
         "answers": {"normal": {"en": "use isna().sum()", "he": "השתמשו ב-isna().sum()"}}},
        {"id": "q2", "step": 2, "question": "למה ה-clean שלי לא משנה את הטבלה?",
         "answers": {"direct": "chained indexing"}},
    ]})
    m = bank.best_match(entries, "איך סופרים כמה ערכים חסרים יש בעמודה", step=1)
    assert m and m["id"] == "q1" and m["score"] >= 0.45
    m = bank.best_match(entries, "How can I count the missing values in each column?", step=1)
    assert m and m["id"] == "q1"
    assert bank.best_match(entries, "מה השעה עכשיו?", step=1) is None
    with pytest.raises(ValueError):
        bank.normalize_entries([{"question": "x", "answers": {"loud": "y"}}])


def test_environment_block_for_windows(client):
    h, sid = _student(client)
    environment.remember_os(sid, "Windows 11 amd64")
    text = environment.tutor_block(sid, exercises.get("ex3-mcalc"))
    assert "Windows 11 amd64" in text and "busybox-w32" in text and "backslash" in text
    # The plugin also sends it with each question.
    _, sid2 = _student(client)
    client.post("/api/ask", json={"session_id": sid2, "message": "hi", "client_os": "Mac OS X 15.5 aarch64"},
                headers=h)  # not this student's session: refused before anything is stored
    assert environment.client_os(sid2) is None
