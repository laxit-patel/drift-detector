"""CycloneDX BOM and SARIF report formats.

Split out of test_audit_render.py when that file was rewritten to test the ranked-actions
renderer (see docs/superpowers/plans/2026-07-16-action-model-reporting.md, Task 4) — these
tests are unrelated to audit_render.py and would otherwise have been deleted, leaving
build_bom with zero coverage anywhere in the suite.
"""
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


def test_cyclonedx_component_matches_vuln_ref_when_resolved_differs_from_floor():
    doc = {"repos": [{"path": "web", "sdks": [
        {"eco": "npm", "pkg": "axios", "ver": "^0.21.1", "resolved": "1.7.4", "versionSource": "lockfile"}]}]}
    findings = [{"repo": "web", "kind": "cve", "ref": "npm/axios", "version": "1.7.4",
                 "id": "GHSA-x", "cve": "CVE-1", "fixed": "1.9", "status": "DEPRECATED",
                 "severity": "HIGH", "detail": "x", "source_url": "u", "tier": 1, "recommendation": "up"}]
    bom = build_bom(doc, findings, "2026-07-15")
    comp_purls = {c["purl"] for c in bom["components"] if "purl" in c}
    vuln_ref = bom["vulnerabilities"][0]["affects"][0]["ref"]
    assert vuln_ref == "pkg:npm/axios@1.7.4"          # resolved version, not the 0.21.1 floor
    assert vuln_ref in comp_purls                     # component exists -> no dangling reference


def test_sarif_shape_and_levels():
    sarif = build_sarif(_DOC, _AUDIT["findings"])
    assert sarif["version"] == "2.1.0"
    results = sarif["runs"][0]["results"]
    assert all(r["level"] == "error" for r in results)      # both DEPRECATED -> error
    cve = next(r for r in results if r["ruleId"] == "cve")
    assert cve["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "svc-a/package.json"
