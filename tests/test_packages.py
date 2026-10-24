"""Exercise packages in the private data folder (backend/packages.py): loading,
what students see, downloads, validation, installing (folder and zip), dashboard
edits written back into the files, export, and the question bank."""
import base64
import io
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("GEMINI_API_KEY", "unused-in-package-tests")

import pytest
import yaml
from fastapi.testclient import TestClient

from backend import bank, db, exercises, packages
from backend.main import app

PKG = "pkg-demo"


@pytest.fixture(scope="module")
def client():
    with TestClient(app, client=("127.0.0.1", 50000)) as tc:
        with db.conn() as c:
            c.execute("INSERT OR IGNORE INTO users (username, login_code, role) VALUES ('Pkg T', 'PKG-T', 'teacher')")
        yield tc
        exercises.set_active("ex3-mcalc")


def _th(tc):
    tok = tc.post("/api/login", json={"code": "PKG-T", "password": "PKG-T"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _student(tc, code):
    with db.conn() as c:
        c.execute("INSERT INTO users (username, login_code, role) VALUES (?, ?, 'student')", (code, code))
    tok = tc.post("/api/login", json={"code": code, "password": code}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _folder(name: str) -> Path:
    """A copy of the fixture package with another id, outside the data folder."""
    dst = Path(tempfile.mkdtemp()) / name
    shutil.copytree(packages.exercises_dir() / PKG, dst)
    text = (dst / "exercise.yaml").read_text(encoding="utf-8").replace(f"exercise_id: {PKG}", f"exercise_id: {name}")
    (dst / "exercise.yaml").write_text(text, encoding="utf-8")
    return dst


def test_data_folder_is_the_test_copy():
    # Never the lecturer's real ../VeriExPrivateData (tests/conftest.py).
    assert "veriexam-data-" in str(packages.DATA_DIR)


def test_package_loads_with_teacher_fields_and_bank(client):
    ex = exercises.get(PKG)
    assert ex["source"] == "package" and ex["implicit_variant"] and ex["variants"][0]["id"] == "default"
    assert ex["steps"][0]["expected"].startswith("3 rows") and ex["steps"][0]["questions"] == 2
    assert ex["steps"][0]["evidence"][0]["command"] == "python count.py"
    assert ex["teacher_notes"].startswith("The answer")
    assert [q["id"] for q in ex["faq"]] == ["q01", "q02"]
    assert ex["download_name"] == "pkg-demo-files.zip"
    # A variant id from before the exercise lost its placeholder variant still opens.
    assert exercises.variant(PKG, "A")["id"] == "default"


def test_students_never_get_teacher_fields(client):
    exercises.set_active(PKG)
    h = _student(client, "PKG-S1")
    s = client.post("/api/sessions", json={"exercise_id": PKG}, headers=h).json()
    r = client.get(f"/api/exercises/active?variant={s['variant']}&session_id={s['session_id']}", headers=h)
    body = r.json()
    assert "Count the rows" in body["brief_md"] and "3 rows" not in r.text and "The answer" not in r.text
    assert body["steps_total"] == 2 and body["step_current"] == 1
    assert body["check_command"] == "python checks.py"
    assert body["terminal"]["blocked_hint"] == "Install packages in PyCharm's Terminal tab."
    assert "pip" in body["terminal"]["allow"]  # a Python exercise


def test_downloads(client):
    r = client.get("/api/files/pkg-demo-files.zip")
    assert r.status_code == 200
    names = sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert names == ["checks.py", "count.py", "data.csv"]
    assert client.get("/api/files/data.csv").text.startswith("a,b")
    for secret in ("solution.py", "teacher.yaml", "exercise.yaml", "source.md"):
        assert client.get(f"/api/files/{secret}").status_code == 404
    # Nothing outside a package's files/: not the server's own folder or database.
    for other in ("veriexam.db", "requirements.txt", "README.md", ".env"):
        assert client.get(f"/api/files/{other}").status_code == 404


def test_validate(client):
    result = packages.validate_package(packages.exercises_dir() / PKG)
    assert result["ok"], result["errors"]
    assert any("question bank has 2" in w for w in result["warnings"])
    s = result["summary"]
    assert (s["steps"], s["minutes"], s["teacher_answers"], s["bank_questions"]) == (2, 15.0, 2, 2)
    assert s["files"] == ["checks.py", "count.py", "data.csv"]

    broken = _folder("pkg-broken")
    (broken / "teacher.yaml").write_text("steps:\n  - expected: x\n  - expected: y\n  - expected: z\n", "utf-8")
    bad = packages.validate_package(broken)
    assert not bad["ok"] and "step 3 doesn't exist" in bad["errors"][0]


def test_install_folder_and_zip(client):
    th = _th(client)
    src = _folder("pkg-two")
    r = client.post("/api/exercises/install", json={"path": str(src)}, headers=th)
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert (packages.exercises_dir() / "pkg-two" / "exercise.yaml").is_file()
    assert exercises.get("pkg-two")["source"] == "package"
    # Installing again keeps the previous version.
    assert client.post("/api/exercises/install", json={"path": str(src)}, headers=th).json()["ok"]
    assert any(p.name.startswith("pkg-two-") for p in (packages.exercises_dir() / ".previous").iterdir())

    zsrc = _folder("pkg-three")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in zsrc.rglob("*"):
            if p.is_file():
                z.write(p, f"pkg-three/{p.relative_to(zsrc).as_posix()}")
    r = client.post("/api/exercises/import", json={"zip_base64": base64.b64encode(buf.getvalue()).decode()},
                    headers=th)
    assert r.json()["ok"], r.text
    assert "pkg-three" in {e["exercise_id"] for e in client.get("/api/exercises", headers=th).json()}

    r = client.post("/api/exercises/import", json={"zip_base64": base64.b64encode(b"not a zip").decode()},
                    headers=th)
    assert not r.json()["ok"]


def test_dashboard_edit_is_written_back_to_the_files(client):
    th = _th(client)
    full = client.get(f"/api/exercises/{PKG}", headers=th).json()
    assert full["steps"][0]["expected"].startswith("3 rows") and full["folder"].endswith(PKG)
    payload = {k: full[k] for k in ("exercise_id", "title_en", "title_he", "default_mode", "brief_md", "variants",
                                    "welcome_suggestions", "required_error_strings", "param_labels")}
    payload["steps"] = [dict(full["steps"][0], text="Run `count.py` again.\n- How many rows?\n"),
                        dict(full["steps"][1], expected="Three.")]
    payload["tutor_notes"] = "Never state the number of rows or columns."
    r = client.put(f"/api/exercises/{PKG}", json=payload, headers=th)
    assert r.status_code == 200, r.text

    folder = packages.exercises_dir() / PKG
    ex_text = (folder / "exercise.yaml").read_text(encoding="utf-8")
    assert ex_text.startswith("# A small package for the tests")      # comments kept
    assert "Run `count.py` again." in ex_text and "expected" not in ex_text  # answers stay out
    assert "variants" not in ex_text                                   # still no variants
    teacher = yaml.safe_load((folder / "teacher.yaml").read_text(encoding="utf-8"))
    assert teacher["steps"][1]["expected"] == "Three."
    assert teacher["steps"][0]["evidence"][0]["command"] == "python count.py"  # untouched fields kept
    ex = exercises.get(PKG)
    assert ex["tutor_notes"].startswith("Never state the number of rows or columns")
    assert ex["steps"][0]["text"].startswith("Run `count.py` again.")
    # No database copy: the folder is the source.
    with db.conn() as c:
        assert c.execute("SELECT 1 FROM exercises WHERE exercise_id = ?", (PKG,)).fetchone() is None


def test_export(client):
    th = _th(client)
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/exercises/{PKG}/export", headers=th).content))
    names = set(z.namelist())
    assert f"{PKG}/exercise.yaml" in names and f"{PKG}/files/data.csv" in names
    assert not any("/solution/" in n for n in names)
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/exercises/ex3-mcalc/export", headers=th).content))
    body = yaml.safe_load(z.read("ex3-mcalc/exercise.yaml"))
    assert body["exercise_id"] == "ex3-mcalc" and body["variants"]


def test_bank_from_the_package(client):
    exercises.set_active(PKG)
    h = _student(client, "PKG-S2")
    sid = client.post("/api/sessions", json={"exercise_id": PKG}, headers=h).json()["session_id"]
    m = bank.match_for_session(sid, "how can I count the rows in a csv file?")
    assert m and m["id"] == "q01"
    m = bank.match_for_session(sid, "איך סופרים את השורות בקובץ CSV")
    assert m and m["id"] == "q01"
