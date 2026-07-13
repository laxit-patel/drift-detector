from agent.lib.github_provider import GitHubProvider
from agent.lib.gitlab_read import HttpResponse

class Fake:
    def __init__(self, routes): self.routes = routes; self.seen = []
    def __call__(self, method, url, headers, params, timeout):
        self.seen.append((url, dict(headers)))
        for k, r in self.routes.items():
            if k in url: return r
        return HttpResponse(404, {}, "null")

def _p(routes):
    p = GitHubProvider("acme", "tok", request=Fake(routes))
    p._by_id[11] = "acme/web"
    return p

def test_get_tree_blobs_only():
    body = '{"tree": [{"path": "package.json", "type": "blob"}, {"path": "src", "type": "tree"}, {"path": "src/a.js", "type": "blob"}], "truncated": false}'
    p = _p({"/git/trees/main": HttpResponse(200, {}, body)})
    assert p.get_tree(11, "main") == ["package.json", "src/a.js"]

def test_get_raw_file_uses_raw_accept_and_returns_text():
    fk = Fake({"/contents/package.json": HttpResponse(200, {}, '{"name":"web"}')})
    p = GitHubProvider("acme", "tok", request=fk); p._by_id[11] = "acme/web"
    assert p.get_raw_file(11, "package.json", "main") == '{"name":"web"}'
    assert "raw" in fk.seen[0][1]["Accept"]              # raw media type requested

def test_get_raw_file_404_none():
    p = _p({"/contents/missing.json": HttpResponse(404, {}, "")})
    assert p.get_raw_file(11, "missing.json", "main") is None
