"""Thin Supabase Auth (GoTrue) REST client: admin calls + auth proxy used by our /v1/auth endpoints."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import AppError, ServiceUnavailable


class SupabaseAuthError(AppError):
    status_code = 400
    code = "auth_error"


class SupabaseAuth:
    def __init__(self, http: httpx.AsyncClient | None = None):
        self._http = http

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=get_settings().supabase_url.rstrip("/") + "/auth/v1", timeout=10.0, trust_env=False
            )
        return self._http

    def _anon_headers(self) -> dict[str, str]:
        key = get_settings().supabase_anon_key.get_secret_value()
        return {"apikey": key, "Content-Type": "application/json"}

    def _admin_headers(self) -> dict[str, str]:
        key = get_settings().supabase_service_role_key.get_secret_value()
        if not key:
            raise ServiceUnavailable("Supabase service role key is not configured")
        return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    async def _send(self, method: str, path: str, *, headers: dict[str, str], json: Any = None,
                    params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            resp = await self._client().request(method, path, headers=headers, json=json, params=params)
        except httpx.HTTPError as e:
            raise ServiceUnavailable("Authentication service unreachable") from e
        if resp.status_code >= 500:
            raise ServiceUnavailable("Authentication service error")
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            msg = data.get("msg") or data.get("error_description") or data.get("message") or "Authentication failed"
            code = str(data.get("error_code") or data.get("error") or "auth_error")
            status = 429 if resp.status_code == 429 else (401 if resp.status_code in (400, 401) and
                                                         "grant" in path else resp.status_code)
            raise SupabaseAuthError(str(msg)[:300], code=code, status_code=status)
        return data if isinstance(data, dict) else {"data": data}

    # --- public auth flows (proxied so we can rate-limit, block disposable emails, audit) ---
    async def signup(self, email: str, password: str, redirect_to: str | None, meta: dict[str, Any]) -> dict[str, Any]:
        params = {"redirect_to": redirect_to} if redirect_to else None
        return await self._send("POST", "/signup", headers=self._anon_headers(),
                                json={"email": email, "password": password, "data": meta}, params=params)

    async def login_password(self, email: str, password: str) -> dict[str, Any]:
        return await self._send("POST", "/token", headers=self._anon_headers(),
                                json={"email": email, "password": password}, params={"grant_type": "password"})

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._send("POST", "/token", headers=self._anon_headers(),
                                json={"refresh_token": refresh_token}, params={"grant_type": "refresh_token"})

    async def magic_link(self, email: str, redirect_to: str | None, create_user: bool = True) -> dict[str, Any]:
        params = {"redirect_to": redirect_to} if redirect_to else None
        return await self._send("POST", "/otp", headers=self._anon_headers(),
                                json={"email": email, "create_user": create_user}, params=params)

    async def verify_otp(self, email: str, token: str, type_: str = "email") -> dict[str, Any]:
        return await self._send("POST", "/verify", headers=self._anon_headers(),
                                json={"email": email, "token": token, "type": type_})

    async def recover(self, email: str, redirect_to: str | None) -> dict[str, Any]:
        params = {"redirect_to": redirect_to} if redirect_to else None
        return await self._send("POST", "/recover", headers=self._anon_headers(), json={"email": email}, params=params)

    async def update_user(self, access_token: str, attrs: dict[str, Any]) -> dict[str, Any]:
        headers = {**self._anon_headers(), "Authorization": f"Bearer {access_token}"}
        return await self._send("PUT", "/user", headers=headers, json=attrs)

    async def logout(self, access_token: str, scope: str = "local") -> None:
        headers = {**self._anon_headers(), "Authorization": f"Bearer {access_token}"}
        await self._send("POST", "/logout", headers=headers, params={"scope": scope})

    def oauth_url(self, provider: str, redirect_to: str) -> str:
        from urllib.parse import urlencode

        base = get_settings().supabase_url.rstrip("/") + "/auth/v1/authorize"
        return f"{base}?{urlencode({'provider': provider, 'redirect_to': redirect_to})}"

    # --- admin ---
    async def admin_get_user(self, user_id: uuid.UUID) -> dict[str, Any]:
        return await self._send("GET", f"/admin/users/{user_id}", headers=self._admin_headers())

    async def admin_delete_user(self, user_id: uuid.UUID) -> None:
        await self._send("DELETE", f"/admin/users/{user_id}", headers=self._admin_headers())


_auth: SupabaseAuth | None = None


def get_supabase_auth() -> SupabaseAuth:
    global _auth
    if _auth is None:
        _auth = SupabaseAuth()
    return _auth


def set_supabase_auth(a: SupabaseAuth | None) -> None:
    global _auth
    _auth = a
