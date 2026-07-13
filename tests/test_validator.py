# tests/test_validator.py
from agent.lib.finding import Finding
from agent import validator

def _f(fid, sev="ACTION", url="https://s", evid="quote", tier=1, wl=False, deadline="", urg=None):
    return Finding(id=fid, projectId=1, repo="c/a", findingType="drift", category="library",
                   tech="x", techKey="lib:npm/x", changeType="breaking", severity=sev,
                   sourceUrl=url, sourceTier=tier, evidence=evid, watchlist=wl,
                   deadlineDate=deadline, urgencyDays=urg)

FETCHED = {"https://s", "https://eol"}

def test_valid_action_kept_and_urgency_recomputed():
    kept, rej = validator.validate_findings([_f("1", deadline="2026-07-20", urg=999)], FETCHED, "2026-07-13")
    assert len(kept) == 1 and rej == []
    assert kept[0].urgencyDays == 7      # recomputed, LLM's 999 overwritten

def test_missing_evidence_rejected():
    kept, rej = validator.validate_findings([_f("1", evid="")], FETCHED, "2026-07-13")
    assert kept == [] and rej[0]["id"] == "1" and "evidence" in rej[0]["reason"]

def test_uncited_url_rejected():
    kept, rej = validator.validate_findings([_f("1", url="https://hallucinated")], FETCHED, "2026-07-13")
    assert kept == [] and "not fetched" in rej[0]["reason"]

def test_tier3_must_be_watchlist():
    kept, rej = validator.validate_findings([_f("1", tier=3, wl=False)], FETCHED, "2026-07-13")
    assert kept == [] and "tier-3" in rej[0]["reason"]
    kept2, rej2 = validator.validate_findings([_f("2", tier=3, wl=True)], FETCHED, "2026-07-13")
    assert len(kept2) == 1 and rej2 == []

def test_ok_findings_pass_untouched():
    kept, rej = validator.validate_findings([_f("1", sev="OK", evid="")], FETCHED, "2026-07-13")
    assert len(kept) == 1 and rej == []       # OK not gated on evidence
