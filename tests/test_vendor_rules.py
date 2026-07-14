import yaml
from agent.lib.vendors import Vendor
from agent.lib.vendor_rules import build_ruleset, write_ruleset, DEFAULT_LANGUAGES


_VS = [Vendor("Stripe", "api:stripe", ("api.stripe.com",), r"/(v\d+)"),
       Vendor("Slack", "api:slack", ("slack.com/api", "hooks.slack.com"), r"/(v\d+)")]


def test_build_ruleset_one_rule_per_vendor_with_metadata():
    rs = build_ruleset(_VS)
    rules = rs["rules"]
    assert len(rules) == 2
    stripe = next(r for r in rules if r["id"] == "stripe-endpoint")
    assert stripe["metadata"] == {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"}
    assert stripe["languages"] == DEFAULT_LANGUAGES


def test_rule_uses_comment_safe_literal_regex_pattern_per_domain():
    rs = build_ruleset(_VS)
    slack = next(r for r in rs["rules"] if r["id"] == "slack-endpoint")
    pats = [p["pattern"] for p in slack["pattern-either"]]
    # two domains -> two literal-regex patterns; dots escaped; NOT raw pattern-regex
    assert '"=~/slack\\.com/api/"' in pats or any("slack" in p and p.startswith('"=~/') for p in pats)
    assert len(pats) == 2
    assert all(p.startswith('"=~/') and p.endswith('/"') for p in pats)


def test_write_ruleset_is_valid_yaml(tmp_path):
    p = tmp_path / "rules.yaml"
    write_ruleset(_VS, str(p))
    loaded = yaml.safe_load(p.read_text())
    assert "rules" in loaded and len(loaded["rules"]) == 2
