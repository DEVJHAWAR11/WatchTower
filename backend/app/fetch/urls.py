"""URL canonicalisation so the same page is fetched once no matter how users typed it."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import idna

_TRACKING_PREFIXES = ("utm_", "mc_", "pk_", "hsa_", "_hs")
_TRACKING_KEYS = {
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "igshid", "ref_src", "_ga", "_gl", "mkt_tok", "si",
    "spm", "trk", "trkCampaign", "tag", "ascsubtag", "affid", "affExtParam1", "affExtParam2",
}


def canonicalize_url(url: str) -> str:
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").rstrip(".").lower()
    try:
        host = idna.encode(host, uts46=True).decode("ascii") if host else host
    except idna.IDNAError:
        pass
    port = parts.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k not in _TRACKING_KEYS
    ]
    query.sort()
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def registrable_domain(host: str) -> str:
    """Approximate eTLD+1 without a network-fetched PSL (handles common Indian 2-level suffixes)."""
    labels = host.lower().strip(".").split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    two_level = {"co.in", "gov.in", "nic.in", "ac.in", "edu.in", "org.in", "net.in", "res.in", "ernet.in",
                 "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "co.jp", "com.sg", "com.br"}
    if ".".join(labels[-2:]) in two_level:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])
