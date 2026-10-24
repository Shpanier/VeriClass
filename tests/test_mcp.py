"""The MCP server (vericlass_mcp/server.py): its tools against the test backend,
and one real MCP round trip over stdio, as Claude Code runs it."""
import asyncio
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-mcp-tests")

import pytest
from fastapi.testclient import TestClient

from backend import db, exercises, packages
from backend.main import app
from vericlass_mcp import server

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES ('MCP T', 'MCP-T', 'teacher')")
        yield tc
        exercises.set_active("ex3-mcalc")


@pytest.fixture()
def tools(client, monkeypatch):
    """The MCP tools, with their HTTP calls going to the test backend."""
    def request(method, url, headers=None, timeout=None, **kw):
        return client.request(method, url.replace(server.URL, ""), headers=headers, **kw)
    monkeypatch.setattr(server.httpx, "request", request)
    return server


def test_status(tools):
    st = tools.status()
    assert st["running"] and st["data_folder"] == str(packages.DATA_DIR)
    assert "pkg-demo" in {e["exercise_id"] for e in st["exercises"]}


def test_write_validate_push_assign(tools):
    made = tools.new_exercise_folder("mcp-lab", title_en="MCP lab")
    folder = Path(made["folder"])
    assert folder.parent == packages.DATA_DIR / "drafts"
    # The template alone is not a finished exercise: fill it from the demo package.
    for name in ("exercise.yaml", "teacher.yaml", "faq.yaml"):
        text = (packages.exercises_dir() / "pkg-demo" / name).read_text(encoding="utf-8")
        (folder / name).write_text(text.replace("pkg-demo", "mcp-lab"), encoding="utf-8")
    shutil.copytree(packages.exercises_dir() / "pkg-demo" / "files", folder / "files", dirs_exist_ok=True)
    v = tools.validate_exercise(str(folder))
    assert v["ok"], v["errors"]

    tools.create_course("mcp-course", "MCP course")
    r = tools.push_exercise(str(folder), course_id="mcp-course", meeting_date="2030-01-15", meeting_title="Lab 3")
    assert r["ok"] and r["course"]["meeting"]["exercise_id"] == "mcp-lab"
    assert exercises.get("mcp-lab")["source"] == "package"
    course = next(c for c in tools.list_courses() if c["course_id"] == "mcp-course")
    assert course["meetings"][0]["meeting_date"] == "2030-01-15" and "mcp-lab" in course["exercises"]
    a = tools.assign_exercise("mcp-course", "ex3-mcalc", make_default=True)
    assert a["default_exercise"] == "ex3-mcalc"

    edit = tools.export_exercise("mcp-lab")
    assert (Path(edit["folder"]) / "exercise.yaml").is_file()


def test_import_students_never_returns_names_or_codes(tools):
    csv = Path(tempfile.mkdtemp()) / "class.csv"
    csv.write_text("name,email\nHidden Person,hidden@x.ac.il\n,nobody@x.ac.il\n", encoding="utf-8")
    dry = tools.import_students(str(csv), course_id="mcp-course", dry_run=True)
    assert dry["counts"] == {"new": 1, "existing": 0, "errors": 1} and "codes_file" not in dry
    done = tools.import_students(str(csv), course_id="mcp-course", dry_run=False)
    assert "Hidden Person" not in str(done)
    codes = Path(done["codes_file"])
    assert codes.parent == packages.DATA_DIR / "codes" and stat.S_IMODE(codes.stat().st_mode) == 0o600
    assert "Hidden Person" in codes.read_text(encoding="utf-8-sig")


def test_same_second_does_not_clash(tools):
    """Imports, pushes and exports right after each other each get their own
    file or folder (the names carry only the second)."""
    csv = Path(tempfile.mkdtemp()) / "pair.csv"
    csv.write_text("name\nFirst Quick\n", encoding="utf-8")
    one = tools.import_students(str(csv), dry_run=False)
    csv.write_text("name\nSecond Quick\n", encoding="utf-8")
    two = tools.import_students(str(csv), dry_run=False)
    assert one["codes_file"] != two["codes_file"]
    assert "Second Quick" in Path(two["codes_file"]).read_text(encoding="utf-8-sig")

    folder = Path(tools.export_exercise("pkg-demo")["folder"])
    assert tools.export_exercise("pkg-demo")["folder"] != str(folder)
    text = (folder / "exercise.yaml").read_text(encoding="utf-8").replace("pkg-demo", "mcp-quick")
    (folder / "exercise.yaml").write_text(text, encoding="utf-8")
    for _ in range(3):
        assert tools.push_exercise(str(folder))["ok"]
    kept = [p for p in (packages.exercises_dir() / ".previous").iterdir() if p.name.startswith("mcp-quick-")]
    assert len(kept) == 2


def test_session_report_is_saved(tools):
    rep = tools.session_report(exercise_id="ex3-mcalc")
    if rep.get("found"):
        assert Path(rep["saved_to"]).parent == packages.DATA_DIR / "reports"


def test_real_mcp_round_trip_over_stdio():
    """Start the server as Claude Code does and call a tool through the protocol."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        params = StdioServerParameters(
            command=sys.executable, args=[str(REPO / "vericlass_mcp" / "server.py")],
            env={**os.environ, "VERICLASS_DATA_DIR": str(packages.DATA_DIR)})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                result = await session.call_tool(
                    "validate_exercise", {"folder": str(packages.exercises_dir() / "pkg-demo")})
                return names, result

    names, result = asyncio.run(run())
    assert {"push_exercise", "validate_exercise", "import_students", "session_report"} <= names
    assert not result.isError
    assert '"ok": true' in result.content[0].text.replace("True", "true").lower()
