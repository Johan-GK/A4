"""
Section 44 -- Login & Security.

Password hashing (44.1), MFA/TOTP (44.2), session/token lifecycle (44.3),
brute-force lockout (44.4). Uses `bcrypt` directly (not passlib) to avoid
version-shim fragility, and `python-jose` for JWT access/refresh tokens.
"""
import datetime as dt
import hashlib
import re
import secrets

import bcrypt
import pyotp
from jose import jwt, JWTError

from .config import settings

COMMON_PASSWORDS = {
    "password", "password1", "12345678", "123456789", "qwerty123",
    "letmein123", "admin1234", "welcome123", "changeme1", "iloveyou1",
}


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def validate_password_policy(plain: str) -> list:
    """Section 44.1: at least 10 chars, checked against a common/breached
    list. Returns a list of violation messages (empty == passes)."""
    problems = []
    if len(plain) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters.")
    if plain.lower() in COMMON_PASSWORDS:
        problems.append("Password is on the common/breached-password list.")
    if not re.search(r"[A-Za-z]", plain) or not re.search(r"[0-9]", plain):
        problems.append("Password must contain both letters and numbers.")
    return problems


def hash_token(token: str) -> str:
    """Session tokens are stored hashed (44.6 -- sensitive fields at rest)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user_id: str, session_id: str, roles: list) -> str:
    expire = dt.datetime.utcnow() + dt.timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    payload = {
        "sub": user_id,
        "sid": session_id,
        "roles": roles,
        "type": "access",
        "exp": expire,
        "iat": dt.datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str, session_id: str) -> str:
    expire = dt.datetime.utcnow() + dt.timedelta(hours=settings.REFRESH_TOKEN_HOURS)
    payload = {
        "sub": user_id,
        "sid": session_id,
        "type": "refresh",
        "exp": expire,
        "iat": dt.datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str):
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


def new_mfa_secret() -> str:
    return pyotp.random_base32()


def mfa_provisioning_uri(secret: str, email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name="PCTS")


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False


def random_idempotency_key() -> str:
    return secrets.token_hex(16)
