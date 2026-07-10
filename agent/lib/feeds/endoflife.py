"""endoflife.date adapter. Emits a lifecycle ChangeEntry per cycle with a concrete EOL date."""
from __future__ import annotations

import requests

from agent.lib.models import ChangeEntry, FeedSpec
from agent.lib.feeds import register


def _http_json(url: str):
    resp = requests.get(url, timeout=30, headers={"User-Agent": "change-monitor/1.0"})
    resp.raise_for_status()
    return resp.json()


@register("endoflife")
def fetch(spec: FeedSpec, *, fetch_json=_http_json) -> list[ChangeEntry]:
    product = spec.url.strip("/")
    data = fetch_json(f"https://endoflife.date/api/{product}.json")
    human_url = f"https://endoflife.date/{product}"
    out: list[ChangeEntry] = []
    for row in data:
        eol = row.get("eol")
        if not isinstance(eol, str):        # bool eol has no concrete date to report
            continue
        cycle = row.get("cycle", "?")
        out.append(ChangeEntry(
            techKey=spec.techKey,
            date=eol,
            changeType="deprecation",
            title=f"{spec.label} {cycle} end-of-life",
            summary=f"{spec.label} {cycle} reaches end-of-life on {eol}.",
            sourceUrl=human_url,
            sourceTier=spec.tier,
            affectedArea=f"cycle {cycle}",
            feedAdapter="endoflife",
        ))
    return out
