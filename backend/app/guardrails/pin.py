import hashlib
import hmac
import secrets
import time

from .. import db

TOKEN_TTL_SECONDS = 30 * 60


def _scrypt(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1)


def _store(key: str, value: str) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def _load(key: str) -> str | None:
    with db.get_conn() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def is_set() -> bool:
    return _load("pin_hash") is not None


def set_pin(pin: str) -> None:
    salt = secrets.token_bytes(16)
    _store("pin_hash", salt.hex() + "$" + _scrypt(pin, salt).hex())


def verify_pin(pin: str) -> bool:
    stored = _load("pin_hash")
    if not stored:
        return False
    salt_hex, hash_hex = stored.split("$", 1)
    candidate = _scrypt(pin, bytes.fromhex(salt_hex))
    return hmac.compare_digest(candidate.hex(), hash_hex)


def clear_pin() -> None:
    with db.get_conn() as conn:
        conn.execute("DELETE FROM app_settings WHERE key IN ('pin_hash', 'pin_token', 'pin_token_expires')")


def issue_token() -> str:
    token = secrets.token_urlsafe(32)
    _store("pin_token", hashlib.sha256(token.encode()).hexdigest())
    _store("pin_token_expires", str(int(time.time()) + TOKEN_TTL_SECONDS))
    return token


def token_valid(token: str | None) -> bool:
    if not token:
        return False
    stored = _load("pin_token")
    expires = _load("pin_token_expires")
    if not stored or not expires:
        return False
    if int(expires) < time.time():
        return False
    return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), stored)