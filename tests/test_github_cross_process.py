"""Regression tests for the discover->inventory cross-process integration.

`inventory` runs in a SEPARATE process from `discover`, so a fresh
GitHubProvider has an empty _by_id (list_candidate_projects never ran here).
The read methods must still resolve id->full_name on their own, and their
errors must be catchable by the same GitLabError family that downstream
(inventory/presence/discover) already catches.
"""
from agent.lib.github_provider import (
    GitHubProvider, GitHubError, GitHubUnreachable, GitHubAuthError,
)
from agent.lib.gitlab_read import HttpResponse, GitLabError, GitLabUnreachable, GitLabAuthError


class Fake:
    def __init__(self, routes): self.routes = routes; self.seen = []
    def __call__(self, method, url, headers, params, timeout):
        self.seen.append(url)
        for k, r in self.routes.items():
            if k in url:
                return r
        return HttpResponse(404, {}, "null")


def test_get_tree_resolves_id_without_list_candidate_projects():
    # Fresh provider (empty _by_id) — the exact `inventory`-process scenario.
    fk = Fake({
        "/repositories/11": HttpResponse(200, {}, '{"full_name": "acme/web"}'),
        "/git/trees/main": HttpResponse(200, {}, '{"tree": [{"path": "composer.json", "type": "blob"}]}'),
    })
    p = GitHubProvider("acme", "tok", request=fk)
    assert p.get_tree(11, "main") == ["composer.json"]
    # id->full_name got resolved via the by-id endpoint and cached
    assert p._by_id[11] == "acme/web"
    assert any("/repositories/11" in u for u in fk.seen)


def test_lazy_resolve_cached_second_call_hits_once():
    fk = Fake({
        "/repositories/11": HttpResponse(200, {}, '{"full_name": "acme/web"}'),
        "/git/trees/main": HttpResponse(200, {}, '{"tree": []}'),
    })
    p = GitHubProvider("acme", "tok", request=fk)
    p.get_tree(11, "main")
    p.get_tree(11, "main")
    assert sum(1 for u in fk.seen if "/repositories/11" in u) == 1  # cached, not re-fetched


def test_get_raw_file_swallows_unresolvable_id():
    # by-id lookup 404s -> GitHubError -> get_raw_file swallows to None (best-effort)
    p = GitHubProvider("acme", "tok", request=Fake({}))  # everything 404s
    assert p.get_raw_file(999, "composer.json", "main") is None


def test_github_exceptions_are_caught_by_gitlab_family():
    # Downstream catches the GitLabError family; GitHub errors must be instances of it
    # so a raising provider degrades to a coverage gap instead of crashing the scan.
    assert issubclass(GitHubError, GitLabError)
    assert issubclass(GitHubUnreachable, GitLabUnreachable)
    assert issubclass(GitHubAuthError, GitLabAuthError)


def test_unreachable_raised_as_gitlab_unreachable():
    def boom(*a, **k):
        raise ConnectionError("network down")
    p = GitHubProvider("acme", "tok", request=boom)
    try:
        p.has_commit_since(11, "2026-01-01T00:00:00Z")
        assert False, "expected raise"
    except GitLabUnreachable:
        pass  # caught by the family discover/cli already handle
