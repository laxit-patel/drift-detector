"""The dashboard renders ACTIONS + endpoints into one self-contained HTML file.
Pure Python; string/JSON assertions only — no browser, no network."""
import json
import re

from agent.lib.dashboard_render import render_dashboard


def _cve(repo="r", ref="npm/axios", version="0.21.1", fixed="1.16.0", severity="HIGH",
         status="DEPRECATED", first_seen="2026-07-15", **kw):
    return {"repo": repo, "ref": ref, "kind": "cve", "version": version, "fixed": fixed,
            "severity": severity, "status": status, "first_seen": first_seen,
            "id": kw.get("id", "CVE-x"), "cve": kw.get("cve", "CVE-x"),
            "detail": kw.get("detail", "summary text"), "recommendation": f"upgrade to >= {fixed}",
            "source_url": kw.get("source_url", "https://osv.dev/x"), "tier": 1}


def _audit(findings):
    # audit WITHOUT a precomputed actions key -> exercises the build_actions fallback
    return {"generated": "2026-07-15", "findings": findings,
            "counts": {"DEPRECATED": sum(1 for f in findings if f["status"] == "DEPRECATED"),
                       "REVIEW": sum(1 for f in findings if f["status"] == "REVIEW"),
                       "reposAffected": len({f["repo"] for f in findings})},
            "coverage": {"notes": ["note one"]}}


def _inv(endpoints=()):
    return {"generated": "2026-07-15",
            "repos": [{"path": "svc-a", "endpoints": list(endpoints)}]}


def _blob(html):
    m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>',
                  html, re.DOTALL)
    assert m, "drift-data blob not found"
    return json.loads(m.group(1).replace("\\u003c", "<"))


def test_is_a_self_contained_html_document():
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    assert html.startswith("<!doctype html>")
    assert html.count('<script id="drift-data"') == 1


def test_blob_action_count_matches_non_suppressed_actions():
    findings = [_cve(ref="npm/a"), _cve(ref="npm/b"), _cve(ref="npm/c")]
    data = _blob(render_dashboard(_inv(), _audit(findings), "2026-07-15"))
    assert len(data["actions"]) == 3


def test_every_command_appears_in_the_output():
    html = render_dashboard(_inv(), _audit([_cve(ref="python/torch", fixed="2.10.0")]),
                            "2026-07-15")
    assert "pip install 'torch>=2.10.0'" in html


def test_tile_counts_are_action_based_not_finding_based():
    # 3 critical FINDINGS on the same package = ONE critical ACTION. The tile must read 1.
    findings = [_cve(ref="npm/mongoose", severity="CRITICAL", id=f"CVE-{i}", cve=f"CVE-{i}")
                for i in range(3)]
    data = _blob(render_dashboard(_inv(), _audit(findings), "2026-07-15"))
    assert data["counts"]["critical"] == 1
    assert data["counts"]["fixes"] == 1


def test_tile_counts_apis_and_unknown_from_endpoints():
    eps = [{"domain": "api.ebay.com", "vendor": "eBay", "version": "v1", "classified": True,
            "file_count": 1, "files": ["a.php:1"]},
           {"domain": "api.stripe.com", "vendor": "Stripe", "version": "v1", "classified": True,
            "file_count": 1, "files": ["b.php:1"]},
           {"domain": "x.internal.io", "vendor": "Unknown", "version": None, "classified": False,
            "file_count": 1, "files": ["c.php:1"]}]
    data = _blob(render_dashboard(_inv(eps), _audit([_cve()]), "2026-07-15"))
    assert data["counts"]["apis"] == 2        # eBay + Stripe
    assert data["counts"]["unknown"] == 1


def test_eol_action_tile_and_no_command():
    eol = {"repo": "r", "ref": "php", "kind": "eol", "version": "^7.4", "fixed": "8.5.8",
           "severity": "EOL", "status": "DEPRECATED", "first_seen": "2026-07-15",
           "detail": "php 7.4 end-of-life 2022-11-28", "recommendation": "upgrade to 8.5.8",
           "source_url": "https://endoflife.date/php", "tier": 1}
    data = _blob(render_dashboard(_inv(), _audit([eol]), "2026-07-15"))
    assert data["counts"]["eol"] == 1
    a = next(a for a in data["actions"] if a["kind"] == "eol")
    assert a["command"] is None and a["fix_version"] == "8.5.8"


def test_sunset_action_files_render_and_tile_counts():
    sunset = {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "version": "v1",
              "severity": "SUNSET", "status": "DEPRECATED", "first_seen": "2026-07-15",
              "detail": "eBay v1 retires 2026-09-30", "date": "2026-09-30",
              "recommendation": "migrate to Sell API before 2026-09-30",
              "source_url": "https://developer.ebay.com/x", "tier": 1,
              "files": ["src/Ebay/x.php:111", "src/Ebay/y.php:540"]}
    html = render_dashboard(_inv(), _audit([sunset]), "2026-07-15")
    data = _blob(html)
    assert data["counts"]["sunsets"] == 1
    assert "src/Ebay/x.php:111" in html           # the moat payload is in the file


def test_zero_sunsets_when_no_sunset_actions():
    data = _blob(render_dashboard(_inv(), _audit([_cve()]), "2026-07-15"))
    assert data["counts"]["sunsets"] == 0


def test_output_is_byte_identical_across_calls():
    inv, audit = _inv(), _audit([_cve(ref="b/z"), _cve(ref="a/y", severity="CRITICAL")])
    assert render_dashboard(inv, audit, "2026-07-15") == render_dashboard(inv, audit, "2026-07-15")


def test_empty_audit_renders_valid_document_with_nothing_found():
    html = render_dashboard(_inv(), _audit([]), "2026-07-15")
    assert html.startswith("<!doctype html>")
    assert _blob(html)["actions"] == []
    assert "Nothing found" in html or "nothing found" in html.lower()


def test_xss_scan_strings_are_escaped_on_both_surfaces():
    evil = 'a<script>alert(1)</script>&"x'
    findings = [_cve(repo=evil)]
    html = render_dashboard(_inv(), _audit(findings), "2026-07-15")
    # 1) the raw payload never appears literally as HTML
    assert "<script>alert(1)</script>" not in html
    # 2) the JSON blob cannot be broken out of: no literal </script> inside it
    blob_raw = re.search(r'<script id="drift-data"[^>]*>(.*?)</script>',
                         html, re.DOTALL).group(1)
    assert "</script>" not in blob_raw
    # 3) it still round-trips: the value is intact once parsed
    data = json.loads(blob_raw.replace("\\u003c", "<"))
    assert data["actions"][0]["repo"] == evil


def test_no_external_assets():
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    assert "<script src" not in html.lower()
    assert '<link rel="stylesheet"' not in html.lower()
    assert "@import" not in html.lower()
    assert '<img src="http' not in html.lower()
