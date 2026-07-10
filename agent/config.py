"""Load and validate config.yaml into typed objects. Fail loud on bad config."""
from __future__ import annotations

from dataclasses import dataclass
import yaml

from agent.lib.models import FeedSpec

ALLOWED_ADAPTERS = {"rss", "endoflife", "github-releases", "registry", "html-changelog"}
ALLOWED_CATEGORIES = {"integration", "framework", "library", "runtime"}
_REQUIRED = ("techKey", "label", "category", "adapter", "url", "tier")


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    kb_root: str
    feeds: list[FeedSpec]
    raw: dict


def _feed_from(d: dict) -> FeedSpec:
    for k in _REQUIRED:
        if d.get(k) in (None, ""):
            raise ConfigError(f"feed {d.get('techKey', '?')}: missing required field '{k}'")
    if d["adapter"] not in ALLOWED_ADAPTERS:
        raise ConfigError(f"feed {d['techKey']}: unknown adapter '{d['adapter']}'")
    if d["category"] not in ALLOWED_CATEGORIES:
        raise ConfigError(f"feed {d['techKey']}: unknown category '{d['category']}'")
    return FeedSpec(
        techKey=d["techKey"], label=d["label"], category=d["category"],
        adapter=d["adapter"], url=str(d["url"]), tier=int(d["tier"]),
        warn=d.get("warn", ""), upgradeGuide=d.get("upgradeGuide", ""),
    )


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    feeds_raw = raw.get("feeds") or []
    if not feeds_raw:
        raise ConfigError("config must declare at least one feed")
    feeds = [_feed_from(f) for f in feeds_raw]
    kb_root = (raw.get("kb") or {}).get("root", "kb/")
    return Config(kb_root=kb_root, feeds=feeds, raw=raw)
