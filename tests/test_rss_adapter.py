from pathlib import Path
from agent.lib.models import FeedSpec
from agent.lib.feeds import rss, get_adapter

FIX = Path(__file__).parent / "fixtures" / "shopify_changelog.xml"

def _spec():
    return FeedSpec(techKey="api:shopify", label="Shopify", category="integration",
                    adapter="rss", url="https://shopify.dev/changelog/feed.xml", tier=1)

def test_rss_parses_items():
    xml = FIX.read_text()
    entries = rss.fetch(_spec(), fetch_text=lambda url: xml)
    assert len(entries) == 2
    first = entries[0]
    assert first.title == "New Bulk Operations endpoint"
    assert first.date == "2026-07-01"
    assert first.techKey == "api:shopify"
    assert first.changeType == "additive"
    assert first.feedAdapter == "rss"
    assert first.sourceUrl == "https://shopify.dev/changelog/bulk-ops"
    assert "<" not in first.summary            # HTML stripped

def test_rss_is_registered():
    assert get_adapter("rss") is rss.fetch
