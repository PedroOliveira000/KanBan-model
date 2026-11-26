"""Password hashing and short-lived access tokens for the Kanban API."""

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv

load_dotenv()

_HASH_SCHEME = "pbkdf2_sha256"
_HASH_ITERATIONS = 600_000
_TOKEN_LIFETIME = timedelta(days=7)


def _auth_secret() -> str:
    secret = os.getenv("KANBAN_AUTH_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("KANBAN_AUTH_SECRET precisa ter pelo menos 32 caracteres")
    return secret


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _HASH_ITERATIONS)
    salt_text = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    digest_text = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{_HASH_SCHEME}${_HASH_ITERATIONS}${salt_text}${digest_text}"


def is_password_hash(value: str) -> bool:
    return value.startswith(f"{_HASH_SCHEME}$")


def verify_password(password: str, stored_value: str) -> bool:
    """Verify current hashes and allow one-time migration of legacy plain values."""
    if not is_password_hash(stored_value):
        return hmac.compare_digest(password.encode("utf-8"), stored_value.encode("utf-8"))

    try:
        scheme, iterations_text, salt_text, digest_text = stored_value.split("$", 3)
        if scheme != _HASH_SCHEME:
            return False
        iterations = int(iterations_text)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(digest_text + "=" * (-len(digest_text) % 4))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + _TOKEN_LIFETIME,
    }
    return jwt.encode(payload, _auth_secret(), algorithm="HS256")


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(
            token,
            _auth_secret(),
            algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp"]},
        )
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Token inválido ou expirado") from exc
