"""Accounts and sessions.

Standard library only. `hashlib.scrypt` is a memory-hard password KDF and
`secrets` is a CSPRNG, so no third-party dependency is needed — which matters
here, because this project has already been broken once by a dependency that
worked locally and was missing from a fresh clone, and authentication is the
worst place to repeat that.

Two things are deliberately never stored in plaintext: the password (scrypt with
a per-user salt) and the session token (SHA-256). Someone who reads the database
file can therefore neither sign in as a member nor replay a live session.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

# Interactive-login scrypt parameters: ~16 MB and a few tens of milliseconds per
# hash. High enough to make offline cracking expensive, low enough that a login
# request does not visibly stall.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DK_LEN = 32

SESSION_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DK_LEN
    )


def hash_password(password: str) -> tuple[str, str]:
    """Return (password_hash, salt), both hex."""
    salt = secrets.token_bytes(16)
    return _derive(password, salt).hex(), salt.hex()


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    try:
        expected = bytes.fromhex(password_hash)
        salt_bytes = bytes.fromhex(salt)
    except ValueError:
        return False
    # Constant-time: a plain `==` leaks how much of the hash matched via timing.
    return hmac.compare_digest(_derive(password, salt_bytes), expected)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(conn: sqlite3.Connection, user_id: int) -> str:
    """Create a session and return the raw token — the only time it exists."""
    token = secrets.token_urlsafe(32)
    now = _now()
    conn.execute(
        """INSERT INTO session (token_hash, user_id, created_at, expires_at)
           VALUES (?,?,?,?)""",
        (
            _token_hash(token),
            user_id,
            now.isoformat(timespec="seconds"),
            (now + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return token


def revoke_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM session WHERE token_hash = ?", (_token_hash(token),))
    conn.commit()


def create_user(conn: sqlite3.Connection, email: str, password: str) -> int:
    """Create an account, adopting any pre-account data on the very first one.

    ABYSS was single-user until now, so the database already holds a plan, some
    lookups and any uploaded benefits with no owner. The first account to be
    created takes them over; later accounts start empty. Without this the
    existing plan would still be sitting in the table, invisible and unreachable.
    """
    password_hash, salt = hash_password(password)
    cur = conn.execute(
        """INSERT INTO user (email, password_hash, salt, created_at)
           VALUES (?,?,?,?)""",
        (email, password_hash, salt, _now().isoformat(timespec="seconds")),
    )
    user_id = int(cur.lastrowid)
    if conn.execute("SELECT COUNT(*) FROM user").fetchone()[0] == 1:
        for table in ("plan", "lookup_history", "appointment"):
            conn.execute(f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL", (user_id,))
    conn.commit()
    return user_id


def normalize_email(email: str) -> str:
    return email.strip().lower()


def user_for_token(conn: sqlite3.Connection, token: str | None) -> int | None:
    """Resolve a bearer token to a user id, or None if it is absent or expired."""
    if not token:
        return None
    row = conn.execute(
        "SELECT user_id, expires_at FROM session WHERE token_hash = ?",
        (_token_hash(token),),
    ).fetchone()
    if not row:
        return None
    if row["expires_at"] <= _now().isoformat(timespec="seconds"):
        conn.execute("DELETE FROM session WHERE token_hash = ?", (_token_hash(token),))
        conn.commit()
        return None
    return int(row["user_id"])


def bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


class Unauthorized(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=401, detail="sign in to continue")
