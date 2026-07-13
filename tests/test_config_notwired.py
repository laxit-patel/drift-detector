import textwrap
import pytest
from agent.config import load_config, ConfigError


def _write(tmp_path, body):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)


def test_html_changelog_feed_rejected_as_not_yet_wired(tmp_path):
    body = """
        kb: { root: kb/ }
        feeds:
          - { techKey: api:foo, label: Foo, category: integration, adapter: html-changelog, url: https://foo.example/changelog, tier: 2 }
    """
    with pytest.raises(ConfigError, match="not yet wired"):
        load_config(_write(tmp_path, body))


def test_registry_feed_rejected_as_not_yet_wired(tmp_path):
    body = """
        kb: { root: kb/ }
        feeds:
          - { techKey: lib:npm/foo, label: Foo, category: library, adapter: registry, url: https://registry.npmjs.org/foo, tier: 1 }
    """
    with pytest.raises(ConfigError, match="registry-scan"):
        load_config(_write(tmp_path, body))
