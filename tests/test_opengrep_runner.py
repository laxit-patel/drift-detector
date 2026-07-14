import json
from agent.lib.opengrep import run_scan


_CANNED = json.dumps({
    "results": [
        {"check_id": "tmp.stripe-endpoint", "path": "src/pay.php",
         "start": {"line": 3, "col": 8}, "end": {"line": 3, "col": 40},
         "extra": {"metadata": {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"},
                   "severity": "INFO", "lines": "requires login"}},
    ],
    "errors": [{"message": "parse error", "path": "src/weird.php"}],
    "paths": {"scanned": ["src/pay.php", "src/weird.php"]},
})


def test_run_scan_parses_matches_from_metadata():
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return _CANNED

    res = run_scan("/repo", "/tmp/rules.yaml", engine="opengrep", run=fake_run)
    assert seen["args"] == ["opengrep", "--config", "/tmp/rules.yaml", "--json", "--quiet", "/repo"]
    m = res["matches"][0]
    assert m == {"checkId": "stripe-endpoint", "vendor": "Stripe", "techKey": "api:stripe",
                 "kind": "endpoint", "path": "src/pay.php", "line": 3}
    assert res["scanned"] == ["src/pay.php", "src/weird.php"]
    assert len(res["errors"]) == 1


def test_run_scan_blank_output_is_empty_not_crash():
    res = run_scan("/repo", "/r.yaml", run=lambda args: "")
    assert res == {"matches": [], "scanned": [], "errors": []}
