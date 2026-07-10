"""The Finding model + findings.json container. The contract Plan 05's LLM stage targets."""
from __future__ import annotations

from dataclasses import dataclass, asdict


def finding_id(project_id: int, tech_key: str, change_ref: str) -> str:
    return f"{project_id}|{tech_key}|{change_ref}"


@dataclass(frozen=True)
class Finding:
    id: str
    projectId: int
    repo: str
    findingType: str          # drift | lifecycle
    category: str             # integration | framework | library | runtime
    tech: str
    techKey: str
    changeType: str           # breaking|security|deprecation|behavioral|additive|eol
    severity: str             # ACTION | REVIEW | OK
    sourceUrl: str
    sourceTier: int
    versionInUse: str = ""
    changeEntryId: str = ""
    watchlist: bool = False
    evidence: str = ""
    businessRiskNote: str = ""
    deadlineDate: str = ""
    urgencyDays: "int | None" = None
    deltaState: str = ""
    firstSeen: str = ""
    lastSeen: str = ""
    needsReview: bool = False
    recommendedAction: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        return cls(**d)


def empty_findings_doc(now: str) -> dict:
    return {
        "schemaVersion": 1,
        "runDate": now,
        "counts": {"action": 0, "review": 0, "ok": 0, "watchlist": 0},
        "delta": {"new": [], "resolved": [], "ongoing": []},
        "findings": [],
        "watchlist": [],
        "coverage": {},
        "reportedWatermarks": {},
    }
