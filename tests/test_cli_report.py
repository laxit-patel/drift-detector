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

def test_report_cli_end_to_end(tmp_path):
    kb_root = str(tmp_path / "kb")
    # KB has a passed PHP EOL entry
    kb_store.append_entries(kb_root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="eol", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://endoflife.date/php", sourceTier=1, evidence="PHP 8.0 EOL 2023-11-26")])
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({
        "records": [{"repo": "c/a", "tech_key": "runtime:php", "kind": "runtime", "version_hint": "8.0", "declared_range": "", "ecosystem": "docker"}],
        "usedTechs": [], "coverage": {"reposScanned": 1}}))
    active = tmp_path / "active.json"
    active.write_text(json.dumps({"active": [{"id": 42, "path_with_namespace": "c/a"}]}))
    outr = tmp_path / "report.md"; outf = tmp_path / "findings.json"

    rc = cli.main(["report", "--config", _cfg(tmp_path, kb_root), "--inventory", str(inv),
                   "--active", str(active), "--prev", "-", "--out-report", str(outr),
                   "--out-findings", str(outf), "--now", "2026-07-12"])
    assert rc == 0
    findings = json.loads(outf.read_text())
    assert findings["counts"]["action"] == 1                       # passed EOL -> ACTION
    md = outr.read_text()
    assert "Business-logic risk" in md and "c/a" in md and "PHP" in md
    assert findings["findings"][0]["deltaState"] == "NEW"


def test_report_persistent_risk_is_ongoing_not_resolved(tmp_path):
    """Regression for the cross-run delta bug: a persistent, still-applicable risk must be
    reported ONGOING on run 2 (not RESOLVED), and only RESOLVED once the tech genuinely
    leaves inventory for two consecutive runs (flap damping)."""
    kb_root = str(tmp_path / "kb")
    kb_store.append_entries(kb_root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="eol", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://endoflife.date/php", sourceTier=1,
        evidence="PHP 8.0 EOL 2023-11-26", affectedArea="cycle 8.0")])

    inv_path = tmp_path / "inventory.json"
    inv_with_php = {
        "records": [{"repo": "c/a", "tech_key": "runtime:php", "kind": "runtime",
                     "version_hint": "8.0", "declared_range": "", "ecosystem": "docker"}],
        "usedTechs": [], "coverage": {"reposScanned": 1}}
    inv_without_php = {"records": [], "usedTechs": [], "coverage": {"reposScanned": 1}}
    inv_path.write_text(json.dumps(inv_with_php))

    active = tmp_path / "active.json"
    active.write_text(json.dumps({"active": [{"id": 42, "path_with_namespace": "c/a"}]}))

    cfg = _cfg(tmp_path, kb_root)

    def _run(prev, now, tag):
        outr, outf = tmp_path / f"r{tag}.md", tmp_path / f"f{tag}.json"
        rc = cli.main(["report", "--config", cfg, "--inventory", str(inv_path), "--active", str(active),
                       "--prev", prev, "--out-report", str(outr), "--out-findings", str(outf), "--now", now])
        assert rc == 0
        return json.loads(outf.read_text()), str(outf)

    # Run 1: NEW ACTION finding.
    findings1, path1 = _run("-", "2026-07-01", 1)
    assert findings1["counts"]["action"] == 1
    fid = findings1["findings"][0]["id"]
    assert findings1["findings"][0]["deltaState"] == "NEW"

    # Run 2: same tech, same version still in inventory -> ONGOING, NOT resolved.
    findings2, path2 = _run(path1, "2026-07-08", 2)
    match2 = [f for f in findings2["findings"] if f["id"] == fid]
    assert len(match2) == 1
    assert match2[0]["deltaState"] == "ONGOING"
    assert fid in findings2["delta"]["ongoing"]
    assert findings2["delta"]["resolved"] == []

    # Tech leaves inventory.
    inv_path.write_text(json.dumps(inv_without_php))

    # Run 3: first absence -> pending, not yet resolved (flap damping).
    findings3, path3 = _run(path2, "2026-07-15", 3)
    assert findings3["delta"]["resolved"] == []

    # Run 4: second consecutive absence -> RESOLVED.
    findings4, _ = _run(path3, "2026-07-22", 4)
    assert fid in findings4["delta"]["resolved"]
