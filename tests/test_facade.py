import json

from agent.lib import facade


_INV = {"repos": [
    {"path": "svc-a", "runtimes": {"php": {"range": "^7.4"}},
     "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^1.0"}],
     "endpoints": [{"vendor": "Shopify", "version": "?", "files": ["oauth.ts:19"]}]},
    {"path": "svc-b", "sdks": [], "endpoints": [
        {"vendor": "Amazon SP-API", "version": "v0", "files": ["client.js:1"]}]},
]}
_AUDIT = {"findings": [
    {"repo": "svc-a", "kind": "eol", "ref": "php", "version": "^7.4", "status": "DEPRECATED",
     "detail": "php 7.4 EOL", "source_url": "u", "recommendation": "8.3"},
    {"repo": "svc-b", "kind": "sunset", "ref": "Amazon SP-API", "version": "v0", "status": "REVIEW",
     "detail": "retires", "files": ["client.js:1"], "source_url": "u2"},
    {"repo": "svc-a", "kind": "cve", "ref": "npm/x", "status": "REVIEW", "suppressed": True},
]}


def test_load_state(tmp_path):
    (tmp_path / "inventory.json").write_text(json.dumps(_INV))
    (tmp_path / "audit.json").write_text(json.dumps(_AUDIT))
    inv, audit = facade.load_state(str(tmp_path))
    assert len(inv["repos"]) == 2 and len(audit["findings"]) == 3
    assert facade.load_state(str(tmp_path / "missing")) == ({}, {})     # tolerant


def test_list_repos_and_query_integrations():
    repos = facade.list_repos(_INV)
    assert repos[0] == {"repo": "svc-a", "apis": ["Shopify"], "runtimes": {"php": "^7.4"}, "packages": 1}
    shop = facade.query_integrations(_INV, vendor="Shopify")
    assert shop == [{"repo": "svc-a", "vendor": "Shopify", "version": "?", "files": ["oauth.ts:19"]}]
    assert facade.query_integrations(_INV, repo="svc-b")[0]["vendor"] == "Amazon SP-API"


def test_get_findings_filters_and_hides_suppressed():
    assert len(facade.get_findings(_AUDIT)) == 2                        # suppressed one hidden
    assert facade.get_findings(_AUDIT, repo="svc-a")[0]["ref"] == "php"
    dep = facade.get_findings(_AUDIT, status="deprecated")
    assert len(dep) == 1 and dep[0]["status"] == "DEPRECATED"


def test_check_dependency_live_shape():
    def fake_http(url, *, method="GET", body=None, timeout=20):
        return {"vulns": [{"id": "GHSA-1", "aliases": ["CVE-1"], "summary": "x",
                           "database_specific": {"severity": "HIGH"},
                           "affected": [{"package": {"ecosystem": "npm", "name": "axios"},
                                         "ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.7.4"}]}]}],
                           "references": [{"url": "u"}]}]}
    r = facade.check_dependency("npm", "axios", "0.21.1", http=fake_http)
    assert r["vulnerable"] is True and r["worst_severity"] == "HIGH"
    assert r["cves"] == ["CVE-1"] and "1.7.4" in r["recommendation"]

    r2 = facade.check_dependency("npm", "clean", "1.0", http=lambda *a, **k: {"vulns": []})
    assert r2["vulnerable"] is False and r2["recommendation"] == "no known advisories"


def test_check_runtime_live():
    def fake_http(url, *, method="GET", body=None, timeout=20):
        return [{"cycle": "7.4", "eol": "2022-11-28", "latest": "7.4.33"},
                {"cycle": "8.3", "eol": "2027-11-01", "latest": "8.3.10"}]
    r = facade.check_runtime("php", "7.4", "2026-07-15", http=fake_http)
    assert r["tracked"] and r["status"] == "DEPRECATED" and r["recommended"] == "8.3.10"
    assert facade.check_runtime("react", "19", "2026-07-15", http=lambda *a, **k: [])["tracked"] is False
