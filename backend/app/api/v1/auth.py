"""Auth endpoints: a thin proxy over Supabase Auth so we can add per-IP throttling, credential-stuffing lockouts,
disposable-email blocking and auditing. Supabase remains the identity provider (passwords never touch our DB)."""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, Query, Request

from app.api.deps import DB, client_ip, rate_limit
from app.core.config import get_settings
from app.core.crypto import sha256_hex
from app.core.errors import RateLimited, Unauthorized, ValidationFailed
from app.core.redis import get_redis
from app.models import AuditLog
from app.schemas.api import EmailIn, LoginIn, PasswordUpdateIn, RefreshIn, SessionOut, SignupIn, VerifyOtpIn
from app.services.supabase import SupabaseAuthError, get_supabase_auth

router = APIRouter(prefix="/auth", tags=["auth"])

FAIL_WINDOW = 900
FAIL_LIMIT_EMAIL = 8
FAIL_LIMIT_IP = 30


def _check_redirect(url: str | None) -> str | None:
    if not url:
        return None
    s = get_settings()
    allowed = {urlsplit(o).netloc for o in [s.frontend_base_url, *s.cors_origins]}
    if urlsplit(url).netloc not in allowed or urlsplit(url).scheme not in ("http", "https"):
        raise ValidationFailed("redirect_to must point to the Watchtower app")
    return url


def _check_email_domain(email: str) -> None:
    domain = email.rsplit("@", 1)[-1].lower()
    if domain in set(get_settings().disposable_email_domains):
        raise ValidationFailed("Please use a permanent email address.", code="disposable_email")


def _session_out(data: dict[str, Any], message: str | None = None) -> SessionOut:
    user = data.get("user") or ({"id": data.get("id"), "email": data.get("email")} if data.get("id") else None)
    if user:
        user = {k: user.get(k) for k in ("id", "email", "email_confirmed_at", "created_at") if k in user}
    return SessionOut(access_token=data.get("access_token"), refresh_token=data.get("refresh_token"),
                      expires_in=data.get("expires_in"), token_type=data.get("token_type"), user=user, message=message)


async def _fail_counters(email: str, ip: str) -> tuple[str, str]:
    return f"authfail:e:{sha256_hex(email.lower())[:32]}", f"authfail:ip:{ip}"


@router.post("/signup", response_model=SessionOut, dependencies=[Depends(rate_limit("signup", 5, 3600, per="ip"))])
async def signup(body: SignupIn, session: DB, request: Request) -> SessionOut:
    _check_email_domain(body.email)
    data = await get_supabase_auth().signup(body.email, body.password, _check_redirect(body.redirect_to),
                                            {"display_name": body.display_name} if body.display_name else {})
    session.add(AuditLog(action="auth.signup", target_type="email", target_id=sha256_hex(body.email.lower())[:32],
                         ip=client_ip(request)))
    msg = None if data.get("access_token") else "Check your inbox to confirm your email."
    return _session_out(data, msg)


@router.post("/login", response_model=SessionOut, dependencies=[Depends(rate_limit("login", 20, 300, per="ip"))])
async def login(body: LoginIn, session: DB, request: Request) -> SessionOut:
    r = get_redis()
    ip = client_ip(request)
    ek, ik = await _fail_counters(body.email, ip)
    if int(await r.get(ek) or 0) >= FAIL_LIMIT_EMAIL or int(await r.get(ik) or 0) >= FAIL_LIMIT_IP:
        raise RateLimited("Too many failed sign-in attempts. Try again in 15 minutes or reset your password.",
                          retry_after=FAIL_WINDOW)
    try:
        data = await get_supabase_auth().login_password(body.email, body.password)
    except SupabaseAuthError as e:
        pipe = r.pipeline()
        pipe.incr(ek)
        pipe.expire(ek, FAIL_WINDOW)
        pipe.incr(ik)
        pipe.expire(ik, FAIL_WINDOW)
        await pipe.execute()
        session.add(AuditLog(action="auth.login_failed", target_type="email",
                             target_id=sha256_hex(body.email.lower())[:32], ip=ip))
        if e.status_code == 429:
            raise
        # Uniform message: don't reveal whether the account exists.
        raise Unauthorized("Invalid email or password", code="invalid_credentials") from e
    await r.delete(ek)
    return _session_out(data)


@router.post("/refresh", response_model=SessionOut, dependencies=[Depends(rate_limit("refresh", 60, 300, per="ip"))])
async def refresh(body: RefreshIn) -> SessionOut:
    try:
        return _session_out(await get_supabase_auth().refresh(body.refresh_token))
    except SupabaseAuthError as e:
        raise Unauthorized("Session expired, please sign in again", code="refresh_failed") from e


@router.post("/logout", status_code=204)
async def logout(authorization: Annotated[str | None, Header()] = None,
                 scope: Annotated[str, Query(pattern="^(local|global|others)$")] = "local") -> None:
    if authorization and authorization.lower().startswith("bearer "):
        try:
            await get_supabase_auth().logout(authorization.split(" ", 1)[1], scope)
        except SupabaseAuthError:
            pass


@router.post("/magic-link", response_model=SessionOut,
             dependencies=[Depends(rate_limit("magic", 5, 3600, per="ip"))])
async def magic_link(body: EmailIn) -> SessionOut:
    _check_email_domain(body.email)
    try:
        await get_supabase_auth().magic_link(body.email, _check_redirect(body.redirect_to))
    except SupabaseAuthError as e:
        if e.status_code == 429:
            raise
    return SessionOut(message="If that address can sign in, a link is on its way.")


@router.post("/verify-otp", response_model=SessionOut, dependencies=[Depends(rate_limit("otp", 10, 900, per="ip"))])
async def verify_otp(body: VerifyOtpIn) -> SessionOut:
    try:
        return _session_out(await get_supabase_auth().verify_otp(body.email, body.token, body.type))
    except SupabaseAuthError as e:
        raise Unauthorized("Invalid or expired code", code="otp_invalid") from e


@router.post("/password/recover", response_model=SessionOut,
             dependencies=[Depends(rate_limit("recover", 5, 3600, per="ip"))])
async def recover(body: EmailIn) -> SessionOut:
    try:
        await get_supabase_auth().recover(body.email, _check_redirect(body.redirect_to))
    except SupabaseAuthError as e:
        if e.status_code == 429:
            raise
    return SessionOut(message="If an account exists for that email, a reset link is on its way.")


@router.post("/password", response_model=SessionOut, dependencies=[Depends(rate_limit("pwupdate", 5, 3600))])
async def update_password(body: PasswordUpdateIn, authorization: Annotated[str | None, Header()] = None) -> SessionOut:
    SignupIn._strength(body.password)  # same strength rules as signup
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Sign in first")
    await get_supabase_auth().update_user(authorization.split(" ", 1)[1], {"password": body.password})
    return SessionOut(message="Password updated.")


@router.get("/oauth/{provider}", response_model=SessionOut)
async def oauth_url(provider: str, redirect_to: str) -> SessionOut:
    if provider not in ("google", "github", "apple"):
        raise ValidationFailed("Unsupported provider")
    url = get_supabase_auth().oauth_url(provider, _check_redirect(redirect_to) or get_settings().frontend_base_url)
    return SessionOut(message=url)
