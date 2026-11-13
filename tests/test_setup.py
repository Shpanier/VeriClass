"""First run and settings: the first lecturer account, the API key stored in
.env and used at once, the students' link, and the dashboard served at /."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-setup-tests")

import pytest
from fastapi.testclient import TestClient

from backend import db, settings, student_llm, tunnel
from backend.main import app

LOCAL = ("127.0.0.1", 50000)


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=LOCAL) as tc:
        yield tc


def _no_teachers():
    with db.conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE role = 'teacher'")]
        for uid in ids:
            c.execute("DELETE FROM auth_tokens WHERE user_id = ?", (uid,))
            c.execute("DELETE FROM users WHERE id = ?", (uid,))


@pytest.fixture()
def teacher(client):
    _no_teachers()
    r = client.post("/api/setup/teacher", json={"name": "Dana Levi", "username": "dana", "password": "secret-1"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# --- the first lecturer account -------------------------------------------------------


def test_a_new_server_asks_for_the_first_account(client):
    _no_teachers()
    s = client.get("/api/setup/status").json()
    assert s["needs_teacher"] is True and s["local"] is True


def test_first_account_signs_in_and_cannot_be_created_twice(client, teacher):
    assert client.get("/api/setup/status").json()["needs_teacher"] is False
    # the chosen username and password work on the ordinary login
    r = client.post("/api/login", json={"code": "dana", "password": "secret-1"})
    assert r.status_code == 200 and r.json()["role"] == "teacher"
    # the default "password = username" does not: a real password was set
    assert client.post("/api/login", json={"code": "dana", "password": "dana"}).status_code == 401
    again = client.post("/api/setup/teacher", json={"name": "Eve", "username": "eve", "password": "secret-2"})
    assert again.status_code == 409


def test_first_account_only_from_this_computer(client):
    _no_teachers()
    body = {"name": "Mallory", "username": "mallory", "password": "secret-3"}
    # through a tunnel the request carries a forwarding header
    r = client.post("/api/setup/teacher", json=body, headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 403
    with TestClient(app, client=("203.0.113.9", 40000)) as remote:
        assert remote.post("/api/setup/teacher", json=body).status_code == 403
        assert remote.get("/api/setup/status").json()["local"] is False


@pytest.mark.parametrize("body, part", [
    ({"name": "", "username": "dana", "password": "secret-1"}, "name"),
    ({"name": "Dana", "username": "d", "password": "secret-1"}, "username"),
    ({"name": "Dana", "username": "has space", "password": "secret-1"}, "username"),
    ({"name": "Dana", "username": "dana", "password": "123"}, "6 characters"),
])
def test_first_account_checks_its_fields(client, body, part):
    _no_teachers()
    r = client.post("/api/setup/teacher", json=body)
    assert r.status_code == 422 and part in r.json()["detail"]


# --- the API key ------------------------------------------------------------------------


def test_env_file_keeps_other_lines_and_comments(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# my notes\nFIRST_KEY=old\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setenv("VERICLASS_ENV_FILE", str(env))
    monkeypatch.setenv("FIRST_KEY", "old")   # save_env sets the process's values too:
    monkeypatch.setenv("SOME_NEW_KEY", "")   # have them restored after the test
    settings.save_env({"FIRST_KEY": "new", "SOME_NEW_KEY": "a value with spaces"})
    text = env.read_text(encoding="utf-8")
    assert text.startswith("# my notes\nFIRST_KEY=new\nOTHER=1\n")
    assert 'SOME_NEW_KEY="a value with spaces"' in text
    assert os.environ["SOME_NEW_KEY"] == "a value with spaces"


def test_saving_a_key_switches_the_provider_without_a_restart(client, teacher, monkeypatch):
    async def fake_test(provider_id, key):
        return {"ok": True, "model_ok": True, "message": "The key works."}

    monkeypatch.setattr(settings, "test_key", fake_test)
    before = {k: os.environ.get(k) for k in ("LLM_PROVIDER", "ANTHROPIC_API_KEY", "CLAUDE_MODEL")}
    try:
        r = client.post("/api/settings/llm", headers=teacher,
                        json={"provider": "anthropic", "api_key": "  sk-ant-test-1234567890  "})
        assert r.status_code == 200, r.text
        llm = r.json()["llm"]
        assert llm["provider"] == "anthropic" and llm["ready"] is True
        assert llm["key_hint"] == "…7890" and "sk-ant" not in r.text
        # the running server uses it at once
        assert student_llm.PROVIDER == "anthropic" and student_llm.KEY_ENV == "ANTHROPIC_API_KEY"
        assert student_llm.MODEL == "claude-haiku-5-5"
        saved = settings.env_file().read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY=sk-ant-test-1234567890" in saved and "LLM_PROVIDER=anthropic" in saved
        # and the settings page never returns the key
        got = client.get("/api/settings", headers=teacher).json()
        assert got["llm"]["ready"] is True and "sk-ant" not in str(got)
    finally:
        for k, v in before.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings.reconfigure()


def test_a_refused_key_is_not_saved(client, teacher, monkeypatch):
    async def refused(provider_id, key):
        return {"ok": False, "message": "The provider refused this key. Copy it again, with no spaces."}

    monkeypatch.setattr(settings, "test_key", refused)
    before = (student_llm.PROVIDER, os.environ.get("ANTHROPIC_API_KEY"))
    r = client.post("/api/settings/llm", headers=teacher,
                    json={"provider": "anthropic", "api_key": "wrong-key-000"})
    assert r.status_code == 422 and "refused" in r.json()["detail"]
    assert (student_llm.PROVIDER, os.environ.get("ANTHROPIC_API_KEY")) == before
    env = settings.env_file()
    assert not env.is_file() or "wrong-key-000" not in env.read_text(encoding="utf-8")


def test_settings_need_a_lecturer(client):
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/share").status_code == 401


def test_chat_language_setting(client, teacher):
    assert client.get("/api/settings", headers=teacher).json()["chat_language"] == "auto"
    assert client.post("/api/settings/chat-language", headers=teacher,
                       json={"language": "he"}).json() == {"chat_language": "he"}
    assert client.post("/api/settings/chat-language", headers=teacher,
                       json={"language": "fr"}).status_code == 422
    client.post("/api/settings/chat-language", headers=teacher, json={"language": "auto"})


# --- the students' link -----------------------------------------------------------------


def test_share_gives_the_chat_link(client, teacher, monkeypatch):
    monkeypatch.setenv("VERICLASS_PORT", "8123")
    monkeypatch.setenv("STUDENT_CHAT_PATH", "/chat")
    monkeypatch.setattr(tunnel, "_external_ngrok", lambda: None)
    s = client.get("/api/share", headers=teacher).json()
    assert s["local_url"] == "http://localhost:8123/chat/"
    assert s["public_url"] is None and s["tunnel"]["state"] == "off"


def test_share_shows_a_tunnel_started_elsewhere(client, teacher, monkeypatch):
    monkeypatch.setenv("STUDENT_CHAT_PATH", "/chat")
    monkeypatch.setattr(tunnel, "_external_ngrok", lambda: "https://my-class.ngrok-free.dev")
    s = client.get("/api/share", headers=teacher).json()
    assert s["public_url"] == "https://my-class.ngrok-free.dev/chat/"
    assert s["tunnel"]["external"] is True


def test_share_shows_an_address_the_lecturer_set_up(client, teacher, monkeypatch):
    monkeypatch.setenv("STUDENT_CHAT_PATH", "/chat")
    monkeypatch.setenv("STUDENT_URL", "https://lab.example.edu/chat/")
    monkeypatch.setattr(tunnel, "_external_ngrok", lambda: None)
    s = client.get("/api/share", headers=teacher).json()
    assert s["public_url"] == "https://lab.example.edu/chat/"
    assert s["local_url"].startswith("http://localhost:")


def test_starting_a_tunnel_without_the_program_says_so(client, teacher, monkeypatch):
    monkeypatch.setattr(tunnel, "find", lambda name: None)
    r = client.post("/api/share/tunnel", headers=teacher, json={"action": "start"})
    assert r.status_code == 409 and "cloudflared" in r.json()["detail"]


def test_overview_counts(client, teacher):
    o = client.get("/api/overview", headers=teacher).json()
    assert o["exercises"] >= 1 and isinstance(o["students"], int) and "llm_ready" in o
