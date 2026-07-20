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


# --- ast-grep dialect ---------------------------------------------------------

def test_astgrep_ruleset_uses_verified_string_kinds_per_language():
    from agent.lib.vendor_rules import build_astgrep_ruleset, AST_STRING_KINDS
    docs = build_astgrep_ruleset(vendors=[])
    by_id = {d["id"]: d for d in docs}
    # PHP double-quoted strings are `encapsed_string`; missing it silently loses call-sites
    php = by_id["url-literal@php"]
    kinds = [c["kind"] for c in php["rule"]["any"]]
    assert kinds == AST_STRING_KINDS["php"] == ["string", "encapsed_string", "heredoc"]
    # Go has no bare `string` kind at all
    assert AST_STRING_KINDS["go"] == ["interpreted_string_literal", "raw_string_literal"]
    # inner-content kinds must NOT appear anywhere (they double-count)
    all_kinds = {c.get("kind") for d in docs for c in d["rule"].get("any", []) if "kind" in c}
    assert not (all_kinds & {"string_fragment", "string_content", "heredoc_body"})


def test_astgrep_rule_ids_carry_language_and_metadata():
    from agent.lib.vendor_rules import build_astgrep_ruleset
    from agent.lib.vendors import Vendor
    v = Vendor("Stripe", "api:stripe", ("stripe.com",), r"/(v[0-9]+)")
    docs = build_astgrep_ruleset([v], languages=["php"])
    ids = {d["id"] for d in docs}
    assert "stripe-endpoint@php" in ids and "path-assembly@php" in ids
    sd = next(d for d in docs if d["id"] == "stripe-endpoint@php")
    assert sd["metadata"] == {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"}


def test_write_ruleset_dialect_follows_the_engine(tmp_path):
    from agent.lib.vendor_rules import write_ruleset
    import yaml
    p = tmp_path / "r.yaml"
    write_ruleset([], str(p), engine="/usr/bin/semgrep")
    assert "rules" in yaml.safe_load(p.read_text())            # semgrep: single doc, rules[]
    write_ruleset([], str(p), engine="/venv/bin/ast-grep")
    docs = [d for d in yaml.safe_load_all(p.read_text()) if d]  # ast-grep: multi-doc
    assert docs and all("language" in d and "rule" in d for d in docs)
