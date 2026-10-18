"""Supabase JWT verification (JWKS, asymmetric) + personal API tokens.

Security properties:
  * Algorithms are pinned: ES256/RS256/EdDSA via JWKS; HS256 only when a legacy secret is configured.
    The `alg` header can never select HS256 against a public key (no alg-confusion).
  * `aud`, `iss`, `exp`, `iat`, `sub` are required and verified.
  * JWKS is cached in-process and refreshed on unknown `kid` (rate limited) to handle key rotation.
  * Anonymous Supabase users are rejected.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt import PyJWK

from app.core.config import get_settings
from app.core.errors import Unauthorized
from app.core.logging import get_logger

log = get_logger(__name__)

ASYMMETRIC_ALGS = {"ES256", "RS256", "EdDSA"}


@dataclass
class Principal:
    user_id: uuid.UUID
    email: str | None
    email_verified: bool
    role: str  # user | admin
    via: str  # jwt | api_token
    claims: dict[str, Any] = field(default_factory=dict)
    scopes: list[str] = field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class JWKSCache:
    def __init__(self, ttl_seconds: int = 600, min_refresh_interval: int = 30):
        self.ttl = ttl_seconds
        self.min_refresh_interval = min_refresh_interval
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()
        self._static: dict[str, Any] | None = None  # test injection

    def set_static(self, jwks: dict[str, Any] | None) -> None:
        self._static = jwks
        self._keys = {}
        self._fetched_at = 0.0

    async def _refresh(self) -> None:
        if self._static is not None:
            data = self._static
        else:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                resp = await client.get(get_settings().jwks_url)
                resp.raise_for_status()
                data = resp.json()
        keys: dict[str, PyJWK] = {}
        for k in data.get("keys", []):
            kid = k.get("kid")
            if not kid:
                continue
            try:
                keys[kid] = PyJWK.from_dict(k)
            except jwt.PyJWTError as e:  # unsupported key type
                log.warning("jwks_key_skipped", kid=kid, error=str(e))
        self._keys = keys
        self._fetched_at = time.monotonic()

    async def get(self, kid: str) -> PyJWK | None:
        now = time.monotonic()
        if kid in self._keys and now - self._fetched_at < self.ttl:
            return self._keys[kid]
        async with self._lock:
            if kid in self._keys and time.monotonic() - self._fetched_at < self.ttl:
                return self._keys[kid]
            if time.monotonic() - self._fetched_at >= self.min_refresh_interval or not self._keys:
                try:
                    await self._refresh()
                except (httpx.HTTPError, ValueError) as e:
                    log.error("jwks_fetch_failed", error=str(e))
            return self._keys.get(kid)


jwks_cache = JWKSCache()


async def decode_supabase_jwt(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise Unauthorized("Malformed token") from e
    alg = header.get("alg")
    options = {"require": ["exp", "iat", "sub", "aud", "iss"]}
    common = {"audience": s.jwt_audience, "issuer": s.jwt_issuer, "leeway": s.jwt_leeway_seconds, "options": options}
    try:
        if alg in ASYMMETRIC_ALGS:
            kid = header.get("kid")
            if not kid:
                raise Unauthorized("Token missing key id")
            jwk = await jwks_cache.get(kid)
            if jwk is None:
                raise Unauthorized("Unknown signing key")
            if jwk.algorithm_name and jwk.algorithm_name != alg:
                raise Unauthorized("Algorithm mismatch")
            claims = jwt.decode(token, jwk.key, algorithms=[alg], **common)
        elif alg == "HS256" and s.supabase_jwt_secret.get_secret_value():
            claims = jwt.decode(token, s.supabase_jwt_secret.get_secret_value(), algorithms=["HS256"], **common)
        else:
            raise Unauthorized("Unsupported token algorithm")
    except jwt.ExpiredSignatureError as e:
        raise Unauthorized("Token expired", code="token_expired") from e
    except jwt.PyJWTError as e:
        raise Unauthorized("Invalid token") from e
    if claims.get("is_anonymous"):
        raise Unauthorized("Anonymous sessions are not allowed")
    if claims.get("role") not in (None, "authenticated"):
        raise Unauthorized("Invalid token role")
    return claims


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    try:
        uid = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError) as e:
        raise Unauthorized("Invalid subject") from e
    app_meta = claims.get("app_metadata") or {}
    user_meta = claims.get("user_metadata") or {}
    # Admin role ONLY from app_metadata (not user-editable in Supabase).
    role = "admin" if isinstance(app_meta, dict) and app_meta.get("role") == "admin" else "user"
    verified = bool(user_meta.get("email_verified")) if isinstance(user_meta, dict) else False
    return Principal(
        user_id=uid,
        email=(claims.get("email") or None),
        email_verified=verified,
        role=role,
        via="jwt",
        claims=claims,
    )
