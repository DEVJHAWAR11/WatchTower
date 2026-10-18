"""Turn fetched bytes (HTML / JSON / RSS / Atom / text) into clean, structured, LLM-safe content."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urldefrag, urljoin

from defusedxml import ElementTree as SafeET
from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.fetch.normalize import sanitize_text

MAX_TEXT_CHARS = 200_000
MAX_LINKS = 500

_DROP_TAGS = ("script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "embed",
              "head", "audio", "video", "picture", "source", "track", "map", "button", "select", "textarea", "form")
_CHROME_SELECTORS = ("nav", "footer", "[role=navigation]", "[role=contentinfo]", "[aria-label*=cookie i]",
                     "[id*=cookie i]", "[class*=cookie-banner i]", "[class*=cookie-consent i]")
_HIDDEN_STYLE = re.compile(
    r"(display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(\.0+)?\s*(;|$)|font-size\s*:\s*0(px|em|rem)?\s*(;|$)"
    r"|left\s*:\s*-\d{3,}px|text-indent\s*:\s*-\d{3,}px|clip\s*:\s*rect\(0)",
    re.I,
)
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt", "fieldset", "figcaption", "figure",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "ol", "p", "pre", "section", "table",
    "tbody", "thead", "tfoot", "tr", "ul", "caption", "summary", "details", "body", "html", "center",
}
_CELL_TAGS = {"td", "th"}
_PRICE_RE = re.compile(
    r"(?:₹|rs\.?|inr|mrp[:\s]*₹?)\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)", re.I
)


@dataclass
class Extracted:
    text: str
    title: str | None = None
    links: list[dict[str, str]] = field(default_factory=list)
    structured: dict[str, Any] = field(default_factory=dict)
    selector_matched: bool | None = None
    kind: str = "page"


def decode_body(content: bytes, declared: str | None) -> str:
    encodings: list[str] = []
    if declared:
        encodings.append(declared)
    head = content[:4096].decode("ascii", "ignore")
    m = re.search(r"""<meta[^>]+charset=["']?([\w\-]+)""", head, re.I)
    if m:
        encodings.append(m.group(1))
    encodings += ["utf-8", "cp1252"]
    for enc in encodings:
        try:
            return content.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", "replace")


def parse_price(raw: str) -> float | None:
    cleaned = raw.replace(",", "").strip()
    try:
        v = float(cleaned)
    except ValueError:
        return None
    return v if 0 < v < 1e10 else None


def find_prices(text: str, limit: int = 20) -> list[float]:
    out: list[float] = []
    for m in _PRICE_RE.finditer(text):
        v = parse_price(m.group(1))
        if v is not None:
            out.append(v)
            if len(out) >= limit:
                break
    return out


def _walk_text(root: LexborNode) -> str:
    parts: list[str] = []
    stack: list[tuple[LexborNode, bool]] = [(root, False)]
    while stack:
        node, closing = stack.pop()
        tag = node.tag or ""
        if closing:
            if tag in _BLOCK_TAGS:
                parts.append("\n")
            elif tag in _CELL_TAGS:
                parts.append(" | ")
            continue
        if tag == "-text":
            parts.append(node.text_content or "")
            continue
        if tag in ("br", "hr"):
            parts.append("\n")
            continue
        if tag in _BLOCK_TAGS:
            parts.append("\n")
            if tag == "li":
                parts.append("• ")
        stack.append((node, True))
        children = []
        child = node.child
        while child is not None:
            children.append(child)
            child = child.next
        for c in reversed(children):
            stack.append((c, False))
    text = "".join(parts)
    text = re.sub(r"(\s*\|\s*)+\n", "\n", text)
    return text


def _json_ld_products(tree: LexborHTMLParser) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for node in tree.css('script[type="application/ld+json"]')[:20]:
        raw = (node.text() or "").strip()
        if not raw or len(raw) > 200_000:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack: list[Any] = [data]
        while stack and len(products) < 10:
            cur = stack.pop()
            if isinstance(cur, list):
                stack.extend(cur[:50])
            elif isinstance(cur, dict):
                t = cur.get("@type")
                types = t if isinstance(t, list) else [t]
                if "Product" in types:
                    offers = cur.get("offers") or {}
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price = None
                    if isinstance(offers, dict):
                        price = offers.get("price") or offers.get("lowPrice")
                    products.append({
                        "name": str(cur.get("name", ""))[:200],
                        "price": parse_price(str(price)) if price is not None else None,
                        "currency": (offers.get("priceCurrency") if isinstance(offers, dict) else None),
                        "availability": (str(offers.get("availability", "")).rsplit("/", 1)[-1]
                                         if isinstance(offers, dict) else None),
                    })
                for v in cur.values():
                    if isinstance(v, dict | list):
                        stack.append(v)
    return products


def extract_html(html: str, base_url: str, *, selector: str | None = None, strip_chrome: bool = True) -> Extracted:
    tree = LexborHTMLParser(html)
    title_node = tree.css_first("title")
    title = sanitize_text(title_node.text())[:300] if title_node else None
    structured: dict[str, Any] = {}
    meta: dict[str, str] = {}
    for m in tree.css("meta[property], meta[name], meta[itemprop]")[:200]:
        key = (m.attributes.get("property") or m.attributes.get("name") or m.attributes.get("itemprop") or "").lower()
        if key in {"description", "og:title", "og:description", "og:price:amount", "product:price:amount",
                   "og:price:currency", "product:availability", "og:availability", "price", "pricecurrency"}:
            meta[key] = sanitize_text(m.attributes.get("content") or "")[:500]
    if meta:
        structured["meta"] = meta
    products = _json_ld_products(tree)
    if products:
        structured["products"] = products

    # Remove non-content and hidden elements BEFORE reading text (hidden text = classic injection vector).
    for tag in _DROP_TAGS:
        for n in tree.css(tag):
            n.decompose()
    for n in tree.css("[hidden], [aria-hidden=true], input[type=hidden]"):
        n.decompose()
    for n in tree.css("[style]"):
        if _HIDDEN_STYLE.search(n.attributes.get("style") or ""):
            n.decompose()
    if strip_chrome:
        for sel in _CHROME_SELECTORS:
            for n in tree.css(sel):
                n.decompose()

    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#", "data:")):
            continue
        absolute = urldefrag(urljoin(base_url, href))[0]
        if not absolute.startswith(("http://", "https://")) or len(absolute) > 2048:
            continue
        text = sanitize_text(a.text(separator=" "))[:200]
        key = f"{text}|{absolute}"
        if key in seen:
            continue
        seen.add(key)
        links.append({"text": text, "href": absolute})
        if len(links) >= MAX_LINKS:
            break

    selector_matched: bool | None = None
    roots: list[LexborNode]
    if selector:
        try:
            roots = tree.css(selector)[:50]
        except Exception:  # invalid selector from spec -> treat as missing
            roots = []
        selector_matched = bool(roots)
        if not roots:
            roots = [tree.body] if tree.body is not None else []
    else:
        roots = [tree.body] if tree.body is not None else ([tree.root] if tree.root is not None else [])
    text = "\n".join(_walk_text(r) for r in roots)
    text = sanitize_text(text, MAX_TEXT_CHARS)
    prices = find_prices(text)
    if prices:
        structured["prices"] = prices[:20]
    return Extracted(text=text, title=title, links=links, structured=structured,
                     selector_matched=selector_matched, kind="page")


def _flatten_json(data: Any, prefix: str = "", out: list[str] | None = None, depth: int = 0) -> list[str]:
    out = [] if out is None else out
    if len(out) > 5000 or depth > 12:
        return out
    if isinstance(data, dict):
        for k, v in list(data.items())[:500]:
            _flatten_json(v, f"{prefix}.{k}" if prefix else str(k), out, depth + 1)
    elif isinstance(data, list):
        for i, v in enumerate(data[:500]):
            _flatten_json(v, f"{prefix}[{i}]", out, depth + 1)
    else:
        out.append(f"{prefix}: {data}")
    return out


def extract_json(body: str, base_url: str) -> Extracted:
    data = json.loads(body)
    lines = _flatten_json(data)
    text = sanitize_text("\n".join(lines), MAX_TEXT_CHARS)
    links: list[dict[str, str]] = []
    for line in lines:
        key, _, val = line.partition(": ")
        val = val.strip()
        if val.startswith(("http://", "https://")) and len(links) < MAX_LINKS:
            links.append({"text": key.rsplit(".", 1)[-1][:200], "href": val[:2048]})
    return Extracted(text=text, links=links, structured={"json": True}, kind="json")


def extract_feed(body: str, base_url: str) -> Extracted:
    root = SafeET.fromstring(body.encode("utf-8") if isinstance(body, str) else body)
    title = None
    items: list[str] = []
    links: list[dict[str, str]] = []

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    for el in root.iter():
        name = local(el.tag)
        if name in ("item", "entry"):
            t = link = date = summary = ""
            for c in el:
                cn = local(c.tag)
                if cn == "title":
                    t = (c.text or "").strip()
                elif cn == "link":
                    link = (c.get("href") or c.text or "").strip()
                elif cn in ("pubdate", "updated", "published", "date"):
                    date = (c.text or "").strip()
                elif cn in ("description", "summary") and not summary:
                    summary = re.sub(r"<[^>]+>", " ", c.text or "")[:300]
            items.append(f"• {t} ({date})\n{summary}".strip())
            if link:
                links.append({"text": t[:200], "href": urljoin(base_url, link)})
        elif name == "title" and title is None:
            title = (el.text or "").strip()[:300]
        if len(items) >= 300:
            break
    text = sanitize_text("\n".join(items), MAX_TEXT_CHARS)
    return Extracted(text=text, title=title, links=links[:MAX_LINKS], structured={"feed": True}, kind="feed")


def extract(content: bytes, content_type: str, encoding: str | None, base_url: str,
            *, selector: str | None = None) -> Extracted:
    body = decode_body(content, encoding)
    ct = (content_type or "").lower()
    stripped = body.lstrip()[:200].lower()
    if "json" in ct or (not ct and stripped.startswith(("{", "["))):
        try:
            return extract_json(body, base_url)
        except ValueError:
            pass
    if "rss" in ct or "atom" in ct or ("xml" in ct and ("<rss" in stripped or "<feed" in stripped)):
        try:
            return extract_feed(body, base_url)
        except Exception:  # noqa: S110 - malformed or hostile XML: fall through to HTML/text
            pass
    if "html" in ct or "<html" in stripped or "<!doctype html" in stripped or "<body" in stripped:
        return extract_html(body, base_url, selector=selector)
    return Extracted(text=sanitize_text(body, MAX_TEXT_CHARS), kind="text",
                     structured={"prices": find_prices(body)[:20]} if find_prices(body) else {})
