"""Drift engine: select KB change entries newer than a caller-supplied watermark."""
from __future__ import annotations

from agent.lib.models import ChangeEntry
from agent.lib import kb_store


def select_drift(entries: list[ChangeEntry], since_date: str | None) -> list[ChangeEntry]:
    picked = [e for e in entries if (not since_date or (e.date and e.date > since_date))]
    return sorted(picked, key=lambda e: e.date)


def drift_for_tech(kb_root: str, techKey: str, since_date: str | None) -> list[ChangeEntry]:
    return select_drift(kb_store.load_entries(kb_root, techKey), since_date)


def compute_drift(kb_root: str, techKeys: list[str], watermarks: dict) -> list[dict]:
    out: list[dict] = []
    for tk in techKeys:
        entries = drift_for_tech(kb_root, tk, watermarks.get(tk))
        if entries:
            out.append({"techKey": tk, "entries": entries})
    return out
