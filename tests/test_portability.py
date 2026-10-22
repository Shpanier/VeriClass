"""Same terminal commands on every OS: the static check of an exercise's commands
(backend/portability.py), the teacher's view of it, and the OS each terminal
line ran on."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-portability-tests")

import pytest
import yaml
from fastapi.testclient import TestClient

from backend import db, exercises, portability, terminal
from backend.main import app

ALLOW = set(terminal.DEFAULT_ALLOW)
TEACHER = "PORT-TEACH"
STUDENT = "PORT-STUDY"


def _ex(*texts, os_check=None):
    steps = [{"title": f"s{i}", "text": t, "expected": "x"} for i, t in enumerate(texts, 1)]
    if os_check:
        steps[0]["os_check"] = os_check
    return {"exercise_id": "port-ex", "steps": steps}


def _rules(ex):
    return {(w["rule"], w["level"]) for w in portability.lint_exercise(ex, ALLOW)}


def test_backslash_is_an_error():
    # The two lines that broke in class on Windows (plugin 0.3.0).
    ex = _ex("```\nprintf \"a\\n\" | awk '{print \"\\\"\" $1}'\n```",
             "```\nsed 's/^10\\.0/x/' access.log\n```")
    warnings = portability.lint_exercise(ex, ALLOW)
    assert [(w["step"], w["rule"], w["level"]) for w in warnings] == [
        (1, "backslash", "error"), (2, "backslash", "error")]


def test_the_fixed_generator_line_is_clean():
    line = ("seq 3 | awk '{ printf \"%cGET%c %d%c\", 34, 34, NR, 10 }' > access.log")
    assert _rules(_ex(f"```\n{line}\n```")) == set()


@pytest.mark.parametrize("line, rule", [
    ("sed -i 's/a/b/' f.txt", "sed-i"),
    ("grep -P '\\d' f.txt", "grep-P"),
    ("date -d yesterday", "date-gnu"),
    ("stat -c %s f.txt", "stat-format"),
    ("head -n -1 f.txt", "head-negative"),
    ("awk '{print strftime()}' f", "gawk-only"),
    ("find . -printf '%p'", "find-printf"),
    ("cat f | tac", "mac-missing"),
])
def test_known_differences(line, rule):
    assert (rule, "error") in _rules(_ex(f"```\n{line}\n```"))


def test_notes_do_not_block():
    ex = _ex("```\nwc -l f\nls -l\ngit add f\n```")
    assert {lvl for _, lvl in _rules(ex)} == {"note"}


def test_sample_output_in_code_blocks_is_not_a_command():
    # A field diagram or sample output starts with a word that is not a program.
    ex = _ex("```\n10.0.0.3 - - [22/Oct] \"GET / HTTP/1.1\" 200\n   $1    $2\n```")
    assert portability.commands_of(ex, ALLOW) == []


def test_os_check_lines_are_checked_in_step_order():
    ex = _ex("```\ncd lab1\n```", "```\nwc -l f\n```", os_check=["sed -i 's/a/b/' f"])
    assert portability.commands_of(ex, ALLOW) == [
        (1, "step", "cd lab1"), (1, "os_check", "sed -i 's/a/b/' f"), (2, "step", "wc -l f")]
    assert ("sed-i", "error") in _rules(ex)


def test_bundled_exercises_have_no_os_errors():
    for path in sorted(Path("config/exercises").glob("*.yaml")):
        ex = yaml.safe_load(path.read_text(encoding="utf-8"))
        allow = set(terminal.policy_for(ex)["allow"])
        errors = [w for w in portability.lint_exercise(ex, allow) if w["level"] == "error"]
        assert errors == [], f"{path.name}: {errors}"


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            for name, code, role in (("Port Teacher", TEACHER, "teacher"), ("Port Student", STUDENT, "student")):
                c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES (?, ?, ?)",
                          (name, code, role))
        yield tc


def _login(tc, code):
    return {"Authorization": f"Bearer {tc.post('/api/login', json={'code': code, 'password': code}).json()['token']}"}


def test_teacher_sees_os_warnings(client):
    h = _login(client, TEACHER)
    payload = {
        "exercise_id": "port-console", "title_en": "Port", "default_mode": "mentor",
        "brief_md": "b", "variants": [{"id": "v1"}],
    }
    assert client.post("/api/exercises", json=payload, headers=h).status_code in (200, 201)
    ex = exercises.get("port-console")
    ex["steps"] = [{"title": "t", "text": "```\nsed -i 's/a/b/' f\n```", "expected": "x"}]
    exercises._check_os(ex)
    full = client.get("/api/exercises/port-console", headers=h).json()
    assert [w["rule"] for w in full["os_warnings"]] == ["sed-i"]
    summary = {e["exercise_id"]: e for e in client.get("/api/exercises", headers=h).json()}
    assert summary["port-console"]["os_errors"] == 1


def test_terminal_line_keeps_os_and_shell(client):
    hs, ht = _login(client, STUDENT), _login(client, TEACHER)
    sid = client.post("/api/sessions", json={}, headers=hs).json()["session_id"]
    body = {"session_id": sid, "line": "wc -l access.log", "allowed": True, "exit_code": 0,
            "client_os": "Windows 11 amd64", "shell": "BusyBox (bundled)"}
    assert client.post("/api/terminal/command", json=body, headers=hs).json()["ok"]
    # An older plugin sends neither field.
    old = {"session_id": sid, "line": "pwd", "allowed": True, "exit_code": 0}
    assert client.post("/api/terminal/command", json=old, headers=hs).json()["ok"]
    rows = client.get(f"/api/terminal/commands?session_id={sid}", headers=ht).json()
    assert [(r["line"], r["client_os"], r["shell"]) for r in rows] == [
        ("pwd", None, None), ("wc -l access.log", "Windows 11 amd64", "BusyBox (bundled)")]
