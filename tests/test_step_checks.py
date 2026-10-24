"""What the teacher sees next to a step submission: how many questions it
answers, the student's terminal evidence, and the plugin's attachment."""
import copy
import os
import tempfile
import threading
import time

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-step-tests")

import pytest
from fastapi.testclient import TestClient

from backend import db, exercises, steps
from backend.main import app

LAB = "step-lab-test"
STEPS = [
    {"title": "Make the log",
     "text": "Run the command.\n\nAnswer:\n- How many lines?\n- Which IP appears twice?\n- What size is it?",
     "expected": "2000 lines",
     "evidence": [{"label": "the log has 2000 lines", "command": r"wc -l", "expect": r"^\s*2000\b"}]},
    {"title": "Search", "text": "ענו על שתי השאלות:\n1. כמה?\n2. למה?", "expected": "x"},
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        lab = copy.deepcopy(exercises.get("ex3-mcalc"))
        lab.update({"exercise_id": LAB, "steps": STEPS})
        exercises._LOADED[LAB] = lab
        exercises.set_active(LAB)  # students outside every course open the active exercise
        with db.conn() as c:
            c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES ('Step Teacher', 'STP-T', 'teacher')")
            c.execute("DELETE FROM system_settings WHERE key = 'review_mode'")
        yield tc
        exercises.set_active("ex3-mcalc")
        exercises._LOADED.pop(LAB, None)


def _student(tc, code):
    with db.conn() as c:
        c.execute("INSERT INTO users (username, login_code, role) VALUES (?, ?, 'student')", (code, code))
    tok = tc.post("/api/login", json={"code": code, "password": code}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    sid = tc.post("/api/sessions", json={"exercise_id": LAB}, headers=h).json()["session_id"]
    return h, sid


def test_question_count():
    assert [steps.question_count(s) for s in STEPS] == [3, 2]
    assert steps.question_count({"text": "no questions here"}) is None
    assert steps.question_count({"text": "x", "questions": 4}) == 4
    # A list inside a code block isn't a question list.
    assert steps.question_count({"text": "Answer:\n```\n- not this\n```\n- a?\n- b?"}) == 2


@pytest.mark.parametrize("answer,questions,want", [
    ("סיימתי שלב 1. התשובות שלי: 1רשומה של מכירת דירה בירושלים.", 6, 1),
    ("סיימתי שלב 1, התשובות שלי: q1 - גודל q2 - int64 q3 - floor 120 q4 - 9999 q5 - 30 q6 - 16 שמות", 6, 6),
    ("סיימתי שלב 1. התשובות שלי: כל שורה מייצגת רישום של דירה שנמכרה", 6, 1),
    ("Done with step 1. Our commands and answers:", 3, 0),
    ("Done with step 2. Our answers:\nwc -l -> 25\ngrep -c x -> 82\nsort | uniq -> 7", 3, 3),
])
def test_answered_count(answer, questions, want):
    # Real submissions from the October 2026 classes.
    assert steps.answered_count(answer, questions) == want


def _done_in_background(tc, h, sid, message, attachment=None):
    box = {}

    def run():
        body = {"session_id": sid, "message": message}
        if attachment:
            body["attachment"] = attachment
        box["r"] = tc.post("/api/ask", json=body, headers=h)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


def test_pending_check_shows_progress_evidence_and_attachment(client):
    h, sid = _student(client, "STP-1")
    # The student's terminal: a broken log first, then nothing else.
    for line, out, code in (("wc -l access.log", "0 access.log", 0), ("ls", "access.log", 0)):
        r = client.post("/api/terminal/command", headers=h, json={
            "session_id": sid, "line": line, "allowed": True, "commands": [line.split()[0]],
            "exit_code": code, "output_tail": out})
        assert r.status_code == 200, r.text
    att = {"filename": "lab.py", "source": "print('hi')", "console": "hi", "check_output": "check 1: PASS"}
    t, box = _done_in_background(client, h, sid, "Done with step 1. Our answers:\n1. 0\n2. none", att)

    teacher = client.post("/api/login", json={"code": "STP-T", "password": "STP-T"}).json()["token"]
    th = {"Authorization": f"Bearer {teacher}"}
    item = None
    for _ in range(100):
        items = [i for i in client.get("/api/step-checks/pending", headers=th).json()["items"]
                 if i["session_id"] == sid]
        if items:
            item = items[0]
            break
        time.sleep(0.05)
    assert item, "no step check appeared"
    assert (item["questions"], item["answered"]) == (3, 2)
    rule = item["evidence"]["rules"][0]
    assert rule["found"] and rule["ok"] is False and rule["line"] == "wc -l access.log"
    assert [x["line"] for x in item["evidence"]["recent"]] == ["wc -l access.log", "ls"]
    assert item["code"] == att

    client.post(f"/api/step-checks/{item['id']}/decide", json={"action": "return", "note": "fix the log"}, headers=th)
    t.join(10)
    assert "look again at step 1" in box["r"].text
