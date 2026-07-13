import pytest
import requests
from agent.lib import github_provider
from agent.lib.github_provider import GitHubProvider, GitHubAuthError, GitHubUnreachable, GitHubError
from agent.lib.gitlab_read import HttpResponse

class FakeReq:
    def __init__(self, script): self.script = script; self.calls = []
    def __call__(self, method, url, headers, params, timeout):
        self.calls.append((url, dict(params or {}), dict(headers)))
        item = self.script[url]
        resp = item.pop(0) if isinstance(item, list) else item
        if isinstance(resp, Exception): raise resp
        return resp

def _r(status, body="[]", headers=None): return HttpResponse(status, headers or {}, body)
def _p(script):
    fr = FakeReq(script); return GitHubProvider("acme", "tok", request=fr), fr

def test_auth_headers_sent():
    p, fr = _p({"https://api.github.com/x": _r(200, "{}")})
    p._get("/x")
    h = fr.calls[0][2]
    assert h["Authorization"] == "Bearer tok" and "github+json" in h["Accept"]
    assert h["X-GitHub-Api-Version"] == "2022-11-28"

def test_401_raises_auth():
    p, _ = _p({"https://api.github.com/x": _r(401)})
    with pytest.raises(GitHubAuthError): p._get("/x")

def test_connection_error_unreachable():
    p, _ = _p({"https://api.github.com/x": ConnectionError("no net")})
    with pytest.raises(GitHubUnreachable): p._get("/x")

def test_404_allowed_returns_response():
    p, _ = _p({"https://api.github.com/x": _r(404)})
    assert p._get("/x", allow_404=True).status == 404
    with pytest.raises(GitHubError):
        p._get("/x")            # 404 without allow_404 -> error

def test_paginated_follows_link_next():
    url = "https://api.github.com/repos"
    nxt = '<https://api.github.com/repos?page=2>; rel="next", <...>; rel="last"'
    p, fr = _p({url: [_r(200, "[1,2]", {"Link": nxt}),
                      "https://api.github.com/repos?page=2"]})
    # second call keyed by the ?page=2 url:
    fr.script["https://api.github.com/repos?page=2"] = _r(200, "[3]", {})
    got = p._get_paginated("/repos")
    assert got == [1, 2, 3]

def test_get_translates_requests_connection_error_to_unreachable():
    p, _ = _p({"https://api.github.com/x": requests.exceptions.ConnectionError("boom")})
    with pytest.raises(GitHubUnreachable):
        p._get("/x")

def test_paginated_respects_max_pages(monkeypatch):
    monkeypatch.setattr(github_provider, "_MAX_PAGES", 3)

    class InfiniteLinkReq:
        def __init__(self):
            self.calls = []

        def __call__(self, method, url, headers, params, timeout):
            self.calls.append(url)
            nxt_url = url + "&next=1" if "?" in url else url + "?next=1"
            nxt = f'<{nxt_url}>; rel="next"'
            return HttpResponse(200, {"Link": nxt}, "[1]")

    fr = InfiniteLinkReq()
    p = GitHubProvider("acme", "tok", request=fr)
    got = p._get_paginated("/repos")
    assert got == [1, 1, 1]
