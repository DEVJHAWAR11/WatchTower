"""SSRF-safe HTTP fetching with manual redirect handling, size/time caps and content-type allowlist."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings
from app.fetch.ssrf import SafeTransport, SSRFBlocked, validate_url

ALLOWED_CONTENT_TYPES = (
    "text/html", "application/xhtml+xml", "text/plain", "application/json", "application/ld+json",
    "application/rss+xml", "application/atom+xml", "application/xml", "text/xml", "application/feed+json",
)
REDIRECT_CODES = {301, 302, 303, 307, 308}


class FetchError(Exception):
    code = "fetch_error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class FetchTimeout(FetchError):
    code = "timeout"


class FetchTooLarge(FetchError):
    code = "too_large"


class FetchBadContentType(FetchError):
    code = "bad_content_type"


class FetchConnectError(FetchError):
    code = "connect_error"


class FetchBlockedURL(FetchError):
    code = "url_blocked"


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    content_type: str
    encoding: str | None
    elapsed_ms: int
    redirects: list[str] = field(default_factory=list)

    @property
    def not_modified(self) -> bool:
        return self.status_code == 304


_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        s = get_settings()
        _client = httpx.AsyncClient(
            transport=SafeTransport(),
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(s.fetch_timeout_seconds, connect=8.0),
            headers={
                "User-Agent": s.fetch_user_agent,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,application/xml;q=0.8,*/*;q=0.5",
                "Accept-Language": "en-IN,en;q=0.9,hi;q=0.6",
            },
        )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def _content_type(headers: httpx.Headers) -> tuple[str, str | None]:
    raw = headers.get("content-type", "")
    main = raw.split(";", 1)[0].strip().lower()
    charset = None
    for part in raw.split(";")[1:]:
        k, _, v = part.strip().partition("=")
        if k.lower() == "charset":
            charset = v.strip().strip('"') or None
    return main, charset


async def safe_fetch(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    method: str = "GET",
    max_bytes: int | None = None,
    allow_any_content_type: bool = False,
    extra_headers: dict[str, str] | None = None,
    json_body: object | None = None,
    content: bytes | None = None,
    client: httpx.AsyncClient | None = None,
) -> FetchResult:
    s = get_settings()
    cap = max_bytes or s.fetch_max_bytes
    client = client or get_http_client()
    headers: dict[str, str] = dict(extra_headers or {})
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    started = time.monotonic()
    current = url
    redirects: list[str] = []
    for _hop in range(s.fetch_max_redirects + 1):
        try:
            validate_url(current)
        except SSRFBlocked as e:
            raise FetchBlockedURL(f"URL not allowed: {e.reason}", code="url_blocked") from e
        try:
            req = client.build_request(method, current, headers=headers, json=json_body if content is None else None,
                                       content=content)
            resp = await client.send(req, stream=True)
        except SSRFBlocked as e:
            if e.reason in ("dns_failed", "dns_empty"):
                raise FetchConnectError("Site address could not be resolved", code="dns_failed") from e
            raise FetchBlockedURL(f"URL not allowed: {e.reason}", code="url_blocked") from e
        except httpx.TimeoutException as e:
            raise FetchTimeout("Timed out") from e
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError) as e:
            raise FetchConnectError(f"Connection failed: {type(e).__name__}") from e
        except httpx.HTTPError as e:
            raise FetchError(f"HTTP error: {type(e).__name__}") from e
        try:
            if resp.status_code in REDIRECT_CODES and "location" in resp.headers:
                nxt = urljoin(current, resp.headers["location"])
                redirects.append(nxt)
                if resp.status_code == 303 or method == "POST":
                    # never re-POST a signed body to a redirect target
                    method, json_body, content = "GET", None, None
                current = nxt
                continue
            ctype, charset = _content_type(resp.headers)
            if resp.status_code == 304:
                body = b""
            else:
                if (
                    resp.status_code < 400
                    and not allow_any_content_type
                    and ctype
                    and not ctype.startswith(ALLOWED_CONTENT_TYPES)
                ):
                    raise FetchBadContentType(f"Unsupported content type: {ctype}")
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > cap * 4:
                    raise FetchTooLarge("Response too large")
                chunks: list[bytes] = []
                total = 0
                try:
                    # aiter_bytes yields *decoded* bytes, so gzip/br bombs are capped too.
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > cap:
                            raise FetchTooLarge("Response too large")
                        chunks.append(chunk)
                except httpx.TimeoutException as e:
                    raise FetchTimeout("Timed out reading body") from e
                except (httpx.ReadError, httpx.RemoteProtocolError, httpx.DecodingError) as e:
                    raise FetchConnectError(f"Read failed: {type(e).__name__}") from e
                body = b"".join(chunks)
            return FetchResult(
                url=url,
                final_url=current,
                status_code=resp.status_code,
                headers={k.lower(): v for k, v in resp.headers.items()},
                content=body,
                content_type=ctype,
                encoding=charset,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                redirects=redirects,
            )
        finally:
            await resp.aclose()
    raise FetchError("Too many redirects", code="too_many_redirects")
