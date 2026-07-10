# agent/kb_ingest.py
"""Ingest orchestration: run each feed's adapter, append to KB, advance watermarks."""
from __future__ import annotations

from dataclasses import replace

from agent.lib.models import FeedSpec, IngestResult
from agent.lib import kb_store
from agent.lib.feeds import get_adapter
# Import built-in adapters so they self-register on import of this module:
from agent.lib.feeds import rss, endoflife  # noqa: F401


def ingest_feed(spec: FeedSpec, kb_root: str, now: str, *, get=get_adapter) -> IngestResult:
    try:
        adapter = get(spec.adapter)
        raw = adapter(spec)
        stamped = [replace(e, ingestedAt=now) for e in raw]
        written = kb_store.append_entries(kb_root, spec.techKey, stamped)
        if raw:
            latest = max(e.date for e in raw if e.date) if any(e.date for e in raw) else ""
            wm = kb_store.read_watermark(kb_root, spec.techKey)
            wm["lastIngestedDate"] = max(wm.get("lastIngestedDate", ""), latest)
            wm["lastRun"] = now
            kb_store.write_watermark(kb_root, spec.techKey, wm)
        return IngestResult(techKey=spec.techKey, adapter=spec.adapter,
                            new_entries=written, status="ok")
    except Exception as exc:  # feed down / parse error -> coverage gap, never crash the run
        return IngestResult(techKey=spec.techKey, adapter=spec.adapter,
                            new_entries=[], status="error", error=str(exc))


def ingest_all(feeds: list[FeedSpec], kb_root: str, now: str, *, get=get_adapter) -> list[IngestResult]:
    return [ingest_feed(spec, kb_root, now, get=get) for spec in feeds]
