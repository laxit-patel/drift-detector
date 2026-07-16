import pytest
from agent.eval import corpus


def _write(tmp_path, text):
    p = tmp_path / "corpus.yaml"
    p.write_text(text)
    return str(p)


_VALID = """
- repo: davidtsadler/ebay-sdk-php
  url: https://github.com/davidtsadler/ebay-sdk-php.git
  sha: "1234567890abcdef1234567890abcdef12345678"
  license: MIT
  category: ebay
  expect: { vendor: eBay, sdk_keywords: [ebay], sunset_host: svcs.ebay.com }
  known_gaps: [sdk-only-no-callsite]
  holdout: false
  fetched_at: "2026-07-16"
"""


def test_loads_a_valid_entry(tmp_path):
    entries = corpus.load_corpus(_write(tmp_path, _VALID))
    assert len(entries) == 1
    e = entries[0]
    assert e["repo"] == "davidtsadler/ebay-sdk-php"
    assert e["expect"]["vendor"] == "eBay"
    assert isinstance(e["sha"], str) and len(e["sha"]) == 40


def test_unquoted_sha_like_value_is_coerced_to_str(tmp_path):
    # an all-digit sha would parse as int without the quotes; loader must coerce
    text = _VALID.replace('"1234567890abcdef1234567890abcdef12345678"',
                          "1234567890123456789012345678901234567890")
    e = corpus.load_corpus(_write(tmp_path, text))[0]
    assert isinstance(e["sha"], str)


def test_rejects_missing_sha(tmp_path):
    bad = _VALID.replace('  sha: "1234567890abcdef1234567890abcdef12345678"\n', "")
    with pytest.raises(ValueError, match="sha"):
        corpus.load_corpus(_write(tmp_path, bad))


def test_rejects_missing_vendor(tmp_path):
    bad = _VALID.replace("vendor: eBay, ", "")
    with pytest.raises(ValueError, match="vendor"):
        corpus.load_corpus(_write(tmp_path, bad))


def test_rejects_non_40hex_sha(tmp_path):
    bad = _VALID.replace('"1234567890abcdef1234567890abcdef12345678"', '"deadbeef"')
    with pytest.raises(ValueError, match="40"):
        corpus.load_corpus(_write(tmp_path, bad))


def test_rejects_known_gap_outside_taxonomy(tmp_path):
    bad = _VALID.replace("[sdk-only-no-callsite]", "[not-a-real-mode]")
    with pytest.raises(ValueError, match="taxonomy|not-a-real-mode"):
        corpus.load_corpus(_write(tmp_path, bad))


def test_taxonomy_is_the_documented_closed_set():
    assert "sdk-only-no-callsite" in corpus.TAXONOMY
    assert "uncatalogued-vendor" in corpus.TAXONOMY
    assert len(corpus.TAXONOMY) == 9
