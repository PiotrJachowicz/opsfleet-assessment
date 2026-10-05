"""JWT identity and brand scopes for the prototype.

Production assumption: the frontend sends a JWT with the user's brand scopes.
This prototype uses a few preset identities and a shared HS256 secret.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

ADMIN_BRAND = "*"

PRESET_USERS: dict[str, dict[str, Any]] = {
    "admin": {
        "sub": "admin",
        "name": "Admin (all brands)",
        "brands": [ADMIN_BRAND],
    },
    "calvin": {
        "sub": "brand-calvin",
        "name": "Calvin Klein analyst",
        "brands": ["Calvin Klein"],
    },
    "levis": {
        "sub": "brand-levis",
        "name": "Levi's analyst",
        "brands": ["Levi's"],
    },
}


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    brands: tuple[str, ...]
    name: str = ""

    @property
    def is_admin(self) -> bool:
        return ADMIN_BRAND in self.brands

    @property
    def allowed_brands(self) -> tuple[str, ...]:
        if self.is_admin:
            return ()
        return self.brands


class AuthError(ValueError):
    pass


_auth_ctx: ContextVar[AuthContext | None] = ContextVar("auth_ctx", default=None)


def get_auth_context() -> AuthContext | None:
    return _auth_ctx.get()


def set_auth_context(ctx: AuthContext | None):
    return _auth_ctx.set(ctx)


def reset_auth_context(token) -> None:
    _auth_ctx.reset(token)


def mint_access_token(
    *,
    preset_key: str,
    secret: str,
    ttl_hours: int = 12,
) -> str:
    if preset_key not in PRESET_USERS:
        raise AuthError(f"unknown preset user: {preset_key}")
    if not secret:
        raise AuthError("JWT secret is not configured")
    profile = PRESET_USERS[preset_key]
    now = datetime.now(UTC)
    payload = {
        "sub": profile["sub"],
        "name": profile["name"],
        "brands": list(profile["brands"]),
        "iat": now,
        "exp": now + timedelta(hours=ttl_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def parse_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("missing Authorization header")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError("Authorization must be Bearer <token>")
    return parts[1].strip()


def verify_access_token(token: str, secret: str) -> AuthContext:
    if not secret:
        raise AuthError("JWT secret is not configured")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthError(f"invalid token: {exc}") from exc

    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        raise AuthError("token missing sub")

    raw_brands = payload.get("brands")
    if not isinstance(raw_brands, list) or not raw_brands:
        raise AuthError("token missing brands claim")
    brands = tuple(str(b).strip() for b in raw_brands if str(b).strip())
    if not brands:
        raise AuthError("token brands claim is empty")

    return AuthContext(
        user_id=user_id,
        brands=brands,
        name=str(payload.get("name") or ""),
    )


def auth_context_from_authorization(authorization: str | None, secret: str) -> AuthContext:
    return verify_access_token(parse_bearer_token(authorization), secret)
