import secrets
import time
from collections import defaultdict
from typing import Optional

from backend import db

_SESSION_TOKENS: dict[str, int] = {}  # token -> user_id
_FAILED_ATTEMPTS: dict[str, list[float]] = defaultdict(list)  # ip -> [timestamps]
_RATE_LIMIT_WINDOW = 60 * 5  # 5 min
_RATE_LIMIT_MAX = 4


def login_with_code(code: str, ip: str) -> Optional[dict]:
    if _is_rate_limited(ip):
        return None
    with db.conn() as c:
        row = c.execute(
            "SELECT id, username, role FROM users WHERE login_code = ?", (code,)
        ).fetchone()
    if not row:
        _FAILED_ATTEMPTS[ip].append(time.time())
        return None
    token = secrets.token_urlsafe(24)
    _SESSION_TOKENS[token] = row["id"]
    return {"token": token, "user_id": row["id"], "username": row["username"], "role": row["role"]}


def user_id_for_token(token: str) -> Optional[int]:
    return _SESSION_TOKENS.get(token)


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    _FAILED_ATTEMPTS[ip] = [t for t in _FAILED_ATTEMPTS[ip] if now - t < _RATE_LIMIT_WINDOW]
    return len(_FAILED_ATTEMPTS[ip]) >= _RATE_LIMIT_MAX
