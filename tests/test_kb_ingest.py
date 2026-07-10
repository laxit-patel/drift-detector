# tests/test_kb_ingest.py
from dataclasses import replace
from agent.lib.models import ChangeEntry, FeedSpec
from agent.lib import kb_store
from agent import kb_ingest

def _spec(adapter="fake-ok"):
    return FeedSpec(techKey="api:shopify", label="Shopify", category="integration",
                    adapter=adapter, url="http://x", tier=1)

def _entry(title):
    return ChangeEntry(techKey="api:shopify", date="2026-07-03", changeType="additive",
                       title=title, summary="", sourceUrl="https://x", sourceTier=1)

def _fake_get(mapping):
    return lambda name: mapping[name]

def test_ingest_feed_appends_and_stamps_now(tmp_path):
    get = _fake_get({"fake-ok": lambda spec, **kw: [_entry("A"), _entry("B")]})
    res = kb_ingest.ingest_feed(_spec(), str(tmp_path), now="2026-07-05", get=get)
    assert res.status == "ok"
    assert len(res.new_entries) == 2
    stored = kb_store.load_entries(str(tmp_path), "api:shopify")
    assert all(e.ingestedAt == "2026-07-05" for e in stored)
    assert kb_store.read_watermark(str(tmp_path), "api:shopify")["lastIngestedDate"] == "2026-07-03"

def test_ingest_feed_is_idempotent(tmp_path):
    get = _fake_get({"fake-ok": lambda spec, **kw: [_entry("A")]})
    kb_ingest.ingest_feed(_spec(), str(tmp_path), now="2026-07-05", get=get)
    res2 = kb_ingest.ingest_feed(_spec(), str(tmp_path), now="2026-07-12", get=get)
    assert res2.new_entries == []          # already present
    assert len(kb_store.load_entries(str(tmp_path), "api:shopify")) == 1

def test_ingest_feed_captures_adapter_error(tmp_path):
    def boom(spec, **kw):
        raise RuntimeError("feed down")
    get = _fake_get({"fake-boom": boom})
    res = kb_ingest.ingest_feed(_spec("fake-boom"), str(tmp_path), now="2026-07-05", get=get)
    assert res.status == "error"
    assert "feed down" in res.error

def test_ingest_all_runs_each_feed(tmp_path):
    get = _fake_get({"fake-ok": lambda spec, **kw: [_entry("A")]})
    feeds = [_spec(), replace(_spec(), techKey="api:twilio")]
    results = kb_ingest.ingest_all(feeds, str(tmp_path), now="2026-07-05", get=get)
    assert [r.status for r in results] == ["ok", "ok"]
