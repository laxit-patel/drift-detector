import json, textwrap
from agent.lib.models import ChangeEntry
from agent.lib import kb_store
from agent import cli

def _cfg(tmp_path, kb_root):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(f"""
        kb: {{ root: {kb_root} }}
        feeds:
          - {{ techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }}
    """))
    return str(p)

def test_classify_report_deterministic(tmp_path):
    kb_root = str(tmp_path / "kb")
    kb_store.append_entries(kb_root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="deprecation", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://endoflife.date/php", sourceTier=1,
        evidence="PHP 8.0 reached EOL 2023-11-26", affectedArea="cycle 8.0")])
    inv = tmp_path / "inv.json"; inv.write_text(json.dumps({
        "records": [{"repo": "c/a", "tech_key": "runtime:php", "kind": "runtime", "version_hint": "8.0", "declared_range": "", "ecosystem": "docker"}],
        "usedTechs": [], "coverage": {"reposScanned": 1}}))
    active = tmp_path / "active.json"; active.write_text(json.dumps({"active": [{"id": 42, "path_with_namespace": "c/a"}]}))
    outr = tmp_path / "r.md"; outf = tmp_path / "f.json"
    rc = cli.main(["classify-report", "--config", _cfg(tmp_path, kb_root), "--inventory", str(inv),
                   "--active", str(active), "--prev", "-", "--out-report", str(outr),
                   "--out-findings", str(outf), "--now", "2026-07-13"])
    assert rc == 0
    doc = json.loads(outf.read_text())
    assert doc["counts"]["action"] == 1        # lifecycle EOL kept (self-cited fetched URL + evidence)
    assert "Business-logic risk" in outr.read_text()
