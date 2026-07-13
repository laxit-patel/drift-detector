import textwrap
import pytest
from agent.config import load_config, ConfigError
from agent.lib.source import make_provider, SourceError
from agent.lib.github_provider import GitHubProvider

FEEDS = "\nfeeds:\n  - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }\n"

def _cfg(tmp_path, body):
    p = tmp_path / "c.yaml"; p.write_text(textwrap.dedent(body) + FEEDS); return load_config(str(p))

def test_github_source_parsed(tmp_path):
    cfg = _cfg(tmp_path, "kb: { root: kb/ }\nsource: { type: github, owner: laxit-patel, tokenEnv: GH_TOKEN }")
    assert cfg.source.type == "github" and cfg.source.github_owner == "laxit-patel"
    assert cfg.source.github_token_env == "GH_TOKEN"

def test_github_requires_owner(tmp_path):
    with pytest.raises(ConfigError, match="owner"):
        _cfg(tmp_path, "kb: { root: kb/ }\nsource: { type: github }")

def test_make_github_provider_with_env_token(tmp_path):
    cfg = _cfg(tmp_path, "kb: { root: kb/ }\nsource: { type: github, owner: acme, tokenEnv: GH_TOKEN }")
    prov = make_provider(cfg, env={"GH_TOKEN": "tok"})
    assert isinstance(prov, GitHubProvider) and prov.owner == "acme"

def test_make_github_no_token_raises(tmp_path, monkeypatch):
    # env empty AND gh fallback stubbed to return "" -> SourceError
    import agent.lib.source as source_mod
    monkeypatch.setattr(source_mod, "_gh_token", lambda: "")
    cfg = _cfg(tmp_path, "kb: { root: kb/ }\nsource: { type: github, owner: acme, tokenEnv: GH_TOKEN }")
    with pytest.raises(SourceError):
        make_provider(cfg, env={})
