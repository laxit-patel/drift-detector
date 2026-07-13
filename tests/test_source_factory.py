import textwrap
import pytest
from agent.config import load_config
from agent.lib.source import make_provider, SourceError
from agent.lib.local_provider import LocalProvider
from agent.lib.gitlab_read import GitLabClient

def _cfg(tmp_path, body):
    p = tmp_path / "config.yaml"; p.write_text(textwrap.dedent(body)); return load_config(str(p))

FEEDS = "\nfeeds:\n  - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }\n"

def test_default_source_is_gitlab(tmp_path):
    cfg = _cfg(tmp_path, "kb: { root: kb/ }" + FEEDS)
    assert cfg.source.type == "gitlab"

def test_make_local_provider(tmp_path):
    (tmp_path / "repos").mkdir()
    cfg = _cfg(tmp_path, f"kb: {{ root: kb/ }}\nsource: {{ type: local, root: {tmp_path}/repos }}" + FEEDS)
    prov = make_provider(cfg)
    assert isinstance(prov, LocalProvider)

def test_make_gitlab_provider(tmp_path):
    cfg = _cfg(tmp_path, "kb: { root: kb/ }\nsource: { type: gitlab }\n"
               "gitlab: { baseUrl: https://gl.test, tokenEnv: GITLAB_READ_TOKEN }" + FEEDS)
    prov = make_provider(cfg, env={"GITLAB_READ_TOKEN": "tok"})
    assert isinstance(prov, GitLabClient)

def test_gitlab_without_token_raises(tmp_path):
    cfg = _cfg(tmp_path, "kb: { root: kb/ }\ngitlab: { baseUrl: https://gl.test, tokenEnv: GITLAB_READ_TOKEN }" + FEEDS)
    with pytest.raises(SourceError):
        make_provider(cfg, env={})
