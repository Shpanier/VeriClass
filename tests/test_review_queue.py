"""The teacher's review queue: the question at once and its answers one by one
(four levels by the default model, one by the best model), the student's
language preselected, drafting again with a stronger model, the question bank
(matching, and saving the teacher's answers into it), sending an answer to the
whole class, and an approved answer that survives a dropped connection."""
import asyncio
import os
import re
import tempfile
import threading
import time

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-review-tests")

import pytest
import yaml
from fastapi.testclient import TestClient

from backend import bank, broadcast, db, environment, exercises, packages, textutil
from backend.agents import llm as agent_llm
from backend.agents import tutor
from backend.main import app
from backend.routes import ask as ask_mod
from backend.routes import review as review_mod

LEVELS = ("nudge", "normal", "more", "direct")


@pytest.fixture(autouse=True)
def short_wait(monkeypatch):
    """A student's request waits 10 minutes for the teacher; a test that fails
    before answering must not hold the client open that long."""
    monkeypatch.setattr(ask_mod, "REVIEW_TIMEOUT_SECONDS", 15)


@pytest.fixture()
def drafts(monkeypatch):
    """A fake tutor: one call per answer. `calls` records them; `hold[level]`
    keeps that level's draft from finishing; `fail[level]` makes it fail."""
    class Calls(list):
        hold: dict = {}
        fail: dict = {}

    calls, hold, fail = Calls(), {}, {}

    async def fake(system_prompt, session_id, question, level, course="", model=None, translate_to=None):
        calls.append({"level": level, "model": model, "prompt": system_prompt, "translate_to": translate_to})
        while hold.get(level) and not model:  # only the default model's drafts are held
            await asyncio.sleep(0.02)
        if fail.get(level):
            raise RuntimeError(f"{level} is broken")
        tag = " regen" if model else ""
        out = {"en": f"{level} en{tag}", "he": f"{level} he{tag}", "model": model or "fake-haiku",
               "question_lang": "", "question_translation": ""}
        # Like the model: Arabic is named and translated; "[he?]" plays a model
        # that translates a Hebrew question anyway.
        if re.search(r"[؀-ۿ]", question):
            out["question_lang"] = "ar"
            out["question_translation"] = f"{translate_to}: translated" if translate_to and not model else ""
        elif "[he?]" in question:
            out["question_lang"] = "he"
            out["question_translation"] = "unneeded"
        return out

    monkeypatch.setattr(tutor, "draft", fake)
    monkeypatch.setattr(agent_llm, "default_model_name", lambda: "fake-haiku")
    calls.hold, calls.fail = hold, fail
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


def _student(tc, exercise_id="ex3-mcalc"):
    """A new student with a session on `exercise_id` (a student outside every
    course opens the active exercise, so it is switched for the call)."""
    code = f"REV-{next(_n)}"
    with db.conn() as c:
        c.execute("INSERT INTO users (username, login_code, role) VALUES (?, ?, 'student')", (code, code))
    tok = tc.post("/api/login", json={"code": code, "password": code}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    exercises.set_active(exercise_id)
    try:
        r = tc.post("/api/sessions", json={"exercise_id": exercise_id}, headers=h)
        assert r.status_code == 200, r.text
        return h, r.json()["session_id"]
    finally:
        exercises.set_active("ex3-mcalc")


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


def _wait_answers(tc, th, rid, n, timeout=10):
    """The review once at least `n` answers have finished (ready or failed)."""
    end = time.time() + timeout
    while time.time() < end:
        item = _item(tc, th, rid)
        if item and len(item["answers"]) >= n:
            return item
        time.sleep(0.05)
    raise AssertionError(f"fewer than {n} answers finished: {item and item['answers']}")


def _item(tc, th, rid):
    return next((r for r in tc.get("/api/reviews/pending", headers=th).json() if r["id"] == rid), None)


def _status(rid):
    with db.conn() as c:
        return c.execute("SELECT status FROM pending_reviews WHERE id = ?", (rid,)).fetchone()["status"]


def _notes(tc, h, sid):
    return tc.get(f"/api/transcript/{sid}", headers=h, params={"origin": "server"}).json()["entries"]


def _reply(sid):
    with db.conn() as c:
        return c.execute("SELECT answer_level, model, body FROM messages WHERE session_id = ? AND role = 'assistant' "
                         "ORDER BY id DESC LIMIT 1", (sid,)).fetchone()


# --- the answers, one by one -------------------------------------------------------

def test_the_question_arrives_at_once_and_the_answers_one_by_one(client, drafts, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(review_mod.student_llm, "BEST_MODEL", "claude-opus-5-5")
    for lvl in ("normal", "more", "direct"):
        drafts.hold[lvl] = True
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_in_background(client, h, sid, "How do I parse argv in C?")
    item = _wait_answers(client, th, _wait_pending(client, th, sid)["id"], 2)
    # The teacher sees the question before most answers exist: the first two
    # that finished (nudge, and the best model's) are on top, the rest are drafting.
    assert item["suggested_lang"] == "en" and item["model"] == "fake-haiku"
    assert {a["slot"] for a in item["answers"]} == {"nudge", "best"}
    assert all(a["status"] == "ready" for a in item["answers"])
    assert sorted(d["slot"] for d in item["drafting"]) == ["direct", "more", "normal"]
    best = next(a for a in item["answers"] if a["slot"] == "best")
    assert (best["level"], best["model"], best["label"]) == ("direct", "claude-opus-5-5", "Opus 5.5")
    assert best["text_en"] == "direct en regen" and best["seconds"] is not None
    nudge = next(a for a in item["answers"] if a["slot"] == "nudge")
    assert (nudge["text_en"], nudge["text_he"], nudge["model"]) == ("nudge en", "nudge he", "fake-haiku")

    for lvl in ("direct", "more", "normal"):
        drafts.hold[lvl] = False
    item = _wait_answers(client, th, item["id"], 5)
    assert item["drafting"] == []
    slots = [a["slot"] for a in item["answers"]]  # in the order they finished: the held ones last
    assert set(slots[:2]) == {"nudge", "best"} and set(slots[2:]) == {"normal", "more", "direct"}
    # Five calls: four by the default model, one by the best model at the direct level.
    assert sorted(((c["level"], c["model"]) for c in drafts), key=str) == [
        ("direct", "claude-opus-5-5"), ("direct", None), ("more", None), ("normal", None), ("nudge", None)]

    r = client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "best", "lang": "en"}, headers=th)
    assert r.status_code == 200, r.text
    assert r.json()["delivered"] == "now" and r.json()["saved_to_bank"] is False and r.json()["sent_to_class"] == 0
    t.join(10)
    assert "direct en regen" in box["r"].text
    row = _reply(sid)
    assert (row["answer_level"], row["model"]) == ("direct", "claude-opus-5-5")
    with db.conn() as c:
        assert c.execute("SELECT chosen_slot FROM pending_reviews WHERE id = ?", (item["id"],)).fetchone()[0] == "best"


def test_without_the_best_model_there_are_four_answers(client, drafts, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_in_background(client, h, sid, "What does argc count?")
    item = _wait_answers(client, th, _wait_pending(client, th, sid)["id"], 4)
    assert sorted(a["slot"] for a in item["answers"]) == sorted(LEVELS) and item["drafting"] == []
    client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "normal", "lang": "en"}, headers=th)
    t.join(10)
    assert box["r"].headers.get(ask_mod.REVIEW_HEADER) == "1"  # the chat stays usable meanwhile
    assert "normal en" in box["r"].text


def test_the_best_answer_can_be_switched_off_or_moved_to_another_level(client, drafts, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    th = _teacher(client)
    cfg = client.get("/api/reviews/config", headers=th).json()
    assert cfg["best_answer"]["enabled"] is True and cfg["best_answer"]["level"] == "direct"
    assert cfg["save_to_bank"] is True and cfg["class_minutes"] == 30
    try:
        r = client.post("/api/reviews/config", json={"best_level": "normal", "save_to_bank": False}, headers=th)
        assert r.json()["best_answer"]["level"] == "normal" and r.json()["save_to_bank"] is False
        assert [s["level"] for s in review_mod.plan_slots() if s["slot"] == "best"] == ["normal"]
        r = client.post("/api/reviews/config", json={"best_answer": False}, headers=th)
        assert r.json()["best_answer"]["enabled"] is False and r.json()["best_answer"]["available"] is True
        assert [s["slot"] for s in review_mod.plan_slots()] == list(LEVELS)
    finally:
        client.post("/api/reviews/config", json={"best_answer": True, "best_level": "direct", "save_to_bank": True},
                    headers=th)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert client.get("/api/reviews/config", headers=th).json()["best_answer"]["available"] is False


def test_a_failed_draft_is_shown_and_drafted_again(client, drafts, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    drafts.fail["more"] = True
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_in_background(client, h, sid, "Why does my loop never end?")
    item = _wait_answers(client, th, _wait_pending(client, th, sid)["id"], 4)
    failed = next(a for a in item["answers"] if a["slot"] == "more")
    assert failed["status"] == "failed" and "more is broken" in failed["error"]
    assert [a["status"] for a in item["answers"] if a["slot"] != "more"] == ["ready"] * 3
    # The failed one can't be sent; the others can.
    assert client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "more"}, headers=th).status_code == 404

    drafts.fail["more"] = False
    r = client.post(f"/api/reviews/{item['id']}/regenerate", json={}, headers=th)  # no model: the failed ones again
    assert r.status_code == 200, r.text
    assert [d["slot"] for d in r.json()["drafting"]] == ["more"]
    item = _wait_answers(client, th, item["id"], 4)
    more = next(a for a in item["answers"] if a["slot"] == "more")
    assert more["status"] == "ready" and more["text_en"] == "more en"
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM review_answers WHERE review_id = ? AND slot = 'more' AND status = 'replaced'",
                         (item["id"],)).fetchone()[0] == 1
    # Nothing failed any more: nothing to draft again without a model.
    assert client.post(f"/api/reviews/{item['id']}/regenerate", json={}, headers=th).status_code == 409
    client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "more", "lang": "en"}, headers=th)
    t.join(10)
    assert "more en" in box["r"].text


def test_regenerate_with_a_stronger_model(client, drafts, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_in_background(client, h, sid, "איך מפרקים את argv?")
    item = _wait_answers(client, th, _wait_pending(client, th, sid)["id"], 4)
    assert item["suggested_lang"] == "he"

    assert client.get("/api/reviews/config", headers=th).json()["regen_models"] == []
    assert client.post(f"/api/reviews/{item['id']}/regenerate", json={"model": "best"}, headers=th).status_code == 400

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    models = client.get("/api/reviews/config", headers=th).json()["regen_models"]
    assert [m["key"] for m in models] == ["strong", "best"]
    r = client.post(f"/api/reviews/{item['id']}/regenerate", json={"model": "best"}, headers=th)
    assert r.status_code == 200, r.text
    assert sorted(d["slot"] for d in r.json()["drafting"]) == sorted(LEVELS)
    assert all(d["model"] == "claude-opus-5-5" for d in r.json()["drafting"])
    item = _wait_answers(client, th, item["id"], 4)
    normal = next(a for a in item["answers"] if a["slot"] == "normal")
    assert normal["model"] == "claude-opus-5-5" and normal["text_he"] == "normal he regen"
    assert [c["model"] for c in drafts[-4:]] == ["claude-opus-5-5"] * 4
    # The regenerated draft saw the same prompt as the first one.
    assert drafts[-1]["prompt"] == drafts[0]["prompt"]

    client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "normal", "lang": "he"}, headers=th)
    t.join(10)
    assert "normal he regen" in box["r"].text
    assert _reply(sid)["model"] == "claude-opus-5-5"
    # A decided question can't be regenerated any more.
    assert client.post(f"/api/reviews/{item['id']}/regenerate", json={"model": "strong"},
                       headers=th).status_code == 409


def test_drafts_cut_by_a_restart_are_marked_failed(client):
    h, sid = _student(client)
    with db.conn() as c:
        rid = c.execute("INSERT INTO pending_reviews (session_id, question, variant_nudge, variant_normal, "
                        "variant_more) VALUES (?, 'cut', '', '', '')", (sid,)).lastrowid
        c.execute("INSERT INTO review_answers (review_id, slot, level, model) VALUES (?, 'nudge', 'nudge', 'm')", (rid,))
    assert review_mod.recover() >= 1
    finished, drafting = review_mod.answers_of(rid)
    assert drafting == [] and finished[0]["status"] == "failed" and "restarted" in finished[0]["error"]


# --- the bank, the teacher's own text, the class ---------------------------------------

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
    assert (_reply(sid)["answer_level"], _reply(sid)["model"]) == ("bank", "bank")


def test_the_teachers_own_answer(client, drafts, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_in_background(client, h, sid, "Can I use goto?")
    item = _wait_pending(client, th, sid)
    assert client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "own"}, headers=th).status_code == 422
    assert client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "elsewhere", "text": "x"},
                       headers=th).status_code == 422
    r = client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "own", "lang": "en", "text": "No. Use a loop."},
                    headers=th)
    assert r.status_code == 200, r.text
    t.join(10)
    assert "No. Use a loop." in box["r"].text
    assert (_reply(sid)["answer_level"], _reply(sid)["model"]) == ("own", None)


def test_a_sent_answer_can_be_saved_into_the_question_bank(client, drafts, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # A package exercise: the entry goes into its faq.yaml.
    h, sid = _student(client, "pkg-demo")
    th = _teacher(client)
    original = [dict(e) for e in exercises.get("pkg-demo")["faq"]]
    original_ex3 = exercises.get("ex3-mcalc").get("faq")
    before = len(original)
    try:
        _saving_into_the_bank(client, h, sid, th, before)
    finally:
        exercises.set_faq("pkg-demo", original)  # leave the shared package as it was
        exercises.get("ex3-mcalc")["faq"] = original_ex3  # and the bundled exercise
        with db.conn() as c:
            c.execute("DELETE FROM exercise_faq WHERE exercise_id = 'ex3-mcalc'")


def _saving_into_the_bank(client, h, sid, th, before):
    t, box = _ask_in_background(client, h, sid, "How many rows are there in the CSV after cleaning?")
    item = _wait_answers(client, th, _wait_pending(client, th, sid)["id"], 4)
    r = client.post(f"/api/reviews/{item['id']}/select",
                    json={"chosen": "direct", "lang": "he", "text": "בדקו len(df) אחרי clean().", "save_to_bank": True},
                    headers=th)
    assert r.status_code == 200, r.text
    assert r.json()["saved_to_bank"] is True
    t.join(10)
    faq = exercises.get("pkg-demo")["faq"]
    assert len(faq) == before + 1
    entry = faq[-1]
    assert entry["question"] == "How many rows are there in the CSV after cleaning?" and entry["step"] == 1
    assert entry["answers"] == {"direct": {"he": "בדקו len(df) אחרי clean().", "en": "בדקו len(df) אחרי clean()."}}
    assert entry["source"] == "teacher" and entry["model"] == "fake-haiku" and entry["approved"] is True
    on_disk = yaml.safe_load((packages.exercises_dir() / "pkg-demo" / "faq.yaml").read_text(encoding="utf-8"))
    assert on_disk["questions"][-1]["id"] == entry["id"] and on_disk["questions"][-1]["source"] == "teacher"
    assert on_disk["questions"][0]["id"] == "q01"  # the skill's entries are kept
    with db.conn() as c:
        assert c.execute("SELECT saved_to_bank FROM pending_reviews WHERE id = ?", (item["id"],)).fetchone()[0] == 1

    # The next student asking about the same thing sees the teacher's answer.
    h2, sid2 = _student(client, "pkg-demo")
    t2, box2 = _ask_in_background(client, h2, sid2, "how many rows in the csv after cleaning")
    item2 = _wait_pending(client, th, sid2)
    assert item2["bank_match"]["id"] == entry["id"] and item2["bank_match"]["answers"]["direct"]["he"].startswith("בדקו")
    # The bank's answer sent (edited) for a reworded question: it goes back into
    # the same entry, which learns the new wording; nothing is duplicated.
    r = client.post(f"/api/reviews/{item2['id']}/select",
                    json={"chosen": "bank", "lang": "he", "text": "len(df).", "level": "direct", "save_to_bank": True},
                    headers=th)
    assert r.json()["saved_to_bank"] is True
    t2.join(10)
    faq = exercises.get("pkg-demo")["faq"]
    assert len(faq) == before + 1 and faq[-1]["id"] == entry["id"]
    assert faq[-1]["answers"] == {"direct": {"he": "len(df).", "en": "len(df)."}}
    # The bank's own answer sent again: the entry still says who wrote it.
    assert (faq[-1]["source"], faq[-1]["model"]) == ("teacher", "fake-haiku")
    assert faq[-1]["paraphrases"] == ["how many rows in the csv after cleaning"]
    # The same question again, at another level: that level is added.
    assert bank.save_answer("pkg-demo", "how many rows in the CSV after cleaning?", "nudge", "en", "Think len().",
                            )["answers"].keys() == {"nudge"}  # a new wording without a match: its own entry
    assert len(exercises.get("pkg-demo")["faq"]) == before + 2
    e = bank.save_answer("pkg-demo", "How many rows are there in the CSV after cleaning?", "nudge", "en", "len?")
    assert e["id"] == entry["id"] and set(e["answers"]) == {"direct", "nudge"}

    # A bundled exercise without a package folder: the bank alone is kept in
    # the database; the exercise itself still comes from its YAML file.
    edited = exercises.get("ex3-mcalc")["edited"]
    h3, sid3 = _student(client)
    t3, box3 = _ask_in_background(client, h3, sid3, "What is argv[0]?")
    item3 = _wait_answers(client, th, _wait_pending(client, th, sid3)["id"], 4)
    r = client.post(f"/api/reviews/{item3['id']}/select", json={"chosen": "nudge", "save_to_bank": True}, headers=th)
    assert r.json()["saved_to_bank"] is True
    t3.join(10)
    assert exercises.get("ex3-mcalc")["faq"][-1]["answers"]["nudge"]["en"] == "nudge en"
    if not edited:
        assert exercises.get("ex3-mcalc")["edited"] is False
        with db.conn() as c:
            assert c.execute("SELECT 1 FROM exercises WHERE exercise_id = 'ex3-mcalc'").fetchone() is None
            data = c.execute("SELECT faq FROM exercise_faq WHERE exercise_id = 'ex3-mcalc'").fetchone()["faq"]
        assert "What is argv[0]?" in data


def test_the_bank_write_back_keeps_every_text_exactly(client):
    """Long lines with runs of spaces (an expected output) and multi-line
    answers survive the round trip through faq.yaml unchanged; the entries
    already there are untouched."""
    ex = exercises.get("pkg-demo")
    before = [dict(e) for e in ex["faq"]]
    long_line = "the `dZ` line must be `[-0.138  0.037  0.035 -0.126]` " * 4
    multi = "first line\n\n  indented second line  \nthird"
    entries = before + [{"id": "t99", "step": None, "question": "q", "paraphrases": ["p  q"],
                         "answers": {"direct": {"en": long_line, "he": multi}}, "approved": True, "source": "teacher"}]
    packages.write_faq(ex, entries)
    back = packages.load_package(packages.exercises_dir() / "pkg-demo")["faq"]
    assert back[:len(before)] == before
    assert back[-1]["answers"]["direct"] == {"en": long_line, "he": multi + "\n"} or \
           back[-1]["answers"]["direct"] == {"en": long_line, "he": multi}
    assert back[-1]["paraphrases"] == ["p  q"] and back[-1]["source"] == "teacher"
    exercises.set_faq("pkg-demo", before)  # leave the package as it was


def test_an_answer_sent_to_the_whole_class(client, drafts, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    h, sid = _student(client)
    th = _teacher(client)
    mates = [_student(client) for _ in range(2)]
    gone_h, gone_sid = _student(client)
    with db.conn() as c:  # left an hour ago: not active now
        c.execute("UPDATE sessions SET last_active_at = datetime('now', '-61 minutes') WHERE id = ?", (gone_sid,))
    other_h, other_sid = _student(client, "pkg-demo")
    assert client.get("/api/broadcast/recipients", headers=th, params={"exercise_id": "ex3-mcalc"}).json()["count"] >= 3

    t, box = _ask_in_background(client, h, sid, "What is the difference between a process and a thread?")
    item = _wait_answers(client, th, _wait_pending(client, th, sid)["id"], 4)
    r = client.post(f"/api/reviews/{item['id']}/select",
                    json={"chosen": "direct", "lang": "en", "text": "A thread shares its process's memory.",
                          "send_to_class": True}, headers=th)
    assert r.status_code == 200, r.text
    t.join(10)
    assert "A thread shares its process's memory." in box["r"].text
    sent = r.json()["sent_to_class"]
    assert sent >= 2
    for mh, msid in mates:
        notes = _notes(client, mh, msid)
        assert len(notes) == 1 and notes[0]["author"] == "tutor" and notes[0]["kind"] == "note"
        assert "answered a question asked in class" in notes[0]["content"]
        assert "process and a thread" in notes[0]["content"] and "shares its process's memory" in notes[0]["content"]
        assert (_reply(msid)["answer_level"], _reply(msid)["model"]) == ("class", None)
    assert _notes(client, gone_h, gone_sid) == []          # not active now
    assert _notes(client, other_h, other_sid) == []        # another exercise
    assert _notes(client, h, sid) == []                    # the asker got the answer itself
    with db.conn() as c:
        assert c.execute("SELECT sent_to_class FROM pending_reviews WHERE id = ?", (item["id"],)).fetchone()[0] == sent

    # A free note to the class, and only to one course's students.
    r = client.post("/api/broadcast", json={"exercise_id": "ex3-mcalc", "text": "Break until 11:15."}, headers=th)
    assert r.status_code == 200 and r.json()["sent"] >= 3
    assert _notes(client, mates[0][0], mates[0][1])[-1]["content"] == "Break until 11:15."
    with db.conn() as c:
        c.execute("UPDATE sessions SET course_id = 'c-a' WHERE id = ?", (mates[0][1],))
    assert broadcast.send("ex3-mcalc", "only course a", course_id="c-a")["sent"] == 1
    assert client.post("/api/broadcast", json={"exercise_id": "nope", "text": "x"}, headers=th).status_code == 404
    assert client.post("/api/broadcast", json={"exercise_id": "ex3-mcalc", "text": "  "}, headers=th).status_code == 422
    assert client.post("/api/broadcast", json={"exercise_id": "ex3-mcalc", "text": "x"}, headers=h).status_code == 403


def test_an_answered_question_is_sent_to_the_class_later(client, drafts, monkeypatch):
    """"Answered recently": an answer already sent to one student goes to the
    rest of the class afterwards, as given or edited for the class."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    h, sid = _student(client)
    th = _teacher(client)
    mate_h, mate_sid = _student(client)
    other_h, other_sid = _student(client, "pkg-demo")

    t, box = _ask_in_background(client, h, sid, "Why does my loop never end?")
    item = _wait_answers(client, th, _wait_pending(client, th, sid)["id"], 4)
    # Not answered yet: not in the list, and it can't go to the class.
    assert all(a["id"] != item["id"] for a in client.get("/api/reviews/answered", headers=th).json())
    assert client.post(f"/api/reviews/{item['id']}/send-to-class", json={}, headers=th).status_code == 409
    r = client.post(f"/api/reviews/{item['id']}/select",
                    json={"chosen": "own", "lang": "en", "text": "Dana, the counter never changes."}, headers=th)
    assert r.status_code == 200 and r.json()["sent_to_class"] == 0
    t.join(10)

    listed = client.get("/api/reviews/answered", headers=th, params={"exercise_id": "ex3-mcalc"}).json()
    mine = next(a for a in listed if a["id"] == item["id"])
    assert mine["text"] == "Dana, the counter never changes." and mine["sent_to_class"] == 0
    assert mine["question"] == "Why does my loop never end?" and mine["username"].startswith("REV-")
    assert all(a["exercise_id"] == "ex3-mcalc" for a in listed)
    assert all(a["id"] != item["id"] for a in client.get(
        "/api/reviews/answered", headers=th, params={"exercise_id": "pkg-demo"}).json())

    # Who it would reach: everyone active on the exercise but the asker.
    everyone = client.get("/api/broadcast/recipients", headers=th, params={"exercise_id": "ex3-mcalc"}).json()["count"]
    others = client.get("/api/broadcast/recipients", headers=th,
                        params={"exercise_id": "ex3-mcalc", "exclude_session": sid}).json()["count"]
    assert others == everyone - 1 and others >= 1

    # Edited for the class (no name in it).
    r = client.post(f"/api/reviews/{item['id']}/send-to-class",
                    json={"text": "The loop's counter never changes."}, headers=th)
    assert r.status_code == 200, r.text
    assert r.json()["sent_to_class"] == others
    notes = _notes(client, mate_h, mate_sid)
    assert len(notes) == 1 and "answered a question asked in class" in notes[0]["content"]
    assert "loop never end" in notes[0]["content"] and "The loop's counter never changes." in notes[0]["content"]
    assert "Dana" not in notes[0]["content"]
    assert _notes(client, h, sid) == []              # the asker has it already
    assert _notes(client, other_h, other_sid) == []  # another exercise
    # Again, as the student got it: the count adds up.
    r = client.post(f"/api/reviews/{item['id']}/send-to-class", json={}, headers=th)
    assert r.status_code == 200
    assert "Dana, the counter never changes." in _notes(client, mate_h, mate_sid)[-1]["content"]
    mine = next(a for a in client.get("/api/reviews/answered", headers=th).json() if a["id"] == item["id"])
    assert mine["sent_to_class"] == 2 * others

    assert client.post("/api/reviews/999999/send-to-class", json={}, headers=th).status_code == 404
    assert client.post(f"/api/reviews/{item['id']}/send-to-class", json={}, headers=h).status_code == 403
    assert client.get("/api/reviews/answered", headers=h).status_code == 403


def test_a_class_note_is_kept_in_messages_when_the_exercise_keeps_no_transcript(client, monkeypatch):
    import copy
    quiet = copy.deepcopy(exercises.get("ex3-mcalc"))
    quiet.update(exercise_id="no-history-test", chat_history=False)
    exercises._LOADED["no-history-test"] = quiet
    try:
        h, sid = _student(client, "no-history-test")
        out = broadcast.send("no-history-test", "a note")
        assert out == {"sent": 0, "skipped": 1}
        assert _reply(sid)["body"] == "a note"
    finally:
        exercises._LOADED.pop("no-history-test")


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
         "answers": {"direct": "chained indexing"}, "source": "teacher", "model": "claude-opus-5-5"},
    ]})
    assert entries[1]["source"] == "teacher" and entries[1]["model"] == "claude-opus-5-5" and "source" not in entries[0]
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


# --- keeping the queue in step with the students -------------------------------------

def _ask_bg(tc, h, sid, message, transcript_client=True):
    box = {}
    headers = {**h, **({"X-VeriClass-Transcript": "1"} if transcript_client else {})}

    def run():
        box["r"] = tc.post("/api/ask", json={"session_id": sid, "message": message}, headers=headers)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


def test_deleting_a_question_the_student_waits_for(client, drafts):
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_bg(client, h, sid, "asdf")
    item = _wait_pending(client, th, sid)
    assert item["waiting"] is True and item["looks_like_noise"] is False
    r = client.post(f"/api/reviews/{item['id']}/delete", json={"note": "Ask about step 2."}, headers=th)
    assert r.status_code == 200 and r.json()["student_told"] == "now"
    t.join(10)
    assert "deleted" in box["r"].text and "Ask about step 2." in box["r"].text
    assert _status(item["id"]) == "deleted" and _item(client, th, item["id"]) is None
    assert client.post(f"/api/reviews/{item['id']}/delete", json={}, headers=th).status_code == 409
    assert _notes(client, h, sid) == []  # told live, no note needed


def test_a_late_answer_reaches_a_student_who_stopped_waiting(client, drafts, monkeypatch):
    monkeypatch.setattr(ask_mod, "REVIEW_TIMEOUT_SECONDS", 0.3)
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_bg(client, h, sid, "מה עושה argv?")
    item = _wait_pending(client, th, sid)
    t.join(10)
    assert "המרצה עוד לא ענה" in box["r"].text   # the wait ended, the question stays
    item = _wait_answers(client, th, item["id"], 4)
    assert item["waiting"] is False
    r = client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "normal", "lang": "he"}, headers=th)
    assert r.status_code == 200 and r.json()["delivered"] == "later"
    notes = _notes(client, h, sid)
    assert len(notes) == 1 and "המרצה ענה על השאלה" in notes[0]["content"] and "normal he" in notes[0]["content"]
    assert _reply(sid)["body"] == "normal he"


def test_a_client_without_a_transcript_still_times_out(client, drafts, monkeypatch):
    monkeypatch.setattr(ask_mod, "REVIEW_TIMEOUT_SECONDS", 0.3)
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_bg(client, h, sid, "What is argv?", transcript_client=False)
    item = _wait_pending(client, th, sid)
    t.join(10)
    assert "No teacher response in time" in box["r"].text
    assert _status(item["id"]) == "expired"


def test_deleting_old_questions_and_telling_the_student_later(client, drafts):
    h, sid = _student(client)
    th = _teacher(client)
    with db.conn() as c:  # questions left behind: nobody waits for them (a restart, a closed chat)
        ids = [c.execute("INSERT INTO pending_reviews (session_id, question, variant_nudge, variant_normal, "
                         "variant_more) VALUES (?, ?, 'n', 'n', 'n')", (sid, q)).lastrowid
               for q in ("old question one", "??", "old question two")]
    items = {r["id"]: r for r in client.get("/api/reviews/pending", headers=th).json()}
    assert all(not items[i]["waiting"] for i in ids)
    assert items[ids[1]]["looks_like_noise"] is True
    # A question from before answers had rows of their own still shows its columns.
    assert [a["slot"] for a in items[ids[0]]["answers"]] == ["nudge", "normal", "more"]

    r = client.post(f"/api/reviews/{ids[0]}/delete", json={"notify": True}, headers=th)
    assert r.json()["student_told"] == "later"
    assert "old question one" in _notes(client, h, sid)[0]["content"]
    r = client.post(f"/api/reviews/{ids[1]}/delete", json={"notify": False}, headers=th)
    assert r.json()["student_told"] == "silent" and len(_notes(client, h, sid)) == 1

    # The student comes back: the chat lists what is still with the teacher.
    open_q = client.get(f"/api/reviews/open/{sid}", headers=h).json()
    assert [q["id"] for q in open_q] == [ids[2]] and open_q[0]["waiting"] is False
    other, _ = _student(client)
    assert client.get(f"/api/reviews/open/{sid}", headers=other).status_code == 403

    # One click deletes every question nobody waits for; a waiting one stays.
    t, box = _ask_bg(client, h, sid, "a live question")
    live = _wait_pending_text(client, th, sid, "a live question")
    r = client.post("/api/reviews/delete-stale", json={}, headers=th)
    assert r.status_code == 200 and r.json()["deleted"] >= 1
    assert _status(ids[2]) == "deleted" and _status(live["id"]) == "pending"
    client.post(f"/api/reviews/{live['id']}/delete", json={}, headers=th)
    t.join(10)
    # Students can't delete questions.
    assert client.post("/api/reviews/delete-stale", json={}, headers=h).status_code == 403


def _wait_pending_text(tc, th, sid, text, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        for r in tc.get("/api/reviews/pending", headers=th).json():
            if r["session_id"] == sid and r["question"] == text:
                return r
        time.sleep(0.05)
    raise AssertionError("no pending review appeared")


def test_asking_again_replaces_the_copy_nobody_waits_for(client, drafts):
    h, sid = _student(client)
    th = _teacher(client)
    with db.conn() as c:
        old = c.execute("INSERT INTO pending_reviews (session_id, question, variant_nudge, variant_normal, "
                        "variant_more) VALUES (?, 'How  do I start?', 'n', 'n', 'n')", (sid,)).lastrowid
    t, box = _ask_bg(client, h, sid, "how do i start?")
    new = _wait_pending_text(client, th, sid, "how do i start?")
    assert new["id"] != old and _status(old) == "replaced"
    _wait_answers(client, th, new["id"], 4)
    client.post(f"/api/reviews/{new['id']}/select", json={"chosen": "nudge", "lang": "en"}, headers=th)
    t.join(10)
    assert "nudge en" in box["r"].text


def test_a_legacy_question_can_be_sent_from_its_columns(client, drafts):
    h, sid = _student(client)
    th = _teacher(client)
    with db.conn() as c:
        rid = c.execute("INSERT INTO pending_reviews (session_id, question, variant_nudge, variant_normal, "
                        "variant_more, variant_normal_he, model) VALUES (?, 'old', 'n', 'old normal', 'm', 'ישן', 'm0')",
                        (sid,)).lastrowid
    r = client.post(f"/api/reviews/{rid}/select", json={"chosen": "normal", "lang": "he"}, headers=th)
    assert r.status_code == 200 and r.json()["delivered"] == "later"
    assert _reply(sid)["body"] == "ישן" and _reply(sid)["model"] == "m0"


def test_transcript_entries_of_another_chat_are_synced(client):
    h, sid = _student(client)
    a = client.post(f"/api/transcript/{sid}", headers=h,
                    json={"client": "tab-a", "entries": [{"author": "student", "content": "from tab a"}]}).json()["ids"]
    client.post(f"/api/transcript/{sid}", headers=h,
                json={"client": "tab-b", "entries": [{"author": "student", "content": "from tab b"}]})
    seen_by_b = client.get(f"/api/transcript/{sid}", headers=h, params={"exclude_client": "tab-b"}).json()["entries"]
    assert [e["content"] for e in seen_by_b] == ["from tab a"]
    seen_by_a = client.get(f"/api/transcript/{sid}", headers=h,
                           params={"exclude_client": "tab-a", "after": a[0]}).json()["entries"]
    assert [e["content"] for e in seen_by_a] == ["from tab b"]


@pytest.mark.parametrize("question,noise", [("", True), ("??", True), ("123 456", True), ("asd", True),
                                             ("aaaa", True), ("אאאא אא", True), ("why?", False),
                                             ("מה זה", False), ("asdf", False)])
def test_noise_detection(question, noise):
    assert review_mod.looks_like_noise(question) is noise


def test_a_note_follows_the_exercise_language_when_the_question_has_none():
    import copy
    he_ex = copy.deepcopy(exercises.get("ex3-mcalc"))
    he_ex.update(exercise_id="he-brief-test", brief_md="תרגיל בעברית.")
    exercises._LOADED["he-brief-test"] = he_ex
    try:
        assert "המרצה מחק" in review_mod.deleted_message("aaaa", None, "he-brief-test")
        # A Hebrew lab's chat is Hebrew, whatever the question looks like.
        assert "המרצה מחק" in review_mod.deleted_message("What is argv?", None, "he-brief-test")
        assert "המרצה מחק" in review_mod.deleted_message("hello from codespace in /x", None, "he-brief-test")
        assert "deleted" in review_mod.deleted_message("aaaa", None, "ex3-mcalc")
        assert "המרצה מחק" in review_mod.deleted_message("מה זה?", None, "ex3-mcalc")
        assert "המרצה ענה על שאלה" in review_mod.class_note("What is argv?", "x", "he-brief-test")
        assert "asked in class" in review_mod.class_note("What is argv?", "x", "ex3-mcalc")
    finally:
        exercises._LOADED.pop("he-brief-test")


def test_a_question_in_another_language_comes_translated(client, drafts, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    h, sid = _student(client)
    th = _teacher(client)
    assert client.get("/api/reviews/config", headers=th).json()["translate_to"] == "he"
    t, box = _ask_in_background(client, h, sid, "كيف أشغل الحاوية؟")
    item = _wait_answers(client, th, _wait_pending(client, th, sid)["id"], 4)
    # Only the quickest draft (nudge) is asked to translate.
    assert [c["translate_to"] for c in drafts if c["level"] == "nudge"] == ["he"]
    assert all(c["translate_to"] is None for c in drafts if c["level"] != "nudge")
    assert (item["question_lang"], item["question_translation"], item["translated_to"]) == ("ar", "he: translated", "he")

    # Drafting again with a stronger model keeps the translation it left out.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    r = client.post(f"/api/reviews/{item['id']}/regenerate", json={"model": "strong"}, headers=th)
    assert r.status_code == 200, r.text
    item = _wait_answers(client, th, item["id"], 4)
    assert item["question_translation"] == "he: translated"
    client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "normal", "lang": "he"}, headers=th)
    t.join(10)


def test_no_translation_for_hebrew_or_english_or_when_off(client, drafts, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    h, sid = _student(client)
    th = _teacher(client)
    t, box = _ask_in_background(client, h, sid, "איך מריצים את הקונטיינר? [he?]")
    item = _wait_answers(client, th, _wait_pending(client, th, sid)["id"], 4)
    assert item["question_lang"] == "he" and item["question_translation"] is None
    client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "normal", "lang": "he"}, headers=th)
    t.join(10)

    assert client.post("/api/reviews/config", json={"translate_to": "fr"}, headers=th).status_code == 422
    r = client.post("/api/reviews/config", json={"translate_to": "off"}, headers=th)
    assert r.status_code == 200 and r.json()["translate_to"] == "off"
    try:
        t, box = _ask_in_background(client, h, sid, "كيف أشغل الحاوية؟")
        item = _wait_answers(client, th, _wait_pending(client, th, sid)["id"], 4)
        assert all(c["translate_to"] is None for c in drafts[-4:])
        assert item["question_lang"] == "ar" and item["question_translation"] is None
        client.post(f"/api/reviews/{item['id']}/select", json={"chosen": "normal", "lang": "he"}, headers=th)
        t.join(10)
    finally:
        client.post("/api/reviews/config", json={"translate_to": "he"}, headers=th)


def test_the_drafting_prompt_asks_for_one_level_and_a_translation_only_when_on():
    assert "Hebrew translation" in tutor._translate_rule("he")
    assert "English translation" in tutor._translate_rule("en")
    assert "leave question_translation empty" in tutor._translate_rule(None)
    for lvl in LEVELS:
        assert lvl.upper() in tutor._LEVEL_RULES[lvl]
    with pytest.raises(ValueError):
        tutor._build_crew("p", "t", "q", "loud")


# --- where the student is, and the chat before the question ----------------------------

def _lab(exercise_id, **extra):
    """A copy of ex3-mcalc registered under `exercise_id` with `extra` on top; pop it when done."""
    import copy
    lab = copy.deepcopy(exercises.get("ex3-mcalc"))
    lab.update(exercise_id=exercise_id, **extra)
    exercises._LOADED[exercise_id] = lab
    return lab


PACED_STEPS = [
    {"label": "A1", "title": "Pull", "text": "Run `docker pull alpine`.",
     "expect_output": [{"match": r"^ALL READY$", "hint": "ALL READY"}]},
    {"label": "A2", "title": "Read", "text": "Read this."},
    {"label": "B1", "title": "Kernel", "text": "Run `uname -r`."},
]


def _record(tc, h, sid, *entries):
    r = tc.post(f"/api/transcript/{sid}", headers=h, json={"entries": list(entries)})
    assert r.status_code == 200, r.text


def _done(tc, th, item, text="ok"):
    r = tc.post(f"/api/reviews/{item['id']}/select", json={"chosen": "own", "lang": "en", "text": text}, headers=th)
    assert r.status_code == 200, r.text


def test_the_card_says_where_the_student_is_and_what_came_before(client, drafts):
    """A class-paced lab: the card names the step (its label and title) and its
    status, and shows the last five transcript entries before the question,
    each cut short, without the question itself."""
    _lab("paced-review-test", steps=PACED_STEPS, pacing="class", open_steps=2)
    try:
        h, sid = _student(client, "paced-review-test")
        th = _teacher(client)
        long_step = "Step one. " * 100  # cut to 400 characters on the card
        _record(client, h, sid,
                {"author": "tutor", "kind": "brief", "content": "Welcome to the lab."},
                {"author": "tutor", "kind": "text", "content": "an old answer, beyond the last five"},
                {"author": "tutor", "kind": "step", "step": 1, "content": long_step},
                {"author": "student", "kind": "output", "step": 1, "content": "something else"},
                {"author": "tutor", "kind": "result", "step": 1, "content": "🔍 That is not the output."},
                {"author": "tutor", "kind": "quiz", "content": "Why is the kernel shared?"},
                {"author": "student", "kind": "text", "content": "What does pull do?"})  # the question, as the chat records it
        t, box = _ask_in_background(client, h, sid, "What does pull do?")
        item = _wait_pending(client, th, sid)
        assert item["step"] == {"n": 1, "total": 3, "label": "A1", "title": "Pull", "status": "open"}
        before = item["before"]
        assert before["source"] == "transcript"
        assert [(e["author"], e["kind"], e["step"]) for e in before["entries"]] == [
            ("tutor", "step", 1), ("student", "output", 1), ("tutor", "result", 1), ("tutor", "quiz", None),
        ] or [(e["author"], e["kind"]) for e in before["entries"]] == [
            ("tutor", "text"), ("tutor", "step"), ("student", "output"), ("tutor", "result"), ("tutor", "quiz"),
        ]
        assert "What does pull do?" not in [e["content"] for e in before["entries"]]
        step_entry = next(e for e in before["entries"] if e["kind"] == "step")
        assert len(step_entry["content"]) == 400 and step_entry["content"].endswith("…")
        assert all(len(e["content"]) <= 400 for e in before["entries"])
        _done(client, th, item)
        t.join(10)

        # Finished every open step: the card shows the last one they did and that they wait for the teacher.
        with db.conn() as c:
            c.execute("INSERT INTO step_checks (session_id, step, answer, status) VALUES (?, 1, '', 'approved')", (sid,))
            c.execute("INSERT INTO step_checks (session_id, step, answer, status) VALUES (?, 2, '', 'approved')", (sid,))
        t, box = _ask_in_background(client, h, sid, "And now?")
        item = _wait_pending(client, th, sid)
        assert item["step"] == {"n": 2, "total": 3, "label": "A2", "title": "Read", "status": "waiting_teacher"}
        # The previous question is now part of what came before (only the new one is left out).
        assert [e["content"] for e in item["before"]["entries"]][-2:] == ["Why is the kernel shared?",
                                                                           "What does pull do?"]
        _done(client, th, item)
        t.join(10)
    finally:
        exercises._LOADED.pop("paced-review-test", None)


def test_a_sign_off_lab_shows_the_step_waiting_for_approval(client, drafts):
    from backend import steps as steps_mod
    _lab("signoff-review-test", steps=[{"title": "Count", "text": "Count the rows.", "expected": "3"},
                                        {"title": "Sum", "text": "Sum them.", "expected": "6"}])
    try:
        h, sid = _student(client, "signoff-review-test")
        th = _teacher(client)
        steps_mod.submit(sid, 1, "Done with step 1: 3 rows")
        t, box = _ask_in_background(client, h, sid, "Is 3 right?")
        item = _wait_pending(client, th, sid)
        assert item["step"] == {"n": 1, "total": 2, "label": "1", "title": "Count", "status": "waiting_check"}
        assert item["before"] == {"source": "transcript", "entries": []}  # nothing recorded: the plugin's chat
        _done(client, th, item)
        t.join(10)
    finally:
        # The pending check must not outlive its exercise: the step-checks list looks the exercise up.
        with db.conn() as c:
            c.execute("DELETE FROM step_checks WHERE session_id = ?", (sid,))
        exercises._LOADED.pop("signoff-review-test", None)


def test_without_a_transcript_the_card_shows_the_model_turns(client, drafts):
    """An exercise that keeps no transcript: the chat before the question is the
    questions and answers in `messages`; no steps means no step line."""
    _lab("no-history-review-test", chat_history=False)
    try:
        h, sid = _student(client, "no-history-review-test")
        th = _teacher(client)
        t, box = _ask_in_background(client, h, sid, "What is a loop?")
        item = _wait_pending(client, th, sid)
        assert item["step"] is None
        assert item["before"] == {"source": "messages", "entries": []}
        _done(client, th, item, "A repeated block.")
        t.join(10)
        t, box = _ask_in_background(client, h, sid, "And a while loop?")
        item = _wait_pending(client, th, sid)
        assert [(e["author"], e["kind"], e["content"]) for e in item["before"]["entries"]] == [
            ("student", "text", "What is a loop?"), ("tutor", "text", "A repeated block."),
        ]
        _done(client, th, item)
        t.join(10)
    finally:
        exercises._LOADED.pop("no-history-review-test", None)


# --- regressions: the question bank and class notes -----------------------------------

def test_saving_an_answer_in_one_language_keeps_the_other(client):
    original = [dict(e) for e in exercises.get("pkg-demo")["faq"]]
    q01 = next(e for e in original if e["id"] == "q01")
    try:
        # The bank's own Hebrew answer sent again (edited): its English text and
        # the entry's other levels stay; who wrote it is unchanged.
        e = bank.save_answer("pkg-demo", "כמה שורות יש בקובץ?", "normal", "he", "טענו ובדקו len(df).",
                             model="bank", merge_into="q01")
        assert e["answers"]["normal"] == {"he": "טענו ובדקו len(df).", "en": q01["answers"]["normal"]["en"]}
        assert e["answers"]["nudge"] == q01["answers"]["nudge"]
        assert "source" not in e and "model" not in e
        back = next(x for x in packages.load_package(packages.exercises_dir() / "pkg-demo")["faq"] if x["id"] == "q01")
        assert back["answers"]["normal"]["en"] == q01["answers"]["normal"]["en"]
        # A level saved in one language: the other gets the same text, as a
        # copy that a later save in the same language replaces.
        q = "What is a tidy table?"
        assert bank.save_answer("pkg-demo", q, "direct", "en", "One row each.", model="m1")["answers"]["direct"] == \
            {"en": "One row each.", "he": "One row each."}
        assert bank.save_answer("pkg-demo", q, "direct", "en", "One row per observation.")["answers"]["direct"] == \
            {"en": "One row per observation.", "he": "One row per observation."}
        assert bank.save_answer("pkg-demo", q, "direct", "he", "שורה לכל תצפית.")["answers"]["direct"] == \
            {"en": "One row per observation.", "he": "שורה לכל תצפית."}
        e = bank.save_answer("pkg-demo", q, "direct", "en", "One row per observation, one column per variable.",
                             model="m2")
        assert e["answers"]["direct"] == {"en": "One row per observation, one column per variable.",
                                          "he": "שורה לכל תצפית."}
        assert (e["source"], e["model"]) == ("teacher", "m2")
    finally:
        exercises.set_faq("pkg-demo", original)


def test_a_bank_write_that_fails_half_way_leaves_faq_yaml_as_it_was(client, monkeypatch):
    ex = exercises.get("pkg-demo")
    folder = packages.exercises_dir() / "pkg-demo"
    before = (folder / "faq.yaml").read_bytes()
    entries = list(ex["faq"])

    class HalfWay:
        def dump(self, data, f):
            f.write("questions:\n  - id: q01\n")
            raise RuntimeError("disk full")

    monkeypatch.setattr(packages, "_rt_yaml", lambda: HalfWay())
    with pytest.raises(RuntimeError):
        bank.save_answer("pkg-demo", "Will this be saved?", "normal", "en", "No.")
    assert (folder / "faq.yaml").read_bytes() == before
    assert not [p.name for p in folder.iterdir() if p.name.endswith(".tmp")]
    assert packages.load_package(folder)["faq"] == entries          # the package still loads
    assert exercises.get("pkg-demo")["faq"] == entries


def test_two_answers_saved_at_once_are_both_kept(client, monkeypatch):
    original = [dict(e) for e in exercises.get("pkg-demo")["faq"]]
    real_set_faq = exercises.set_faq

    def slow_set_faq(exercise_id, entries):
        time.sleep(0.2)  # between reading the bank and writing it back
        real_set_faq(exercise_id, entries)

    monkeypatch.setattr(exercises, "set_faq", slow_set_faq)
    try:
        threads = [threading.Thread(target=bank.save_answer,
                                    args=("pkg-demo", f"race question {i}?", "normal", "en", f"answer {i}"))
                   for i in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        for faq in (exercises.get("pkg-demo")["faq"],
                    packages.load_package(packages.exercises_dir() / "pkg-demo")["faq"]):
            assert {"race question 1?", "race question 2?"} <= {e["question"] for e in faq}
    finally:
        real_set_faq("pkg-demo", original)


def test_a_class_note_is_no_hint_in_the_grade_signals(client):
    from backend.grading import features
    h, sid = _student(client)
    with db.conn() as c:
        c.execute("UPDATE sessions SET course_id = 'c-feat' WHERE id = ?", (sid,))
        c.execute("INSERT INTO messages (session_id, role, body, mode_at_time, created_at) "
                  "VALUES (?, 'user', 'How do I parse argv?', 'mentor', datetime('now', '-60 seconds'))", (sid,))
        c.execute("INSERT INTO messages (session_id, role, body, mode_at_time, answer_level, created_at) "
                  "VALUES (?, 'assistant', 'Look at strtol.', 'mentor', 'nudge', datetime('now', '-50 seconds'))",
                  (sid,))
    assert broadcast.send("ex3-mcalc", "Break until 11:15.", course_id="c-feat")["sent"] == 1
    with db.conn() as c:
        c.execute("INSERT INTO submissions (session_id, source_code) VALUES (?, 'int main(){}')", (sid,))
    f = features.extract(sid)
    assert f["hints"]["total"] == 1 and f["hints"]["nudge"] == 1 and "class" not in f["hints"]
    assert f["timing"]["hint_to_submit_sec"] >= 45     # from the tutor's hint, not the class note
    assert f["timing"]["median_gap_sec"] == 10          # the student's own turns only


def test_a_class_note_reaches_only_the_students_of_the_askers_group(client):
    asker_h, asker = _student(client)                       # outside every course
    mate_h, mate = _student(client)                         # outside every course too
    other_h, other = _student(client)
    with db.conn() as c:
        c.execute("UPDATE sessions SET course_id = 'c-bc' WHERE id = ?", (other,))
        uid = c.execute("SELECT user_id FROM sessions WHERE id = ?", (asker,)).fetchone()["user_id"]
        tid = c.execute("SELECT id FROM users WHERE login_code = 'REV-T'").fetchone()["id"]
        # The asker's other session on the exercise (another login), and a teacher's test session.
        c.execute("INSERT INTO sessions (id, user_id, exercise, mode, variant) "
                  "VALUES ('bc-asker-2', ?, 'ex3-mcalc', 'mentor', 'v1')", (uid,))
        c.execute("INSERT INTO sessions (id, user_id, exercise, mode, variant) "
                  "VALUES ('bc-teacher', ?, 'ex3-mcalc', 'mentor', 'v1')", (tid,))
    try:
        ids = {r["id"] for r in broadcast.recipients("ex3-mcalc", None, exclude_session=asker)}
        assert mate in ids
        assert not ids & {asker, "bc-asker-2", "bc-teacher", other}
        assert {r["id"] for r in broadcast.recipients("ex3-mcalc", "c-bc")} == {other}
    finally:
        with db.conn() as c:
            c.execute("DELETE FROM sessions WHERE id IN ('bc-asker-2', 'bc-teacher')")


def test_saving_the_bank_of_a_bundled_exercise_leaves_the_rest_to_its_file(client, tmp_path):
    import shutil

    from backend.main import EXERCISES_DIR
    eid = "ex5-pycalc"
    folder = tmp_path / "exercises"
    shutil.copytree(EXERCISES_DIR, folder)
    exercises.load_all(folder)
    exercises.load_from_db()
    try:
        assert exercises.get(eid)["edited"] is False
        bank.save_answer(eid, "What does float('3.5') give?", "normal", "en", "The number 3.5.")
        assert exercises.get(eid)["edited"] is False
        with db.conn() as c:
            assert c.execute("SELECT 1 FROM exercises WHERE exercise_id = ?", (eid,)).fetchone() is None
        # The lecturer changes the file later: after a restart the change counts, and the bank is kept.
        path = folder / f"{eid}.yaml"
        text = path.read_text(encoding="utf-8")
        title = next(line for line in text.splitlines() if line.startswith("title_en:"))
        path.write_text(text.replace(title, 'title_en: "Changed in the file"'), encoding="utf-8")
        exercises.reload_all()
        ex = exercises.get(eid)
        assert ex["title_en"] == "Changed in the file" and ex["edited"] is False and ex["source"] == "yaml"
        assert ex["faq"][-1]["question"] == "What does float('3.5') give?"
    finally:
        with db.conn() as c:
            c.execute("DELETE FROM exercise_faq WHERE exercise_id = ?", (eid,))
        exercises.load_all(EXERCISES_DIR)
        exercises.load_from_db()
