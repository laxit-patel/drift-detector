"""Deterministic severity mapping (spec §6). Rule-decidable cases resolve here;
'additive'/ambiguous entries are marked needsReview for Plan 05's LLM stage."""
from __future__ import annotations

from datetime import date

from agent.lib.finding import Finding, finding_id

_ACTION_TYPES = {"breaking", "security"}
_LIFECYCLE_TYPES = {"eol", "deprecation"}


def days_until(date_iso: str, now: str) -> "int | None":
    if not date_iso:
        return None
    try:
        return (date.fromisoformat(date_iso) - date.fromisoformat(now)).days
    except ValueError:
        return None


def map_severity(change_type, deadline_date, now, review_horizon_months=6):
    if change_type in _ACTION_TYPES:
        return "ACTION", False
    if change_type in _LIFECYCLE_TYPES:
        d = days_until(deadline_date, now)
        if d is None:
            return "REVIEW", False
        if d < 0:
            return "ACTION", False
        if d <= review_horizon_months * 30:
            return "REVIEW", False
        return "OK", False
    if change_type == "behavioral":
        return "REVIEW", False
    if change_type == "additive":
        return "OK", True
    return "REVIEW", True


_ACTIONS = {
    "ACTION": "Schedule migration work — a breaking/sunset change affects this repo.",
    "REVIEW": "Assess impact and monitor — a deprecation/behavioral change or upcoming EOL.",
    "OK": "No action; recorded for the audit trail.",
}


def candidate_to_finding(candidate, now, *, review_horizon_months=6) -> Finding:
    ce = candidate["changeEntry"]
    ctype = ce.get("changeType", "additive")
    deadline = ce.get("date", "") if ctype in _LIFECYCLE_TYPES else ""
    severity, needs_review = map_severity(ctype, deadline, now, review_horizon_months)
    finding_type = "lifecycle" if ctype == "eol" else "drift"
    change_ref = f"lifecycle:{severity}" if ctype == "eol" else ce.get("id", "")
    return Finding(
        id=finding_id(candidate["projectId"], candidate["techKey"], change_ref),
        projectId=candidate["projectId"], repo=candidate["repo"],
        findingType=finding_type, category=candidate.get("category", "library"),
        tech=candidate["techKey"].split("/")[-1], techKey=candidate["techKey"],
        changeType=ctype, severity=severity,
        sourceUrl=ce.get("sourceUrl", ""), sourceTier=int(ce.get("sourceTier", 1)),
        versionInUse=candidate.get("versionInUse", ""),
        changeEntryId=ce.get("id", ""), evidence=ce.get("evidence", ""),
        deadlineDate=deadline, urgencyDays=days_until(deadline, now),
        firstSeen=now, lastSeen=now, needsReview=needs_review,
        recommendedAction=_ACTIONS[severity],
    )
