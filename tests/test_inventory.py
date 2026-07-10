import json
from agent import inventory
from agent.lib.gitlab_read import GitLabForbidden

PATTERNS = [{"techKey": "api:amazon-sp-api", "query": "sellingpartnerapi", "label": "SP-API"}]

class FakeClient:
    def __init__(self, trees, files, hits=None, tree_error=None):
        self._trees = trees          # id -> [paths]
        self._files = files          # (id, path) -> content or None
        self._hits = hits or {}      # query -> blobs
        self._tree_error = tree_error
    def get_tree(self, pid, ref):
        if self._tree_error:
            raise self._tree_error
        return self._trees.get(pid, [])
    def get_raw_file(self, pid, path, ref):
        return self._files.get((pid, path))
    def search_blobs(self, pid, query):
        return self._hits.get(query, [])

def _entry(pid, path, ref="main"):
    return {"id": pid, "path_with_namespace": path, "scanned_ref": ref}

def test_inventory_repo_parses_manifest_and_presence():
    client = FakeClient(
        trees={1: ["package.json", "README.md"]},
        files={(1, "package.json"): '{"dependencies":{"stripe":"12.0.0"}}'},
        hits={"sellingpartnerapi": [{"path": "src/A.php"}]},
    )
    res = inventory.inventory_repo(client, _entry(1, "clients/a"), PATTERNS)
    assert any(r.tech_key == "lib:npm/stripe" for r in res["records"])
    assert any(u.tech_key == "api:amazon-sp-api" for u in res["usedTechs"])
    assert res["notes"]["noManifest"] is False

def test_inventory_repo_no_manifests_flagged():
    client = FakeClient(trees={1: ["README.md", "LICENSE"]}, files={})
    res = inventory.inventory_repo(client, _entry(1, "clients/a"), PATTERNS)
    assert res["records"] == [] and res["notes"]["noManifest"] is True

def test_inventory_repo_unparsable_manifest_flagged():
    client = FakeClient(trees={1: ["package.json"]}, files={(1, "package.json"): "{ broken"})
    res = inventory.inventory_repo(client, _entry(1, "clients/a"), PATTERNS)
    assert res["records"] == []
    assert res["notes"]["unparsed"] and "package.json" in res["notes"]["unparsed"][0]["path"]

def test_inventory_repo_tree_forbidden_is_coverage_gap():
    client = FakeClient(trees={}, files={}, tree_error=GitLabForbidden("/projects/1"))
    res = inventory.inventory_repo(client, _entry(1, "clients/secret"), PATTERNS)
    assert res["notes"]["repoError"] is not None and res["records"] == []

def test_build_inventory_aggregates_and_covers(tmp_path):
    client = FakeClient(
        trees={1: ["package.json"], 2: ["README.md"]},
        files={(1, "package.json"): '{"dependencies":{"stripe":"12.0.0"}}'},
    )
    active = {"active": [_entry(1, "clients/a"), _entry(2, "clients/b")]}
    inv = inventory.build_inventory(client, active, PATTERNS, "2026-07-12")
    assert inv["coverage"]["reposScanned"] == 2
    assert any(r["tech_key"] == "lib:npm/stripe" for r in inv["records"])
    assert {"repo": "clients/b", "reason": "no manifests detected"} in inv["coverage"]["reposNoManifests"]
    out = tmp_path / "inventory.json"
    inventory.write_inventory(str(out), inv)
    assert json.loads(out.read_text())["coverage"]["reposScanned"] == 2
