"""Class-paced labs (backend/pacing.py): steps open from the start, the
teacher opening the rest per course, the pasted-output check, and quiz
questions that wait for the teacher's approval."""
import copy
import os
import tempfile
from pathlib import Path

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-pacing-tests")

import pytest
import yaml
from fastapi.testclient import TestClient

from backend import db, exercises, packages, pacing, prompting
from backend.agents import grader
from backend.main import app

LAB = "paced-lab-test"
Q1 = "Why is the kernel the same in both containers?"
Q2 = "What does uname -r print?"
STEPS = [
    {"label": "A1", "title": "Pull", "text": "Run `docker pull alpine`.",
     "expect_output": [{"match": r"^ALL READY$", "hint": "ALL READY"}, r"alpine:3\.20"],
     "quiz": [{"q": Q1, "answer": "A container has no kernel of its own."}, {"q": Q2}]},
    {"label": "A2", "title": "Read", "text": "Read this."},
    {"label": "B1", "title": "Kernel", "text": "Run `uname -r`.",
     "expect_output": [{"match": r"azure|linuxkit", "hint": "a kernel version"}]},
    {"label": "B2", "title": "Last", "text": "The end."},
]
GOOD = "docker.io/library/alpine:3.20\nALL READY\n"


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        lab = copy.deepcopy(exercises.get("ex3-mcalc"))
        lab.update({"exercise_id": LAB, "steps": copy.deepcopy(STEPS), "pacing": "class", "open_steps": 2})
        exercises._LOADED[LAB] = lab
        exercises.set_active(LAB)  # students outside every course open the active exercise
        with db.conn() as c:
            c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES ('Pace Teacher', 'PCE-T', 'teacher')")
            c.execute("DELETE FROM system_settings WHERE key = 'review_mode'")
        yield tc
        exercises.set_active("ex3-mcalc")
        exercises._LOADED.pop(LAB, None)


@pytest.fixture
def teacher(client):
    tok = client.post("/api/login", json={"code": "PCE-T", "password": "PCE-T"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _student(tc, code):
    with db.conn() as c:
        c.execute("INSERT INTO users (username, login_code, role) VALUES (?, ?, 'student')", (code, code))
    tok = tc.post("/api/login", json={"code": code, "password": code}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    sid = tc.post("/api/sessions", json={"exercise_id": LAB}, headers=h).json()["session_id"]
    return h, sid


def _state(tc, h, sid):
    r = tc.get(f"/api/steps/state/{sid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _finish(tc, h, sid, step, output=""):
    r = tc.post("/api/steps/finish", headers=h,
                json={"session_id": sid, "step": step, "output": output})
    assert r.status_code == 200, r.text
    return r.json()


def _release(tc, teacher, n, course_id=None):
    r = tc.post(f"/api/pacing/{LAB}/release", headers=teacher, json={"course_id": course_id, "released": n})
    assert r.status_code == 200, r.text
    return r.json()["released"]


def test_open_steps_then_the_teacher_opens_more(client, teacher):
    _release(client, teacher, 2)  # the steps open from the start
    h, sid = _student(client, "PCE-1")
    st = _state(client, h, sid)
    assert st["open"] and st["step"]["label"] == "A1" and st["step"]["needs_output"]
    assert st["released"] == 2 and st["total"] == 4
    assert "Step A1 · Pull" in st["step"]["markdown"]

    # The output lacks the last line: nothing is stored, the student is told what.
    r = _finish(client, h, sid, 1, "docker.io/library/alpine:3.20\n")
    assert r["status"] == "missing" and r["missing"] == ["ALL READY"]
    assert _state(client, h, sid)["current"] == 1

    r = _finish(client, h, sid, 1, GOOD)
    assert r["status"] == "done" and r["ok"] is True and r["quiz"] == 0  # nothing approved yet
    assert r["state"]["step"]["label"] == "A2" and not r["state"]["step"]["needs_output"]
    assert _finish(client, h, sid, 1, GOOD)["status"] == "wrong_step"

    r = _finish(client, h, sid, 2)
    assert r["status"] == "done" and r["ok"] is None
    st = r["state"]
    assert st["waiting_teacher"] and not st["open"] and st["current_label"] == "B1"
    assert _finish(client, h, sid, 3, "x")["status"] == "not_open"

    assert _release(client, teacher, 3) == 3
    st = _state(client, h, sid)
    assert st["open"] and st["step"]["label"] == "B1"


def test_release_is_clamped_and_kept_per_course(client, teacher):
    assert _release(client, teacher, 99) == 4
    assert _release(client, teacher, -5) == 0  # nothing open
    assert _release(client, teacher, 1) == 1   # part of the steps open from the start
    ex = exercises.get(LAB)
    assert _release(client, teacher, 3, "course-x") == 3
    assert pacing.released(ex, "course-x") == 3
    assert pacing.released(ex, None) == 1  # students outside every course: unchanged
    assert pacing.released(ex, "course-y") == 2  # no marker yet: open_steps
    _release(client, teacher, 4)


def test_teacher_can_close_part_of_the_setup_steps(client, teacher):
    h, sid = _student(client, "PCE-60")
    assert _release(client, teacher, 1, "course-s") == 1
    with db.conn() as c:
        c.execute("UPDATE sessions SET course_id = 'course-s' WHERE id = ?", (sid,))
    st = _state(client, h, sid)
    assert st["released"] == 1 and st["open"] and st["step"]["label"] == "A1"
    _finish(client, h, sid, 1, GOOD)
    st = _state(client, h, sid)
    assert st["waiting_teacher"] and not st["open"]  # A2 is open from the start, but closed now
    assert _finish(client, h, sid, 2)["status"] == "not_open"
    _release(client, teacher, 2, "course-s")
    assert _state(client, h, sid)["open"]


def test_a_wrong_output_waits_for_the_teacher_who_can_let_it_through(client, teacher):
    _release(client, teacher, 4)
    h, sid = _student(client, "PCE-2")
    _finish(client, h, sid, 1, GOOD)
    _finish(client, h, sid, 2)
    r = _finish(client, h, sid, 3, "first try")
    assert r["status"] == "missing" and r["state"]["waiting_review"] and r["state"]["current"] == 3
    r = _finish(client, h, sid, 3, "nothing useful")  # pasting again replaces the waiting one
    assert r["status"] == "missing"

    def me():
        view = client.get(f"/api/pacing/{LAB}", headers=teacher).json()
        course = next(c for c in view["courses"] if c["course_id"] == "")
        return view, course, next(s for s in course["students"] if s["username"] == "PCE-2")

    view, course, s = me()
    assert s["current"] == 3 and s["flags"] == []
    assert [(w["label"], w["missing"], w["output"]) for w in s["waiting"]] == \
        [("B1", ["a kernel version"], "nothing useful")]
    assert view["steps"][2]["hints"] == ["a kernel version"]
    assert [x["label"] for x in view["steps"]] == ["A1", "A2", "B1", "B2"]
    assert view["steps"][0]["checked"] and view["steps"][0]["quiz"] == 2

    # Students can't let themselves through, and a wrong step is refused.
    assert client.post(f"/api/pacing/{LAB}/let-through", headers=h,
                       json={"session_id": sid, "step": 3}).status_code == 403
    assert client.post(f"/api/pacing/{LAB}/let-through", headers=teacher,
                       json={"session_id": sid, "step": 2}).status_code == 409
    assert client.post(f"/api/pacing/{LAB}/let-through", headers=teacher,
                       json={"session_id": sid, "step": 3}).status_code == 200

    st = client.get(f"/api/steps/state/{sid}", headers=h).json()
    assert st["current"] == 4 and st["open"] and not st["waiting_review"]
    view, course, s = me()
    assert s["current"] == 4 and s["current_label"] == "B2" and s["waiting"] == []
    assert s["flags"] == [{"step": 3, "label": "B1", "missing": ["a kernel version"],
                           "output": "nothing useful"}]
    assert course["done"]["3"] >= 1 and course["here"]["4"] >= 1


def test_a_right_output_after_a_wrong_one_clears_the_wait(client, teacher):
    _release(client, teacher, 4)
    h, sid = _student(client, "PCE-11")
    _finish(client, h, sid, 1, GOOD)
    _finish(client, h, sid, 2)
    assert _finish(client, h, sid, 3, "oops")["status"] == "missing"
    assert _finish(client, h, sid, 3, "Linux 6.8.0-azure")["status"] == "done"
    view = client.get(f"/api/pacing/{LAB}", headers=teacher).json()
    s = next(s for c in view["courses"] for s in c["students"] if s["username"] == "PCE-11")
    assert s["current"] == 4 and s["waiting"] == [] and s["flags"] == []


def test_quiz_waits_for_approval_and_blocks_the_next_step(client, teacher, monkeypatch):
    graded = {}

    async def fake_grade(question, answer, params, reference=None):
        graded.update(question=question, answer=answer, reference=reference)
        return 2, "נכון"

    monkeypatch.setattr(grader, "grade", fake_grade)
    view = client.get(f"/api/pacing/{LAB}", headers=teacher).json()
    q1 = next(q for q in view["quiz"] if q["q"] == Q1)
    assert q1["approved"] is False and q1["label"] == "A1"

    # Approve one question, in the teacher's own wording.
    r = client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher,
                    json={"approved": True, "body": "Why do both containers show the same kernel?"})
    assert r.status_code == 200 and r.json()["approved"] is True
    assert client.post(f"/api/pacing/{LAB}/quiz/nope", headers=teacher, json={"approved": True}).status_code == 404

    h, sid = _student(client, "PCE-3")
    r = _finish(client, h, sid, 1, GOOD)
    assert r["status"] == "done" and r["quiz"] == 1
    st = r["state"]
    assert st["quiz_pending"] == 1 and not st["open"] and not st["waiting_teacher"]
    assert _finish(client, h, sid, 2)["status"] == "quiz_pending"

    pending = client.get(f"/api/probes/pending/{sid}", headers=h).json()
    assert len(pending) == 1
    assert pending[0]["source"] == "quiz" and pending[0]["quiz_step"] == "A1"
    assert pending[0]["body"] == "Why do both containers show the same kernel?"  # the approved wording

    r = client.post("/api/probes/answer", headers=h, json={"probe_id": pending[0]["id"], "answer": "no kernel"})
    assert r.status_code == 200 and r.json()["auto_grade"] == 2
    assert graded["reference"] == "A container has no kernel of its own."
    st = _state(client, h, sid)
    assert st["open"] and st["step"]["label"] == "A2"

    # Withdrawing the approval: later students get no question.
    client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": False})
    h4, sid4 = _student(client, "PCE-4")
    assert _finish(client, h4, sid4, 1, GOOD)["quiz"] == 0


def test_always_question_is_asked_without_approval(client, teacher, monkeypatch):
    qx = "What does the code you just pasted do?"
    lab = copy.deepcopy(exercises.get(LAB))
    lab["steps"][0]["quiz"] = [{"q": qx, "answer": "It writes two files.", "always": True}]
    monkeypatch.setitem(exercises._LOADED, LAB, lab)
    item = next(q for q in pacing.quiz_items(lab) if q["q"] == qx)
    assert item["always"] and item["approved"] and item["step"] == 1

    h, sid = _student(client, "PCE-AL1")
    assert _finish(client, h, sid, 1, GOOD)["quiz"] == 1
    pending = client.get(f"/api/probes/pending/{sid}", headers=h).json()
    assert [p["body"] for p in pending] == [qx]

    # The dashboard's choice wins: switched off, later students aren't asked.
    client.post(f"/api/pacing/{LAB}/quiz/{item['key']}", headers=teacher, json={"approved": False})
    assert not next(q for q in pacing.quiz_items(lab) if q["q"] == qx)["approved"]
    h2, sid2 = _student(client, "PCE-AL2")
    assert _finish(client, h2, sid2, 1, GOOD)["quiz"] == 0


def test_package_rejects_a_non_boolean_always(tmp_path):
    folder = tmp_path / "always-lab"
    (folder / "files").mkdir(parents=True)
    (folder / "exercise.yaml").write_text(yaml.safe_dump({
        "exercise_id": "always-lab", "title_en": "Always", "default_mode": "mentor", "brief_md": "Hi",
        "steps": [{"title": "One", "text": "Paste it.", "minutes": 1}]}), encoding="utf-8")
    (folder / "teacher.yaml").write_text(yaml.safe_dump({"steps": [
        {"expected": "x", "quiz": [{"q": "What does it do?", "answer": "x", "always": "yes"}]}]}), encoding="utf-8")
    result = packages.validate_package(folder)
    assert not result["ok"] and any("always" in e for e in result["errors"])


def test_changed_question_text_needs_a_new_approval(client):
    ex = exercises.get(LAB)
    key = pacing.quiz_key(Q2)
    pacing.set_quiz(ex, key, True)
    assert next(q for q in pacing.quiz_items(ex) if q["key"] == key)["approved"]
    changed = copy.deepcopy(ex)
    changed["steps"][0]["quiz"][1] = {"q": Q2 + " Explain."}
    assert not next(q for q in pacing.quiz_items(changed) if q["step"] == 1 and "Explain" in q["q"])["approved"]
    # Whitespace alone doesn't change the key.
    assert pacing.quiz_key("a  b\n c") == pacing.quiz_key("a b c")


def test_typed_done_gets_the_button_how_to_without_a_model(client):
    h, sid = _student(client, "PCE-5")
    r = client.post("/api/ask", headers=h, json={"session_id": sid, "message": "Done with step 1"})
    assert r.status_code == 200
    assert "Done" in r.text and "button" in r.text
    assert _state(client, h, sid)["current"] == 1  # nothing finished


def test_tutor_sees_only_the_current_step(client):
    h, sid = _student(client, "PCE-6")
    s = {"id": sid, "exercise": LAB, "variant": _variant(sid), "mode": "mentor", "course_id": None}
    prompt = prompting.system_prompt_for(s)
    assert "Step A1 · Pull" in prompt and "Kernel" not in prompt and "Done with step" not in prompt


def _variant(sid):
    with db.conn() as c:
        return c.execute("SELECT variant FROM sessions WHERE id = ?", (sid,)).fetchone()["variant"]


def test_a_paced_lab_resumes_an_old_session(client):
    h, sid = _student(client, "PCE-7")
    with db.conn() as c:
        c.execute("UPDATE sessions SET last_active_at = datetime('now', '-3 hours') WHERE id = ?", (sid,))
    again = client.post("/api/sessions", json={"exercise_id": LAB}, headers=h).json()["session_id"]
    assert again == sid


def test_students_cannot_open_steps_or_read_the_class(client):
    h, sid = _student(client, "PCE-8")
    assert client.post(f"/api/pacing/{LAB}/release", headers=h, json={"released": 4}).status_code == 403
    assert client.get(f"/api/pacing/{LAB}", headers=h).status_code == 403
    other_h, _ = _student(client, "PCE-9")
    assert client.get(f"/api/steps/state/{sid}", headers=other_h).status_code == 403


def test_brief_has_no_step_and_says_paced(client):
    h, sid = _student(client, "PCE-10")
    r = client.get("/api/exercises/active", headers=h, params={"variant": _variant(sid), "session_id": sid})
    body = r.json()
    assert body["pacing"] == "class" and body["steps_total"] == 4
    assert "Step 1 of" not in body["brief_md"]


def test_validation():
    base = {"exercise_id": "x", "title_en": "x", "default_mode": "mentor", "brief_md": "x",
            "variants": [{"id": "a"}], "steps": [{"title": "t", "text": "t"}]}
    exercises.validate({**base, "pacing": "class", "open_steps": 1}, "t")
    with pytest.raises(ValueError, match="pacing"):
        exercises.validate({**base, "pacing": "everyone"}, "t")
    with pytest.raises(ValueError, match="open_steps"):
        exercises.validate({**base, "pacing": "class", "open_steps": 5}, "t")
    with pytest.raises(ValueError, match="needs steps"):
        exercises.validate({**{k: v for k, v in base.items() if k != "steps"}, "pacing": "class"}, "t")
    with pytest.raises(ValueError, match="workspace"):
        exercises.validate({**base, "workspace": "laptop"}, "t")


def _package(tmp: Path, teacher_steps) -> Path:
    folder = tmp / "paced-pkg"
    folder.mkdir()
    (folder / "exercise.yaml").write_text(yaml.safe_dump({
        "exercise_id": "paced-pkg", "title_en": "Paced", "default_mode": "mentor", "brief_md": "Hi",
        "pacing": "class", "open_steps": 1, "workspace": "codespace",
        "steps": [{"label": "A1", "title": "One", "text": "```bash\nsed -i 's/a/b/' f\n```"},
                  {"label": "A2", "title": "Two", "text": "two"}],
    }), encoding="utf-8")
    (folder / "teacher.yaml").write_text(yaml.safe_dump({"steps": teacher_steps}), encoding="utf-8")
    return folder


def test_package_with_output_checks_and_quiz(tmp_path):
    folder = _package(tmp_path, [
        {"expected": "b", "expect_output": [r"^ok$", {"match": "done", "hint": "the word done"}],
         "quiz": [{"q": "Why?", "answer": "Because."}, {"q": "How?"}]},
        {"expected": "x"},
    ])
    result = packages.validate_package(folder)
    assert result["ok"], result["errors"]
    assert result["summary"]["checked_steps"] == 1 and result["summary"]["quiz_questions"] == 2
    assert any("no `answer:`" in w for w in result["warnings"])
    # A Codespace exercise isn't linted for Windows/macOS differences (sed -i).
    assert not any("sed" in w for w in result["warnings"] + result["errors"])
    ex = packages.load_package(folder)
    assert ex["steps"][0]["expect_output"][0] == r"^ok$"
    # Teacher-only keys never reach exercise.yaml on export.
    student, teacher_part = packages.split_teacher_fields(ex)
    assert "quiz" not in student["steps"][0] and "quiz" in teacher_part["steps"][0]


def test_package_with_a_broken_pattern(tmp_path):
    folder = _package(tmp_path, [{"expect_output": ["(unclosed"]}])
    result = packages.validate_package(folder)
    assert not result["ok"] and "(unclosed" in result["errors"][0] and "broken" in result["errors"][0]


MARKDOWN_LAB = """---
exercise_id: md-lab
title_en: MD lab
default_mode: mentor
pacing: class
open_steps: 1
---

# brief
Hello **class**.

# steps

## A1 | First | 3
Run it:

```bash
# a comment, not a header
cat > f <<'END'
## not a step either
END
```

~~~yaml teacher
expected: f exists
expect_output:
  - match: '^ok$'
    hint: ok
quiz:
  - q: Why?
    answer: Because.
~~~

## A2 | Second |
Read.
"""


def test_steps_from_markdown(tmp_path, monkeypatch):
    """scripts/steps_from_markdown.py: headers inside code blocks stay code, the
    teacher block goes to teacher.yaml."""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "steps_from_markdown", Path(__file__).parent.parent / "scripts" / "steps_from_markdown.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    source = tmp_path / "source.md"
    source.write_text(MARKDOWN_LAB, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["steps_from_markdown.py", str(source)])
    mod.main()
    ex = yaml.safe_load((tmp_path / "exercise.yaml").read_text(encoding="utf-8"))
    teacher_part = yaml.safe_load((tmp_path / "teacher.yaml").read_text(encoding="utf-8"))
    assert ex["brief_md"] == "Hello **class**.\n" and ex["pacing"] == "class"
    assert [s["label"] for s in ex["steps"]] == ["A1", "A2"] and ex["steps"][0]["minutes"] == 3
    assert "minutes" not in ex["steps"][1]
    text = ex["steps"][0]["text"]
    assert "# a comment, not a header" in text and "## not a step either" in text and "~~~" not in text
    assert teacher_part["steps"][0]["expect_output"][0]["match"] == "^ok$"
    assert teacher_part["steps"][0]["quiz"] == [{"q": "Why?", "answer": "Because."}]
    assert teacher_part["steps"][1] == {}


# --- the transcript, going back to an earlier step, and resuming ----------------------

def _log(tc, h, sid, *entries):
    r = tc.post(f"/api/transcript/{sid}", headers=h, json={"entries": list(entries)})
    assert r.status_code == 200, r.text
    return r.json()["ids"]


def test_transcript_is_kept_and_replayed_in_order(client, teacher):
    h, sid = _student(client, "PCE-20")
    _log(client, h, sid, {"author": "tutor", "kind": "brief", "content": "Welcome"},
         {"author": "tutor", "kind": "step", "step": 1, "content": "Step A1"})
    _log(client, h, sid, {"author": "student", "kind": "output", "step": 1, "content": "ALL READY"})
    t = client.get(f"/api/transcript/{sid}", headers=h).json()
    assert t["enabled"] and not t["truncated"]
    assert [(e["author"], e["kind"], e["step"], e["content"]) for e in t["entries"]] == [
        ("tutor", "brief", None, "Welcome"), ("tutor", "step", 1, "Step A1"),
        ("student", "output", 1, "ALL READY")]
    assert t["last_id"] == t["entries"][-1]["id"]
    # After a given id, and only the server's own notes.
    first = t["entries"][0]["id"]
    assert len(client.get(f"/api/transcript/{sid}", headers=h, params={"after": first}).json()["entries"]) == 2
    assert client.get(f"/api/transcript/{sid}", headers=h, params={"origin": "server"}).json()["entries"] == []
    # The teacher reads any session; another student reads and writes none.
    assert len(client.get(f"/api/transcript/{sid}", headers=teacher).json()["entries"]) == 3
    other, _ = _student(client, "PCE-21")
    assert client.get(f"/api/transcript/{sid}", headers=other).status_code == 403
    assert client.post(f"/api/transcript/{sid}", headers=other,
                       json={"entries": [{"author": "student", "content": "x"}]}).status_code == 403
    assert client.post(f"/api/transcript/{sid}", headers=teacher,
                       json={"entries": [{"author": "tutor", "content": "x"}]}).status_code == 403
    # Unknown kinds and authors are refused.
    assert client.post(f"/api/transcript/{sid}", headers=h,
                       json={"entries": [{"author": "tutor", "kind": "weird", "content": "x"}]}).status_code == 400
    assert client.post(f"/api/transcript/{sid}", headers=h,
                       json={"entries": [{"author": "admin", "content": "x"}]}).status_code == 422


def test_replay_is_capped_and_says_so(client, monkeypatch):
    h, sid = _student(client, "PCE-22")
    _log(client, h, sid, *[{"author": "tutor", "content": f"m{i}"} for i in range(5)])
    monkeypatch.setenv("CHAT_HISTORY_REPLAY_MAX", "3")
    t = client.get(f"/api/transcript/{sid}", headers=h).json()
    assert [e["content"] for e in t["entries"]] == ["m2", "m3", "m4"] and t["truncated"]


def test_chat_history_can_be_switched_off(client):
    h, sid = _student(client, "PCE-23")
    ex = exercises.get(LAB)
    ex["chat_history"] = False
    try:
        assert _log(client, h, sid, {"author": "tutor", "content": "x"}) == []
        t = client.get(f"/api/transcript/{sid}", headers=h).json()
        assert t == {"enabled": False, "entries": [], "truncated": False, "last_id": 0}
    finally:
        ex.pop("chat_history")
    assert client.get(f"/api/transcript/{sid}", headers=h).json()["entries"] == []  # nothing was kept


def test_teacher_sends_a_student_back_and_the_chat_hears_it(client, teacher, monkeypatch):
    async def right(question, answer, params, reference=None):
        return 2, "right"

    monkeypatch.setattr(grader, "grade", right)  # 2/2: moves on by itself
    ex = exercises.get(LAB)
    for q in pacing.quiz_items(ex):
        pacing.set_quiz(ex, q["key"], q["q"] == Q2)  # only Q2 (step A1) is asked
    _release(client, teacher, 4)
    h, sid = _student(client, "PCE-24")
    assert _finish(client, h, sid, 1, GOOD)["quiz"] == 1
    probe = client.get(f"/api/probes/pending/{sid}", headers=h).json()[0]
    client.post("/api/probes/answer", headers=h, json={"probe_id": probe["id"], "answer": "6.8"})
    _finish(client, h, sid, 2)
    assert _finish(client, h, sid, 3, "no kernel here")["status"] == "missing"  # waits for the teacher
    assert _state(client, h, sid)["current"] == 3

    # Back to A2: step 2 and later no longer count, the waiting output is gone.
    r = client.post(f"/api/sessions/{sid}/reset", headers=teacher, json={"step": 2})
    assert r.status_code == 200 and r.json() == {"session_id": sid, "from": 3, "to": 2}
    st = _state(client, h, sid)
    assert st["current"] == 2 and st["open"] and not st["waiting_review"]
    notes = client.get(f"/api/transcript/{sid}", headers=h, params={"origin": "server"}).json()["entries"]
    assert [(n["kind"], n["step"], n["author"]) for n in notes] == [("reset", 2, "system")]
    assert "step A2" in notes[0]["content"]
    with db.conn() as c:
        kept = c.execute("SELECT step, status FROM step_checks WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
    assert [(k["step"], k["status"]) for k in kept] == [(1, "approved"), (2, "reset"), (3, "reset")]

    # Back to the beginning: A1's question is asked again when A1 is done again.
    r = client.post(f"/api/sessions/{sid}/reset", headers=teacher, json={"step": 1})
    assert r.json()["to"] == 1
    assert _finish(client, h, sid, 1, GOOD)["quiz"] == 1
    # ...and a reset withdraws a question still waiting for its answer.
    client.post(f"/api/sessions/{sid}/reset", headers=teacher, json={"step": 1})
    assert client.get(f"/api/probes/pending/{sid}", headers=h).json() == []
    st = _state(client, h, sid)
    assert st["current"] == 1 and st["open"]

    # Forward is not a reset; a student can't reset.
    assert client.post(f"/api/sessions/{sid}/reset", headers=teacher, json={"step": 4}).json()["to"] == 1
    assert client.post(f"/api/sessions/{sid}/reset", headers=h, json={"step": 1}).status_code == 403
    pacing.set_quiz(ex, pacing.quiz_key(Q2), False)


def test_teacher_sends_the_whole_course_back(client, teacher):
    _release(client, teacher, 4, "course-z")
    with db.conn() as c:
        c.execute("INSERT OR IGNORE INTO courses (course_id, name) VALUES ('course-z', 'Z')")
        c.execute("INSERT OR IGNORE INTO course_exercises (course_id, exercise_id) VALUES ('course-z', ?)", (LAB,))
    people = []
    for code in ("PCE-30", "PCE-31", "PCE-32"):
        with db.conn() as c:
            c.execute("INSERT INTO users (username, login_code, role) VALUES (?, ?, 'student')", (code, code))
            uid = c.execute("SELECT id FROM users WHERE login_code = ?", (code,)).fetchone()["id"]
            c.execute("INSERT INTO course_members (course_id, user_id) VALUES ('course-z', ?)", (uid,))
        tok = client.post("/api/login", json={"code": code, "password": code}).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        sid = client.post("/api/sessions", json={"course_id": "course-z", "exercise_id": LAB},
                          headers=h).json()["session_id"]
        people.append((h, sid))
    for h, sid in people[:2]:
        _finish(client, h, sid, 1, GOOD)
        _finish(client, h, sid, 2)
    r = client.post(f"/api/exercises/{LAB}/reset", headers=teacher, json={"course_id": "course-z", "step": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["sessions"] == 3 and body["moved"] == 2
    assert [_state(client, h, sid)["current"] for h, sid in people] == [2, 2, 1]
    # Students outside the course were not touched.
    assert all(res["session_id"] in {sid for _, sid in people} for res in body["results"])


def test_resume_minutes_decides_which_session_a_login_opens(client):
    h, sid = _student(client, "PCE-40")
    with db.conn() as c:
        c.execute("UPDATE sessions SET last_active_at = datetime('now', '-3 hours') WHERE id = ?", (sid,))
    ex = exercises.get(LAB)
    ex["resume_minutes"] = 60
    try:
        fresh = client.post("/api/sessions", json={"exercise_id": LAB}, headers=h).json()["session_id"]
        assert fresh != sid  # older than an hour: a new session
        ex["resume_minutes"] = 0
        with db.conn() as c:
            c.execute("UPDATE sessions SET last_active_at = datetime('now', '-9 days') WHERE id = ?", (fresh,))
            c.execute("UPDATE sessions SET last_active_at = datetime('now', '-10 days') WHERE id = ?", (sid,))
        assert client.post("/api/sessions", json={"exercise_id": LAB}, headers=h).json()["session_id"] == fresh
    finally:
        ex.pop("resume_minutes")


def test_history_settings_are_validated():
    base = {"exercise_id": "x", "title_en": "x", "default_mode": "mentor", "brief_md": "x",
            "variants": [{"id": "v1", "params": {}, "test_inputs": []}]}
    exercises._validate({**base, "chat_history": False, "resume_minutes": 0}, "t")
    with pytest.raises(ValueError, match="chat_history"):
        exercises._validate({**base, "chat_history": "yes"}, "t")
    with pytest.raises(ValueError, match="resume_minutes"):
        exercises._validate({**base, "resume_minutes": -5}, "t")


# --- output pasted as a chat message -------------------------------------------------------

def _detect(tc, h, sid, text):
    r = tc.post("/api/steps/detect", headers=h, json={"session_id": sid, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_output_pasted_as_a_message_is_recognized(client):
    h, sid = _student(client, "PCE-50")
    for q in pacing.quiz_items(exercises.get(LAB)):
        pacing.set_quiz(exercises.get(LAB), q["key"], False)
    found = {"step": 1, "label": "A1", "needs_output": True, "checks": 2}
    # Default (confirm): a full match is the answer; anything else, ask the student.
    assert _detect(client, h, sid, GOOD) == {"kind": "output", "matched": 2, **found}
    maybe = _detect(client, h, sid, "ALL READY")
    assert maybe == {"kind": "maybe", "matched": 1, **found}
    assert "hint" not in str(maybe) and "alpine" not in str(maybe)  # never gives the checks away
    assert _detect(client, h, sid, "why does docker pull take so long?") == {"kind": "maybe", "matched": 0, **found}
    assert _detect(client, h, sid, "   ") == {"kind": "question"}

    ex = exercises.get(LAB)
    try:
        ex["output_in_chat"] = "accept"
        assert _detect(client, h, sid, GOOD)["kind"] == "output"
        assert _detect(client, h, sid, "ALL READY")["kind"] == "maybe"
        assert _detect(client, h, sid, "why does docker pull take so long?") == {"kind": "question"}
        ex["output_in_chat"] = "ask"
        assert _detect(client, h, sid, GOOD)["kind"] == "maybe"
        assert _detect(client, h, sid, "why?") == {"kind": "question"}
        ex["output_in_chat"] = "off"
        assert _detect(client, h, sid, GOOD) == {"kind": "question"}
    finally:
        ex.pop("output_in_chat")
    # Another student can't ask about this session.
    other, _ = _student(client, "PCE-51")
    assert client.post("/api/steps/detect", headers=other, json={"session_id": sid, "text": GOOD}).status_code == 403

    # A step without checks: confirm asks "a question, or done with the step?"; accept doesn't.
    _finish(client, h, sid, 1, GOOD)
    assert _detect(client, h, sid, "I read it") == {"kind": "maybe", "step": 2, "label": "A2", "needs_output": False}
    try:
        ex["output_in_chat"] = "accept"
        assert _detect(client, h, sid, "I read it") == {"kind": "question"}
    finally:
        ex.pop("output_in_chat")
    # No open step (waiting for the teacher): always a question.


def test_ask_finishes_the_step_when_the_message_is_its_output(client):
    h, sid = _student(client, "PCE-52")
    r = client.post("/api/ask", headers=h, json={"session_id": sid, "message": GOOD})
    assert r.status_code == 200 and "A1" in r.text
    st = _state(client, h, sid)
    assert st["current"] == 2


def test_output_in_chat_is_validated():
    base = {"exercise_id": "x", "title_en": "x", "default_mode": "mentor", "brief_md": "x",
            "variants": [{"id": "v1", "params": {}, "test_inputs": []}]}
    exercises._validate({**base, "output_in_chat": "ask"}, "t")
    exercises._validate({**base, "output_in_chat": "confirm"}, "t")
    with pytest.raises(ValueError, match="output_in_chat"):
        exercises._validate({**base, "output_in_chat": "maybe"}, "t")


def test_a_question_approved_late_is_asked_of_students_past_its_step(client, teacher):
    ex = exercises.get(LAB)
    for q in pacing.quiz_items(ex):
        pacing.set_quiz(ex, q["key"], False)
    _release(client, teacher, 2, "course-q")
    with db.conn() as c:
        c.execute("INSERT OR IGNORE INTO courses (course_id, name) VALUES ('course-q', 'Q')")
    people = {}
    for code in ("PCE-70", "PCE-71"):
        h, sid = _student(client, code)
        with db.conn() as c:
            c.execute("UPDATE sessions SET course_id = 'course-q' WHERE id = ?", (sid,))
        people[code] = (h, sid)
    h70, sid70 = people["PCE-70"]
    assert _finish(client, h70, sid70, 1, GOOD)["quiz"] == 0     # nothing approved yet: no question
    st = _state(client, h70, sid70)
    assert st["current"] == 2 and st["open"]

    key = pacing.quiz_key(Q1)
    view = client.get(f"/api/pacing/{LAB}", headers=teacher).json()
    course = next(c for c in view["courses"] if c["course_id"] == "course-q")
    assert course["quiz_missed"][key] == 1                       # PCE-70 is past A1, never asked
    assert view["steps"][0]["quiz"] == 2 and view["steps"][0]["quiz_approved"] == 0

    r = client.post(f"/api/pacing/{LAB}/quiz/{key}", headers=teacher,
                    json={"approved": True, "ask_finished": True, "course_id": "course-q"})
    assert r.status_code == 200 and r.json()["asked_now"] == 1
    pending = client.get(f"/api/probes/pending/{sid70}", headers=h70).json()
    assert [p["quiz_step"] for p in pending] == ["A1"]
    st = _state(client, h70, sid70)
    assert st["quiz_pending"] == 1 and not st["open"]            # A2 waits for the answer
    assert client.get(f"/api/probes/pending/{people['PCE-71'][1]}", headers=people["PCE-71"][0]).json() == []

    # Asking again doesn't ask twice; the counter is back to 0.
    r = client.post(f"/api/pacing/{LAB}/quiz/{key}", headers=teacher,
                    json={"approved": True, "ask_finished": True, "course_id": "course-q"})
    assert r.json()["asked_now"] == 0
    view = client.get(f"/api/pacing/{LAB}", headers=teacher).json()
    assert next(c for c in view["courses"] if c["course_id"] == "course-q")["quiz_missed"][key] == 0
    # Without ask_finished, approving asks nobody at once.
    key2 = pacing.quiz_key(Q2)
    assert client.post(f"/api/pacing/{LAB}/quiz/{key2}", headers=teacher,
                       json={"approved": True}).json()["asked_now"] == 0
    for q in pacing.quiz_items(ex):
        pacing.set_quiz(ex, q["key"], False)


def test_a_student_with_no_open_step_only_asks_questions(client, teacher):
    _release(client, teacher, 1, "course-w")
    h, sid = _student(client, "PCE-80")
    with db.conn() as c:
        c.execute("UPDATE sessions SET course_id = 'course-w' WHERE id = ?", (sid,))
    _finish(client, h, sid, 1, GOOD)
    assert _state(client, h, sid)["waiting_teacher"]
    assert _detect(client, h, sid, "what happens next?") == {"kind": "question"}


def test_teacher_sends_a_wrong_output_back(client, teacher):
    for q in pacing.quiz_items(exercises.get(LAB)):
        pacing.set_quiz(exercises.get(LAB), q["key"], False)
    _release(client, teacher, 4)
    h, sid = _student(client, "PCE-90")
    _finish(client, h, sid, 1, GOOD)
    _finish(client, h, sid, 2)
    assert _finish(client, h, sid, 3, "asdfasdf")["status"] == "missing"

    # Only the teacher, and only for an output that waits at that step.
    assert client.post(f"/api/pacing/{LAB}/decline", headers=h,
                       json={"session_id": sid, "step": 3}).status_code == 403
    assert client.post(f"/api/pacing/{LAB}/decline", headers=teacher,
                       json={"session_id": sid, "step": 2}).status_code == 409
    r = client.post(f"/api/pacing/{LAB}/decline", headers=teacher,
                    json={"session_id": sid, "step": 3, "note": "Run uname -r inside the container."})
    assert r.status_code == 200

    st = _state(client, h, sid)
    assert st["current"] == 3 and st["open"] and not st["waiting_review"]  # same step, nothing waits
    view = client.get(f"/api/pacing/{LAB}", headers=teacher).json()
    me = next(s for c in view["courses"] for s in c["students"] if s["session_id"] == sid)
    assert me["waiting"] == [] and me["flags"] == []
    notes = client.get(f"/api/transcript/{sid}", headers=h, params={"origin": "server"}).json()["entries"]
    assert [(n["kind"], n["step"]) for n in notes] == [("returned", 3)]
    assert "isn't right yet" in notes[0]["content"] and "Run uname -r inside the container." in notes[0]["content"]
    with db.conn() as c:
        row = c.execute("SELECT status, teacher_note, answer FROM step_checks WHERE session_id = ? AND step = 3",
                        (sid,)).fetchone()
    assert (row["status"], row["teacher_note"], row["answer"]) == ("returned", "Run uname -r inside the container.",
                                                                  "asdfasdf")  # kept for the record
    assert client.post(f"/api/pacing/{LAB}/decline", headers=teacher,
                       json={"session_id": sid, "step": 3}).status_code == 409  # already sent back

    # They paste again: a wrong one waits again, a right one moves them on.
    assert _finish(client, h, sid, 3, "still wrong")["status"] == "missing"
    assert _finish(client, h, sid, 3, "Linux 6.8.0-azure")["status"] == "done"
    assert _state(client, h, sid)["current"] == 4


def _open_quiz(client, teacher, monkeypatch, code):
    """A student who finished A1 and has its (approved) quiz question open."""
    async def fake_grade(question, answer, params, reference=None):
        return 1, "partly"

    monkeypatch.setattr(grader, "grade", fake_grade)
    q1 = next(q for q in client.get(f"/api/pacing/{LAB}", headers=teacher).json()["quiz"] if q["q"] == Q1)
    client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": True})
    h, sid = _student(client, code)
    assert _finish(client, h, sid, 1, GOOD)["quiz"] == 1
    return h, sid, q1


def _session_row(sid):
    with db.conn() as c:
        return dict(c.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone())


def _classify(client, h, sid, text):
    r = client.post("/api/probes/classify", headers=h, json={"session_id": sid, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_student_with_an_open_question_can_still_ask(client, teacher, monkeypatch):
    h, sid, q1 = _open_quiz(client, teacher, monkeypatch, "PCE-AQ1")
    try:
        probe_id = client.get(f"/api/probes/pending/{sid}", headers=h).json()[0]["id"]
        # detect (default): an answer is the answer; a question asks the student first.
        d = _classify(client, h, sid, "Because a container shares the host's kernel.")
        assert (d["kind"], d["mode"], d["probe"]["id"]) == ("answer", "detect", probe_id)
        assert _classify(client, h, sid, "What does kernel mean here?")["kind"] == "maybe"
        assert _classify(client, h, sid, "לא הבנתי את השאלה")["kind"] == "maybe"
        # The tutor knows the open question and must not answer it for them.
        prompt = prompting.system_prompt_for(_session_row(sid))
        assert "OPEN QUESTIONS" in prompt and "never answer them" in prompt
        ex = exercises.get(LAB)
        ex["answer_in_chat"] = "confirm"
        assert _classify(client, h, sid, "Because a container shares the host's kernel.")["kind"] == "maybe"
        ex["answer_in_chat"] = "answer"
        assert _classify(client, h, sid, "What does kernel mean here?")["kind"] == "answer"
        ex.pop("answer_in_chat")

        r = client.post("/api/probes/answer", headers=h, json={"probe_id": probe_id, "answer": "shared kernel"})
        assert r.status_code == 200
        # Answered: nothing is open, a message is an ordinary one, and the question is closed.
        assert _classify(client, h, sid, "shared kernel")["kind"] == "none"
        assert "OPEN QUESTIONS" not in prompting.system_prompt_for(_session_row(sid))
        again = client.post("/api/probes/answer", headers=h, json={"probe_id": probe_id, "answer": "again"})
        assert again.status_code == 409
    finally:
        exercises.get(LAB).pop("answer_in_chat", None)
        client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": False})


def test_a_step_output_while_a_teachers_question_is_open_goes_to_the_step(client, teacher):
    # A teacher's question can be open while a step is: the step's output is not its answer.
    h, sid = _student(client, "PCE-AQ3")
    assert client.post("/api/probe/send", headers=teacher,
                       json={"session_id": sid, "bodies": ["What did you pull?"]}).status_code == 200
    assert _classify(client, h, sid, GOOD)["kind"] == "step"
    assert _classify(client, h, sid, "docker.io/library/alpine:3.20")["kind"] == "step"  # a partial match
    assert _classify(client, h, sid, "The alpine image")["kind"] == "answer"
    assert _classify(client, h, sid, "Which image do you mean?")["kind"] == "maybe"


def test_a_withdrawn_question_cant_be_answered(client, teacher, monkeypatch):
    h, sid, q1 = _open_quiz(client, teacher, monkeypatch, "PCE-AQ2")
    try:
        probe_id = client.get(f"/api/probes/pending/{sid}", headers=h).json()[0]["id"]
        assert client.post(f"/api/sessions/{sid}/reset", headers=teacher, json={"step": 1}).status_code == 200
        assert client.get(f"/api/probes/pending/{sid}", headers=h).json() == []
        r = client.post("/api/probes/answer", headers=h, json={"probe_id": probe_id, "answer": "late"})
        assert r.status_code == 409 and "cancelled" in r.json()["detail"]
    finally:
        client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": False})


def test_answer_in_chat_is_validated():
    base = {"exercise_id": "x", "title_en": "x", "default_mode": "mentor", "brief_md": "x",
            "variants": [{"id": "v1", "params": {}, "test_inputs": []}]}
    exercises._validate({**base, "answer_in_chat": "confirm"}, "t")
    with pytest.raises(ValueError, match="answer_in_chat"):
        exercises._validate({**base, "answer_in_chat": "maybe"}, "t")


# --- a quiz answer graded 0/2 waits for the teacher (exercise.yaml quiz_review) --------

def _held_answer(client, teacher, monkeypatch, code, grade=0, why="not about the kernel"):
    """A student who finished A1 and answered its quiz question; the grader gave `grade`."""
    async def fake_grade(question, answer, params, reference=None):
        return grade, why

    monkeypatch.setattr(grader, "grade", fake_grade)
    q1 = next(q for q in client.get(f"/api/pacing/{LAB}", headers=teacher).json()["quiz"] if q["q"] == Q1)
    client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": True})
    h, sid = _student(client, code)
    assert _finish(client, h, sid, 1, GOOD)["quiz"] == 1
    probe = client.get(f"/api/probes/pending/{sid}", headers=h).json()[0]
    r = client.post("/api/probes/answer", headers=h, json={"probe_id": probe["id"], "answer": "no idea"})
    assert r.status_code == 200, r.text
    return h, sid, q1, probe, r.json()


def _pacing_student(client, teacher, code):
    view = client.get(f"/api/pacing/{LAB}", headers=teacher).json()
    return next(s for c in view["courses"] for s in c["students"] if s["username"] == code)


def _server_notes(client, h, sid):
    return client.get(f"/api/transcript/{sid}", headers=h, params={"origin": "server"}).json()["entries"]


def _review(client, teacher, probe_id, action, **more):
    return client.post(f"/api/pacing/{LAB}/answer-review", headers=teacher,
                       json={"probe_id": probe_id, "action": action, **more})


def test_a_zero_answer_waits_for_the_teacher_who_lets_the_student_continue(client, teacher, monkeypatch):
    h, sid, q1, probe, r = _held_answer(client, teacher, monkeypatch, "PCE-ZR1")
    try:
        assert r["auto_grade"] == 0 and r["review"] is True
        assert r["why"] is None  # the grader's reason is the teacher's: it may give the answer away
        st = _state(client, h, sid)
        assert st["quiz_review"] == 1 and st["quiz_pending"] == 0
        assert not st["open"] and not st["waiting_teacher"] and st["current"] == 2
        assert _finish(client, h, sid, 2)["status"] == "quiz_review"
        assert client.get(f"/api/probes/pending/{sid}", headers=h).json() == []  # nothing to answer meanwhile

        # The teacher sees the answer, the grade and the grader's reason.
        s = _pacing_student(client, teacher, "PCE-ZR1")
        assert s["quiz_review"] == 1 and s["quiz_pending"] == 0
        row = s["quiz"][0]
        assert (row["id"], row["review"], row["grade"], row["answer"], row["why"]) == (
            probe["id"], "waiting", 0, "no idea", "not about the kernel")

        # The tutor knows, and neither answers the question nor shows the next step.
        prompt = prompting.system_prompt_for(_session_row(sid))
        assert "ANSWERS WITH THE TEACHER" in prompt and probe["body"] in prompt
        assert "Step A1 · Pull" in prompt and "Step A2" not in prompt

        # Only the teacher decides.
        assert _review(client, h, probe["id"], "approve").status_code in (401, 403)
        assert _review(client, teacher, probe["id"], "approve", grade=3).status_code == 422
        assert _review(client, teacher, probe["id"], "approve").status_code == 200
        st = _state(client, h, sid)
        assert st["quiz_review"] == 0 and st["open"] and st["step"]["label"] == "A2"
        row = _pacing_student(client, teacher, "PCE-ZR1")["quiz"][0]
        assert (row["review"], row["grade"]) == ("approved", 0)  # let through; the grade stays
        notes = _server_notes(client, h, sid)
        assert len(notes) == 1 and notes[0]["kind"] == "result" and "A1" in notes[0]["content"]
        assert _review(client, teacher, probe["id"], "approve").status_code == 409  # decided already
        assert "ANSWERS WITH THE TEACHER" not in prompting.system_prompt_for(_session_row(sid))
    finally:
        client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": False})


def test_the_teacher_can_correct_the_grade_when_approving(client, teacher, monkeypatch):
    h, sid, q1, probe, _ = _held_answer(client, teacher, monkeypatch, "PCE-ZR2")
    try:
        assert _review(client, teacher, probe["id"], "approve", grade=2).status_code == 200
        row = _pacing_student(client, teacher, "PCE-ZR2")["quiz"][0]
        assert (row["review"], row["grade"]) == ("approved", 2)
        assert "2/2" in _server_notes(client, h, sid)[0]["content"]
        assert _state(client, h, sid)["open"]
    finally:
        client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": False})


def test_the_teacher_asks_for_another_answer(client, teacher, monkeypatch):
    h, sid, q1, probe, _ = _held_answer(client, teacher, monkeypatch, "PCE-ZR3")
    try:
        r = _review(client, teacher, probe["id"], "return", note="Think about what a container shares.", grade=2)
        assert r.status_code == 200
        # The same question is open again; the first answer is kept for the record.
        pending = client.get(f"/api/probes/pending/{sid}", headers=h).json()
        assert len(pending) == 1 and pending[0]["id"] != probe["id"]
        assert pending[0]["body"] == probe["body"] and pending[0]["quiz_step"] == "A1"
        st = _state(client, h, sid)
        assert st["quiz_pending"] == 1 and st["quiz_review"] == 0 and not st["open"]
        rows = _pacing_student(client, teacher, "PCE-ZR3")["quiz"]
        assert [(q["review"], q["status"], q["grade"]) for q in rows] == [("returned", "answered", 0),
                                                                        (None, "pending", None)]
        notes = _server_notes(client, h, sid)
        assert len(notes) == 1 and notes[0]["kind"] == "note"
        assert "A1" in notes[0]["content"] and "Think about what a container shares." in notes[0]["content"]
        assert _review(client, teacher, probe["id"], "return").status_code == 409

        # A second 0/2 waits again; a better answer moves them on.
        again = client.post("/api/probes/answer", headers=h, json={"probe_id": pending[0]["id"], "answer": "?"})
        assert again.json()["review"] is True
        second = pending[0]["id"]
        assert _review(client, teacher, second, "return").status_code == 200
        third = client.get(f"/api/probes/pending/{sid}", headers=h).json()[0]

        async def good(question, answer, params, reference=None):
            return 2, "right"

        monkeypatch.setattr(grader, "grade", good)
        r = client.post("/api/probes/answer", headers=h, json={"probe_id": third["id"], "answer": "the host's kernel"})
        assert r.json()["review"] is False and r.json()["auto_grade"] == 2
        st = _state(client, h, sid)
        assert st["open"] and st["step"]["label"] == "A2" and st["quiz_review"] == 0
    finally:
        client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": False})


def test_quiz_review_decides_which_grades_wait(client, teacher, monkeypatch):
    ex = exercises.get(LAB)
    try:
        # partial (the default): 1/2 waits too; only 2/2 moves on by itself.
        h, sid, q1, _, r = _held_answer(client, teacher, monkeypatch, "PCE-ZR5", grade=1)
        assert r["review"] is True and _state(client, h, sid)["quiz_review"] == 1
        h, sid, _, _, r = _held_answer(client, teacher, monkeypatch, "PCE-ZR6", grade=2)
        assert r["review"] is False and _state(client, h, sid)["open"]
        # zero: a partial answer moves on by itself.
        ex["quiz_review"] = "zero"
        h, sid, _, _, r = _held_answer(client, teacher, monkeypatch, "PCE-ZR4", grade=1)
        assert r["review"] is False and _state(client, h, sid)["open"]
        # off: as before, the grade is only recorded.
        ex["quiz_review"] = "off"
        h, sid, _, _, r = _held_answer(client, teacher, monkeypatch, "PCE-ZR7", grade=0)
        assert r["review"] is False and r["auto_grade"] == 0 and _state(client, h, sid)["open"]
        assert r["why"] == "not about the kernel"  # not held: the student sees the reason, as before
        assert _pacing_student(client, teacher, "PCE-ZR7")["quiz"][0]["review"] is None
    finally:
        ex.pop("quiz_review", None)
        client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": False})


def test_an_ungraded_answer_does_not_wait(client, teacher, monkeypatch):
    q1 = next(q for q in client.get(f"/api/pacing/{LAB}", headers=teacher).json()["quiz"] if q["q"] == Q1)
    client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": True})
    try:
        async def broken(question, answer, params, reference=None):
            raise RuntimeError("the grader is down")

        monkeypatch.setattr(grader, "grade", broken)
        h, sid = _student(client, "PCE-ZR8")
        assert _finish(client, h, sid, 1, GOOD)["quiz"] == 1
        probe = client.get(f"/api/probes/pending/{sid}", headers=h).json()[0]
        r = client.post("/api/probes/answer", headers=h, json={"probe_id": probe["id"], "answer": "x"}).json()
        assert r["auto_grade"] is None and r["review"] is False
        assert _state(client, h, sid)["open"]
    finally:
        client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": False})


def test_a_reset_withdraws_an_answer_that_waited(client, teacher, monkeypatch):
    h, sid, q1, probe, _ = _held_answer(client, teacher, monkeypatch, "PCE-ZR9")
    try:
        assert _state(client, h, sid)["quiz_review"] == 1
        assert client.post(f"/api/sessions/{sid}/reset", headers=teacher, json={"step": 1}).status_code == 200
        st = _state(client, h, sid)
        assert st["quiz_review"] == 0 and st["open"] and st["current"] == 1
        assert _pacing_student(client, teacher, "PCE-ZR9")["quiz"][0]["review"] == "reset"
        assert _review(client, teacher, probe["id"], "approve").status_code == 409  # nothing waits any more
    finally:
        client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher, json={"approved": False})


def test_a_teachers_own_question_never_waits(client, teacher, monkeypatch):
    # Only a step's quiz holds the next step; a question the teacher sent is just graded.
    async def zero(question, answer, params, reference=None):
        return 0, "no"

    monkeypatch.setattr(grader, "grade", zero)
    h, sid = _student(client, "PCE-ZR10")
    pid = client.post("/api/probe/send", headers=teacher,
                      json={"session_id": sid, "bodies": ["What did you pull?"]}).json()["probe_ids"][0]
    r = client.post("/api/probes/answer", headers=h, json={"probe_id": pid, "answer": "x"}).json()
    assert r["auto_grade"] == 0 and r["review"] is False
    assert _state(client, h, sid)["open"]
    assert _review(client, teacher, pid, "approve").status_code == 409


def test_quiz_review_is_validated():
    base = {"exercise_id": "x", "title_en": "x", "default_mode": "mentor", "brief_md": "x",
            "variants": [{"id": "v1", "params": {}, "test_inputs": []}]}
    for value in ("zero", "partial", "off"):
        exercises._validate({**base, "quiz_review": value}, "t")
    with pytest.raises(ValueError, match="quiz_review"):
        exercises._validate({**base, "quiz_review": "always"}, "t")
    assert pacing.quiz_review({}) == "partial" and pacing.quiz_review({"quiz_review": "off"}) == "off"


# --- the teacher moves a student, or withdraws a question (interrupting their chat) -----

def _approve_only(*questions):
    ex = exercises.get(LAB)
    for q in pacing.quiz_items(ex):
        pacing.set_quiz(ex, q["key"], q["q"] in questions)


def _grade_with(monkeypatch, grade, why="ok"):
    async def fake(question, answer, params, reference=None):
        return grade, why

    monkeypatch.setattr(grader, "grade", fake)


def _move(client, teacher, sid, n):
    r = client.post(f"/api/sessions/{sid}/move", headers=teacher, json={"step": n})
    assert r.status_code == 200, r.text
    return r.json()


def _checks(sid):
    with db.conn() as c:
        return [(k["step"], k["status"]) for k in c.execute(
            "SELECT step, status FROM step_checks WHERE session_id = ? ORDER BY id", (sid,))]


def test_moving_a_student_forward_skips_the_steps_and_opens_them_for_that_student(client, teacher):
    _approve_only()
    _release(client, teacher, 1)
    try:
        h, sid = _student(client, "PCE-MV1")
        h2, sid2 = _student(client, "PCE-MV2")
        assert _finish(client, h, sid, 1, GOOD)["status"] == "done"
        assert _state(client, h, sid)["waiting_teacher"]  # A2 isn't open to the class

        r = _move(client, teacher, sid, 4)
        assert (r["from"], r["to"], r["how"]) == (2, 4, "forward")
        st = _state(client, h, sid)
        assert st["open"] and st["step"]["label"] == "B2" and st["released"] == 4
        assert _checks(sid) == [(1, "approved"), (2, "skipped"), (3, "skipped")]
        assert _state(client, h2, sid2)["released"] == 1  # only for that student
        note = _server_notes(client, h, sid)[-1]
        assert (note["kind"], note["step"]) == ("reset", 4) and "stopped" in note["content"] and "B2" in note["content"]
        s = _pacing_student(client, teacher, "PCE-MV1")
        assert (s["current"], s["skipped"], s["released_to"]) == (4, ["A2", "B1"], 4)
        assert _finish(client, h, sid, 4)["status"] == "done"
        assert _state(client, h, sid)["finished"]
        # Students can't move anyone; the step is clamped to the lab.
        assert client.post(f"/api/sessions/{sid}/move", headers=h, json={"step": 1}).status_code == 403
        assert _move(client, teacher, sid2, 99)["to"] == 4
    finally:
        _release(client, teacher, 2)


def test_moving_a_student_back_drops_their_answers_and_asks_again(client, teacher, monkeypatch):
    _approve_only(Q2)
    _grade_with(monkeypatch, 2)
    _release(client, teacher, 4)
    try:
        h, sid = _student(client, "PCE-MV3")
        assert _finish(client, h, sid, 1, GOOD)["quiz"] == 1
        probe = client.get(f"/api/probes/pending/{sid}", headers=h).json()[0]
        assert client.post("/api/probes/answer", headers=h, json={"probe_id": probe["id"], "answer": "6.8"}).json()["review"] is False
        _finish(client, h, sid, 2)
        assert _state(client, h, sid)["current"] == 3

        r = _move(client, teacher, sid, 1)
        assert (r["from"], r["to"], r["how"]) == (3, 1, "back")
        assert _checks(sid) == [(1, "reset"), (2, "reset")]
        rows = _pacing_student(client, teacher, "PCE-MV3")["quiz"]
        assert [(q["status"], q["answer"]) for q in rows] == [("reset", "6.8")]  # kept, no longer counts
        assert "stopped" in _server_notes(client, h, sid)[-1]["content"]
        # Done again: the question is asked again.
        assert _finish(client, h, sid, 1, GOOD)["quiz"] == 1
        assert len(client.get(f"/api/probes/pending/{sid}", headers=h).json()) == 1
    finally:
        _approve_only()


def test_moving_a_student_to_their_own_step_starts_it_over(client, teacher):
    _approve_only()
    _release(client, teacher, 4)
    h, sid = _student(client, "PCE-MV4")
    _finish(client, h, sid, 1, GOOD)
    _finish(client, h, sid, 2)
    assert _finish(client, h, sid, 3, "nothing useful")["status"] == "missing"
    assert _state(client, h, sid)["waiting_review"]
    r = _move(client, teacher, sid, 3)
    assert (r["from"], r["to"], r["how"]) == (3, 3, "again")
    st = _state(client, h, sid)
    assert st["open"] and st["step"]["label"] == "B1" and not st["waiting_review"]
    assert _checks(sid)[-1] == (3, "reset")
    notes = _server_notes(client, h, sid)
    assert (notes[-1]["kind"], notes[-1]["step"]) == ("reset", 3)
    # Nothing pending: the chat is still told, so it shows the step again.
    _move(client, teacher, sid, 3)
    assert len(_server_notes(client, h, sid)) == len(notes) + 1


def test_moving_a_student_to_their_step_shows_it_even_when_the_class_hasnt_opened_it(client, teacher):
    _approve_only()
    _release(client, teacher, 1)
    try:
        h, sid = _student(client, "PCE-MV5")
        _finish(client, h, sid, 1, GOOD)
        assert _state(client, h, sid)["waiting_teacher"]          # A2 isn't open to the class
        assert _move(client, teacher, sid, 2)["how"] == "again"
        st = _state(client, h, sid)
        assert st["open"] and st["step"]["label"] == "A2"
    finally:
        _release(client, teacher, 2)


def _course_student(tc, code, course):
    with db.conn() as c:
        c.execute("INSERT OR IGNORE INTO courses (course_id, name) VALUES (?, ?)", (course, course))
        c.execute("INSERT OR IGNORE INTO course_exercises (course_id, exercise_id) VALUES (?, ?)", (course, LAB))
        c.execute("INSERT INTO users (username, login_code, role) VALUES (?, ?, 'student')", (code, code))
        uid = c.execute("SELECT id FROM users WHERE login_code = ?", (code,)).fetchone()["id"]
        c.execute("INSERT INTO course_members (course_id, user_id) VALUES (?, ?)", (course, uid))
    tok = tc.post("/api/login", json={"code": code, "password": code}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    sid = tc.post("/api/sessions", json={"course_id": course, "exercise_id": LAB}, headers=h).json()["session_id"]
    return h, sid


def test_withdrawing_a_question_tells_each_student_their_own_question_and_answer(client, teacher, monkeypatch):
    _approve_only(Q1, Q2)
    _grade_with(monkeypatch, 2)
    _release(client, teacher, 4, "course-wd")
    try:
        hx, sx = _course_student(client, "PCE-WD1", "course-wd")   # answers one question, the other still open
        hy, sy = _course_student(client, "PCE-WD2", "course-wd")   # answers both
        for h, sid in ((hx, sx), (hy, sy)):
            assert _finish(client, h, sid, 1, GOOD)["quiz"] == 2
        px = client.get(f"/api/probes/pending/{sx}", headers=hx).json()
        py = client.get(f"/api/probes/pending/{sy}", headers=hy).json()
        body1, body2 = px[0]["body"], px[1]["body"]
        assert body2 == Q2
        client.post("/api/probes/answer", headers=hx, json={"probe_id": px[0]["id"], "answer": "x answers one"})
        client.post("/api/probes/answer", headers=hy, json={"probe_id": py[0]["id"], "answer": "y answers one"})
        client.post("/api/probes/answer", headers=hy, json={"probe_id": py[1]["id"], "answer": "y answers two"})
        assert not _state(client, hx, sx)["open"]  # x still has Q2 open

        key2 = pacing.quiz_key(Q2)
        r = client.post(f"/api/pacing/{LAB}/quiz/{key2}", headers=teacher,
                        json={"approved": False, "withdraw_asked": True, "course_id": "course-wd"})
        assert r.status_code == 200 and r.json()["withdrawn_now"] == 2

        # x: the open question is gone; told so, about that question only.
        assert client.get(f"/api/probes/pending/{sx}", headers=hx).json() == []
        assert _state(client, hx, sx)["open"]
        nx = _server_notes(client, hx, sx)[-1]
        assert nx["kind"] == "cancelled" and Q2 in nx["content"] and "No need to answer" in nx["content"]
        assert body1 not in nx["content"] and "x answers one" not in nx["content"]
        # y: told with their own answer to that question, not the other one.
        ny = _server_notes(client, hy, sy)[-1]
        assert ny["kind"] == "cancelled" and Q2 in ny["content"] and "y answers two" in ny["content"]
        assert body1 not in ny["content"] and "y answers one" not in ny["content"]
        rows = {q["body"]: q["status"] for q in _pacing_student(client, teacher, "PCE-WD2")["quiz"]}  # noqa
        assert rows == {body1: "answered", Q2: "withdrawn"}
        with db.conn() as c:
            counted = [r["body"] for r in c.execute(
                "SELECT body FROM probes WHERE session_id = ? AND status NOT IN ('withdrawn', 'reset')", (sy,))]
        assert counted == [body1]

        # Approved again: asked again of both (a withdrawn answer counts as not asked).
        r = client.post(f"/api/pacing/{LAB}/quiz/{key2}", headers=teacher,
                        json={"approved": True, "ask_finished": True, "course_id": "course-wd"})
        assert r.json()["asked_now"] == 2
        # Without withdraw_asked, withdrawing only stops asking it.
        r = client.post(f"/api/pacing/{LAB}/quiz/{key2}", headers=teacher, json={"approved": False})
        assert r.json()["withdrawn_now"] == 0 and len(client.get(f"/api/probes/pending/{sx}", headers=hx).json()) == 1
    finally:
        _approve_only()


def test_withdrawing_releases_an_answer_that_waited_for_the_teacher(client, teacher, monkeypatch):
    h, sid, q1, probe, r = _held_answer(client, teacher, monkeypatch, "PCE-WD3", grade=1)
    try:
        assert r["review"] is True and _state(client, h, sid)["quiz_review"] == 1
        client.post(f"/api/pacing/{LAB}/quiz/{q1['key']}", headers=teacher,
                    json={"approved": False, "withdraw_asked": True, "course_id": None})
        st = _state(client, h, sid)
        assert st["quiz_review"] == 0 and st["open"]
        row = _pacing_student(client, teacher, "PCE-WD3")["quiz"][0]
        assert (row["status"], row["review"]) == ("withdrawn", "withdrawn")
        assert "no idea" in _server_notes(client, h, sid)[-1]["content"]
    finally:
        _approve_only()


def test_the_teachers_text_goes_with_either_decision(client, teacher, monkeypatch):
    h, sid, q1, probe, _ = _held_answer(client, teacher, monkeypatch, "PCE-TX1", grade=1)
    try:
        assert _review(client, teacher, probe["id"], "return", note="Line one.\nLine two.").status_code == 200
        note = _server_notes(client, h, sid)[-1]["content"]
        assert "> Line one.\n> Line two." in note
        again = client.get(f"/api/probes/pending/{sid}", headers=h).json()[0]
        client.post("/api/probes/answer", headers=h, json={"probe_id": again["id"], "answer": "still partial"})
        assert _review(client, teacher, again["id"], "approve", note="Close enough: a container has no kernel.").status_code == 200
        note = _server_notes(client, h, sid)[-1]["content"]
        assert note.startswith("✅") and "> Close enough: a container has no kernel." in note
        with db.conn() as c:
            assert c.execute("SELECT teacher_note FROM probes WHERE id = ?", (again["id"],)).fetchone()[0] == \
                "Close enough: a container has no kernel."
    finally:
        _approve_only()


@pytest.mark.parametrize("text, asks", [
    ("What does kernel mean?", True),
    ("why the same kernel", True),
    ("מה זה kernel", True),
    ("לא הבנתי מה צריך לכתוב", True),
    ("תסביר שוב בבקשה", True),
    ("هل هذا صحيح", True),
    ("ממש לא ברור לי?", True),
    ("Because the container shares the host kernel.", False),
    ("כי לקונטיינר אין kernel משלו", False),
    ("ls file?.txt shows it", False),
    ("6.8.0-1015-azure", False),
    ("", False),
])
def test_looks_like_question(text, asks):
    from backend import textutil
    assert textutil.looks_like_question(text) is asks


# --- regressions: moving students, skipped steps, and what counts ---------------------------

def test_sending_back_or_closing_takes_back_the_steps_opened_for_one_student(client, teacher):
    """A student moved forward has the steps up to there opened for them alone
    (released_to). Moving them back, sending them back with the class, or
    closing steps for the course takes that back; opening more doesn't."""
    _approve_only()
    _release(client, teacher, 1)
    try:
        h, sid = _student(client, "PCE-OWN1")
        _finish(client, h, sid, 1, GOOD)
        _move(client, teacher, sid, 4)
        assert _state(client, h, sid)["released"] == 4
        # Back to a step the course has open: nothing is left open for them alone.
        _move(client, teacher, sid, 1)
        st = _state(client, h, sid)
        assert (st["current"], st["released"]) == (1, 1)
        assert _pacing_student(client, teacher, "PCE-OWN1")["released_to"] is None
        _finish(client, h, sid, 1, GOOD)
        assert _state(client, h, sid)["waiting_teacher"]          # A2 isn't open to the class
        # Back to a step the course hasn't opened: that step stays open to them, no later one.
        _move(client, teacher, sid, 4)
        _move(client, teacher, sid, 3)
        st = _state(client, h, sid)
        assert st["open"] and (st["current"], st["released"]) == (3, 3)
        assert _finish(client, h, sid, 3, "6.8.0-linuxkit")["status"] == "done"
        assert _state(client, h, sid)["waiting_teacher"]          # B2 was opened for them, not any more

        # Sent back with the class (the course reset).
        h2, sid2 = _student(client, "PCE-OWN2")
        _finish(client, h2, sid2, 1, GOOD)
        _move(client, teacher, sid2, 4)
        r = client.post(f"/api/exercises/{LAB}/reset", headers=teacher, json={"step": 1, "session_ids": [sid2]})
        assert r.status_code == 200 and r.json()["moved"] == 1
        st = _state(client, h2, sid2)
        assert (st["current"], st["released"]) == (1, 1)

        # The teacher closes steps for the course: closed for the student too; opening more isn't.
        h3, sid3 = _student(client, "PCE-OWN3")
        _finish(client, h3, sid3, 1, GOOD)
        _move(client, teacher, sid3, 4)
        _release(client, teacher, 2)
        assert _state(client, h3, sid3)["released"] == 4
        _release(client, teacher, 1)
        assert _state(client, h3, sid3)["released"] == 1
        assert _pacing_student(client, teacher, "PCE-OWN3")["released_to"] is None
    finally:
        _release(client, teacher, 2)


def test_moving_forward_keeps_the_records_of_the_steps_done_and_skips_each_step_once(client, teacher):
    _approve_only()
    _release(client, teacher, 4)
    try:
        h, sid = _student(client, "PCE-SK1")
        assert _finish(client, h, sid, 1, "something else")["status"] == "missing"
        assert client.post(f"/api/pacing/{LAB}/decline", headers=teacher,
                           json={"session_id": sid, "step": 1}).status_code == 200
        _finish(client, h, sid, 1, GOOD)
        _finish(client, h, sid, 2)
        assert _finish(client, h, sid, 3, "no kernel here")["status"] == "missing"  # waits for the teacher
        r = _move(client, teacher, sid, 4)
        assert (r["from"], r["to"], r["how"]) == (3, 4, "forward")
        # A1's sent-back output stays what it was; B1's waiting output no longer
        # counts (kept, like a reset); B1 is skipped once.
        assert _checks(sid) == [(1, "returned"), (1, "approved"), (2, "approved"), (3, "reset"), (3, "skipped")]
        s = _pacing_student(client, teacher, "PCE-SK1")
        assert (s["current"], s["skipped"], s["waiting"]) == (4, ["B1"], [])
        assert _state(client, h, sid)["open"]
    finally:
        _release(client, teacher, 2)


def test_a_question_approved_late_is_not_asked_about_a_step_the_student_skipped(client, teacher):
    _approve_only()
    _release(client, teacher, 4, "course-skq")
    try:
        hd, sd = _course_student(client, "PCE-SKQ1", "course-skq")   # does A1
        hs, ss = _course_student(client, "PCE-SKQ2", "course-skq")   # moved past A1 without doing it
        _finish(client, hd, sd, 1, GOOD)
        _move(client, teacher, ss, 3)
        key = pacing.quiz_key(Q1)
        view = client.get(f"/api/pacing/{LAB}", headers=teacher).json()
        assert next(c for c in view["courses"] if c["course_id"] == "course-skq")["quiz_missed"][key] == 1
        r = client.post(f"/api/pacing/{LAB}/quiz/{key}", headers=teacher,
                        json={"approved": True, "ask_finished": True, "course_id": "course-skq"})
        assert r.json()["asked_now"] == 1
        assert len(client.get(f"/api/probes/pending/{sd}", headers=hd).json()) == 1
        assert client.get(f"/api/probes/pending/{ss}", headers=hs).json() == []
        assert _state(client, hs, ss)["open"]
    finally:
        _approve_only()


def test_the_review_card_names_the_step_a_question_is_about(client, teacher, monkeypatch):
    from backend import whereabouts
    ex = exercises.get(LAB)
    _approve_only(Q2)
    _release(client, teacher, 4, "course-wh")
    try:
        h, sid = _course_student(client, "PCE-WH1", "course-wh")
        session = {"id": sid, "course_id": "course-wh"}
        _finish(client, h, sid, 1, GOOD)                      # A1's question is open; A2 is next
        where = whereabouts.step_of(session, ex)
        assert (where["status"], where["n"], where["label"]) == ("quiz", 1, "A1")
        _grade_with(monkeypatch, 2)
        probe = client.get(f"/api/probes/pending/{sid}", headers=h).json()[0]
        client.post("/api/probes/answer", headers=h, json={"probe_id": probe["id"], "answer": "6.8"})
        _finish(client, h, sid, 2)
        # A question about A1 approved late, asked of a student on B1.
        key = pacing.quiz_key(Q1)
        client.post(f"/api/pacing/{LAB}/quiz/{key}", headers=teacher,
                    json={"approved": True, "ask_finished": True, "course_id": "course-wh"})
        where = whereabouts.step_of(session, ex)
        assert (where["status"], where["n"], where["label"]) == ("quiz", 1, "A1")
        # Its answer, graded too low, waits for the teacher: still about A1.
        _grade_with(monkeypatch, 0)
        probe = client.get(f"/api/probes/pending/{sid}", headers=h).json()[0]
        client.post("/api/probes/answer", headers=h, json={"probe_id": probe["id"], "answer": "no idea"})
        where = whereabouts.step_of(session, ex)
        assert (where["status"], where["n"], where["label"]) == ("quiz_review", 1, "A1")
    finally:
        _approve_only()


def test_an_answer_sent_back_no_longer_counts_in_the_grade_signals(client, teacher, monkeypatch):
    from backend.grading import features
    h, sid, q1, probe, _ = _held_answer(client, teacher, monkeypatch, "PCE-FT1", grade=0)
    try:
        assert _review(client, teacher, probe["id"], "return").status_code == 200
        _grade_with(monkeypatch, 2)
        again = client.get(f"/api/probes/pending/{sid}", headers=h).json()[0]
        client.post("/api/probes/answer", headers=h, json={"probe_id": again["id"], "answer": "it shares the host kernel"})
        p = features.extract(sid)["probes"]
        assert (p["count"], p["avg_grade"]) == (1, 2)
        assert [qa["a"] for qa in p["qa"]] == ["it shares the host kernel"]
    finally:
        _approve_only()


def test_skipped_steps_are_no_submissions_in_the_report_or_the_attendance(client, teacher):
    import datetime

    from backend import courses, reports
    _approve_only()
    _release(client, teacher, 4, "course-rep")
    h, sid = _course_student(client, "PCE-REP1", "course-rep")
    _finish(client, h, sid, 1, GOOD)
    _move(client, teacher, sid, 4)                             # A2 and B1 skipped
    rep = reports.session_report(exercise_id=LAB, course_id="course-rep")
    assert rep["students"] == 1 and rep["per_student"][0]["step_submissions"] == 1
    assert rep["steps"]["submissions"] == 1 and rep["steps"]["decision_seconds"]["n"] == 1
    meeting = courses.add_meeting("course-rep", datetime.date.today().isoformat(), LAB)
    try:
        row = next(r for r in courses.attendance(meeting["id"])["rows"] if r["username"] == "PCE-REP1")
        assert (row["step_submissions"], row["steps_approved"]) == (1, 1)
    finally:
        courses.delete_meeting(meeting["id"])
