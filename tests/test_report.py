from agent.lib.finding import Finding
from agent import report

def _f(fid, sev, tk, repo="c/a", ct="breaking", evid="changed", wl=False):
    return Finding(id=fid, projectId=1, repo=repo, findingType="drift", category="library",
                   tech=tk.split("/")[-1], techKey=tk, changeType=ct, severity=sev,
                   sourceUrl="https://src", sourceTier=1, evidence=evid, deltaState="NEW",
                   watchlist=wl, versionInUse="12.0")

def test_assemble_counts_and_split():
    stamped = [_f("1", "ACTION", "lib:npm/a"), _f("2", "REVIEW", "lib:npm/b"),
               _f("3", "OK", "lib:npm/c"), _f("4", "REVIEW", "api:x", wl=True)]
    doc = report.assemble_findings_doc(stamped, {"new": ["1"], "resolved": [], "ongoing": [], "_resolvedPending": ["9"]},
                                       {"reposScanned": 3}, {"runtime:php": "2026-07-01"}, "2026-07-12")
    assert doc["counts"] == {"action": 1, "review": 1, "ok": 1, "watchlist": 1}
    assert len(doc["findings"]) == 3 and len(doc["watchlist"]) == 1
    assert doc["reportedWatermarks"]["_resolvedPending"] == ["9"]      # persisted for next week
    assert "_resolvedPending" not in doc["delta"]                     # stripped from display block

def test_render_leads_with_business_risk():
    doc = report.assemble_findings_doc([_f("1", "ACTION", "api:amazon-sp-api", evid="BuyerInfo now optional")],
                                       {"new": ["1"], "resolved": [], "ongoing": []}, {"reposScanned": 2}, {}, "2026-07-12")
    md = report.render_report(doc)
    assert md.index("Business-logic risk") < md.index("Delta")       # risk section leads
    assert "BuyerInfo now optional" in md and "c/a" in md
    assert "2026-07-12" in md

def test_empty_sections_show_none():
    doc = report.assemble_findings_doc([], {"new": [], "resolved": [], "ongoing": []}, {"reposScanned": 0}, {}, "2026-07-12")
    md = report.render_report(doc)
    assert "_none_" in md    # empty ACTION section is explicit, not omitted
