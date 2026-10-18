"""Line-level diffs between two views of a page, plus new-item detection."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.fetch.normalize import line_signature, normalize_volatile

MAX_DIFF_LINES = 400


@dataclass
class TextDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.removed

    @property
    def size_chars(self) -> int:
        return sum(len(x) for x in self.added) + sum(len(x) for x in self.removed)

    def summary(self, max_lines: int = 6) -> str:
        if self.is_empty:
            return "No textual change"
        parts = [f"+{len(self.added)} / -{len(self.removed)} lines"]
        for line in self.added[:max_lines]:
            parts.append(f"+ {line[:160]}")
        for line in self.removed[: max(0, max_lines - len(self.added[:max_lines]))]:
            parts.append(f"- {line[:160]}")
        return "\n".join(parts)

    def signatures(self) -> set[str]:
        return {line_signature(x) for x in self.added + self.removed}


def diff_lines(old: str, new: str) -> TextDiff:
    """Multiset line diff on volatile-normalised lines. O(n), order of the new page preserved."""
    old_lines = [x for x in old.splitlines() if x.strip()]
    new_lines = [x for x in new.splitlines() if x.strip()]
    old_norm = Counter(normalize_volatile(x) for x in old_lines)
    new_norm = Counter(normalize_volatile(x) for x in new_lines)
    added: list[str] = []
    budget = new_norm - old_norm
    for line in new_lines:
        k = normalize_volatile(line)
        if budget.get(k, 0) > 0:
            added.append(line)
            budget[k] -= 1
            if len(added) >= MAX_DIFF_LINES:
                break
    removed: list[str] = []
    budget = old_norm - new_norm
    for line in old_lines:
        k = normalize_volatile(line)
        if budget.get(k, 0) > 0:
            removed.append(line)
            budget[k] -= 1
            if len(removed) >= MAX_DIFF_LINES:
                break
    return TextDiff(added=added, removed=removed)


def item_key(item: dict[str, str]) -> str:
    return f"{normalize_volatile(item.get('text', '')).strip().lower()}|{item.get('href', '')}"


def new_items(old: list[dict[str, str]], new: list[dict[str, str]]) -> list[dict[str, str]]:
    old_keys = {item_key(i) for i in old}
    return [i for i in new if item_key(i) not in old_keys and i.get("text")]
