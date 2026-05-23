import re

from backend import db

_ID_RE = re.compile(r"\b\d{9}\b")
_HOME_RE = re.compile(r"/home/[^/\s]+")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_ISRAELI_PHONE_RE = re.compile(r"\b0?5\d[-\s]?\d{3}[-\s]?\d{4}\b")


def sanitize(text: str) -> str:
    if not text:
        return text
    text = _ID_RE.sub("<ID>", text)
    text = _HOME_RE.sub("/home/<USER>", text)
    text = _EMAIL_RE.sub("<EMAIL>", text)
    text = _ISRAELI_PHONE_RE.sub("<PHONE>", text)
    for name in _student_names():
        if not name:
            continue
        text = re.sub(rf"\b{re.escape(name)}\b", "<STUDENT>", text, flags=re.IGNORECASE)
    return text


def _student_names() -> list[str]:
    with db.conn() as c:
        rows = c.execute("SELECT username FROM users WHERE role = 'student'").fetchall()
    names: list[str] = []
    for r in rows:
        names.extend(part for part in r["username"].split() if len(part) >= 2)
    return names
