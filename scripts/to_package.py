"""Turn a one-file exercise (config/exercises/<id>.yaml) into an exercise package
in the private data folder (backend/packages.py), keeping its comments:

    python scripts/to_package.py config/exercises/lab1-linux-git.yaml
    python scripts/to_package.py config/exercises/dl2-lab2-apartments.yaml \\
        --files config/exercise_files/lab2-apartments.zip --download lab2-apartments.zip \\
        --check-command "python checks.py"

Teacher-only step fields (expected, os_check, evidence, questions) move to
teacher.yaml. A single placeholder variant (no parameters, no tests) is dropped:
the exercise then has its implicit variant, and old sessions still open it.
--files takes a zip (extracted), a folder (copied) or single files.
"""
import argparse
import shutil
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ruamel.yaml import YAML  # noqa: E402
from ruamel.yaml.comments import CommentedMap  # noqa: E402

from backend import packages  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="the exercise's YAML file")
    ap.add_argument("--files", nargs="*", default=[], help="what students download: a zip, a folder or files")
    ap.add_argument("--download", help="the zip's name at /api/files/<name> (default <exercise_id>.zip)")
    ap.add_argument("--check-command", help="run by the plugin on each step submission, e.g. 'python checks.py'")
    ap.add_argument("--out", default=str(packages.exercises_dir()), help="where the package folder goes")
    ap.add_argument("--force", action="store_true", help="replace an existing package folder")
    args = ap.parse_args()

    rt = YAML()
    rt.preserve_quotes = True
    rt.width = 100
    rt.indent(mapping=2, sequence=4, offset=2)
    src = Path(args.source)
    doc = rt.load(src.read_text(encoding="utf-8"))
    eid = doc["exercise_id"]
    target = Path(args.out).expanduser() / eid
    if target.exists():
        if not args.force:
            raise SystemExit(f"{target} exists (use --force to replace it)")
        shutil.rmtree(target)
    target.mkdir(parents=True)

    t_steps = []
    for step in doc.get("steps") or []:
        t_steps.append({k: step.pop(k) for k in packages.TEACHER_STEP_KEYS if k in step})
    variants = doc.get("variants") or []
    if len(variants) == 1 and not variants[0].get("params") and not variants[0].get("test_inputs"):
        del doc["variants"]
    if args.download:
        doc["download"] = args.download
    if args.check_command:
        doc["check_command"] = args.check_command

    with (target / packages.EXERCISE_FILE).open("w", encoding="utf-8") as f:
        rt.dump(doc, f)
    if any(t_steps):
        teacher = CommentedMap()
        teacher["steps"] = t_steps
        teacher.yaml_set_start_comment(
            "Teacher-only: the expected answers and checks of each step (in step order).\n"
            "Never sent to students or to the tutor model.")
        with (target / packages.TEACHER_FILE).open("w", encoding="utf-8") as f:
            rt.dump(teacher, f)

    files = target / packages.FILES_DIR
    for item in map(Path, args.files):
        files.mkdir(exist_ok=True)
        if item.suffix == ".zip":
            with zipfile.ZipFile(item) as z:
                z.extractall(files)
        elif item.is_dir():
            shutil.copytree(item, files, dirs_exist_ok=True)
        else:
            shutil.copy2(item, files / item.name)
    (target / "source.md").write_text(
        f"# Source\n\nConverted from `{src.name}` on {time.strftime('%Y-%m-%d')} "
        f"(scripts/to_package.py).\n", encoding="utf-8")

    result = packages.validate_package(target)
    print(f"{eid}: {'OK' if result['ok'] else 'ERRORS'} -> {target}")
    for e in result["errors"]:
        print("  error:", e)
    for w in result["warnings"]:
        print("  warning:", w)
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
