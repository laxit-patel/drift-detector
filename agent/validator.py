"""Trust gate: mechanically verify LLM-produced findings before they are reported."""
from __future__ import annotations

from dataclasses import replace

from agent.classify_rules import days_until

_ACTIONABLE = {"ACTION", "REVIEW"}


def validate_findings(findings: list, fetched_urls: set, now: str):
    kept, rejected = [], []
    for f in findings:
        if f.severity not in _ACTIONABLE:
            kept.append(f)
            continue
        if not (f.evidence or "").strip():
            rejected.append({"id": f.id, "reason": "missing evidence quote"})
            continue
        if f.sourceUrl not in fetched_urls:
            rejected.append({"id": f.id, "reason": f"sourceUrl not fetched this run: {f.sourceUrl}"})
            continue
        if f.sourceTier == 3 and not f.watchlist:
            rejected.append({"id": f.id, "reason": "tier-3 finding must be watchlist-only"})
            continue
        kept.append(replace(f, urgencyDays=days_until(f.deadlineDate, now)))
    return kept, rejected
