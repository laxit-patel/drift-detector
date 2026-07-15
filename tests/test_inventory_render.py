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
