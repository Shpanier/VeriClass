"""The sample package in examples/ stays a valid exercise, so a new lecturer's
first upload works."""
from pathlib import Path

from backend import packages

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_the_sample_lab_is_a_valid_package():
    r = packages.validate_package(EXAMPLES / "first-lab")
    assert r["ok"], r["errors"]
    s = r["summary"]
    assert s["exercise_id"] == "first-lab" and s["pacing"] == "class"
    assert s["steps"] == 3 and s["quiz_questions"] == 2 and s["checked_steps"] == 3


def test_the_sample_zip_installs(tmp_path):
    import io
    import zipfile

    buf = io.BytesIO()
    folder = EXAMPLES / "first-lab"
    with zipfile.ZipFile(buf, "w") as z:
        for p in folder.rglob("*"):
            if p.is_file():
                z.write(p, Path("first-lab") / p.relative_to(folder))
    r = packages.install_zip(buf.getvalue(), replace=True)
    assert r["ok"], r["errors"]
