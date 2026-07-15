import yaml

from agent.lib.vendor_rules import build_ruleset, write_ruleset, DEFAULT_LANGUAGES


def test_ruleset_is_one_broad_url_rule():
    rs = build_ruleset()
    assert len(rs["rules"]) == 1
    rule = rs["rules"][0]
    assert rule["id"] == "url-literal"
    assert rule["metadata"] == {"kind": "url"}
    assert rule["languages"] == DEFAULT_LANGUAGES
    # AST-aware string-literal match on http(s):// (skips comments), not a raw pattern-regex
    assert rule["pattern"] == r'"=~/https?:\/\//"'
    assert "pattern-regex" not in rule


def test_write_ruleset_is_valid_yaml(tmp_path):
    p = tmp_path / "rules.yaml"
    write_ruleset(None, str(p))
    loaded = yaml.safe_load(p.read_text())
    assert loaded["rules"][0]["id"] == "url-literal"
