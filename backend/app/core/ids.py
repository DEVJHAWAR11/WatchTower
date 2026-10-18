"""Time-ordered UUIDv7 ids (better index locality than uuid4) and slugs."""

from __future__ import annotations

import os
import re
import time
import unicodedata
import uuid


def uuid7() -> uuid.UUID:
    ts_ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    rand_a = rand >> 62 & 0xFFF
    rand_b = rand & ((1 << 62) - 1)
    value = (ts_ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b
    return uuid.UUID(int=value)


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    slug = _SLUG_STRIP.sub("-", norm).strip("-")
    return (slug[:max_len].rstrip("-")) or "watch"
