"""Core data models for the change-monitoring agent. Pure data, no I/O."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict

CHANGE_TYPES = {"breaking", "deprecation", "behavioral", "security", "additive"}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "entry"


def techkey_to_dir(techKey: str) -> str:
    """Filesystem-safe directory name for a techKey (e.g. 'api:amazon-sp-api')."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", techKey)


def _stable_hash(text: str) -> str:
    """Deterministic 8-hex-char hash (hashlib, NOT builtin hash() which is per-process randomized for str)."""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:8]


@dataclass(frozen=True)
class ChangeEntry:
    techKey: str
    date: str            # ISO 'YYYY-MM-DD'
    changeType: str
    title: str
    summary: str
    sourceUrl: str
    sourceTier: int
    evidence: str = ""
    affectedArea: str = ""
    breaking: bool = False
    ingestedAt: str = ""
    feedAdapter: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(
                self, "id",
                f"{self.techKey}|{self.date}|{slugify(self.title)}|{_stable_hash(self.title)}",
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ChangeEntry":
        return cls(**d)


@dataclass(frozen=True)
class FeedSpec:
    techKey: str
    label: str
    category: str        # integration | framework | library | runtime
    adapter: str         # rss | endoflife | github-releases | registry | html-changelog
    url: str
    tier: int
    warn: str = ""
    upgradeGuide: str = ""


@dataclass
class IngestResult:
    techKey: str
    adapter: str
    new_entries: list      # list[ChangeEntry]
    status: str            # "ok" | "error"
    error: str | None = None
