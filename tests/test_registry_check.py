import json
from pathlib import Path
from agent.lib.registry_check import check_package

FIX = Path(__file__).parent / "fixtures"

def _load(name):
    return json.loads((FIX / name).read_text())

def test_npm_deprecated_flagged():
    entries = check_package("lib:npm/request", fetch_json=lambda url: _load("npm_deprecated.json"), now="2026-07-13")
    assert len(entries) == 1
    e = entries[0]
    assert e.changeType == "deprecation" and e.techKey == "lib:npm/request"
    assert "deprecated" in e.summary.lower() and e.sourceUrl.startswith("https://registry.npmjs.org")

def test_npm_not_deprecated_returns_empty():
    entries = check_package("lib:npm/express", fetch_json=lambda url: {"name": "express", "versions": {}}, now="2026-07-13")
    assert entries == []

def test_packagist_abandoned_flagged():
    entries = check_package("lib:composer/foo/bar", fetch_json=lambda url: _load("packagist_abandoned.json"), now="2026-07-13")
    assert len(entries) == 1 and entries[0].techKey == "lib:composer/foo/bar"

def test_non_library_techkey_ignored():
    assert check_package("runtime:php", fetch_json=lambda url: {}, now="2026-07-13") == []
    assert check_package("api:stripe", fetch_json=lambda url: {}, now="2026-07-13") == []

def test_fetch_error_returns_empty():
    def boom(url): raise ConnectionError("down")
    assert check_package("lib:npm/x", fetch_json=boom, now="2026-07-13") == []
