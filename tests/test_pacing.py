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


def test_teacher_sends_a_student_back_and_the_chat_hears_it(client, teacher):
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
    assert _detect(client, h, sid, GOOD) == {"kind": "output", "step": 1, "label": "A1", "matched": 2, "checks": 2}
    maybe = _detect(client, h, sid, "ALL READY")
    assert maybe["kind"] == "maybe" and maybe["matched"] == 1
    assert "hint" not in str(maybe) and "alpine" not in str(maybe)  # never gives the checks away
    assert _detect(client, h, sid, "why does docker pull take so long?") == {"kind": "question"}
    assert _detect(client, h, sid, "   ") == {"kind": "question"}

    ex = exercises.get(LAB)
    try:
        ex["output_in_chat"] = "ask"
        assert _detect(client, h, sid, GOOD)["kind"] == "maybe"
        ex["output_in_chat"] = "off"
        assert _detect(client, h, sid, GOOD) == {"kind": "question"}
    finally:
        ex.pop("output_in_chat")
    # Another student can't ask about this session.
    other, _ = _student(client, "PCE-51")
    assert client.post("/api/steps/detect", headers=other, json={"session_id": sid, "text": GOOD}).status_code == 403

    # A step without checks: a message is always a question.
    _finish(client, h, sid, 1, GOOD)
    assert _detect(client, h, sid, GOOD) == {"kind": "question"}


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
    with pytest.raises(ValueError, match="output_in_chat"):
        exercises._validate({**base, "output_in_chat": "maybe"}, "t")
