"""SSRF protection.

Two layers, both always on:
 1. `validate_url` pre-flight: scheme/port/userinfo/hostname rules, IP literal checks.
 2. `SafeNetworkBackend`: resolves the hostname *at connect time*, rejects any non-public address and connects
    to the exact IP it validated. This defeats DNS rebinding (no second resolution) and redirect tricks
    (every hop goes through the same backend). TLS still verifies against the original hostname (SNI).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import typing
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend

from app.core.config import get_settings

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443, 8080, 8443}
MAX_URL_LENGTH = 2048
BLOCKED_HOST_SUFFIXES = (
    ".localhost", ".local", ".internal", ".intranet", ".lan", ".home", ".corp", ".home.arpa", ".localdomain",
    ".svc", ".cluster.local", ".consul", ".test", ".example", ".invalid", ".onion", ".arpa",
)
BLOCKED_HOSTS = {"localhost", "metadata", "metadata.google.internal", "instance-data", "kubernetes", "kubernetes.default"}
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_EXTRA_BLOCKED_V4 = [ipaddress.ip_network(n) for n in ("0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24", "198.18.0.0/15")]


class SSRFBlocked(Exception):
    """Raised when a URL or resolved address is not allowed."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    scheme: str
    host: str
    port: int


Resolver = Callable[[str, int], Awaitable[list[str]]]


async def _system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    seen: list[str] = []
    for family, *_rest, sockaddr in infos:
        if family in (socket.AF_INET, socket.AF_INET6):
            ip = str(sockaddr[0]).split("%", 1)[0]
            if ip not in seen:
                seen.append(ip)
    return seen


_resolver: Resolver = _system_resolver


def set_resolver(resolver: Resolver | None) -> None:
    """Test hook: inject a fake DNS resolver."""
    global _resolver
    _resolver = resolver or _system_resolver


def ip_is_public(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip_is_public(str(ip.ipv4_mapped))
        if ip.sixtofour is not None and not ip_is_public(str(ip.sixtofour)):
            return False
        if ip.teredo is not None:
            return False
        if ip in _NAT64:
            return ip_is_public(str(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)))
    else:
        if any(ip in n for n in _EXTRA_BLOCKED_V4):
            return False
    if ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return False
    if ip.is_private:
        return False
    return ip.is_global


def _private_allowed_for(host: str) -> bool:
    s = get_settings()
    return s.is_test and host.lower() in {h.lower() for h in s.test_private_hosts}


def _parse_ip_literal(host: str) -> str | None:
    h = host.strip("[]")
    try:
        return str(ipaddress.ip_address(h))
    except ValueError:
        pass
    # inet_aton accepts legacy forms: 2130706433, 0x7f.1, 0177.0.0.1, 127.1
    if all(c in "0123456789abcdefxABCDEFX." for c in h) and any(c.isdigit() for c in h):
        try:
            return socket.inet_ntoa(socket.inet_aton(h))
        except OSError:
            return None
    return None


def validate_url(url: str) -> ValidatedURL:
    if not url or len(url) > MAX_URL_LENGTH:
        raise SSRFBlocked("url_length")
    if any(c in url for c in ("\r", "\n", "\t", "\x00", " ")):
        raise SSRFBlocked("url_whitespace")
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, ValueError) as e:
        raise SSRFBlocked("url_invalid") from e
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFBlocked("scheme_not_allowed")
    if parsed.userinfo:
        raise SSRFBlocked("userinfo_not_allowed")
    host = (parsed.host or "").lower().rstrip(".")
    if not host:
        raise SSRFBlocked("host_missing")
    if parsed.port not in ALLOWED_PORTS and not _private_allowed_for(host):
        raise SSRFBlocked("port_not_allowed")
    port = parsed.port or (443 if scheme == "https" else 80)
    literal = _parse_ip_literal(host)
    if literal is not None:
        if not ip_is_public(literal) and not _private_allowed_for(host):
            raise SSRFBlocked("ip_not_public")
    else:
        if host in BLOCKED_HOSTS or host.endswith(BLOCKED_HOST_SUFFIXES):
            if not _private_allowed_for(host):
                raise SSRFBlocked("host_not_allowed")
        if "." not in host and not _private_allowed_for(host):
            raise SSRFBlocked("host_not_fqdn")
    return ValidatedURL(url=str(parsed), scheme=scheme, host=host, port=port)


async def resolve_public(host: str, port: int) -> list[str]:
    literal = _parse_ip_literal(host)
    allow_private = _private_allowed_for(host)
    if literal is not None:
        if not allow_private and not ip_is_public(literal):
            raise SSRFBlocked("ip_not_public")
        return [literal]
    try:
        ips = await _resolver(host, port)
    except (socket.gaierror, OSError) as e:
        raise SSRFBlocked("dns_failed") from e
    if not ips:
        raise SSRFBlocked("dns_empty")
    if allow_private:
        return ips
    # If ANY record is non-public we refuse: mixed answers are a classic rebinding setup.
    if any(not ip_is_public(ip) for ip in ips):
        raise SSRFBlocked("resolved_ip_not_public")
    return ips


class SafeNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self._inner = AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - signature defined by httpcore
        local_address: str | None = None,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        ips = await resolve_public(host, port)
        last_exc: Exception | None = None
        for ip in ips[:4]:
            try:
                return await self._inner.connect_tcp(
                    ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout, OSError) as e:
                last_exc = e
        raise httpcore.ConnectError(str(last_exc) if last_exc else "connect failed")

    async def connect_unix_socket(self, *args: typing.Any, **kwargs: typing.Any) -> httpcore.AsyncNetworkStream:
        raise SSRFBlocked("unix_socket_not_allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class SafeTransport(httpx.AsyncHTTPTransport):
    """httpx transport whose connection pool uses SafeNetworkBackend. Proxies/env are never used."""

    def __init__(self, *, limits: httpx.Limits | None = None, http2: bool = False):
        limits = limits or httpx.Limits(max_connections=200, max_keepalive_connections=50, keepalive_expiry=30)
        super().__init__(trust_env=False, limits=limits, http2=http2)
        ssl_context = httpx.create_ssl_context(trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=True,
            http2=http2,
            network_backend=SafeNetworkBackend(),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        validate_url(str(request.url))
        try:
            return await super().handle_async_request(request)
        except httpx.ConnectError as e:
            # Surface SSRF refusals raised inside the backend with their real reason.
            cause: BaseException | None = e
            while cause is not None:
                if isinstance(cause, SSRFBlocked):
                    raise cause from e
                cause = cause.__cause__ or cause.__context__
            raise
