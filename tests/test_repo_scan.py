import json
from pathlib import Path
from agent.lib.vendors import Vendor
from agent.lib.repo_scan import scan_repo


def _w(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


_VENDORS = [Vendor("Stripe", "api:stripe", ("api.stripe.com",), r'/(v\d+)')]


def _fake_opengrep(canned):
    return lambda args: canned


def test_scan_repo_assembles_manifests_and_endpoints(tmp_path):
    _w(tmp_path, "composer.json", '{"require": {"php": "^8.2", "laravel/framework": "^12.0"}}')
    _w(tmp_path, "pay.php", '$u = "https://api.stripe.com/v1/charges";\n')
    canned = json.dumps({"results": [
        {"check_id": "x.stripe-endpoint", "path": "pay.php", "start": {"line": 1},
         "extra": {"metadata": {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"}}}],
        "errors": [], "paths": {"scanned": ["pay.php"]}})
    git = lambda args: {"rev-parse HEAD": "sha1", "rev-parse --abbrev-ref HEAD": "main",
                        "log -1 --format=%cI": "2026-07-10"}[" ".join(args[2:])]

    record, note = scan_repo(str(tmp_path), "acme/web", 1, _VENDORS, "/rules.yaml",
                             engine="semgrep", run=_fake_opengrep(canned), git=git)
    assert record["id"] == 1 and record["path"] == "acme/web" and record["head_sha"] == "sha1"
    assert record["runtimes"]["php"]["range"] == "^8.2"
    assert "laravel/framework" in record["frameworks"]
    assert record["endpoints"][0]["techKey"] == "api:stripe" and record["endpoints"][0]["version"] == "v1"
    assert note["opengrepErrors"] == []


def test_scan_repo_drops_empty_domain_endpoints(tmp_path):
    _w(tmp_path, "x.php", 'nothing matches a known domain here\n')
    canned = json.dumps({"results": [
        {"check_id": "x.stripe-endpoint", "path": "x.php", "start": {"line": 1},
         "extra": {"metadata": {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"}}}],
        "errors": [], "paths": {"scanned": ["x.php"]}})
    record, _ = scan_repo(str(tmp_path), "r", 1, _VENDORS, "/r.yaml", engine="semgrep",
                          run=_fake_opengrep(canned), git=lambda a: "")
    assert record["endpoints"] == []                           # domain unresolved -> dropped
