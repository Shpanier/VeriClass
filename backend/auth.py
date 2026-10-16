import secrets
import time
from collections import defaultdict
from typing import Optional

from backend import db

# token -> {"id": int, "username": str, "role": str}. Role is cached on the
# token so every authorized request avoids a DB round-trip; a role change needs
# a re-login, which is fine for a lab-session tool.
_SESSION_TOKENS: dict[str, dict] = {}
_FAILED_ATTEMPTS: dict[str, list[float]] = defaultdict(list)  # ip -> [timestamps]
_RATE_LIMIT_WINDOW = 60 * 5  # 5 min
_RATE_LIMIT_MAX = 4


def login_with_code(code: str, ip: str, allow_teacher: bool = True,
                    rate_limit: bool = True) -> Optional[dict]:
    if rate_limit and _is_rate_limited(ip):
        return {"rate_limited": True}
    with db.conn() as c:
        row = c.execute(
            "SELECT id, username, role FROM users WHERE login_code = ?", (code,)
        ).fetchone()
    if not row:
        if rate_limit:
            _FAILED_ATTEMPTS[ip].append(time.time())
        return None
    if row["role"] == "teacher" and not allow_teacher:
        return {"blocked": True}
    token = secrets.token_urlsafe(24)
    _SESSION_TOKENS[token] = {"id": row["id"], "username": row["username"], "role": row["role"]}
    return {"token": token, "user_id": row["id"], "username": row["username"], "role": row["role"]}


def user_for_token(token: str) -> Optional[dict]:
    """Full user record ({id, username, role}) for a bearer token, or None."""
    return _SESSION_TOKENS.get(token)


def user_id_for_token(token: str) -> Optional[int]:
    rec = _SESSION_TOKENS.get(token)
    return rec["id"] if rec else None


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    _FAILED_ATTEMPTS[ip] = [t for t in _FAILED_ATTEMPTS[ip] if now - t < _RATE_LIMIT_WINDOW]
    return len(_FAILED_ATTEMPTS[ip]) >= _RATE_LIMIT_MAX
