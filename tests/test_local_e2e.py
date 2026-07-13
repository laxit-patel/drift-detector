import json, textwrap
from agent.lib.models import ChangeEntry
from agent.lib import kb_store
from agent import cli

def test_local_source_end_to_end(tmp_path, monkeypatch):
    repos = tmp_path / "repos"; repos.mkdir()
    acme = repos / "acme"; (acme / ".git").mkdir(parents=True)
    (acme / "Dockerfile").write_text("FROM php:8.0-alpine\n")
    from agent.lib import local_provider
    monkeypatch.setattr(local_provider, "_default_run",
                        lambda args: ("main" if "rev-parse" in " ".join(args) else "2026-07-01T00:00:00+00:00"))
    kb_root = str(tmp_path / "kb")
    kb_store.append_entries(kb_root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="deprecation", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://endoflife.date/php", sourceTier=1,
        evidence="PHP 8.0 EOL 2023-11-26", affectedArea="cycle 8.0")])
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent(f"""
        kb: {{ root: {kb_root} }}
        source: {{ type: local, root: {repos} }}
        scan: {{ activeWindowDays: 3650 }}
        feeds:
          - {{ techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }}
    """))
    active = tmp_path / "a.json"; inv = tmp_path / "i.json"
    pats = tmp_path / "p.yaml"; pats.write_text("- {techKey: api:x, query: zzz, label: X}\n")
    outr = tmp_path / "r.md"; outf = tmp_path / "f.json"

    assert cli.main(["discover", "--config", str(cfg), "--now", "2026-07-13", "--out", str(active)]) == 0
    assert cli.main(["inventory", "--config", str(cfg), "--active", str(active), "--out", str(inv),
                     "--patterns", str(pats), "--now", "2026-07-13"]) == 0
    assert cli.main(["classify-report", "--config", str(cfg), "--inventory", str(inv), "--active", str(active),
                     "--prev", "-", "--out-report", str(outr), "--out-findings", str(outf), "--now", "2026-07-13"]) == 0
    doc = json.loads(outf.read_text())
    assert doc["counts"]["action"] == 1        # PHP 8.0 EOL on a repo running php 8.0, all from LOCAL disk
    assert "acme" in outr.read_text()
