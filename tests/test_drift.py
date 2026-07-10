# tests/test_drift.py
from agent.lib.models import ChangeEntry
from agent.lib import kb_store
from agent import drift

def _e(title, date, tk="api:shopify"):
    return ChangeEntry(techKey=tk, date=date, changeType="additive", title=title,
                       summary="", sourceUrl="https://x", sourceTier=1)

def test_select_drift_filters_by_since():
    entries = [_e("old", "2026-06-01"), _e("edge", "2026-07-01"), _e("new", "2026-07-08")]
    got = drift.select_drift(entries, "2026-07-01")
    assert [e.title for e in got] == ["new"]          # strictly newer than watermark

def test_select_drift_none_returns_all_sorted():
    entries = [_e("b", "2026-07-08"), _e("a", "2026-07-01")]
    assert [e.title for e in drift.select_drift(entries, None)] == ["a", "b"]

def test_drift_for_tech_reads_kb(tmp_path):
    root = str(tmp_path)
    kb_store.append_entries(root, "api:shopify", [_e("old", "2026-06-01"), _e("new", "2026-07-08")])
    got = drift.drift_for_tech(root, "api:shopify", "2026-07-01")
    assert [e.title for e in got] == ["new"]

def test_compute_drift_omits_empty(tmp_path):
    root = str(tmp_path)
    kb_store.append_entries(root, "api:shopify", [_e("new", "2026-07-08")])
    kb_store.append_entries(root, "api:twilio", [_e("stale", "2026-01-01", tk="api:twilio")])
    out = drift.compute_drift(root, ["api:shopify", "api:twilio"],
                              {"api:shopify": "2026-07-01", "api:twilio": "2026-06-01"})
    assert len(out) == 1
    assert out[0]["techKey"] == "api:shopify"
    assert [e.title for e in out[0]["entries"]] == ["new"]
