import json, textwrap
from agent import cli

class FakeClient:
    def get_tree(self, pid, ref): return ["package.json"]
    def get_raw_file(self, pid, path, ref): return '{"dependencies":{"stripe":"12.0.0"}}'
    def search_blobs(self, pid, query): return []

def _files(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        kb: { root: kb/ }
        gitlab: { baseUrl: https://gl.test, tokenEnv: GITLAB_READ_TOKEN, expectedNamespaces: [clients] }
        feeds:
          - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }
    """))
    active = tmp_path / "active-repos.json"
    active.write_text(json.dumps({"active": [{"id": 1, "path_with_namespace": "clients/a", "scanned_ref": "main"}]}))
    pats = tmp_path / "patterns.yaml"
    pats.write_text("- {techKey: api:stripe, query: api.stripe.com, label: Stripe}\n")
    return str(cfg), str(active), str(pats)

def test_inventory_cli_writes_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITLAB_READ_TOKEN", "tok")
    cfg, active, pats = _files(tmp_path)
    out = tmp_path / "inventory.json"
    rc = cli.main(["inventory", "--config", cfg, "--active", active, "--out", str(out),
                   "--patterns", pats], client=FakeClient())
    assert rc == 0
    data = json.loads(out.read_text())
    assert any(r["tech_key"] == "lib:npm/stripe" for r in data["records"])
    assert data["coverage"]["reposScanned"] == 1
    assert "clients/a" in capsys.readouterr().out
