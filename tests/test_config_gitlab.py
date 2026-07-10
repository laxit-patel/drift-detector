import textwrap
import pytest
from agent.config import load_config, ConfigError

def _write(tmp_path, body):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)

BASE_FEEDS = textwrap.dedent("""
    feeds:
      - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }
""")

def test_gitlab_and_scan_parsed(tmp_path):
    cfg = load_config(_write(tmp_path, textwrap.dedent("""
        kb: { root: kb/ }
        gitlab:
          baseUrl: https://gitlab.example.internal
          tokenEnv: GITLAB_READ_TOKEN
          expectedNamespaces: [clients, internal]
        scan:
          activeWindowDays: 90
          alwaysInclude: [clients/legacy]
          deny: [internal/sandbox]
          branchOverrides: { clients/acme: release }
          maxRepos: 50
    """) + BASE_FEEDS))
    assert cfg.gitlab.base_url == "https://gitlab.example.internal"
    assert cfg.gitlab.token_env == "GITLAB_READ_TOKEN"
    assert cfg.gitlab.expected_namespaces == ["clients", "internal"]
    assert cfg.scan.active_window_days == 90
    assert cfg.scan.always_include == ["clients/legacy"]
    assert cfg.scan.deny == ["internal/sandbox"]
    assert cfg.scan.branch_overrides == {"clients/acme": "release"}
    assert cfg.scan.max_repos == 50

def test_scan_defaults_when_absent(tmp_path):
    cfg = load_config(_write(tmp_path, "kb: { root: kb/ }\n" + BASE_FEEDS))
    assert cfg.gitlab is None
    assert cfg.scan.active_window_days == 90     # default
    assert cfg.scan.allow == [] and cfg.scan.deny == []

def test_gitlab_section_requires_baseurl_and_tokenenv(tmp_path):
    with pytest.raises(ConfigError, match="baseUrl"):
        load_config(_write(tmp_path, textwrap.dedent("""
            kb: { root: kb/ }
            gitlab: { tokenEnv: GITLAB_READ_TOKEN }
        """) + BASE_FEEDS))
