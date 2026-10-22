"""Login passwords.

Every user logs in with their login code (their username, e.g. the part of the
college email before the @) and a password. Until the teacher sets one, the
password is the login code itself, typed in any case: users.password_hash is
NULL and nothing secret is stored. A set password is stored only as a salted
PBKDF2-SHA256 hash, and is case-sensitive.

Set or reset passwords with POST /api/users/{id}/password (teacher) or
scripts/set_password.py.
"""
import hashlib
import hmac
import secrets
from typing import Optional

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000
MIN_LENGTH = 6


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode(), _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt}${digest.hex()}"


def verify(password: str, stored_hash: Optional[str], login_code: str) -> bool:
    """True when `password` opens this account. No stored hash: the password is
    the login code (case-insensitive, like the code itself)."""
    if not password:
        return False
    if not stored_hash:
        return hmac.compare_digest(password.strip().upper().encode(), login_code.upper().encode())
    try:
        algo, iterations, salt, expected = stored_hash.split("$")
    except ValueError:
        return False
    if algo != _ALGO:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode(), int(iterations))
    return hmac.compare_digest(digest.hex(), expected)


def check_new(password: str) -> Optional[str]:
    """Why a new password can't be used, or None when it can."""
    if len(password) < MIN_LENGTH:
        return f"A password needs at least {MIN_LENGTH} characters."
    if password != password.strip():
        return "A password can't start or end with a space."
    return None
