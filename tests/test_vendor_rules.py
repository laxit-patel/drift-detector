import yaml

from agent.lib.vendors import Vendor
from agent.lib.vendor_rules import build_ruleset, write_ruleset, DEFAULT_LANGUAGES

_VS = [Vendor("Stripe", "api:stripe", ("stripe.com",), r"/(v\d+)"),
       Vendor("Mailgun", "api:mailgun", ("mailgun.net", "mailgun.com"), r"/(v\d+)")]


def test_ruleset_has_broad_url_rule_plus_one_per_vendor():
    rs = build_ruleset(_VS)
    rules = rs["rules"]
    assert len(rules) == 1 + len(_VS)                       # broad URL rule + per-vendor
    url = next(r for r in rules if r["id"] == "url-literal")
    assert url["metadata"] == {"kind": "url"} and url["pattern"] == r'"=~/https?:\/\//"'
    mg = next(r for r in rules if r["id"] == "mailgun-endpoint")
    assert mg["metadata"] == {"vendor": "Mailgun", "techKey": "api:mailgun", "kind": "endpoint"}
    assert all(p["pattern"].startswith('"=~/') for p in mg["pattern-either"])   # comment-safe literals
    assert url["languages"] == DEFAULT_LANGUAGES


def test_build_ruleset_none_is_just_the_url_rule():
    assert [r["id"] for r in build_ruleset()["rules"]] == ["url-literal"]


def test_write_ruleset_is_valid_yaml(tmp_path):
    p = tmp_path / "rules.yaml"
    write_ruleset(_VS, str(p))
    loaded = yaml.safe_load(p.read_text())
    assert loaded["rules"][0]["id"] == "url-literal" and len(loaded["rules"]) == 3
