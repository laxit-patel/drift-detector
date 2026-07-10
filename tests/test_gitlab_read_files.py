# tests/test_gitlab_read_files.py
from agent.lib.gitlab_read import GitLabClient, HttpResponse

class Fake:
    def __init__(self, routes):   # routes: (substring-in-url) -> HttpResponse
        self.routes = routes; self.seen = []
    def __call__(self, method, url, headers, params, timeout):
        self.seen.append((url, dict(params or {})))
        for k, r in self.routes.items():
            if k in url:
                return r
        return HttpResponse(404, {}, "null")

def _c(routes):
    return GitLabClient("https://gl.test", "tok", request=Fake(routes))

def test_get_tree_returns_blob_paths_only():
    body = '[{"path":"package.json","type":"blob"},{"path":"src","type":"tree"},{"path":"src/a.js","type":"blob"}]'
    c = _c({"/repository/tree": HttpResponse(200, {"X-Next-Page": ""}, body)})
    assert c.get_tree(1, "main") == ["package.json", "src/a.js"]

def test_get_raw_file_returns_text():
    c = _c({"/repository/files/": HttpResponse(200, {}, '{"name":"x"}')})
    assert c.get_raw_file(1, "package.json", "main") == '{"name":"x"}'

def test_get_raw_file_url_encodes_path():
    f = Fake({"/repository/files/": HttpResponse(200, {}, "data")})
    GitLabClient("https://gl.test", "tok", request=f).get_raw_file(1, "src/app/config.php", "main")
    assert "src%2Fapp%2Fconfig.php" in f.seen[0][0]

def test_get_raw_file_404_returns_none():
    c = _c({"/repository/files/": HttpResponse(404, {}, "null")})
    assert c.get_raw_file(1, "missing.json", "main") is None

def test_search_blobs_returns_matches():
    c = _c({"/search": HttpResponse(200, {"X-Next-Page": ""},
            '[{"path":"src/Amazon.php","data":"sellingpartnerapi"}]')})
    got = c.search_blobs(1, "sellingpartnerapi")
    assert got[0]["path"] == "src/Amazon.php"
