import pytest

from app.fetch.client import FetchBlockedURL, safe_fetch
from app.fetch.ssrf import SSRFBlocked, ip_is_public, resolve_public, validate_url


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost/", "http://LOCALHOST./admin", "http://0.0.0.0/", "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/", "http://metadata.google.internal/", "http://10.0.0.1/",
    "http://192.168.1.1/", "http://172.16.5.4/", "http://100.64.0.1/", "http://2130706433/", "http://0x7f.1/",
    "http://0177.0.0.1/", "http://127.1/", "http://[::ffff:127.0.0.1]/", "http://[::ffff:a9fe:a9fe]/",
    "http://[fd00::1]/", "http://[fe80::1]/", "http://[64:ff9b::7f00:1]/", "http://[2002:7f00:1::]/",
    "file:///etc/passwd", "gopher://example.com/", "ftp://example.com/", "dict://example.com:11211/",
    "http://user:pass@example.com/", "http://example.com:22/", "http://example.com:6379/",
    "http://printer.local/", "http://svc.internal/", "http://intranet/", "http://example.com/\r\nHost: x",
    "javascript:alert(1)", "http://" + "a" * 2100 + ".com/",
])
def test_validate_url_blocks(url: str) -> None:
    with pytest.raises(SSRFBlocked):
        validate_url(url)


@pytest.mark.parametrize("url", [
    "https://ssc.gov.in/", "http://example.com/path?q=1", "https://example.com:443/x", "https://93.184.216.34/",
    "https://xn--80ak6aa92e.com/", "https://sub.domain.co.in/a/b",
])
def test_validate_url_allows(url: str) -> None:
    assert validate_url(url).host


@pytest.mark.parametrize("ip,public", [
    ("8.8.8.8", True), ("93.184.216.34", True), ("2606:4700::1111", True), ("127.0.0.1", False),
    ("10.1.2.3", False), ("169.254.169.254", False), ("100.100.100.200", False), ("224.0.0.1", False),
    ("::ffff:10.0.0.1", False), ("fc00::1", False), ("198.18.0.1", False), ("255.255.255.255", False),
])
def test_ip_is_public(ip: str, public: bool) -> None:
    assert ip_is_public(ip) is public


async def test_dns_rebinding_and_mixed_answers_blocked(site) -> None:  # noqa: ANN001
    with pytest.raises(SSRFBlocked):
        await resolve_public("rebind.example.com", 80)
    with pytest.raises(SSRFBlocked):
        await resolve_public("mixed.example.com", 80)
    assert await resolve_public("public.example.com", 443) == ["93.184.216.34"]


async def test_redirect_to_internal_is_blocked(site) -> None:  # noqa: ANN001
    site.set("site.test", "/go", "", status=302, headers={"Location": "http://169.254.169.254/latest/"})
    with pytest.raises(FetchBlockedURL):
        await safe_fetch(site.url("site.test", "/go"))


async def test_redirect_to_private_dns_name_is_blocked(site) -> None:  # noqa: ANN001
    site.set("site.test", "/go2", "", status=301, headers={"Location": "http://rebind.example.com/"})
    with pytest.raises(FetchBlockedURL):
        await safe_fetch(site.url("site.test", "/go2"))


async def test_fetch_allowed_test_host_and_size_cap(site) -> None:  # noqa: ANN001
    url = site.set("site.test", "/ok", "<html><body>hello</body></html>")
    res = await safe_fetch(url)
    assert res.status_code == 200 and b"hello" in res.content
    big = site.set("site.test", "/big", "x" * 200_000, headers={"Content-Type": "text/plain"})
    from app.fetch.client import FetchTooLarge

    with pytest.raises(FetchTooLarge):
        await safe_fetch(big, max_bytes=50_000)


async def test_bad_content_type_rejected(site) -> None:  # noqa: ANN001
    from app.fetch.client import FetchBadContentType

    url = site.set("site.test", "/bin", b"\x00\x01", headers={"Content-Type": "application/octet-stream"})
    with pytest.raises(FetchBadContentType):
        await safe_fetch(url)


async def test_redirect_loop_limited(site) -> None:  # noqa: ANN001
    from app.fetch.client import FetchError

    site.set("site.test", "/loop", "", status=302, headers={"Location": "/loop"})
    with pytest.raises(FetchError):
        await safe_fetch(site.url("site.test", "/loop"))


def test_private_host_override_only_in_test_env(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "env", "prod")
    with pytest.raises(SSRFBlocked):
        validate_url("http://site.test:8080/")
