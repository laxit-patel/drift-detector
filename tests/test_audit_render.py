from agent.lib.audit_render import render_audit_md
from agent.lib.cyclonedx import build_bom
from agent.lib.sarif import build_sarif


_DOC = {
    "repos": [{
        "path": "svc-a",
        "runtimes": {"php": {"range": "^7.4"}},
        "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^0.21.1", "file": "package.json"}],
    }],
}
_AUDIT = {
    "generated": "2026-07-14",
    "counts": {"DEPRECATED": 2, "REVIEW": 0, "reposAffected": 1},
    "findings": [
        {"repo": "svc-a", "kind": "cve", "ref": "npm/axios", "version": "^0.21.1",
         "id": "GHSA-x", "cve": "CVE-1", "fixed": "1.7.4", "status": "DEPRECATED", "severity": "HIGH",
         "detail": "axios SSRF", "date": None, "source_url": "https://osv.dev/x", "tier": 1,
         "recommendation": "upgrade to >= 1.7.4"},
        {"repo": "svc-a", "kind": "eol", "ref": "php", "version": "^7.4", "status": "DEPRECATED",
         "severity": "EOL", "detail": "php 7.4 end-of-life 2022-11-28", "date": "2022-11-28",
         "source_url": "https://endoflife.date/php", "tier": 1, "recommendation": "upgrade to 8.3.10"},
    ],
    "coverage": {"notes": ["Versions are the DECLARED manifest floor — verify against your lockfile."]},
}


def test_audit_md_leads_with_urgent_and_tables():
    md = render_audit_md(_AUDIT)
    assert "Deprecation & Vulnerability Audit" in md
    assert "action-required" in md and "Most urgent" in md
    assert "npm/axios" in md and "php" in md
    assert "https://osv.dev/x" in md                      # cited source
    assert "manifest floor" in md                         # coverage note carried through


def test_audit_md_empty():
    md = render_audit_md({"generated": "2026-07-14", "counts": {}, "findings": [], "coverage": {}})
    assert "No deprecation or vulnerability findings" in md


def test_cyclonedx_bom_shape():
    bom = build_bom(_DOC, _AUDIT["findings"], "2026-07-14")
    assert bom["bomFormat"] == "CycloneDX" and bom["specVersion"] == "1.6"
    purls = [c["purl"] for c in bom["components"] if "purl" in c]
    assert "pkg:npm/axios@0.21.1" in purls
    v = bom["vulnerabilities"][0]
    assert v["id"] == "CVE-1" and v["affects"][0]["ref"] == "pkg:npm/axios@0.21.1"
    assert v["ratings"][0]["severity"] == "high"
    # php EOL surfaced as a framework component property
    php = next(c for c in bom["components"] if c["name"] == "php")
    assert any(p["value"] == "DEPRECATED" for p in php.get("properties", []))


def test_sarif_shape_and_levels():
    sarif = build_sarif(_DOC, _AUDIT["findings"])
    assert sarif["version"] == "2.1.0"
    results = sarif["runs"][0]["results"]
    assert all(r["level"] == "error" for r in results)      # both DEPRECATED -> error
    cve = next(r for r in results if r["ruleId"] == "cve")
    assert cve["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "svc-a/package.json"
