"""Set or reset login passwords (backend/passwords.py).

Usage:
    python scripts/set_password.py yossico                 # asks for the new password
    python scripts/set_password.py yossico --reset         # back to the default: the login code
    python scripts/set_password.py --reset-all --role student

Until a password is set, a user's password is their login code. The dashboard's
Courses tab can do the same for one user at a time.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import db, passwords  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("code", nargs="?", help="the user's login code (username)")
    ap.add_argument("--reset", action="store_true", help="password back to the login code")
    ap.add_argument("--reset-all", action="store_true", help="reset every user (see --role)")
    ap.add_argument("--role", choices=["student", "teacher"], help="with --reset-all: only this role")
    args = ap.parse_args()
    db.init_schema()

    if args.reset_all:
        where, params = ("WHERE role = ?", (args.role,)) if args.role else ("", ())
        with db.conn() as c:
            n = c.execute(f"UPDATE users SET password_hash = NULL {where}", params).rowcount
        print(f"Reset {n} passwords to the login code.")
        return
    if not args.code:
        ap.error("give a login code, or --reset-all")

    code = args.code.strip().upper()
    stored = None
    if not args.reset:
        new = getpass.getpass(f"New password for {code.lower()}: ")
        problem = passwords.check_new(new)
        if problem:
            sys.exit(problem)
        if getpass.getpass("Again: ") != new:
            sys.exit("The two passwords are different.")
        stored = passwords.hash_password(new)
    with db.conn() as c:
        if c.execute("UPDATE users SET password_hash = ? WHERE login_code = ?", (stored, code)).rowcount == 0:
            sys.exit(f"No user with login code {code.lower()}.")
    print(f"{code.lower()}: " + ("password set." if stored else "password is the login code again."))


if __name__ == "__main__":
    main()
