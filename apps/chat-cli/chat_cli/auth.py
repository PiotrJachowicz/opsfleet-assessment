"""Preset JWT minting for the chat CLI (mirrors service auth claims)."""

from __future__ import annotations

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


def mint_access_token(*, preset_key: str, secret: str, ttl_hours: int = 12) -> str:
    if preset_key not in PRESET_USERS:
        raise ValueError(f"unknown preset: {preset_key}")
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


def format_presets() -> str:
    lines = []
    for key, profile in PRESET_USERS.items():
        brands = ", ".join(profile["brands"])
        lines.append(f"  {key:8s}  {profile['name']}  brands=[{brands}]")
    return "\n".join(lines)
