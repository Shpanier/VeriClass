"""Student lists from a CSV file: preview, then create the accounts and add them
to a course. Used by the dashboard (Courses tab), scripts/add_students.py
--csv and the MCP tool import_students.

Columns are recognized by name, in English or Hebrew, in any order:

    name (or first name + last name)   required
    email, student id                  optional; they tell students with the same name apart
    course, group                      optional; a course can also be chosen for the whole file

A Moodle participants export (First name, Last name/Surname, Email address)
works as is, and so does a CSV saved from Excel in Hebrew (Windows-1255). A file
with no header row is read as one name per line.
"""
import csv
import io
import re
import secrets
import string
from typing import Any, Optional

from backend import db

_ALIASES = {
    "name": {"name", "full name", "fullname", "student", "student name", "username", "שם", "שם מלא",
             "שם הסטודנט", "שם סטודנט", "שם התלמיד"},
    "first": {"first name", "firstname", "first", "given name", "שם פרטי"},
    "last": {"last name", "lastname", "surname", "family name", "last", "שם משפחה"},
    "email": {"email", "e-mail", "email address", "e-mail address", "mail", "דואל", "דוא\"ל", "דוא״ל",
              "מייל", "דואר אלקטרוני", "כתובת דואר אלקטרוני"},
    "student_id": {"id", "student id", "id number", "student number", "תעודת זהות", "ת.ז", "ת.ז.", "ת\"ז",
                   "ת״ז", "מספר סטודנט", "מספר זהות", "מספר תעודת זהות"},
    "course": {"course", "course id", "course_id", "קורס", "מזהה קורס"},
    "group": {"group", "section", "group name", "קבוצה", "כיתה"},
}
_NAME_MAX = 100
_ROWS_MAX = 2000


def generate_code() -> str:
    """8 chars, hyphen-separated: 3-4 split → 'K3M-9XQ2'."""
    alphabet = string.ascii_uppercase + string.digits
    left = "".join(secrets.choice(alphabet) for _ in range(3))
    right = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"{left}-{right}"


def decode(data: bytes) -> str:
    """UTF-8 (with or without BOM), else Excel's Hebrew Windows-1255."""
    for enc in ("utf-8-sig", "cp1255"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _key(header: str) -> Optional[str]:
    h = re.sub(r"\s+", " ", header.replace("﻿", "").strip().strip('"').lower())
    for key, names in _ALIASES.items():
        if h in names:
            return key
    return None


def parse(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows of {line, name, email, student_id, course, group} and the columns
    recognized. A row may carry `error`."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    table = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not table:
        return [], []
    keys = [_key(c) for c in table[0]]
    has_header = any(keys)
    body = table[1:] if has_header else table
    if not has_header:
        keys = ["name"] + [None] * (len(table[0]) - 1)
    rows = []
    for i, cells in enumerate(body[:_ROWS_MAX], start=2 if has_header else 1):
        rec: dict[str, Any] = {"line": i}
        for key, cell in zip(keys, cells):
            if key and cell.strip():
                rec[key] = cell.strip()
        if not has_header:
            # No header: other cells may still be an email or an ID number.
            for cell in cells[1:]:
                cell = cell.strip()
                if "@" in cell:
                    rec.setdefault("email", cell)
                elif re.fullmatch(r"\d{5,10}", cell):
                    rec.setdefault("student_id", cell)
        name = rec.pop("name", "") or " ".join(x for x in (rec.pop("first", ""), rec.pop("last", "")) if x)
        rec.pop("first", None)
        rec.pop("last", None)
        rec["name"] = re.sub(r"\s+", " ", name).strip()[:_NAME_MAX]
        if "email" in rec:
            rec["email"] = rec["email"].lower()
        if not rec["name"]:
            rec["error"] = "no name"
        rows.append(rec)
    return rows, sorted({k for k in keys if k} - {"first", "last"} | ({"name"} if "first" in keys else set()))


def plan(text: str, default_course: Optional[str] = None) -> dict[str, Any]:
    """What an import would do, without changing anything."""
    rows, columns = parse(text)
    with db.conn() as c:
        courses = {r["course_id"] for r in c.execute("SELECT course_id FROM courses")}
        users = [dict(r) for r in c.execute("SELECT id, username, login_code, role, email, student_id FROM users")]
    by_email = {u["email"].lower(): u for u in users if u["email"]}
    by_sid = {u["student_id"]: u for u in users if u["student_id"]}
    by_name = {u["username"]: u for u in users}
    seen: set[tuple] = set()
    for r in rows:
        r["course"] = r.get("course") or default_course
        if r.get("error"):
            continue
        if r["course"] and r["course"] not in courses:
            r["error"] = f"unknown course '{r['course']}'"
            continue
        ident = (r.get("email") or "", r.get("student_id") or "", "" if r.get("email") or r.get("student_id")
                 else r["name"])
        if ident in seen:
            r["error"] = "appears twice in the file"
            continue
        seen.add(ident)
        user = (by_email.get(r.get("email") or "") or by_sid.get(r.get("student_id") or "")
                or (by_name.get(r["name"]) if not (r.get("email") or r.get("student_id")) else None))
        if user is None and r["name"] in by_name:
            other = by_name[r["name"]]
            # Same name, different person (their email or ID differs): keep both apart.
            if other["email"] or other["student_id"]:
                r["username"] = f"{r['name']} ({r.get('student_id') or r.get('email', '').split('@')[0]})"
            else:
                user = other
        if user is not None:
            if user["role"] != "student":
                r["error"] = "that account is a teacher"
                continue
            r.update(status="existing", user_id=user["id"], code=user["login_code"])
        else:
            r["status"] = "new"
    counts = {s: sum(1 for r in rows if r.get("status") == s) for s in ("new", "existing")}
    counts["errors"] = sum(1 for r in rows if r.get("error"))
    return {"rows": rows, "counts": counts, "columns": columns}


def apply(text: str, default_course: Optional[str] = None) -> dict[str, Any]:
    """Create the new accounts, update emails/IDs/groups, add everyone to their
    course. Returns the plan with each row's login code."""
    result = plan(text, default_course)
    with db.conn() as c:
        for r in result["rows"]:
            if r.get("error"):
                continue
            if r["status"] == "new":
                username = r.get("username") or r["name"]
                for _ in range(10):
                    code = generate_code()
                    try:
                        cur = c.execute(
                            "INSERT INTO users (username, login_code, role, email, student_id, group_name) "
                            "VALUES (?, ?, 'student', ?, ?, ?)",
                            (username, code, r.get("email"), r.get("student_id"), r.get("group")),
                        )
                    except Exception as e:  # sqlite3.IntegrityError: code or name taken
                        if "username" in str(e):
                            r["error"] = "an account with this name already exists"
                            break
                        continue
                    r.update(user_id=cur.lastrowid, code=code)
                    break
                if r.get("error"):
                    r.pop("status", None)
                    continue
            else:
                c.execute(
                    "UPDATE users SET email = COALESCE(email, ?), student_id = COALESCE(student_id, ?), "
                    "group_name = COALESCE(?, group_name) WHERE id = ?",
                    (r.get("email"), r.get("student_id"), r.get("group"), r["user_id"]),
                )
            if r["course"]:
                c.execute("INSERT OR IGNORE INTO course_members (course_id, user_id) VALUES (?, ?)",
                          (r["course"], r["user_id"]))
    result["counts"]["errors"] = sum(1 for r in result["rows"] if r.get("error"))
    result["counts"]["new"] = sum(1 for r in result["rows"] if r.get("status") == "new")
    return result


def codes_csv(rows: list[dict[str, Any]]) -> str:
    """name,login code,course for the imported rows (to print or hand out)."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["name", "login code", "email", "course", "group"])
    for r in rows:
        if r.get("code") and not r.get("error"):
            w.writerow([r.get("username") or r["name"], r["code"], r.get("email") or "", r.get("course") or "",
                        r.get("group") or ""])
    return out.getvalue()
