"""Signing (HMAC tokens for unsubscribe/links), encryption at rest (Fernet), token hashing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_payload(payload: dict[str, Any], purpose: str, ttl_seconds: int | None = None) -> str:
    """Compact signed token: base64(json).base64(hmac). Purpose-bound so tokens can't be swapped across uses."""
    body = dict(payload)
    body["_p"] = purpose
    if ttl_seconds:
        body["_e"] = int(time.time()) + ttl_seconds
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    key = get_settings().signing_secret.get_secret_value().encode()
    sig = hmac.new(key, raw, hashlib.sha256).digest()
    return f"{_b64(raw)}.{_b64(sig)}"


def verify_payload(token: str, purpose: str) -> dict[str, Any] | None:
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = _unb64(raw_b64)
        sig = _unb64(sig_b64)
    except (ValueError, TypeError):
        return None
    key = get_settings().signing_secret.get_secret_value().encode()
    if not hmac.compare_digest(hmac.new(key, raw, hashlib.sha256).digest(), sig):
        return None
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("_p") != purpose:
        return None
    exp = body.get("_e")
    if exp is not None and int(exp) < int(time.time()):
        return None
    body.pop("_p", None)
    body.pop("_e", None)
    return body


def _fernet() -> Fernet:
    s = get_settings()
    key = s.encryption_key.get_secret_value()
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(b"enc:" + s.signing_secret.get_secret_value().encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_api_token() -> tuple[str, str, str]:
    """Returns (token, prefix, sha256). Token shown to the user once."""
    secret = secrets.token_urlsafe(32)
    token = f"wt_{secret}"
    return token, token[:10], hash_token(token)


def sha256_hex(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", "ignore"))
        h.update(b"\x1f")
    return h.hexdigest()
