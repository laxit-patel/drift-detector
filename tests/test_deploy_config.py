"""Guards the shipped production config: it must load and carry the marketplace feeds."""
from agent.config import load_config


def test_deploy_config_loads_and_has_marketplace_feeds():
    cfg = load_config("deploy/config.yaml")
    by_tk = {f.techKey: f for f in cfg.feeds}

    # SP-API: official changelog RSS (not the interim GitHub-commits feed)
    sp = by_tk["api:amazon-sp-api"]
    assert sp.adapter == "rss"
    assert sp.url == "https://developer-docs.amazon.com/sp-api/changelog.rss"

    # Walmart: wired via the html-changelog adapter (Task 1)
    wm = by_tk["api:walmart-marketplace"]
    assert wm.adapter == "html-changelog"

    # Shopify: still the official Atom feed
    assert by_tk["api:shopify"].adapter == "rss"

    # eBay is deferred — must NOT be present
    assert "api:ebay" not in by_tk
