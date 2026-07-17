"""The dashboard renders ACTIONS + endpoints into one self-contained HTML file.
Pure Python; string/JSON assertions only — no browser, no network."""
import json
import re
import shutil
import subprocess
import textwrap

import pytest

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


def test_severity_attribute_uses_attribute_safe_escaping():
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    js = html.split("<script>")[-1]
    assert "escA" in js                                  # an attribute-safe escaper exists
    assert 'sev-\'+escA(a.worst)' in js                   # and it guards the severity class attribute
    assert 'class="sev-\'+esc(a.worst)' not in js         # the unsafe text-escaper must not be reinstated there


def test_suppressed_findings_are_excluded_from_actions():
    normal = _cve(ref="npm/keep")
    muted = _cve(ref="npm/muted")
    muted["suppressed"] = True
    data = _blob(render_dashboard(_inv(), _audit([normal, muted]), "2026-07-15"))
    refs = {a["ref"] for a in data["actions"]}
    assert "npm/keep" in refs
    assert "npm/muted" not in refs


def test_no_external_assets():
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    assert "<script src" not in html.lower()
    assert '<link rel="stylesheet"' not in html.lower()
    assert "@import" not in html.lower()
    assert '<img src="http' not in html.lower()


def test_client_js_wires_every_interaction():
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    js = html.split('<script>')[-1]
    # hooks that genuinely live in the JS (data-filter is an HTML attribute, read as dataset.filter)
    for hook in ("addEventListener", "dataset.filter", "localStorage",
                 "aria-pressed", "theme-toggle", "search"):
        assert hook in js, hook
    # the accordion + copy affordances exist
    assert "navigator.clipboard" in js or "copy" in js.lower()


def test_projection_carries_every_field_the_ui_reads():
    sunset = {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "version": "v1",
              "severity": "SUNSET", "status": "DEPRECATED", "first_seen": "2026-07-15",
              "detail": "d", "date": "2026-09-30", "recommendation": "migrate before 2026-09-30",
              "source_url": "https://x", "tier": 1, "files": ["src/Ebay/x.php:111"]}
    data = _blob(render_dashboard(_inv(), _audit([sunset, _cve()]), "2026-07-15"))
    a = data["actions"][0]
    for k in ("repo", "ref", "kind", "current_version", "fix_version", "command",
              "recommendation", "worst", "status", "finding_count", "cves", "sources", "files"):
        assert k in a, k
    # endpoint rows carry what the endpoint view needs
    eps_inv = _inv([{"domain": "api.ebay.com", "vendor": "eBay", "version": "v1",
                     "classified": True, "file_count": 1, "files": ["a.php:1"]}])
    ep = _blob(render_dashboard(eps_inv, _audit([_cve()]), "2026-07-15"))["endpoints"][0]
    for k in ("repo", "domain", "vendor", "version", "classified", "file_count", "files"):
        assert k in ep, k


def test_apis_filter_selects_classified_endpoints_only():
    # Regression guard: the "APIs used" tile's count is distinct classified vendors, and its
    # click-through filter must show ONLY classified endpoints — otherwise it and "Unknown
    # hosts" don't cleanly partition the endpoint rows (apis would fall through to "all").
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    js = html.split("<script>")[-1]
    assert 'f==="apis"' in js
    assert "return e.classified" in js


def test_source_href_uses_attribute_safe_escaping():
    # Regression guard for the Task 1 attribute-XSS fix: actionDetail() builds an <a href="...">
    # from scan-controlled source URLs. That interpolation MUST go through escA (which escapes
    # quotes), not esc (text-only escaping) — otherwise a malicious source_url containing a
    # `"` can break out of the href attribute. Reverting escA(s) -> esc(s) must fail this test.
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    js = html.split("<script>")[-1]
    assert "escA" in js
    assert '<a href="\'+escA(s)' in js
    assert '<a href="\'+esc(s)' not in js
    assert '<a href="\'+esc(u)' not in js


def test_source_links_are_scheme_restricted_to_http():
    # Regression guard for the javascript:-URL residual-XSS fix: escA escapes HTML
    # metacharacters but does NOT validate the URL scheme, so a compromised/malicious
    # upstream advisory feed (OSV / endoflife / vendor-sunset registry) could supply a
    # source_url of `javascript:...` that renders as a clickable, code-executing link.
    # A safeUrl() scheme allow-list must gate every href built from a.sources.
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    js = html.split("<script>")[-1]
    assert "safeUrl" in js
    assert "https?:" in js or "http" in js            # an http(s) allow-list is present
    # and the sources renderer routes the URL through the guard before ever building an href
    assert "safeUrl(u)" in js
    # a non-http(s) URL must NOT be handed to escA and turned into a clickable href at all —
    # it must fall back to plain escaped text instead (the ternary's else-branch is esc(u))
    assert '<a href="\'+escA(s)' in js
    assert ": esc(u)" in js


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed (optional JS smoke)")
def test_node_smoke_safe_url_rejects_javascript_scheme(tmp_path):
    # Actually execute the real safeUrl() implementation extracted from the emitted JS (not
    # a reimplementation) and prove it rejects a javascript: source_url while accepting
    # http(s) ones — the guard the sources renderer routes every href through.
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    m = re.search(r"function safeUrl\(u\)\{[^}]*\}", js)
    assert m, "safeUrl() not found in emitted JS"
    harness = tmp_path / "run_safeurl.js"
    harness.write_text(textwrap.dedent(f"""
        {m.group(0)}
        console.log(JSON.stringify({{
            javascript: safeUrl("javascript:alert(1)"),
            data: safeUrl("data:text/html,<script>alert(1)</script>"),
            bare: safeUrl("evil.example/x"),
            https: safeUrl("https://osv.dev/x"),
            http: safeUrl("http://endoflife.date/php")
        }}));
    """))
    out = subprocess.run(["node", str(harness)], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip())
    assert result["javascript"] is None
    assert result["data"] is None
    assert result["bare"] is None
    assert result["https"] == "https://osv.dev/x"
    assert result["http"] == "http://endoflife.date/php"


def test_permalink_github_blob_shape():
    from agent.lib.dashboard_render import _permalink
    assert _permalink("https://github.com/o/r", "SHA", "src/x.php:37") == \
        "https://github.com/o/r/blob/SHA/src/x.php#L37"


def test_permalink_gitlab_dash_blob_shape():
    from agent.lib.dashboard_render import _permalink
    assert _permalink("https://gitlab.com/o/r", "SHA", "src/x.php:37") == \
        "https://gitlab.com/o/r/-/blob/SHA/src/x.php#L37"


def test_permalink_self_hosted_gitlab_via_env(monkeypatch):
    from agent.lib.dashboard_render import _permalink
    monkeypatch.setenv("DRIFT_GITLAB_HOSTS", "git.topsdemo.in")
    assert _permalink("https://git.topsdemo.in/rushikesh/ebayapi", "SHA", "src/config/ebay.php:39") == \
        "https://git.topsdemo.in/rushikesh/ebayapi/-/blob/SHA/src/config/ebay.php#L39"


def test_permalink_unknown_host_and_missing_bits_are_none(monkeypatch):
    from agent.lib.dashboard_render import _permalink
    monkeypatch.delenv("DRIFT_GITLAB_HOSTS", raising=False)
    assert _permalink("https://bitbucket.org/o/r", "SHA", "src/x.php:1") is None   # unknown host
    assert _permalink(None, "SHA", "src/x.php:1") is None                          # no remote
    assert _permalink("https://github.com/o/r", None, "src/x.php:1") is None       # no sha


def test_permalink_missing_line_omits_anchor():
    from agent.lib.dashboard_render import _permalink
    assert _permalink("https://github.com/o/r", "SHA", "src/x.php") == \
        "https://github.com/o/r/blob/SHA/src/x.php"


def test_projection_rewrites_files_to_loc_href_dicts():
    # a sunset action whose repo has a github remote -> each file becomes {loc, href}
    from agent.lib.dashboard_render import _build_projection
    inv = {"repos": [{"path": "r", "remote_url": "https://github.com/o/r", "head_sha": "SHA",
                      "endpoints": []}]}
    audit = {"actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "status": "DEPRECATED",
                          "worst": "SUNSET", "finding_count": 1, "files": ["src/x.php:37"],
                          "fixes": [], "sources": []}]}
    proj = _build_projection(inv, audit)
    f = proj["actions"][0]["files"][0]
    assert f == {"loc": "src/x.php:37", "href": "https://github.com/o/r/blob/SHA/src/x.php#L37"}


def test_projection_files_href_none_for_local_repo():
    from agent.lib.dashboard_render import _build_projection
    inv = {"repos": [{"path": "r", "remote_url": None, "head_sha": "SHA", "endpoints": []}]}
    audit = {"actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "status": "DEPRECATED",
                          "worst": "SUNSET", "finding_count": 1, "files": ["src/x.php:37"],
                          "fixes": [], "sources": []}]}
    f = _build_projection(inv, audit)["actions"][0]["files"][0]
    assert f == {"loc": "src/x.php:37", "href": None}


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed (optional JS smoke)")
def test_node_smoke_executes_client_js_and_renders_rows(tmp_path):
    # Actually run the embedded JS in a DOM-less shim to prove it parses the blob and
    # builds the right number of action rows. Skips cleanly when node is absent.
    html = render_dashboard(_inv(), _audit([_cve(ref="npm/a"), _cve(ref="npm/b")]), "2026-07-15")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    blob = re.search(r'<script id="drift-data"[^>]*>(.*?)</script>', html, re.DOTALL).group(1)
    harness = tmp_path / "run.js"
    harness.write_text(textwrap.dedent(f"""
        // minimal DOM shim: enough for the dashboard JS to render rows and count them.
        // body.children is a real array (pushed to on appendChild, cleared on innerHTML="")
        // because render() reads body.children.length to toggle the empty state.
        let rows = 0;
        function el(){{ let kids=[]; return {{
            _cls:"", set className(v){{this._cls=v}}, get className(){{return this._cls}},
            set innerHTML(v){{ if(v==="") kids=[]; }}, set textContent(v){{this._t=v}},
            get innerHTML(){{return this._t||""}},
            get children(){{ return kids; }},
            appendChild(c){{ kids.push(c); if(this._id==="tbody-marker") rows++; }}, addEventListener(){{}},
            querySelector(){{ let e=el(); e._id="tbody-marker"; return e; }},
            querySelectorAll(){{ return []; }}, style:{{}}, dataset:{{}}, hidden:false
        }} }};
        const blob = {json.dumps(blob)};
        global.navigator = {{ clipboard:{{ writeText(){{}} }} }};
        global.localStorage = {{ getItem(){{return null}}, setItem(){{}} }};
        global.document = {{
            getElementById(id){{ if(id==="drift-data") return {{textContent: blob.replace(/\\\\u003c/g,"<")}};
                                 let e=el(); return e; }},
            querySelector(){{ let e=el(); e._id="tbody-marker"; return e; }},
            querySelectorAll(){{ return []; }}, createElement(){{ return el(); }},
            documentElement:{{ setAttribute(){{}}, getAttribute(){{return "dark"}} }},
            addEventListener(){{}}
        }};
        {js}
        console.log(rows);
    """))
    out = subprocess.run(["node", str(harness)], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "2"      # two actions -> two rows rendered by the real JS


def _sunset_inv_audit(remote_url, files=("src/x.php:37", "src/y.php:39")):
    inv = {"repos": [{"path": "r", "remote_url": remote_url, "head_sha": "SHA", "endpoints": []}]}
    audit = {"generated": "2026-07-17", "coverage": {},
             "actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "status": "DEPRECATED",
                          "worst": "SUNSET", "finding_count": 1, "recommendation": "migrate",
                          "files": list(files), "fixes": [], "sources": []}]}
    return inv, audit


def test_call_sites_render_one_per_line_with_blob_link_for_remote():
    from agent.lib.dashboard_render import render_dashboard
    inv, audit = _sunset_inv_audit("https://github.com/o/r")
    js = render_dashboard(inv, audit, "2026-07-17").split("<script>")[-1]
    # the render emits an <a href> to the pinned blob and does NOT comma-join
    assert "/blob/SHA/src/x.php#L37" in render_dashboard(inv, audit, "2026-07-17")
    assert "'Used at: '+a.files.map(esc).join" not in js          # the old inline join is gone


def test_local_repo_call_site_is_text_plus_copy_no_href():
    from agent.lib.dashboard_render import render_dashboard
    inv, audit = _sunset_inv_audit(None)                          # local repo, no remote
    html_out = render_dashboard(inv, audit, "2026-07-17")
    js = html_out.split("<script>")[-1]
    assert "navigator.clipboard.writeText" in js                  # a copy affordance exists
    assert "f.href" in js and "f.loc" in js                       # renders the {loc,href} shape


def test_no_token_in_rendered_html_even_if_remote_had_one():
    # belt-and-suspenders: even though Task 1 strips at capture, assert nothing leaks here.
    from agent.lib.dashboard_render import render_dashboard
    inv, audit = _sunset_inv_audit("https://github.com/o/r")       # already stripped upstream
    out = render_dashboard(inv, audit, "2026-07-17")
    assert "glpat-" not in out and "@github.com" not in out


def test_call_site_loc_is_xss_escaped():
    from agent.lib.dashboard_render import render_dashboard
    inv, audit = _sunset_inv_audit(None, files=['a<script>alert(1)</script>:1'])
    out = render_dashboard(inv, audit, "2026-07-17")
    assert "<script>alert(1)</script>" not in out                 # not literal in the HTML
