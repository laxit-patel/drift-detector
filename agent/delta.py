"""Week-over-week delta over stable finding ids, with 2-run flap damping on RESOLVED."""
from __future__ import annotations

from dataclasses import replace

_ACTIONABLE = {"ACTION", "REVIEW"}


def _actionable_ids(findings_dicts):
    return {f["id"]: f for f in findings_dicts if f.get("severity") in _ACTIONABLE}


def compute_delta(current: list, previous_doc: dict, now: str):
    prev_findings = _actionable_ids(previous_doc.get("findings", []))
    prev_pending = set((previous_doc.get("reportedWatermarks") or {}).get("_resolvedPending", []))

    curr = {f.id: f for f in current if f.severity in _ACTIONABLE}
    curr_ids, prev_ids = set(curr), set(prev_findings)

    new = sorted(curr_ids - prev_ids)
    ongoing = sorted(curr_ids & prev_ids)
    resolved = sorted(i for i in prev_pending if i not in curr_ids)   # was pending, still absent -> RESOLVED
    next_pending = sorted(prev_ids - curr_ids)                        # newly disappeared -> pending for next week

    stamped = []
    for f in current:
        state = "NEW" if f.id in new else ("ONGOING" if f.id in ongoing else f.deltaState)
        first_seen = f.firstSeen
        if f.id in ongoing:
            first_seen = prev_findings[f.id].get("firstSeen", f.firstSeen)
        stamped.append(replace(f, deltaState=state, firstSeen=first_seen))

    return ({"new": new, "resolved": resolved, "ongoing": ongoing,
             "_resolvedPending": next_pending}, stamped)
