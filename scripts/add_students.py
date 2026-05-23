"""Seed the users table with student rows + random login codes.

Usage:
    python scripts/add_students.py --names "Yossi Cohen,Shira Levi,Ahmed Alyan"

Prints a table of name → code that the instructor distributes to students.
"""
import argparse
import secrets
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--names", required=True, help="Comma-separated student names")
    args = parser.parse_args()

    db.init_schema()
    names = [n.strip() for n in args.names.split(",") if n.strip()]

    rows = []
    with db.conn() as c:
        for name in names:
            for _ in range(5):
                code = generate_code()
                try:
                    c.execute(
                        "INSERT INTO users (username, login_code, role) VALUES (?, ?, 'student')",
                        (name, code),
                    )
                    rows.append((name, code))
                    break
                except Exception as e:
                    if "UNIQUE" in str(e):
                        continue
                    raise

    print(f"\nSeeded {len(rows)} students:\n")
    print(f"| {'Name':<24} | {'Login code':<10} |")
    print(f"|{'-' * 26}|{'-' * 12}|")
    for name, code in rows:
        print(f"| {name:<24} | {code:<10} |")
    print()


if __name__ == "__main__":
    main()
