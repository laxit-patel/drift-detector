# tests/test_delta.py
from agent.lib.finding import Finding
from agent import delta


def _f(fid, sev="ACTION", first="2026-07-05"):
    return Finding(id=fid, projectId=1, repo="c/a", findingType="drift", category="library",
                   tech="x", techKey="lib:npm/x", changeType="breaking", severity=sev,
                   sourceUrl="https://x", sourceTier=1, firstSeen=first, lastSeen=first)


def _doc(ids, pending=None):
    return {"findings": [_f(i).to_dict() for i in ids],
            "reportedWatermarks": {"_resolvedPending": pending or []}}


def test_first_run_all_new():
    d, stamped = delta.compute_delta([_f("a"), _f("b")], {}, "2026-07-12")
    assert set(d["new"]) == {"a", "b"} and d["resolved"] == [] and d["ongoing"] == []
    assert all(s.deltaState == "NEW" for s in stamped)


def test_ongoing_and_new():
    prev = _doc(["a"])
    d, stamped = delta.compute_delta([_f("a"), _f("b")], prev, "2026-07-12")
    assert d["new"] == ["b"] and d["ongoing"] == ["a"]
    a = next(s for s in stamped if s.id == "a")
    assert a.deltaState == "ONGOING" and a.firstSeen == "2026-07-05"     # carried forward


def test_resolved_needs_two_consecutive_absences():
    # 'a' present last week, gone this week -> first absence -> pending, NOT resolved yet
    prev = _doc(["a"])
    d, _ = delta.compute_delta([], prev, "2026-07-12")
    assert d["resolved"] == []
    # next week 'a' still gone AND was pending -> RESOLVED
    prev2 = {"findings": [], "reportedWatermarks": {"_resolvedPending": ["a"]}}
    d2, _ = delta.compute_delta([], prev2, "2026-07-19")
    assert d2["resolved"] == ["a"]
