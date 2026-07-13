"""Map scoped contract changes -> shared Finding objects, with carry-forward persistence so
one-shot contract changes stay ONGOING across weekly runs instead of aging out."""
from __future__ import annotations

from agent.lib.finding import Finding, finding_id

_VERDICT_CHANGETYPE = {"BREAKING": "breaking", "AMBIGUOUS": "behavioral", "ADDITIVE": "additive"}

_ACTIONS = {
    "ACTION": "Schedule migration — a breaking API contract change affects this repo.",
    "REVIEW": "Assess impact — an ambiguous contract change affects this repo.",
    "OK": "No action; recorded for the audit trail.",
}


def _severity(verdict: str, used: bool):
    """Returns (severity, watchlist). Unused breaks/ambiguities are recorded on the watchlist."""
    if verdict in ("BREAKING", "AMBIGUOUS"):
        sev = "ACTION" if verdict == "BREAKING" else "REVIEW"
        return (sev, False) if used else ("OK", True)
    return ("OK", False)                                        # ADDITIVE


def _source_url(marketplace: str, api: str) -> str:
    if marketplace == "sp-api":
        return f"https://github.com/amzn/selling-partner-api-models/blob/main/models/{api}.json"
    return ""


def changes_to_findings(scoped: list, repo_ids: dict, now: str) -> list:
    findings: list = []
    for s in scoped:
        verdict = s.get("verdict", "")
        severity, watch = _severity(verdict, s.get("used", False))
        change_ref = f"{s.get('opKey','')}|{s.get('detail','')}"
        pid = repo_ids.get(s.get("repo", ""), 0)
        tech_key = s.get("techKey", "")
        findings.append(Finding(
            id=finding_id(pid, tech_key, change_ref),
            projectId=pid, repo=s.get("repo", ""),
            findingType="contract-drift", category="integration",
            tech=tech_key.split(":")[-1], techKey=tech_key,
            changeType=_VERDICT_CHANGETYPE.get(verdict, "behavioral"),
            severity=severity, watchlist=watch,
            sourceUrl=_source_url(s.get("marketplace", ""), s.get("api", "")), sourceTier=1,
            evidence=s.get("detail", ""), changeEntryId=change_ref,
            firstSeen=now, lastSeen=now, recommendedAction=_ACTIONS.get(severity, ""),
        ))
    return findings


def carry_forward(new_findings: list, prev_doc: dict, now: str) -> list:
    by_id: dict = {}
    for d in (prev_doc.get("findings", []) + prev_doc.get("watchlist", [])):
        if d.get("findingType") == "contract-drift":
            by_id[d["id"]] = Finding.from_dict(d)
    for f in new_findings:
        by_id[f.id] = f                                        # new supersedes stale prior of same id
    return list(by_id.values())
