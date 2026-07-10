"""RSS/Atom adapter. Normalises feed items into additive ChangeEntry records."""
from __future__ import annotations

import re
import time

import feedparser
import requests

from agent.lib.models import ChangeEntry, FeedSpec
from agent.lib.feeds import register

_TAG = re.compile(r"<[^>]+>")


def _http_get(url: str) -> str:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "change-monitor/1.0"})
    resp.raise_for_status()
    return resp.text


def _to_date(entry) -> str:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    return time.strftime("%Y-%m-%d", st) if st else ""


def _clean(text: str) -> str:
    return _TAG.sub("", text or "").strip()


@register("rss")
def fetch(spec: FeedSpec, *, fetch_text=_http_get) -> list[ChangeEntry]:
    parsed = feedparser.parse(fetch_text(spec.url))
    out: list[ChangeEntry] = []
    for e in parsed.entries:
        out.append(ChangeEntry(
            techKey=spec.techKey,
            date=_to_date(e),
            changeType="additive",
            title=e.get("title", "").strip(),
            summary=_clean(e.get("summary", "")),
            sourceUrl=e.get("link", spec.url),
            sourceTier=spec.tier,
            feedAdapter="rss",
        ))
    return out
