# tests/test_discover.py
import json
import pytest
from agent.config import GitLabConfig, ScanConfig, Config
from agent.lib.gitlab_read import GitLabForbidden, GitLabError, GitLabUnreachable
from agent import discover

def _cfg(**scan):
    return Config(kb_root="kb/", feeds=[], raw={},
                  gitlab=GitLabConfig("https://gl.test", "GITLAB_READ_TOKEN", ["clients"]),
                  scan=ScanConfig(**scan))

class FakeClient:
    """Stands in for GitLabClient: canned candidates + per-id commit results."""
    def __init__(self, candidates, commits, forbidden=(), errors=None):
        self._cands = candidates
        self._commits = commits          # id -> committed_date or None
        self._forbidden = set(forbidden)
        self._errors = errors or {}      # id -> Exception instance to raise
    def list_candidate_projects(self, since_iso):
        return self._cands
    def has_commit_since(self, pid, since_iso, ref=None):
        if pid in self._errors:
            raise self._errors[pid]
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

def test_allow_restricts_to_allow_and_always():
    # allow set: only clients/a is allowed; clients/b is a real-commit repo but NOT in allow -> excluded.
    # clients/c is in always_include (and not in allow) -> still kept (allow ∪ always_include).
    client = FakeClient(
        [_proj(1, "clients/a"), _proj(2, "clients/b"), _proj(3, "clients/c")],
        {1: "2026-06-20T00:00:00Z", 2: "2026-06-20T00:00:00Z", 3: None},
    )
    res = discover.discover(_cfg(allow=["clients/a"], always_include=["clients/c"]), client, "2026-07-10")
    paths = {r["path_with_namespace"] for r in res["active"]}
    assert paths == {"clients/a", "clients/c"}
    assert {"repo": "clients/b", "reason": "not_in_allow"} in res["excluded"]

def test_max_repos_caps_and_excludes():
    client = FakeClient(
        [_proj(1, "clients/a"), _proj(2, "clients/b")],
        {1: "2026-06-20T00:00:00Z", 2: "2026-06-20T00:00:00Z"},
    )
    res = discover.discover(_cfg(max_repos=1), client, "2026-07-10")
    assert len(res["active"]) == 1
    assert any(e["reason"] == "max_repos_cap" for e in res["excluded"])

def test_probe_http_error_becomes_coverage_gap():
    client = FakeClient(
        [_proj(1, "clients/a"), _proj(5, "clients/broken")],
        {1: "2026-06-20T00:00:00Z"},
        errors={5: GitLabError("404 on /projects/5/repository/commits")},
    )
    res = discover.discover(_cfg(), client, "2026-07-10")
    assert [r["path_with_namespace"] for r in res["active"]] == ["clients/a"]
    assert {"repo": "clients/broken", "reason": "probe_error"} in res["excluded"]

def test_unreachable_during_probe_is_fatal():
    client = FakeClient(
        [_proj(1, "clients/a")],
        {},
        errors={1: GitLabUnreachable("dropped")},
    )
    with pytest.raises(GitLabUnreachable):
        discover.discover(_cfg(), client, "2026-07-10")
