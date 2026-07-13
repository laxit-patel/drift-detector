# agent/kb_ingest.py
"""Ingest orchestration: run each feed's adapter, append to KB, advance watermarks."""
from __future__ import annotations

from dataclasses import replace

from agent.lib.models import FeedSpec, IngestResult
from agent.lib import kb_store
from agent.lib.feeds import get_adapter
# Import built-in adapters so they self-register on import of this module:
from agent.lib.feeds import rss, endoflife, html_changelog  # noqa: F401

# Adapters that fetch a whole page and skip re-processing when it is unchanged.
# They accept prior_hash=<last page hash> and return (entries, page_hash);
# plain adapters (rss/endoflife) are called as adapter(spec) and return a list.
HASH_ADAPTERS = {"html-changelog"}


def ingest_feed(spec: FeedSpec, kb_root: str, now: str, *, get=get_adapter) -> IngestResult:
    try:
        adapter = get(spec.adapter)
        wm = kb_store.read_watermark(kb_root, spec.techKey)
        if spec.adapter in HASH_ADAPTERS:
            raw, page_hash = adapter(spec, prior_hash=wm.get("pageHash", ""))
        else:
            raw, page_hash = adapter(spec), None
        stamped = [replace(e, ingestedAt=now) for e in raw]
        written = kb_store.append_entries(kb_root, spec.techKey, stamped)
        if page_hash is not None or raw:            # advance watermark on any run that fetched
            if page_hash is not None:
                wm["pageHash"] = page_hash
            latest = max((e.date for e in raw if e.date), default="")
            if latest:
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
