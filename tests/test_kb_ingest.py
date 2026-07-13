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


def _hash_spec():
    return FeedSpec(techKey="api:walmart-marketplace", label="Walmart Marketplace",
                    category="integration", adapter="html-changelog",
                    url="http://x/whatsnew", tier=1)


def test_hash_adapter_threads_page_hash_and_skips_unchanged(tmp_path):
    # Fake html-changelog: records the prior_hash it was handed; returns ([], "H1")
    # when told the page is unchanged (prior_hash == "H1"), else one entry + "H1".
    seen = {}

    def fake(spec, prior_hash=""):
        seen["prior"] = prior_hash
        if prior_hash == "H1":
            return [], "H1"                              # unchanged page -> nothing new
        return ([ChangeEntry(techKey=spec.techKey, date="2026-07-03", changeType="breaking",
                             title="Item spec v5", summary="", sourceUrl=spec.url, sourceTier=1)],
                "H1")

    get = _fake_get({"html-changelog": fake})

    # First run: no prior hash -> structures, appends, stores pageHash "H1".
    r1 = kb_ingest.ingest_feed(_hash_spec(), str(tmp_path), now="2026-07-05", get=get)
    assert r1.status == "ok" and len(r1.new_entries) == 1
    assert seen["prior"] == ""                           # nothing threaded in on the first run
    wm = kb_store.read_watermark(str(tmp_path), "api:walmart-marketplace")
    assert wm["pageHash"] == "H1" and wm["lastRun"] == "2026-07-05"

    # Second run: stored "H1" threaded back in -> page unchanged -> no new entries.
    r2 = kb_ingest.ingest_feed(_hash_spec(), str(tmp_path), now="2026-07-12", get=get)
    assert seen["prior"] == "H1"                          # stored hash was passed to the adapter
    assert r2.new_entries == []
    assert kb_store.read_watermark(str(tmp_path), "api:walmart-marketplace")["pageHash"] == "H1"


def test_plain_adapter_unaffected_by_hash_wiring(tmp_path):
    # rss/endoflife-style adapter: called as adapter(spec), returns a plain list, no pageHash.
    get = _fake_get({"rss": lambda spec, **kw: [_entry("A")]})
    spec = FeedSpec(techKey="api:shopify", label="Shopify", category="integration",
                    adapter="rss", url="http://x", tier=1)
    res = kb_ingest.ingest_feed(spec, str(tmp_path), now="2026-07-05", get=get)
    assert res.status == "ok" and len(res.new_entries) == 1
    assert "pageHash" not in kb_store.read_watermark(str(tmp_path), "api:shopify")


def test_config_accepts_html_changelog_feed(tmp_path):
    from agent.config import load_config
    p = tmp_path / "c.yaml"
    p.write_text(
        "kb: { root: kb/ }\n"
        "feeds:\n"
        "  - { techKey: api:walmart-marketplace, label: Walmart, category: integration,"
        " adapter: html-changelog, url: http://x, tier: 1 }\n"
    )
    cfg = load_config(str(p))
    assert cfg.feeds[0].adapter == "html-changelog"


def test_html_changelog_registered_after_importing_ingest():
    from agent.lib.feeds import get_adapter, html_changelog
    assert get_adapter("html-changelog") is html_changelog.fetch
