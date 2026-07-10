import json, textwrap
from agent import cli
from agent.lib.gitlab_read import GitLabAuthError

class FakeClient:
    def __init__(self, cands, commits):
        self._c, self._m = cands, commits
    def list_candidate_projects(self, since):
        return self._c
    def has_commit_since(self, pid, since, ref=None):
        return self._m.get(pid)

class FakeErrorClient:
    def list_candidate_projects(self, since):
        raise GitLabAuthError("401")
    def has_commit_since(self, pid, since, ref=None):
        raise AssertionError("should not be called")

def _cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        kb: { root: kb/ }
        gitlab: { baseUrl: https://gl.test, tokenEnv: GITLAB_READ_TOKEN, expectedNamespaces: [clients, missingns] }
        scan: { activeWindowDays: 90 }
        feeds:
          - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }
    """))
    return str(p)

def test_discover_writes_output_and_warns_missing_namespace(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITLAB_READ_TOKEN", "tok")
    out = tmp_path / "active-repos.json"
    client = FakeClient([{"id": 1, "path_with_namespace": "clients/a", "default_branch": "main",
                          "last_activity_at": "2026-07-01T00:00:00Z"}], {1: "2026-06-20T00:00:00Z"})
    rc = cli.main(["discover", "--config", _cfg(tmp_path), "--now", "2026-07-10",
                   "--out", str(out)], client=client)
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["active"][0]["path_with_namespace"] == "clients/a"
    err = capsys.readouterr().out
    assert "WARNING" in err and "missingns" in err        # expected namespace not covered

def test_discover_fails_loud_without_token(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITLAB_READ_TOKEN", raising=False)
    rc = cli.main(["discover", "--config", _cfg(tmp_path), "--now", "2026-07-10",
                   "--out", str(tmp_path / "o.json")], client=None)
    assert rc == 2

def test_discover_infra_error_returns_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITLAB_READ_TOKEN", "tok")
    fake = FakeErrorClient()
    rc = cli.main(["discover", "--config", _cfg(tmp_path), "--now", "2026-07-10",
                   "--out", str(tmp_path / "o.json")], client=fake)
    assert rc == 2
