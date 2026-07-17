import yaml

from agent.lib.vendor_rules import build_ruleset, write_ruleset, DEFAULT_LANGUAGES
from agent.lib.vendors import Vendor

_VS = [Vendor("Stripe", "api:stripe", ("stripe.com",), r"/(v\d+)"),
       Vendor("Mailgun", "api:mailgun", ("mailgun.net", "mailgun.com"), r"/(v\d+)")]


def _by_kind(ruleset):
    return {r["metadata"]["kind"]: r for r in ruleset["rules"] if "kind" in r.get("metadata", {})}


def test_ruleset_has_path_literal_sink_and_assembly_rules():
    rs = build_ruleset(vendors=[])
    kinds = _by_kind(rs)
    # path-literal: string-literal regex over all languages, matches a version segment
    assert "path-literal" in kinds
    pl = kinds["path-literal"]
    assert pl["languages"] == build_ruleset(vendors=[])["rules"][0]["languages"]  # same DEFAULT_LANGUAGES
    assert "v[0-9]" in pl["pattern"] and "[0-9]{4}-[0-9]{2}-[0-9]{2}" in pl["pattern"]
    # sink: PHP-only, curl_exec + CURLOPT_URL + Guzzle client
    assert "sink" in kinds
    sk = kinds["sink"]
    assert sk["languages"] == ["php"]
    pats = " ".join(p.get("pattern", "") for p in sk["pattern-either"])
    assert "curl_exec" in pats and "CURLOPT_URL" in pats and "GuzzleHttp\\Client" in pats
    # path-assembly: PHP-only, getHost() . $path
    assert "path-assembly" in kinds
    pa = kinds["path-assembly"]
    assert pa["languages"] == ["php"]
    assert "getHost()" in pa["pattern"]


def test_ruleset_has_broad_url_rule_plus_one_per_vendor():
    rs = build_ruleset(_VS)
    rules = rs["rules"]
    assert len(rules) == 1 + len(_VS) + 3                   # broad URL rule + per-vendor + 3 new rules
    url = next(r for r in rules if r["id"] == "url-literal")
    assert url["metadata"] == {"kind": "url"} and url["pattern"] == r'"=~/https?:\/\//"'
    mg = next(r for r in rules if r["id"] == "mailgun-endpoint")
    assert mg["metadata"] == {"vendor": "Mailgun", "techKey": "api:mailgun", "kind": "endpoint"}
    assert all(p["pattern"].startswith('"=~/') for p in mg["pattern-either"])   # comment-safe literals
    assert url["languages"] == DEFAULT_LANGUAGES


def test_build_ruleset_none_is_just_the_url_rule():
    assert [r["id"] for r in build_ruleset()["rules"]] == ["url-literal", "path-literal", "php-http-sink", "path-assembly"]


def test_write_ruleset_is_valid_yaml(tmp_path):
    p = tmp_path / "rules.yaml"
    write_ruleset(_VS, str(p))
    loaded = yaml.safe_load(p.read_text())
    assert loaded["rules"][0]["id"] == "url-literal" and len(loaded["rules"]) == 6
