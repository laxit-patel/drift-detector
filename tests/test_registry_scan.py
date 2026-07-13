import json
from pathlib import Path

from agent import registry_scan
from agent.lib import kb_store

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text())


def test_scan_inventory_packages_checks_lib_techkeys_only(tmp_path):
    root = str(tmp_path / "kb")
    inventory = {
        "records": [
            {"repo": "g/r", "tech_key": "lib:npm/request", "kind": "library"},
            {"repo": "g/r", "tech_key": "runtime:php", "kind": "runtime"},
        ]
    }

    def fetch_json(url):
        return _load("npm_deprecated.json")

    checked = registry_scan.scan_inventory_packages(
        inventory, root, fetch_json=fetch_json, now="2026-07-13"
    )

    assert checked == ["lib:npm/request"]
    entries = kb_store.load_entries(root, "lib:npm/request")
    assert len(entries) == 1
    assert entries[0].changeType == "deprecation"


def test_scan_inventory_packages_dedupes_techkeys(tmp_path):
    root = str(tmp_path / "kb")
    inventory = {
        "records": [
            {"repo": "g/r1", "tech_key": "lib:npm/request", "kind": "library"},
            {"repo": "g/r2", "tech_key": "lib:npm/request", "kind": "library"},
        ]
    }
    calls = []

    def fetch_json(url):
        calls.append(url)
        return _load("npm_deprecated.json")

    checked = registry_scan.scan_inventory_packages(
        inventory, root, fetch_json=fetch_json, now="2026-07-13"
    )
    assert checked == ["lib:npm/request"]
    assert len(calls) == 1


def test_scan_inventory_packages_no_hits_writes_nothing(tmp_path):
    root = str(tmp_path / "kb")
    inventory = {"records": [{"repo": "g/r", "tech_key": "lib:npm/express", "kind": "library"}]}

    def fetch_json(url):
        return {"name": "express", "versions": {}}

    checked = registry_scan.scan_inventory_packages(
        inventory, root, fetch_json=fetch_json, now="2026-07-13"
    )
    assert checked == ["lib:npm/express"]
    assert kb_store.load_entries(root, "lib:npm/express") == []
