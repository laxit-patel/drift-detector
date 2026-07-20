import json

import yaml

from agent.lib.engine import run_scan
from tests import astgrep_fake


def _rules(tmp_path):
    """A real ast-grep rule file — run_scan recovers metadata from it, not from output."""
    p = tmp_path / "rules.yaml"
    p.write_text(yaml.safe_dump(
        {"id": "stripe-endpoint@php", "language": "php",
         "metadata": {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"},
         "rule": {"kind": "string", "regex": "stripe"}}))
    return p


def test_run_scan_invokes_ast_grep_and_recovers_metadata(tmp_path):
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return astgrep_fake.canned(astgrep_fake.hit("stripe-endpoint", "src/pay.php", 3))

    rules = _rules(tmp_path)
    res = run_scan("/repo", str(rules), engine="ast-grep", run=fake_run)
    assert seen["args"] == ["ast-grep", "scan", "-r", str(rules), "--json=compact", "/repo"]
    # metadata comes from the rule file; the @lang suffix is stripped; line is 1-indexed
    assert res["matches"][0] == {"checkId": "stripe-endpoint", "vendor": "Stripe",
                                 "techKey": "api:stripe", "kind": "endpoint",
                                 "path": "src/pay.php", "line": 3}


def test_line_numbers_are_shifted_from_ast_greps_zero_index(tmp_path):
    raw = json.dumps([{"ruleId": "stripe-endpoint@php", "file": "a.php",
                       "range": {"start": {"line": 0}}}])          # first line of the file
    res = run_scan("/repo", str(_rules(tmp_path)), run=lambda a: raw)
    assert res["matches"][0]["line"] == 1                          # not 0


def test_unknown_rule_id_yields_empty_metadata_not_a_crash(tmp_path):
    raw = astgrep_fake.canned(astgrep_fake.hit("never-declared", "a.php", 2))
    res = run_scan("/repo", str(_rules(tmp_path)), run=lambda a: raw)
    m = res["matches"][0]
    assert m["checkId"] == "never-declared" and m["kind"] == "" and m["vendor"] == ""


def test_run_scan_blank_output_is_empty_not_crash(tmp_path):
    res = run_scan("/repo", str(_rules(tmp_path)), run=lambda args: "")
    assert res == {"matches": [], "scanned": [], "errors": []}


def test_missing_rule_file_degrades_to_empty_metadata(tmp_path):
    raw = astgrep_fake.canned(astgrep_fake.hit("stripe-endpoint", "a.php", 1))
    res = run_scan("/repo", str(tmp_path / "nope.yaml"), run=lambda a: raw)
    assert res["matches"][0]["kind"] == ""                         # no crash, just unclassified
