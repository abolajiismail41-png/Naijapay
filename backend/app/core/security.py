import asyncio
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.errors import UnauthorizedError

_ALGORITHM = "HS256"
_hasher = PasswordHasher()
# Verified when the account does not exist so timing does not reveal which phones are registered.
_DUMMY_HASH = _hasher.hash("timing-equalisation-only")


async def hash_secret(plain: str) -> str:
    return await asyncio.to_thread(_hasher.hash, plain)


async def verify_secret(stored_hash: str | None, plain: str) -> bool:
    try:
        await asyncio.to_thread(_hasher.verify, stored_hash or _DUMMY_HASH, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return stored_hash is not None


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def keyed_digest(key: str, *parts: str) -> str:
    return hmac.new(key.encode(), "|".join(parts).encode(), hashlib.sha256).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def new_otp() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def encode_token(secret: str, typ: str, subject: str, ttl: timedelta, **claims: Any) -> str:
    now = datetime.now(UTC)
    payload = {**claims, "sub": subject, "typ": typ, "iat": now, "exp": now + ttl,
               "jti": uuid.uuid4().hex}
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_token(secret: str, token: str, typ: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, secret, algorithms=[_ALGORITHM],
                            options={"require": ["exp", "iat", "sub", "typ"]})
    except jwt.PyJWTError:
        raise UnauthorizedError("Your session is invalid or has expired.") from None
    if claims.get("typ") != typ:
        raise UnauthorizedError("Your session is invalid or has expired.")
    return claims
