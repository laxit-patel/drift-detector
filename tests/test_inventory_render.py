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
