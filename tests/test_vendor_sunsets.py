from agent.lib import vendor_sunsets as vs
from agent.audit import audit_inventory
from agent.lib.sarif import build_sarif


_NOOP = {"osv_query": lambda *a, **k: [], "eol_check": lambda *a, **k: None,
         "http": lambda *a, **k: {}}


def test_unquoted_date_coerced_to_str_stays_json_serializable(tmp_path):
    import json
    p = tmp_path / "s.yaml"
    p.write_text("- { vendor: Amazon SP-API, version: v0, retires: 2026-09-30, source: u }\n")  # unquoted!
    loaded = vs.load_sunsets(str(p))
    assert isinstance(loaded[0]["retires"], str) and loaded[0]["retires"] == "2026-09-30"
    out = audit_inventory(_doc("Amazon SP-API", "v0", ["a.js:1"]), "2026-07-15",
                          sunsets=loaded, **_NOOP)
    json.dumps(out)                                    # must not raise (was: date not serializable)


def test_version_less_entry_is_dropped(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("- { vendor: X, source: u }\n- { vendor: Y, version: v1, source: u }\n")
    loaded = vs.load_sunsets(str(p))
    assert [s["vendor"] for s in loaded] == ["Y"]      # X has no version -> dropped


def test_catalog_loads_and_status():
    cat = vs.load_sunsets()
    assert any(s["vendor"] == "Amazon MWS" for s in cat)          # seeded entry
    assert vs.status_for("2020-01-01", "2026-07-15", confirmed=True) == "DEPRECATED"
    assert vs.status_for("2027-01-01", "2026-07-15", confirmed=True) == "REVIEW"
    assert vs.status_for(None, "2026-07-15", confirmed=True) == "DEPRECATED"     # deprecated, no date
    assert vs.status_for("2020-01-01", "2026-07-15", confirmed=False) == "REVIEW"  # unconfirmed


def _doc(vendor, version, files):
    return {"repos": [{"path": "svc", "endpoints": [
        {"vendor": vendor, "version": version, "files": files}]}]}


def test_exact_version_match_future_is_review_with_filelines():
    sun = [{"vendor": "Amazon SP-API", "version": "v0", "retires": "2026-09-30",
            "replacement": "v2", "source": "https://amzn/x"}]
    out = audit_inventory(_doc("Amazon SP-API", "v0", ["orders/client.js:1", "sync.js:4"]),
                          "2026-07-15", sunsets=sun, **_NOOP)
    f = next(x for x in out["findings"] if x["kind"] == "sunset")
    assert f["status"] == "REVIEW" and f["ref"] == "Amazon SP-API"
    assert f["files"] == ["orders/client.js:1", "sync.js:4"]       # the code-level differentiator
    assert "migrate to v2 before 2026-09-30" in f["recommendation"]
    assert f["source_url"] == "https://amzn/x"


def test_whole_api_star_matches_any_version_and_past_is_deprecated():
    sun = [{"vendor": "Amazon MWS", "version": "*", "retires": "2024-01-01", "source": "u"}]
    out = audit_inventory(_doc("Amazon MWS", "?", ["mws.php:9"]), "2026-07-15", sunsets=sun, **_NOOP)
    f = next(x for x in out["findings"] if x["kind"] == "sunset")
    assert f["status"] == "DEPRECATED" and "mws.php:9" in f["files"]


def test_unknown_version_is_review_verify():
    sun = [{"vendor": "Shopify", "version": "2023-01", "retires": "2020-01-01", "source": "u"}]
    out = audit_inventory(_doc("Shopify", "?", ["oauth.ts:19"]), "2026-07-15", sunsets=sun, **_NOOP)
    f = next(x for x in out["findings"] if x["kind"] == "sunset")
    assert f["status"] == "REVIEW" and "verify" in f["detail"]      # can't confirm they're on 2023-01


def test_non_matching_version_not_flagged():
    sun = [{"vendor": "Amazon SP-API", "version": "v0", "retires": "2026-09-30", "source": "u"}]
    out = audit_inventory(_doc("Amazon SP-API", "v3", ["x.js:1"]), "2026-07-15", sunsets=sun, **_NOOP)
    assert not any(x["kind"] == "sunset" for x in out["findings"])  # they're on v3, not v0


def test_sunset_findings_get_precise_sarif_locations():
    sun = [{"vendor": "Amazon SP-API", "version": "v0", "retires": "2020-01-01", "source": "u"}]
    doc = _doc("Amazon SP-API", "v0", ["orders/client.js:17"])
    out = audit_inventory(doc, "2026-07-15", sunsets=sun, **_NOOP)
    sarif = build_sarif(doc, out["findings"])
    r = next(x for x in sarif["runs"][0]["results"] if x["ruleId"] == "sunset")
    loc = r["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "svc/orders/client.js"      # repo/path
    assert loc["region"]["startLine"] == 17                             # the :17 line
