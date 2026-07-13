# tests/test_html_changelog.py
from agent.lib.models import FeedSpec
from agent.lib.feeds import html_changelog, get_adapter

def _spec():
    return FeedSpec(techKey="api:amazon-sp-api", label="SP-API", category="integration",
                    adapter="html-changelog", url="https://x/changelog", tier=1)

def test_structures_page_when_changed():
    def struct(text, spec):
        return [{"date": "2026-07-03", "changeType": "breaking", "title": "Orders change",
                 "summary": "BuyerInfo optional", "evidence": "BuyerInfo is now optional"}]
    entries, h = html_changelog.fetch(_spec(), fetch_text=lambda u: "<html>new</html>",
                                      structure_fn=struct, prior_hash="")
    assert len(entries) == 1 and entries[0].changeType == "breaking"
    assert entries[0].techKey == "api:amazon-sp-api" and h                     # a hash was returned

def test_unchanged_page_skips_llm():
    calls = []
    def struct(text, spec): calls.append(1); return []
    # first call to learn the hash
    _, h = html_changelog.fetch(_spec(), fetch_text=lambda u: "same", structure_fn=struct, prior_hash="")
    # second call with prior_hash == h -> no structure_fn call
    entries, h2 = html_changelog.fetch(_spec(), fetch_text=lambda u: "same", structure_fn=struct, prior_hash=h)
    assert entries == [] and h2 == h and calls == [1]                          # struct called once, not twice

def test_registered():
    assert get_adapter("html-changelog") is html_changelog.fetch
