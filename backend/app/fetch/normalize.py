"""Text sanitisation, volatile-token normalisation, hashing and simhash."""

from __future__ import annotations

import hashlib
import re
import unicodedata

# zero-width, bidi overrides/isolates, word joiners, BOM, soft hyphen, other invisible formatting chars
_INVISIBLE = re.compile(
    "[­͏؜ᅟᅠ឴឵᠋-᠎​-‏‪-‮"
    "⁠-⁯ㅤ︀-️﻿ﾠ\U000e0000-\U000e007f]"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_SPACES = re.compile(r"[ \t  -   　]+")

# Volatile tokens that change without meaning (clocks, counters, tokens)
_VOLATILE = [
    (re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s*(am|pm|AM|PM|IST|UTC|GMT)?\b"), "<time>"),
    (re.compile(r"\b\d+\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)\s+ago\b", re.I), "<ago>"),
    (re.compile(r"\b(just now|moments? ago|a minute ago|an hour ago|yesterday|today)\b", re.I), "<ago>"),
    (re.compile(r"\b[\d,]+\s*(views?|visitors?|hits?|online|watching|reads?)\b", re.I), "<count>"),
    (re.compile(r"\b(visitor|hit)s?\s*(count|counter|no\.?)?\s*[:\-]?\s*[\d,]+", re.I), "<count>"),
    (re.compile(r"\b(last\s+updated|updated\s+on|as\s+on|generated\s+on|page\s+last\s+modified)\b[^\n]{0,40}", re.I), "<updated>"),
    (re.compile(r"\b[0-9a-f]{24,}\b", re.I), "<hex>"),
    (re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"), "<token>"),
    (re.compile(r"©\s*\d{4}(\s*[-–]\s*\d{4})?"), "<copyright>"),
]


def sanitize_text(text: str, max_chars: int | None = None) -> str:
    """Normalise unicode and strip invisible/control characters used to hide prompt-injection payloads."""
    t = unicodedata.normalize("NFKC", text)
    t = _INVISIBLE.sub("", t)
    t = _CONTROL.sub(" ", t)
    lines: list[str] = []
    prev = None
    for raw in t.splitlines():
        line = _SPACES.sub(" ", raw).strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line == prev:
            continue
        lines.append(line)
        prev = line
    out = "\n".join(lines).strip()
    if max_chars is not None and len(out) > max_chars:
        out = out[:max_chars]
    return out


def normalize_volatile(text: str) -> str:
    t = text
    for rx, repl in _VOLATILE:
        t = rx.sub(repl, t)
    return t


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_volatile(text).encode("utf-8")).hexdigest()


def raw_hash(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


_TOKEN = re.compile(r"\w+", re.UNICODE)


def simhash64(text: str, shingle: int = 3) -> int:
    tokens = _TOKEN.findall(normalize_volatile(text).lower())
    if not tokens:
        return 0
    weights = [0] * 64
    grams = (
        [" ".join(tokens[i : i + shingle]) for i in range(max(1, len(tokens) - shingle + 1))]
        if len(tokens) >= shingle
        else [" ".join(tokens)]
    )
    for g in grams:
        h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
        for b in range(64):
            weights[b] += 1 if (h >> b) & 1 else -1
    value = 0
    for b in range(64):
        if weights[b] > 0:
            value |= 1 << b
    # store as signed BIGINT
    return value - (1 << 64) if value >= (1 << 63) else value


def hamming64(a: int, b: int) -> int:
    return bin((a ^ b) & ((1 << 64) - 1)).count("1")


_DIGITS = re.compile(r"\d+")


def line_signature(line: str) -> str:
    """Shape of a line with numbers erased; used to learn 'noise' lines (e.g. 'Visitors: 1234')."""
    shape = _DIGITS.sub("#", normalize_volatile(line).lower())
    shape = _SPACES.sub(" ", shape).strip()
    return hashlib.blake2b(shape.encode(), digest_size=8).hexdigest()
