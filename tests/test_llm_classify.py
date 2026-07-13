# tests/test_llm_classify.py
from agent.lib.finding import Finding
from agent import llm_classify

def _f(fid, needs=True, ct="additive", sev="OK"):
    return Finding(id=fid, projectId=1, repo="c/a", findingType="drift", category="library",
                   tech="x", techKey="lib:npm/x", changeType=ct, severity=sev,
                   sourceUrl="https://s", sourceTier=1, evidence="", needsReview=needs,
                   deadlineDate="")

def test_reclassify_upgrades_severity_from_llm_verdict():
    def fake(items):
        return [{"id": items[0]["id"], "changeType": "breaking",
                 "evidence": "changelog: removed getFoo()", "businessRiskNote": "callers of getFoo break"}]
    out, unresolved = llm_classify.reclassify([_f("1")], "2026-07-13", classify_fn=fake)
    assert unresolved == []
    f = out[0]
    assert f.changeType == "breaking" and f.severity == "ACTION"    # map_severity(breaking)->ACTION
    assert f.needsReview is False and "getFoo" in f.evidence and f.businessRiskNote

def test_non_needsreview_passthrough_and_no_llm_call():
    called = []
    def fake(items): called.append(items); return []
    out, unresolved = llm_classify.reclassify([_f("1", needs=False, ct="breaking", sev="ACTION")],
                                              "2026-07-13", classify_fn=fake)
    assert called == []                     # no needsReview -> classify_fn not called
    assert out[0].severity == "ACTION"

def test_missing_verdict_stays_unresolved():
    out, unresolved = llm_classify.reclassify([_f("1")], "2026-07-13", classify_fn=lambda items: [])
    assert unresolved == ["1"]
    assert out[0].needsReview is True       # left for coverage gap
