import textwrap
import pytest
from agent.config import load_config, ConfigError

def _write(tmp_path, body):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)

VALID = """
    kb: { root: kb/ }
    feeds:
      - { techKey: api:shopify, label: Shopify, category: integration, adapter: rss, url: https://shopify.dev/changelog/feed.xml, tier: 1 }
      - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }
"""

def test_load_valid_config(tmp_path):
    cfg = load_config(_write(tmp_path, VALID))
    assert cfg.kb_root == "kb/"
    assert len(cfg.feeds) == 2
    assert cfg.feeds[0].techKey == "api:shopify"
    assert cfg.feeds[1].adapter == "endoflife"

def test_unknown_adapter_rejected(tmp_path):
    body = VALID.replace("adapter: rss", "adapter: telepathy")
    with pytest.raises(ConfigError, match="unknown adapter"):
        load_config(_write(tmp_path, body))

def test_missing_required_field_rejected(tmp_path):
    body = """
        kb: { root: kb/ }
        feeds:
          - { techKey: api:shopify, label: Shopify, category: integration, adapter: rss, tier: 1 }
    """
    with pytest.raises(ConfigError, match="url"):
        load_config(_write(tmp_path, body))

def test_no_feeds_rejected(tmp_path):
    with pytest.raises(ConfigError, match="at least one feed"):
        load_config(_write(tmp_path, "kb: { root: kb/ }\nfeeds: []\n"))
