from agent.lib.github_provider import GitHubProvider
from agent.lib.gitlab_read import HttpResponse

class Fake:
    def __init__(self, routes): self.routes = routes; self.seen = []
    def __call__(self, method, url, headers, params, timeout):
        self.seen.append((url, dict(params or {})))
        for k, r in self.routes.items():
            if k in url: return r
        return HttpResponse(404, {}, "null")

def _p(routes): return GitHubProvider("acme", "tok", request=Fake(routes))

REPOS = ('[{"id": 11, "full_name": "acme/web", "default_branch": "main", "pushed_at": "2026-07-01T00:00:00Z", "archived": false},'
         ' {"id": 12, "full_name": "acme/old", "default_branch": "main", "pushed_at": "2026-06-01T00:00:00Z", "archived": true},'
         ' {"id": 13, "full_name": "someoneelse/x", "default_branch": "main", "pushed_at": "2026-06-01T00:00:00Z", "archived": false}]')

def test_list_repos_filters_owner_and_archived():
    p = _p({"/user/repos": HttpResponse(200, {}, REPOS)})
    got = p.list_candidate_projects("2026-04-14")
    paths = {r["path_with_namespace"] for r in got}
    assert paths == {"acme/web"}                        # archived + other-owner dropped
    assert got[0]["id"] == 11 and got[0]["default_branch"] == "main"
    assert got[0]["last_activity_at"].startswith("2026-07-01")
    assert p._by_id[11] == "acme/web"                   # id->full_name mapped

def test_has_commit_since():
    p = _p({"/user/repos": HttpResponse(200, {}, REPOS),
            "/repos/acme/web/commits": HttpResponse(200, {}, '[{"commit": {"committer": {"date": "2026-06-20T10:00:00Z"}}}]')})
    p.list_candidate_projects("2026-04-14")             # populate id map
    assert p.has_commit_since(11, "2026-04-14").startswith("2026-06-20")

def test_has_commit_since_none_when_empty():
    p = _p({"/user/repos": HttpResponse(200, {}, REPOS),
            "/repos/acme/web/commits": HttpResponse(200, {}, "[]")})
    p.list_candidate_projects("2026-04-14")
    assert p.has_commit_since(11, "2026-04-14") is None
