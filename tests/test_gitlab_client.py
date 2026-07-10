import pytest
from agent.lib.gitlab_read import (
    GitLabClient, HttpResponse, GitLabAuthError, GitLabForbidden, GitLabUnreachable,
)

class FakeTransport:
    """Scripts (method,url)->list of HttpResponse (popped in order) or a raised exc."""
    def __init__(self, script):
        self.script = script
        self.calls = []
    def __call__(self, method, url, headers, params, timeout):
        self.calls.append((url, dict(params or {}), dict(headers)))
        item = self.script[url]
        if isinstance(item, list):
            resp = item.pop(0)
        else:
            resp = item
        if isinstance(resp, Exception):
            raise resp
        return resp

def _resp(status, body="[]", headers=None):
    return HttpResponse(status=status, headers=headers or {}, body_text=body)

def _client(script):
    t = FakeTransport(script)
    return GitLabClient("https://gl.test", "tok", request=t), t

def test_get_sends_private_token_header():
    c, t = _client({"https://gl.test/api/v4/version": _resp(200, '{"version":"16.0"}')})
    r = c.get("/version")
    assert r.json()["version"] == "16.0"
    assert t.calls[0][2]["PRIVATE-TOKEN"] == "tok"

def test_401_raises_auth_error():
    c, _ = _client({"https://gl.test/api/v4/projects": _resp(401)})
    with pytest.raises(GitLabAuthError):
        c.get("/projects")

def test_403_raises_forbidden():
    c, _ = _client({"https://gl.test/api/v4/projects/5": _resp(403)})
    with pytest.raises(GitLabForbidden):
        c.get("/projects/5")

def test_connection_error_raises_unreachable():
    c, _ = _client({"https://gl.test/api/v4/version": ConnectionError("no route")})
    with pytest.raises(GitLabUnreachable):
        c.get("/version")

def test_429_retries_once_then_succeeds():
    url = "https://gl.test/api/v4/projects"
    c, t = _client({url: [_resp(429, headers={"Retry-After": "0"}), _resp(200, "[1]")]})
    r = c.get("/projects")
    assert r.status == 200 and len(t.script) >= 0
    assert len(t.calls) == 2

def test_paginated_follows_x_next_page():
    url = "https://gl.test/api/v4/projects"
    c, t = _client({url: [
        _resp(200, "[1,2]", headers={"X-Next-Page": "2"}),
        _resp(200, "[3]", headers={"X-Next-Page": ""}),
    ]})
    got = c.get_paginated("/projects")
    assert got == [1, 2, 3]
    assert t.calls[1][1].get("page") == 2
