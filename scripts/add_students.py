"""Seed the users table with student / teacher rows + random login codes.

Usage:
    python scripts/add_students.py --names "Yossi Cohen,Shira Levi,Ahmed Alyan"
    python scripts/add_students.py --teachers "Dr. Cohen"
    python scripts/add_students.py --names "..." --teachers "Dr. Cohen"

At least one of --names / --teachers is required. Teachers get a login code
too — that code is what signs them into the dashboard (which is now behind an
instructor login).

Prints a table of name → code to distribute.
"""
import argparse
import secrets
import sqlite3
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import db


def generate_code() -> str:
    """8 chars, hyphen-separated: 3-4 split → 'K3M-9XQ2'."""
    alphabet = string.ascii_uppercase + string.digits
    left = "".join(secrets.choice(alphabet) for _ in range(3))
    right = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"{left}-{right}"


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
    args = parser.parse_args()
    if not args.names and not args.teachers:
        parser.error("provide --names and/or --teachers")

    db.init_schema()
    students = [n.strip() for n in (args.names or "").split(",") if n.strip()]
    teachers = [n.strip() for n in (args.teachers or "").split(",") if n.strip()]

    with db.conn() as c:
        student_rows = _seed(c, students, "student")
        teacher_rows = _seed(c, teachers, "teacher")

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


if __name__ == "__main__":
    main()
