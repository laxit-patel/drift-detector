from agent.lib.gitlab_read import GitLabClient, HttpResponse

class Fake:
    def __init__(self, routes):  # routes: dict[path_prefix] -> HttpResponse
        self.routes = routes
        self.seen = []
    def __call__(self, method, url, headers, params, timeout):
        self.seen.append((url, dict(params or {})))
        for key, resp in self.routes.items():
            if key in url:
                return resp
        return HttpResponse(404, {}, "null")

def _c(routes):
    return GitLabClient("https://gl.test", "tok", request=Fake(routes))

def test_list_candidate_projects_passes_filters():
    f = Fake({"/projects": HttpResponse(200, {"X-Next-Page": ""},
              '[{"id":1,"path_with_namespace":"clients/a","default_branch":"main","last_activity_at":"2026-07-01T0:0:0Z"}]')})
    c = GitLabClient("https://gl.test", "tok", request=f)
    got = c.list_candidate_projects("2026-04-11")
    assert got[0]["id"] == 1
    assert f.seen[0][1]["last_activity_after"] == "2026-04-11"
    assert f.seen[0][1]["archived"] == "false"
    assert f.seen[0][1]["simple"] == "true"

def test_has_commit_since_returns_committed_date():
    c = _c({"/repository/commits": HttpResponse(200, {}, '[{"committed_date":"2026-06-20T10:00:00Z"}]')})
    assert c.has_commit_since(1, "2026-04-11") == "2026-06-20T10:00:00Z"

def test_has_commit_since_none_when_empty():
    c = _c({"/repository/commits": HttpResponse(200, {}, "[]")})
    assert c.has_commit_since(1, "2026-04-11") is None

def test_has_commit_since_uses_all_true_and_since():
    f = Fake({"/repository/commits": HttpResponse(200, {}, "[]")})
    GitLabClient("https://gl.test", "tok", request=f).has_commit_since(9, "2026-04-11", ref="release")
    _, params = f.seen[0]
    assert params["all"] == "true" and params["since"] == "2026-04-11" and params["ref_name"] == "release"
