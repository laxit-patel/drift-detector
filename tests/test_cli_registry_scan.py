import json
import textwrap

from agent import cli, registry_scan
from agent.lib import kb_store


def _cfg(tmp_path):
    root = tmp_path / "kb"
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(f"""
        kb: {{ root: {root} }}
        feeds:
          - {{ techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }}
    """))
    return str(p), str(root)


def test_cli_registry_scan_checks_inventory_libs(tmp_path, monkeypatch, capsys):
    cfg, root = _cfg(tmp_path)
    inv_path = tmp_path / "inventory.json"
    inv_path.write_text(json.dumps({
        "records": [
            {"repo": "g/r", "tech_key": "lib:npm/request", "kind": "library"},
            {"repo": "g/r", "tech_key": "runtime:php", "kind": "runtime"},
        ]
    }))

    payload = {"name": "request", "dist-tags": {"latest": "2.88.2"},
               "versions": {"2.88.2": {"name": "request", "version": "2.88.2",
                                        "deprecated": "request has been deprecated"}}}
    monkeypatch.setattr(registry_scan, "_http_json", lambda url: payload)

    rc = cli.main(["registry-scan", "--config", cfg, "--inventory", str(inv_path), "--now", "2026-07-13"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1" in out and "techKey" in out.lower() or "checked" in out.lower()

    entries = kb_store.load_entries(root, "lib:npm/request")
    assert len(entries) == 1
    assert entries[0].changeType == "deprecation"
