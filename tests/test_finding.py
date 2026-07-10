# tests/test_finding.py
from agent.lib.finding import Finding, finding_id, empty_findings_doc

def test_finding_id():
    assert finding_id(12345, "api:amazon-sp-api", "sp|2026-07-03|x") == "12345|api:amazon-sp-api|sp|2026-07-03|x"

def test_finding_roundtrip():
    f = Finding(id="1|runtime:php|lifecycle:ACTION", projectId=1, repo="c/a",
                findingType="lifecycle", category="runtime", tech="PHP", techKey="runtime:php",
                changeType="eol", severity="ACTION", sourceUrl="https://eol", sourceTier=1,
                evidence="PHP 8.0 EOL 2023-11-26", urgencyDays=-600)
    assert Finding.from_dict(f.to_dict()) == f
    assert f.needsReview is False and f.watchlist is False

def test_empty_doc_shape():
    d = empty_findings_doc("2026-07-12")
    assert d["runDate"] == "2026-07-12"
    assert d["counts"] == {"action": 0, "review": 0, "ok": 0, "watchlist": 0}
    assert d["delta"] == {"new": [], "resolved": [], "ongoing": []}
    assert d["findings"] == [] and d["watchlist"] == []
