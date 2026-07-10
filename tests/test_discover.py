# tests/test_discover.py
import json
from agent.config import GitLabConfig, ScanConfig, Config
from agent.lib.gitlab_read import GitLabClient, HttpResponse, GitLabForbidden
from agent import discover

def _cfg(**scan):
    return Config(kb_root="kb/", feeds=[], raw={},
                  gitlab=GitLabConfig("https://gl.test", "GITLAB_READ_TOKEN", ["clients"]),
                  scan=ScanConfig(**scan))

class FakeClient:
    """Stands in for GitLabClient: canned candidates + per-id commit results."""
    def __init__(self, candidates, commits, forbidden=()):
        self._cands = candidates
        self._commits = commits          # id -> committed_date or None
        self._forbidden = set(forbidden)
    def list_candidate_projects(self, since_iso):
        return self._cands
    def has_commit_since(self, pid, since_iso, ref=None):
        if pid in self._forbidden:
            raise GitLabForbidden(f"/projects/{pid}")
        return self._commits.get(pid)

def _proj(pid, path, branch="main"):
    return {"id": pid, "path_with_namespace": path, "default_branch": branch,
            "last_activity_at": "2026-07-01T00:00:00Z"}

def test_since_iso_math():
    assert discover.since_iso("2026-07-10", 90) == "2026-04-11"

def test_keeps_repos_with_real_commit():
    client = FakeClient([_proj(1, "clients/a"), _proj(2, "clients/b")],
                        {1: "2026-06-20T00:00:00Z", 2: None})   # 2 has no real in-window commit
    res = discover.discover(_cfg(), client, "2026-07-10")
    assert [r["path_with_namespace"] for r in res["active"]] == ["clients/a"]
    assert {"repo": "clients/b", "reason": "no_recent_commit"} in res["excluded"]
    assert res["active"][0]["scanned_ref"] == "main"
    assert res["namespacesCovered"] == ["clients"]

def test_always_include_overrides_no_commit():
    client = FakeClient([_proj(2, "clients/b")], {2: None})
    res = discover.discover(_cfg(always_include=["clients/b"]), client, "2026-07-10")
    assert res["active"][0]["reason"] == "always_include"

def test_deny_excludes():
    client = FakeClient([_proj(1, "internal/sandbox")], {1: "2026-06-01T00:00:00Z"})
    res = discover.discover(_cfg(deny=["internal/sandbox"]), client, "2026-07-10")
    assert res["active"] == []
    assert {"repo": "internal/sandbox", "reason": "deny"} in res["excluded"]

def test_forbidden_becomes_coverage_gap():
    client = FakeClient([_proj(7, "clients/secret")], {}, forbidden=[7])
    res = discover.discover(_cfg(), client, "2026-07-10")
    assert {"repo": "clients/secret", "reason": "forbidden"} in res["excluded"]

def test_branch_override_sets_scanned_ref():
    client = FakeClient([_proj(1, "clients/a")], {1: "2026-06-20T00:00:00Z"})
    res = discover.discover(_cfg(branch_overrides={"clients/a": "release"}), client, "2026-07-10")
    assert res["active"][0]["scanned_ref"] == "release"

def test_write_active_repos(tmp_path):
    out = tmp_path / "active-repos.json"
    discover.write_active_repos(str(out), {"active": [], "excluded": []})
    assert json.loads(out.read_text())["active"] == []
