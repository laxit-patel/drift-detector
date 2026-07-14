from agent.lib import osv


_AXIOS_VULN = {
    "id": "GHSA-3g43-6gmg-66jw",
    "aliases": ["CVE-2026-44495"],
    "summary": "axios SSRF and credential leak",
    "database_specific": {"severity": "HIGH"},
    "affected": [{"ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.7.4"}]}]}],
    "references": [{"type": "ADVISORY", "url": "https://github.com/advisories/GHSA-3g43-6gmg-66jw"}],
}


def _fake_http(url, *, method="GET", body=None, timeout=20):
    assert method == "POST" and "osv.dev" in url
    if body["package"]["name"] == "axios":
        return {"vulns": [_AXIOS_VULN]}
    return {"vulns": []}


def test_query_package_normalizes_vuln():
    vulns = osv.query_package("npm", "axios", "0.21.1", http=_fake_http)
    assert len(vulns) == 1
    v = vulns[0]
    assert v["id"] == "GHSA-3g43-6gmg-66jw"
    assert v["cve"] == "CVE-2026-44495"           # picked from aliases
    assert v["severity"] == "HIGH"
    assert v["fixed"] == "1.7.4"
    assert v["url"].startswith("https://github.com/advisories/")


def test_query_package_skips_unsupported_ecosystem_and_missing_version():
    assert osv.query_package("go", "x", "1.0", http=_fake_http) == []
    assert osv.query_package("npm", "axios", None, http=_fake_http) == []


def test_query_all_dedupes_by_key():
    calls = {"n": 0}

    def counting(url, *, method="GET", body=None, timeout=20):
        calls["n"] += 1
        return {"vulns": []}

    pkgs = [("npm", "react", "19.0.0"), ("npm", "react", "19.0.0"), ("npm", "react-dom", "19.0.0")]
    result = osv.query_all(pkgs, http=counting)
    assert calls["n"] == 2                          # react queried once despite two occurrences
    assert set(result.keys()) == {("npm", "react", "19.0.0"), ("npm", "react-dom", "19.0.0")}
