"""The invariants must catch the two bugs that actually shipped.

Each test below RECONSTRUCTS a broken payload exactly as it was produced on 2026-07-20
and asserts the check fires. A guard that cannot be shown to catch its motivating bug is
decoration, so these are written as reproductions first and regressions second.
"""
import json

import pytest

from agent.lib import verify
from agent.lib.verify import Violation


def _sunset_finding(op, date, rec, files, domain=None):
    return {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "severity": "SUNSET",
            "status": "DEPRECATED", "operation": op, "domain": domain, "version": None,
            "date": date, "recommendation": rec, "files": files,
            "first_seen": "2026-07-20"}


TWELVE = [
    _sunset_finding("GetCategoryFeatures", "2026-06-04", "migrate to Metadata API",
                    ["src/Ebay/EbayCategoryFieldsFeature.php:72"]),
    _sunset_finding("GetCategories", "2026-04-15", "migrate to Taxonomy API",
                    ["src/Ebay/EbayCategoryFieldsFeature.php:18"]),
    _sunset_finding("AddDispute", "2023-01-27", "migrate to Post-Order API",
                    ["src/Ebay/EbayOrderCancel.php:17"]),
    _sunset_finding(None, "2022-04-30", "migrate to Sell Feed API",
                    ["src/Ebay/src/LMS/ServiceEndpointsAndTokens.php:9"],
                    domain="webservices.ebay.com"),
    _sunset_finding(None, "2022-04-30", "migrate to Sell Feed API",
                    ["src/Ebay/src/LMS/ServiceEndpointsAndTokens.php:12"],
                    domain="storage.ebay.com"),
]


# --------------------------------------------------------------------------- bug #1
def test_tile_count_catches_the_sunset_collapse():
    """SHIPPED BUG: build_actions grouped on (repo, ref), so five retirements with five
    dates became ONE action and the tile read `Sunsets 1`. Tile and table agreed with
    each other — both wrong — which is why nothing caught it. Recomputing from findings
    is the independent path that disagrees."""
    collapsed = {
        "counts": {"sunsets": 1, "eol": 0, "private": 0},
        "actions": [{"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "unit": None,
                     "recommendation": "migrate to Metadata API", "finding_count": 5}],
        "private": [],
    }
    with pytest.raises(Violation) as e:
        verify.check_tile_counts(collapsed, TWELVE)
    assert e.value.check == "sunset-grouping"
    assert "5 distinct" in str(e.value)


def test_tile_count_passes_when_grouped_per_operation():
    ok = {
        "counts": {"sunsets": 5, "eol": 0, "private": 0},
        "actions": [{"repo": "ebayapi", "ref": "eBay", "kind": "sunset",
                     "unit": verify.sunset_unit(f), "recommendation": f["recommendation"],
                     "finding_count": 1} for f in TWELVE],
        "private": [],
    }
    verify.check_tile_counts(ok, TWELVE)          # must not raise


def test_tile_disagreeing_with_its_own_table_is_caught():
    """The simpler half: the number on the tile vs the rows the filter yields."""
    bad = {"counts": {"sunsets": 9, "eol": 0, "private": 0},
           "actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "unit": "X",
                        "recommendation": "y", "finding_count": 1}],
           "private": []}
    with pytest.raises(Violation) as e:
        verify.check_tile_counts(bad, [])
    assert e.value.check == "tile-vs-table"


# --------------------------------------------------------------------------- bug #2
def test_projection_parity_catches_the_dropped_unit_field():
    """SHIPPED BUG: build_actions gained `unit`, but _action_view whitelists fields and
    dropped it, so twelve rows rendered as bare "eBay". The unit test passed because it
    asserted on build_actions output, one layer below what anybody reads."""
    action = {"repo": "ebayapi", "ref": "eBay", "kind": "sunset",
              "unit": "GetCategoryFeatures", "recommendation": "migrate", "fixes": []}
    projected = {"repo": "ebayapi", "ref": "eBay", "kind": "sunset",
                 "recommendation": "migrate"}          # `unit` silently absent
    with pytest.raises(Violation) as e:
        verify.check_projection_parity(action, projected)
    assert e.value.check == "projection-parity"
    assert "unit" in str(e.value)


def test_projection_parity_allows_declared_drops():
    """`fixes` is deliberately not projected (it is the raw finding list). Declaring it
    is what keeps the check honest rather than merely noisy."""
    action = {"repo": "r", "ref": "eBay", "kind": "sunset", "fixes": [1, 2, 3]}
    verify.check_projection_parity(action, {"repo": "r", "ref": "eBay", "kind": "sunset"})


def test_row_labels_must_be_distinct():
    """The reader-facing symptom of bug #2: four rows that look the same."""
    dupes = {"actions": [
        {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "unit": None,
         "recommendation": "migrate to Sell Feed API before 2022-04-30"},
        {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "unit": None,
         "recommendation": "migrate to Sell Feed API before 2022-04-30"},
    ]}
    with pytest.raises(Violation) as e:
        verify.check_row_labels_distinct(dupes)
    assert e.value.check == "row-identity"


def test_row_labels_distinct_once_the_host_is_carried():
    ok = {"actions": [
        {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "unit": "webservices.ebay.com",
         "recommendation": "migrate to Sell Feed API before 2022-04-30"},
        {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "unit": "storage.ebay.com",
         "recommendation": "migrate to Sell Feed API before 2022-04-30"},
    ]}
    verify.check_row_labels_distinct(ok)


# --------------------------------------------------------------------------- the rail
def test_accessor_coverage_catches_a_field_the_page_reads_but_nothing_emits():
    js = 'var label = a.ref + " " + a.unit; row(a.repo, a.missingField);'
    with pytest.raises(Violation) as e:
        verify.check_accessor_coverage(js, {"actions": {"ref", "unit", "repo"}})
    assert "missingField" in str(e.value)


def test_blob_parity_detects_a_page_carrying_different_data():
    html = '<script id="drift-data" type="application/json">{"counts":{"sunsets":1}}</script>'
    with pytest.raises(Violation) as e:
        verify.check_blob_matches_payload(html, json.dumps({"counts": {"sunsets": 12}}))
    assert e.value.check == "blob-parity"


def test_blob_parity_tolerates_escaping_and_indentation():
    """The embedded copy escapes `<` and dashboard.json is indented; only the DATA must
    match. Comparing bytes here would fail on a correct pair."""
    payload = {"note": "a <script> tag in scan data"}
    from agent.lib.dashboard_render import _blob
    html = f'<script id="drift-data" type="application/json">{_blob(payload)}</script>'
    verify.check_blob_matches_payload(html, json.dumps(payload, indent=2))


# ------------------------------------------------- wired to the REAL code, not fixtures
def _real_payload():
    from agent.lib.actions import build_actions
    from agent.lib.dashboard_render import build_payload
    actions = build_actions(TWELVE)
    audit = {"generated": "2026-07-20", "findings": TWELVE, "actions": actions,
             "counts": {"reposAffected": 1}}
    inventory = {"repos": [{"path": "ebayapi", "endpoints": [], "sdks": []}],
                 "scope": {"reposScanned": 2}, "coverage": {}}
    return build_payload(inventory, audit), actions


def test_live_projection_parity_over_real_build_actions():
    """The guard that matters: run the REAL action dicts through the REAL projection.
    If someone adds a field to build_actions and forgets the projection, this fails —
    which is precisely what shipped as twelve rows labelled "eBay"."""
    payload, actions = _real_payload()
    assert actions and payload["actions"]
    for action, projected in zip(actions, payload["actions"]):
        verify.check_projection_parity(action, projected)


def test_live_accessor_coverage_over_the_real_client_js():
    """Every a.field / e.field the shipped page reads must exist in the real payload."""
    from agent.lib.dashboard_render import _CLIENT_JS
    payload, _ = _real_payload()
    verify.check_accessor_coverage(_CLIENT_JS, {
        "actions": set(payload["actions"][0]),
        "endpoints": set(payload["endpoints"][0]) if payload.get("endpoints") else None,
        "private": set(payload["private"][0]) if payload.get("private") else None,
    })


def test_live_invariants_hold_on_the_real_payload():
    payload, _ = _real_payload()
    assert verify.verify_payload(payload, TWELVE) == []


def test_live_blob_parity_between_html_and_payload():
    """dashboard.html embeds exactly the payload dashboard.json holds."""
    from agent.lib.dashboard_render import render_payload
    payload, _ = _real_payload()
    verify.check_blob_matches_payload(render_payload(payload, "2026-07-20"),
                                      json.dumps(payload))


# ------------------------------------------------------------------ the CLI entrypoint
def test_drift_verify_cli_passes_clean_and_fails_tampered(tmp_path, capsys):
    """`drift-scan verify` is the claim the assistant is allowed to make. It must exit 0
    on a consistent report and 3 on an inconsistent one — never the reverse."""
    from agent.cli import main
    from agent.lib.dashboard_render import render_payload
    payload, _ = _real_payload()
    (tmp_path / "dashboard.json").write_text(json.dumps(payload, indent=2))
    (tmp_path / "audit.json").write_text(json.dumps({"findings": TWELVE}))
    (tmp_path / "dashboard.html").write_text(render_payload(payload, "2026-07-20"))

    assert main(["verify", "--state", str(tmp_path)]) == 0

    # tamper exactly as bug #1 presented: the tile disagrees with its table
    bad = json.loads((tmp_path / "dashboard.json").read_text())
    bad["counts"]["sunsets"] = 1
    (tmp_path / "dashboard.json").write_text(json.dumps(bad, indent=2))
    assert main(["verify", "--state", str(tmp_path)]) == 3
    assert "tile-vs-table" in capsys.readouterr().out


def test_drift_verify_reports_nothing_to_verify_rather_than_passing(tmp_path):
    """An absent report must never read as a clean one — the same 'cannot check is not
    clean' rule the --fail-on-deprecated gate already follows (exit 4)."""
    from agent.cli import main
    assert main(["verify", "--state", str(tmp_path)]) == 4


# ------------------------------------------------------- the UNAUDITED tile obeys the rail
def test_unaudited_tile_must_match_its_own_panel():
    """The new tile is held to the same rule as every other: the number equals the rows.
    Added WITH the feature, not after a user reports four identical rows."""
    bad = {"counts": {"sunsets": 0, "eol": 0, "private": 0, "unaudited": 3},
           "actions": [], "private": [],
           "catalog": [{"vendor": "eBay", "verdict": "UNAUDITED", "callSites": 162},
                       {"vendor": "Amazon SP-API", "verdict": "CURRENT", "callSites": 272}]}
    with pytest.raises(Violation) as e:
        verify.check_tile_counts(bad, [])
    assert e.value.check == "tile-vs-table"
    assert "unaudited" in str(e.value)


def test_unaudited_tile_excludes_current_vendors():
    """A vendor whose page WAS checked is not a gap and must not inflate the tile."""
    ok = {"counts": {"sunsets": 0, "eol": 0, "private": 0, "unaudited": 1},
          "actions": [], "private": [],
          "catalog": [{"vendor": "eBay", "verdict": "UNAUDITED", "callSites": 162},
                      {"vendor": "Amazon SP-API", "verdict": "CURRENT", "callSites": 272}]}
    verify.check_tile_counts(ok, [])


def test_catalog_accessor_coverage_over_the_real_client_js():
    """renderCatalog reads r.vendor / r.verdict / r.callSites — all must exist."""
    from agent.lib.dashboard_render import _CLIENT_JS
    verify.check_accessor_coverage(_CLIENT_JS, {"catalog": {
        "vendor", "verdict", "callSites", "catalogEntries", "checked", "reasons", "source"}})
