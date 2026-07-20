"""Regressions from the deliberate self-audit (2026-07-20).

Every test here corresponds to a bug that was FOUND AND REPRODUCED in the shipped
tool. They share one theme: the scanner must never look more confident than its
evidence — neither by losing evidence silently, nor by claiming more than it saw.
"""
import tempfile
from pathlib import Path

from agent import absorb
from agent.lib import shapes
from agent.lib.endpoints import scan_endpoints
from agent.lib.engine import run_scan
from agent.lib.vendors import Vendor

_EBAY = Vendor("eBay", "api:ebay", ("ebay.com",), r"/(v[0-9]+)")
_STRIPE = Vendor("Stripe", "api:stripe", ("stripe.com",), r"/(v[0-9]+)")
_KINDS = {"php": ["sink", "path-assembly", "url"]}


def test_malformed_engine_output_is_an_error_not_a_clean_scan():
    """A crash mid-write or a stray warning line before the JSON must not read as
    'scanned, found nothing' — that is indistinguishable from a clean repo."""
    res = run_scan("/repo", "/nope.yaml", run=lambda a: "WARNING: oom\n{truncated")
    assert res["errors"], "a parse failure must surface, not vanish"
    assert "not valid JSON" in res["errors"][0]["message"]


def test_multiline_literal_is_read_from_matched_text_not_the_start_line(tmp_path):
    """A heredoc carries its URL past the node's first line; reading only that line
    lost it from endpoints AND residue."""
    (tmp_path / "h.php").write_text("x")
    out = scan_endpoints([{"kind": "url", "path": "h.php", "line": 2,
                           "text": "<<<EOT\nhttps://api.stripe.com/v1/charges\nEOT"}],
                         str(tmp_path), [_STRIPE])
    assert [e["domain"] for e in out["endpoints"]] == ["api.stripe.com"]


def test_a_repo_of_unmodeled_languages_cannot_report_known(tmp_path):
    """Kotlin/Rust/Swift are not in the extension map, so the census was empty and the
    coverage loop had nothing to iterate — reporting KNOWN for a repo we cannot read."""
    (tmp_path / "Main.kt").write_text('val u = "https://api.stripe.com/v1/x"')
    sh = shapes.build(str(tmp_path), "kt", [], {"pathLiterals": [], "sinks": []}, _KINDS)
    assert sh["verdict"] == "UNKNOWN" and shapes.UNMODELED_LANGUAGE in sh["reasons"]


def test_a_genuinely_empty_repo_is_still_known(tmp_path):
    """The fix must not turn 'nothing to miss' into a false alarm."""
    (tmp_path / "README.md").write_text("# docs")
    sh = shapes.build(str(tmp_path), "docs", [], {"pathLiterals": [], "sinks": []}, _KINDS)
    assert sh["verdict"] == "KNOWN" and sh["reasons"] == []


def test_orphan_operation_markers_become_residue_not_nothing(tmp_path):
    """With 2 classified vendors the attribution guard correctly declines — but the
    marker is still evidence of an API call and must not disappear."""
    (tmp_path / "cfg.php").write_text("$a='https://api.ebay.com'; $b='https://api.stripe.com';")
    out = scan_endpoints([{"kind": "url", "path": "cfg.php", "line": 1},
                          {"kind": "operation-marker", "path": "w.php", "line": 1,
                           "text": "'<GetWeatherRequest>'"}], str(tmp_path), [_EBAY, _STRIPE])
    assert not any(e.get("operation") for e in out["endpoints"])       # not attributed
    assert out["residue"]["operations"] == [{"operation": "GetWeather", "loc": "w.php:1"}]


def test_inferred_attribution_is_labelled_distinctly_from_observed(tmp_path):
    """Single-vendor attribution is a guess about the REPO, not evidence from the LINE.
    A reader must be able to tell which is which."""
    (tmp_path / "cfg.php").write_text("$h='https://api.ebay.com';")
    (tmp_path / "op.php").write_text("x")
    out = scan_endpoints([{"kind": "url", "path": "cfg.php", "line": 1},
                          {"kind": "operation-marker", "path": "op.php", "line": 1,
                           "text": "'<GetOrdersRequest>'"}], str(tmp_path), [_EBAY])
    by = {e.get("operation") or e["domain"]: e["attribution"] for e in out["endpoints"]}
    assert by["api.ebay.com"] == "observed"      # the host was read at that line
    assert by["GetOrders"] == "inferred"         # the vendor was assumed from the repo


def test_gate_rejects_a_proposal_that_attributes_beyond_its_claim():
    """An over-broad pattern sweeps up call-sites nobody reviewed. Every attributed
    site must be named in the claim."""
    before = {"endpoints": [{"vendor": "Amazon SP-API", "files": ["real.php:1"]}],
              "residue": {"pathLiterals": [{"loc": "a.php:7"}, {"loc": "b.php:3"}]}}
    after = {"endpoints": [{"vendor": "Amazon SP-API",
                            "files": ["real.php:1", "a.php:7", "b.php:3"]}],
             "residue": {"pathLiterals": []}}
    problems = absorb.verify_against_repo("/r", [{"id": "x"}], ["a.php:7"],
                                          scan=lambda i: after if i else before)
    assert any("did not claim" in p and "b.php:3" in p for p in problems)


def test_attestation_cannot_bleed_between_two_repos_of_the_same_name(tmp_path):
    """`svc` is a common basename; two unrelated repos with identical residue shared an
    attestation key, so reviewing one silently cleared the other."""
    residue = {"pathLiterals": [{"sample": "/v2/checkout", "loc": "gw.php:3"}], "sinks": []}
    fp = shapes.residue_fingerprint(residue)
    shapes.attest(str(tmp_path), "svc", fp, resolved_by="A", date="2026-07-20",
                  repo_abs="/orgA/svc")
    at = shapes.load_attestations(str(tmp_path))
    assert shapes.is_attested(at, "svc", fp, "/orgA/svc")          # the reviewed one
    assert not shapes.is_attested(at, "svc", fp, "/orgB/svc")      # never reviewed


def test_grade_cannot_contradict_the_verdict():
    """A Go-only repo produces no residue, so the grade said HIGH while the verdict
    said UNKNOWN(no-egress-signal), in the same document."""
    from agent.inventory_scan import _coverage_grade
    assert _coverage_grade(attributed=0, unattributed_paths=0, sinks=0,
                           verdict="UNKNOWN") == "PARTIAL"
    assert _coverage_grade(attributed=5, unattributed_paths=0, sinks=0,
                           verdict="KNOWN") == "HIGH"
