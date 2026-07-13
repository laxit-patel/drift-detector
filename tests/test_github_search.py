from agent.lib.github_provider import GitHubProvider, GitHubError
from agent.lib.gitlab_read import HttpResponse

class Fake:
    def __init__(self, resp): self.resp = resp; self.seen = []
    def __call__(self, method, url, headers, params, timeout):
        self.seen.append((url, dict(params or {})))
        if isinstance(self.resp, Exception): raise self.resp
        return self.resp

def _p(resp):
    p = GitHubProvider("acme", "tok", request=Fake(resp)); p._by_id[11] = "acme/web"; return p

def test_search_returns_paths():
    p = _p(HttpResponse(200, {}, '{"items": [{"path": "src/Amazon.php"}, {"path": "b.php"}]}'))
    hits = p.search_blobs(11, "sellingpartnerapi")
    assert [h["path"] for h in hits] == ["src/Amazon.php", "b.php"]

def test_search_scopes_to_repo():
    fk = Fake(HttpResponse(200, {}, '{"items": []}')); p = GitHubProvider("acme", "tok", request=fk); p._by_id[11] = "acme/web"
    p.search_blobs(11, "stripe")
    assert "repo:acme/web" in fk.seen[0][1]["q"] and "stripe" in fk.seen[0][1]["q"]

def test_search_error_returns_empty():
    p = _p(HttpResponse(403, {"X-RateLimit-Remaining": "0"}, ""))   # rate limited
    assert p.search_blobs(11, "x") == []
