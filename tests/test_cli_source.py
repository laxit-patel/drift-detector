import json, textwrap
from agent import cli

def _local_repo(root, name, files):
    d = root / name; (d / ".git").mkdir(parents=True)
    for rel, content in files.items():
        p = d / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)

def test_discover_and_inventory_local_source(tmp_path, monkeypatch):
    repos = tmp_path / "repos"; repos.mkdir()
    _local_repo(repos, "acme", {"package.json": '{"dependencies":{"stripe":"12.0.0"}}',
                                "src/Amazon.php": "sellingpartnerapi client"})
    # git activity is read via subprocess; stub it so no real git/commits are needed.
    from agent.lib import local_provider
    monkeypatch.setattr(local_provider, "_default_run",
                        lambda args: ("main" if "rev-parse" in " ".join(args)
                                      else "2026-07-01T00:00:00+00:00"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent(f"""
        kb: {{ root: {tmp_path}/kb }}
        source: {{ type: local, root: {repos} }}
        scan: {{ activeWindowDays: 3650 }}
        feeds:
          - {{ techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }}
    """))
    active = tmp_path / "active.json"; inv = tmp_path / "inv.json"
    pats = tmp_path / "patterns.yaml"; pats.write_text("- {techKey: api:amazon-sp-api, query: sellingpartnerapi, label: SP-API}\n")

    rc = cli.main(["discover", "--config", str(cfg), "--now", "2026-07-13", "--out", str(active)])
    assert rc == 0
    data = json.loads(active.read_text())
    assert data["active"] and data["active"][0]["path_with_namespace"] == "acme"

    rc = cli.main(["inventory", "--config", str(cfg), "--active", str(active),
                   "--out", str(inv), "--patterns", str(pats), "--now", "2026-07-13"])
    assert rc == 0
    d = json.loads(inv.read_text())
    assert any(r["tech_key"] == "lib:npm/stripe" for r in d["records"])          # manifest parsed from disk
    assert any(u["tech_key"] == "api:amazon-sp-api" for u in d["usedTechs"])     # presence via local grep
