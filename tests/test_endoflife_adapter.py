import json
from pathlib import Path
from agent.lib.models import FeedSpec
from agent.lib.feeds import endoflife, get_adapter

FIX = json.loads((Path(__file__).parent / "fixtures" / "endoflife_php.json").read_text())

def _spec():
    return FeedSpec(techKey="runtime:php", label="PHP", category="runtime",
                    adapter="endoflife", url="php", tier=1)

def test_endoflife_emits_entry_per_dated_cycle():
    entries = endoflife.fetch(_spec(), fetch_json=lambda url: FIX)
    # fixture has cycles 8.3 (eol date), 8.2 (eol date), 8.1 (eol bool true -> skipped)
    dates = sorted(e.date for e in entries)
    assert dates == ["2025-12-08", "2026-12-31"]
    e = next(e for e in entries if e.date == "2025-12-08")
    assert e.changeType == "deprecation"
    assert e.techKey == "runtime:php"
    assert "8.2" in e.title
    assert e.sourceUrl == "https://endoflife.date/php"

def test_endoflife_registered():
    assert get_adapter("endoflife") is endoflife.fetch
