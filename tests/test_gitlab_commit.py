from agent.lib.gitlab_read import GitLabClient, HttpResponse

class FakePost:
    def __init__(self): self.calls = []
    def __call__(self, method, url, headers, params, timeout, body=None):
        self.calls.append((method, url, body))
        return HttpResponse(201, {}, '{"id":"abc123"}')

def test_create_commit_posts_actions():
    fp = FakePost()
    c = GitLabClient("https://gl.test", "wtok", request=fp)
    out = c.create_commit(9, "main", "msg", [{"action": "create", "file_path": "a.md", "content": "x"}])
    assert out["id"] == "abc123"
    method, url, body = fp.calls[0]
    assert method == "POST" and "/projects/9/repository/commits" in url
    assert body["branch"] == "main" and body["actions"][0]["file_path"] == "a.md"
