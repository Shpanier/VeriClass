"""Seed the users table with student / teacher rows + random login codes.

Usage:
    python scripts/add_students.py --names "Yossi Cohen,Shira Levi,Ahmed Alyan"
    python scripts/add_students.py --teachers "Dr. Cohen"
    python scripts/add_students.py --names "..." --teachers "Dr. Cohen"
    python scripts/add_students.py --names "..." --course devops-2026
    python scripts/add_students.py --csv roster.csv --course dl-2026 [--dry-run] [--codes-out codes.csv]

At least one of --names / --teachers is required. Teachers get a login code
too — that code is what signs them into the dashboard (which is now behind an
instructor login). The password starts as the login code (backend/passwords.py;
change it with scripts/set_password.py). --course adds the new students to an
existing course (create courses in the dashboard's Courses tab).

Prints a table of name → code to distribute.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import courses, db, roster
from backend.roster import generate_code


def _seed(c, names: list[str], role: str) -> list[tuple[str, str]]:
    rows = []
    for name in names:
        for _ in range(5):
            code = generate_code()
            try:
                c.execute(
                    "INSERT INTO users (username, login_code, role) VALUES (?, ?, ?)",
                    (name, code, role),
                )
                rows.append((name, code))
                break
            except sqlite3.IntegrityError:
                continue  # code (or username) collision — retry with a new code
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--names", help="Comma-separated student names")
    parser.add_argument("--teachers", help="Comma-separated instructor names (role=teacher)")
    parser.add_argument("--course", help="Add the new students to this course (its id, e.g. devops-2026)")
    parser.add_argument("--csv", help="A student list (name / first+last name, email, student id, course, group)")
    parser.add_argument("--dry-run", action="store_true", help="With --csv: show what would happen, change nothing")
    parser.add_argument("--codes-out", help="With --csv: write name,login code,... for the imported students here")
    args = parser.parse_args()
    if not args.names and not args.teachers and not args.csv:
        parser.error("provide --names, --teachers and/or --csv")

    db.init_schema()
    if args.csv:
        _import_csv(args)
        if not args.names and not args.teachers:
            return
    students = [n.strip() for n in (args.names or "").split(",") if n.strip()]
    teachers = [n.strip() for n in (args.teachers or "").split(",") if n.strip()]

    if args.course and courses.get(args.course) is None:
        parser.error(f"no course '{args.course}': create it in the dashboard's Courses tab first")

    with db.conn() as c:
        student_rows = _seed(c, students, "student")
        teacher_rows = _seed(c, teachers, "teacher")
        ids = [c.execute("SELECT id FROM users WHERE username = ?", (n,)).fetchone()["id"]
               for n, _ in student_rows]
    if args.course and ids:
        courses.add_members(args.course, ids)
        print(f"\nAdded {len(ids)} students to course {args.course}.")

    def _table(title, rows):
        if not rows:
            return
        print(f"\nSeeded {len(rows)} {title}:\n")
        print(f"| {'Name':<24} | {'Login code':<10} |")
        print(f"|{'-' * 26}|{'-' * 12}|")
        for name, code in rows:
            print(f"| {name:<24} | {code:<10} |")
        print()

    _table("students", student_rows)
    _table("teachers (dashboard login)", teacher_rows)


def _import_csv(args) -> None:
    if args.course and courses.get(args.course) is None:
        raise SystemExit(f"no course '{args.course}': create it in the dashboard's Courses tab first")
    with open(args.csv, "rb") as f:
        text = roster.decode(f.read())
    result = roster.plan(text, args.course) if args.dry_run else roster.apply(text, args.course)
    for r in result["rows"]:
        state = f"ERROR: {r['error']}" if r.get("error") else r["status"]
        print(f"line {r['line']:>4}  {r.get('username') or r['name']:<28} {r.get('course') or '-':<14} {state}")
    c = result["counts"]
    print(f"\n{c['new']} new, {c['existing']} existing, {c['errors']} with errors"
          + (" (dry run: nothing changed)" if args.dry_run else ""))
    if args.codes_out and not args.dry_run:
        with open(args.codes_out, "w", encoding="utf-8-sig", newline="") as f:
            f.write(roster.codes_csv(result["rows"]))
        print(f"Login codes written to {args.codes_out}. Keep this file out of git.")


if __name__ == "__main__":
    main()
