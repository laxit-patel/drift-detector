from agent.lib.inventory_render import render_inventory_md


_DOC = {
    "generated": "2026-07-14",
    "scope": {"reposScanned": 2},
    "repos": [
        {"path": "acme/orders", "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^1.6"}],
         "endpoints": [{"vendor": "Amazon SP-API", "version": "v0"}]},
        {"path": "acme/web", "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^1.6"}],
         "endpoints": [{"vendor": "Amazon SP-API", "version": "v0"},
                       {"vendor": "Stripe", "version": "v1"}],
         "frameworks": {"laravel/framework": {"ver": "^12.0"}}},
    ],
    "unique_api_versions": [{"vendor": "Amazon SP-API", "version": "v0"}, {"vendor": "Stripe", "version": "v1"}],
    "runtimes": {"php": ["^8.2", "^8.3"]},
    "unique_packages": [{"eco": "npm", "pkg": "axios"}],
    "coverage": {"reposScanned": 2, "reposErrored": []},
}


def test_render_has_key_sections_and_counts():
    md = render_inventory_md(_DOC)
    assert "# " in md and "Scope" in md
    assert "Third-party APIs" in md
    assert "Amazon SP-API" in md and "| 2 |" in md          # SP-API used by 2 repos
    assert "Stripe" in md                                    # used by 1 repo
    assert "Runtimes" in md and "php" in md
    assert "axios" in md                                     # SDKs section
    assert "Coverage" in md


def test_render_empty_doc_does_not_crash():
    md = render_inventory_md({"repos": [], "coverage": {}})
    assert isinstance(md, str) and "Third-party APIs" in md


def test_render_includes_frameworks_section():
    md = render_inventory_md(_DOC)
    assert "Frameworks" in md and "laravel/framework" in md


def test_render_has_summary_and_per_repo_with_file_line():
    doc = {**_DOC, "repos": [
        {"path": "acme/orders", "ref": "main", "head_sha": "abcdef1234567",
         "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^1.6"}],
         "endpoints": [{"vendor": "Amazon SP-API", "version": "v0",
                        "domain": "sellingpartnerapi-na.amazon.com",
                        "files": ["src/orders.js:17", "src/sync.js:4"]}]},
    ]}
    md = render_inventory_md(doc)
    assert "1 repos ·" in md and "third-party APIs" in md    # one-line summary
    assert "## Per repo" in md and "### acme/orders" in md
    assert "src/orders.js:17" in md                          # code-level file:line surfaced


def test_render_leads_with_drift_when_diff_present():
    diff = {"reposAdded": ["acme/new"], "reposRemoved": [],
            "changes": [{"repo": "acme/web",
                         "endpointsAdded": [], "endpointsRemoved": [],
                         "sdksAdded": [], "sdksRemoved": [],
                         "sdkVersionChanges": [{"eco": "npm", "pkg": "axios", "from": "^1.5", "to": "^1.6"}],
                         "runtimeChanges": []}]}
    md = render_inventory_md(_DOC, diff)
    assert "Drift since last scan" in md and "Repos added" in md
    assert "axios: ^1.5 → ^1.6" in md
    # drift appears before the APIs table
    assert md.index("Drift since last scan") < md.index("Third-party APIs")


def test_render_no_drift_section_without_changes():
    md = render_inventory_md(_DOC, {"reposAdded": [], "reposRemoved": [], "changes": []})
    assert "Drift since last scan" not in md


def test_unknown_external_endpoints_surfaced_and_excluded_from_apis():
    doc = {"generated": "2026-07-15", "scope": {}, "coverage": {}, "repos": [
        {"path": "a", "endpoints": [
            {"vendor": "Stripe", "version": "v1", "domain": "api.stripe.com"},
            {"vendor": "Unknown", "domain": "api.feedonomics.com", "version": "v2"}]}]}
    md = render_inventory_md(doc)
    assert "Unknown external endpoints" in md and "api.feedonomics.com" in md
    apis = md.split("Third-party APIs")[1].split("## ")[0]
    assert "Stripe" in apis and "Unknown" not in apis        # Unknown gets its own section, not the API table


def test_coverage_shows_private_sources_loudly():
    doc = {"generated": "2026-07-15", "scope": {}, "repos": [], "coverage": {
        "reposScanned": 3, "reposErrored": [],
        "repos": {"discovered": 3, "scanned": 3, "errored": 0},
        "endpoints": {"known": 5, "unknownExternal": 2},
        "packages": {"total": 40, "lockfileResolved": 30, "floorOnly": 10},
        "privateSources": [{"repo": "EbayApi", "packages": [{"pkg": "tops/ebay-wrapper"}],
                            "repositories": ["https://git.topsdemo.in/x.git"]}]}}
    md = render_inventory_md(doc)
    assert "5 known-vendor · 2 unknown external" in md
    assert "30 lockfile-exact · 10 declared-floor-only" in md
    assert "private package sources the scan can't see" in md
    assert "tops/ebay-wrapper" in md and "git.topsdemo.in" in md


def test_per_repo_no_longer_flags_sdk_undercount():
    # Spec B's blanket "N SDK package(s) ... may not be listed as endpoints" per-repo caveat
    # is replaced by the coverage-grade line (see below) — merely having SDKs no longer warns.
    doc = {"generated": "2026-07-17", "repos": [
        {"path": "with-sdk", "sdks": [{"eco": "composer", "pkg": "dts/ebay-sdk-php", "ver": "^18"}],
         "endpoints": [], "runtimes": {}, "frameworks": {}},
        {"path": "no-sdk", "sdks": [], "endpoints": [
            {"vendor": "eBay", "version": "v1", "files": ["a.php:1"], "domain": "svcs.ebay.com"}],
         "runtimes": {}, "frameworks": {}},
    ]}
    md = render_inventory_md(doc)
    assert "may not be listed as endpoints" not in md
    assert "SDK-mediated" not in md
    with_block = md.split("### with-sdk")[1].split("###")[0]
    assert "⚠" not in with_block


def test_per_repo_shows_coverage_grade_line():
    # a repo carrying a coverage grade + residue counts renders the grade, not the old SDK line
    doc = {"generated": "2026-07-17", "repos": [
        {"path": "amazonspapi", "sdks": [{"eco": "composer", "pkg": "dts/foo", "ver": "^1"}],
         "endpoints": [], "runtimes": {}, "frameworks": {}},
    ], "coverage": {"residue": {"byRepo": [
        {"repo": "amazonspapi", "attributed": 0, "unattributedPaths": 262,
         "unresolvedSinks": 3, "grade": "LOW"}]}}}
    md = render_inventory_md(doc)
    block = md.split("### amazonspapi")[1].split("###")[0]
    assert "LOW" in block and "262" in block
    assert "may not be listed as endpoints" not in block


def test_per_repo_high_grade_shows_no_warning():
    doc = {"generated": "2026-07-17", "repos": [
        {"path": "clean-repo", "sdks": [], "endpoints": [], "runtimes": {}, "frameworks": {}},
    ], "coverage": {"residue": {"byRepo": [
        {"repo": "clean-repo", "attributed": 10, "unattributedPaths": 0,
         "unresolvedSinks": 0, "grade": "HIGH"}]}}}
    md = render_inventory_md(doc)
    block = md.split("### clean-repo")[1].split("## Coverage")[0]
    assert "⚠ **Coverage:" not in block
