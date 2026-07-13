# Change Monitor — Plan 07: GitHub Source Provider

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native `GitHubProvider` that implements the same 5-method `SourceProvider` seam over the GitHub REST API — list repos, verify recent commits, read trees/files, best-effort code search — so `discover`/`inventory` scan GitHub repos **without cloning**. Wire it into `make_provider` behind `source.type: github`, resolving the token from an env var or the user's existing `gh auth token` login (no PAT to manage). Additive; GitLab/Local and the whole downstream pipeline are untouched.

**Architecture:** `GitHubProvider(owner, token, *, request=<http>)` mirrors `GitLabClient`/`LocalProvider`: all HTTP goes through an injected `request` callable (default = `requests`), so every unit test uses fakes — no network. It maps GitHub's `full_name` (owner/repo) addressing to the numeric repo `id` the pipeline uses. The five methods return the exact shapes discover/inventory already consume. `make_provider` gains a `github` branch that resolves the token (`env[tokenEnv]`, else `gh auth token`). No changes to KB, candidates, classify, delta, report, or delivery.

**Tech Stack:** Python 3.11+, pytest, requests (already present). Reuses `agent.lib.gitlab_read.HttpResponse` as a generic HTTP response type.

## Global Constraints

- Python **3.11+**. Use the project venv: `source .venv/bin/activate` before python/pytest.
- **No network in unit tests.** `GitHubProvider` takes an injected `request(method, url, headers, params) -> HttpResponse`; the `gh auth token` fallback and the `requests` default are `# pragma: no cover`. Tests inject fakes.
- **Read-only.** Only GET requests to the GitHub API. No writes anywhere.
- **The five-method contract is the seam** (identical signatures/return-shapes to `GitLabClient`/`LocalProvider`): `list_candidate_projects(since_iso) -> list[dict]` ({id:int, path_with_namespace, default_branch, last_activity_at}), `has_commit_since(project_id, since_iso, ref=None) -> str|None`, `get_tree(project_id, ref) -> list[str]`, `get_raw_file(project_id, path, ref) -> str|None`, `search_blobs(project_id, query) -> list[dict]` ([{"path": ...}]).
- **Never silent-OK carries through:** a per-repo API error surfaces via the existing discover/inventory coverage-gap paths. GitHub **code search is best-effort** (rate-limited, default-branch, index-dependent) — `search_blobs` returns `[]` on a search error rather than raising, and this limitation is documented (presence detection on GitHub is weaker than local grep).
- **Auth headers:** `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`.
- Package root `agent/`; tests in `tests/`. TDD throughout (failing test first). Explicit `git add` of only a task's files. Commit after every task.

**This is Plan 07** (additive; the third provider). GitLab/Local unchanged.

---

### Task 1: GitHubProvider HTTP core (auth, pagination, error contract)

**Files:**
- Create: `agent/lib/github_provider.py`
- Test: `tests/test_github_core.py`

**Interfaces:**
- Consumes `agent.lib.gitlab_read.HttpResponse` (generic `status/headers/body_text/.json()`).
- Produces:
  - Exceptions `GitHubError`, `GitHubUnreachable`, `GitHubAuthError`.
  - `GitHubProvider(owner, token, *, request=_default_request, timeout=30)`.
  - `_get(path, params=None, *, allow_404=False, accept=None) -> HttpResponse` — prefixes `https://api.github.com`, adds auth headers (overriding `Accept` when `accept` given); on connection error → `GitHubUnreachable`; 401 → `GitHubAuthError`; 404 with `allow_404` → returns the response; other ≥400 → `GitHubError` (message includes status + any `X-RateLimit-Remaining`).
  - `_get_paginated(path, params=None) -> list` — follows the `Link` header `rel="next"` (parse the `<url>; rel="next"` token), concatenating JSON arrays; stops when no `next`.
  - `request` contract: `request(method, url, headers, params, timeout) -> HttpResponse`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_github_core.py
import pytest
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_github_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.github_provider'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/github_provider.py
"""Native GitHub SourceProvider: scan repos via the GitHub REST API, no cloning.
Implements the same five read methods as GitLabClient/LocalProvider. HTTP is injected."""
from __future__ import annotations

import re

from agent.lib.gitlab_read import HttpResponse

_API = "https://api.github.com"
_LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


class GitHubError(Exception):
    pass


class GitHubUnreachable(GitHubError):
    pass


class GitHubAuthError(GitHubError):
    pass


def _default_request(method, url, headers, params, timeout):  # pragma: no cover - real HTTP
    import requests
    resp = requests.request(method, url, headers=headers, params=params, timeout=timeout)
    return HttpResponse(status=resp.status_code, headers=dict(resp.headers), body_text=resp.text)


class GitHubProvider:
    def __init__(self, owner, token, *, request=_default_request, timeout=30):
        self.owner = owner
        self._token = token
        self._request = request
        self._timeout = timeout
        self._by_id = {}                 # id -> full_name, populated by list_candidate_projects

    def _headers(self, accept=None):
        return {"Authorization": f"Bearer {self._token}",
                "Accept": accept or "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "change-monitor/1.0"}

    def _get(self, path, params=None, *, allow_404=False, accept=None) -> HttpResponse:
        url = path if path.startswith("http") else _API + path
        try:
            resp = self._request("GET", url, self._headers(accept), params or {}, self._timeout)
        except (ConnectionError, TimeoutError) as exc:
            raise GitHubUnreachable(str(exc)) from exc
        if resp.status == 401:
            raise GitHubAuthError(f"401 on {path}")
        if resp.status == 404 and allow_404:
            return resp
        if resp.status >= 400:
            rem = resp.headers.get("X-RateLimit-Remaining", "?")
            raise GitHubError(f"{resp.status} on {path} (rate-limit-remaining={rem})")
        return resp

    def _get_paginated(self, path, params=None) -> list:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        out, url = [], path
        while url:
            resp = self._get(url, params if url == path else None)
            out.extend(resp.json() or [])
            m = _LINK_NEXT.search(resp.headers.get("Link", ""))
            url = m.group(1) if m else None
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_github_core.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/github_provider.py tests/test_github_core.py
git commit -m "feat(source): GitHubProvider HTTP core (auth, Link pagination, error contract)"
```

---

### Task 2: list_candidate_projects + has_commit_since

**Files:**
- Modify: `agent/lib/github_provider.py`
- Test: `tests/test_github_repos.py`

**Interfaces:**
- Adds to `GitHubProvider`:
  - `list_candidate_projects(since_iso) -> list[dict]` — `GET /user/repos?affiliation=owner&sort=pushed` (paginated; the authed token's own repos, incl private), filtered to `full_name` starting with `f"{self.owner}/"`. Populates `self._by_id[id] = full_name`. Returns `[{id, path_with_namespace: full_name, default_branch, last_activity_at: pushed_at}]` for non-archived repos.
  - `has_commit_since(project_id, since_iso, ref=None) -> str|None` — `GET /repos/{full_name}/commits?per_page=1&since={since_iso}` (+ `sha={ref}` when given); returns the top commit's `commit.committer.date` or `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_github_repos.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_github_repos.py -v`
Expected: FAIL — `AttributeError: 'GitHubProvider' object has no attribute 'list_candidate_projects'`

- [ ] **Step 3: Write minimal implementation**

Append to `GitHubProvider`:

```python
    def _full_name(self, project_id):
        return self._by_id[project_id]

    def list_candidate_projects(self, since_iso: str) -> list:
        repos = self._get_paginated("/user/repos", {"affiliation": "owner", "sort": "pushed"})
        out = []
        prefix = f"{self.owner}/"
        for r in repos:
            if r.get("archived") or not r.get("full_name", "").startswith(prefix):
                continue
            self._by_id[r["id"]] = r["full_name"]
            out.append({"id": r["id"], "path_with_namespace": r["full_name"],
                        "default_branch": r.get("default_branch") or "main",
                        "last_activity_at": r.get("pushed_at", "")})
        return out

    def has_commit_since(self, project_id, since_iso, ref=None) -> "str | None":
        params = {"per_page": 1, "since": since_iso}
        if ref:
            params["sha"] = ref
        commits = self._get(f"/repos/{self._full_name(project_id)}/commits", params).json() or []
        if not commits:
            return None
        return commits[0].get("commit", {}).get("committer", {}).get("date")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_github_repos.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/github_provider.py tests/test_github_repos.py
git commit -m "feat(source): GitHub list_candidate_projects + commits-strict has_commit_since"
```

---

### Task 3: get_tree + get_raw_file

**Files:**
- Modify: `agent/lib/github_provider.py`
- Test: `tests/test_github_files.py`

**Interfaces:**
- Adds:
  - `get_tree(project_id, ref) -> list[str]` — `GET /repos/{full_name}/git/trees/{ref}?recursive=1`; return `path` for entries with `type == "blob"`. (If the response `truncated` is true, the tree is over GitHub's cap — still return what came back; a truncated giant repo is an accepted limitation.)
  - `get_raw_file(project_id, path, ref) -> str|None` — `GET /repos/{full_name}/contents/{path}?ref={ref}` with `Accept: application/vnd.github.raw` (raw body); 404 → `None`; a 403 "too large" (>1 MB via contents API) → `None` (manifests are small; accepted limitation).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_github_files.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_github_files.py -v`
Expected: FAIL — `AttributeError: ... 'get_tree'`

- [ ] **Step 3: Write minimal implementation**

Append to `GitHubProvider`:

```python
    def get_tree(self, project_id, ref) -> list:
        data = self._get(f"/repos/{self._full_name(project_id)}/git/trees/{ref}",
                         {"recursive": "1"}).json() or {}
        return [t["path"] for t in (data.get("tree") or []) if t.get("type") == "blob"]

    def get_raw_file(self, project_id, path, ref) -> "str | None":
        resp = self._get(f"/repos/{self._full_name(project_id)}/contents/{path}",
                         {"ref": ref}, allow_404=True, accept="application/vnd.github.raw")
        return resp.body_text if resp.status == 200 else None
```

Note: `_get` raises `GitHubError` on 403 (e.g. "too large"); to make `get_raw_file` return `None` there instead, wrap the call:
```python
    def get_raw_file(self, project_id, path, ref) -> "str | None":
        try:
            resp = self._get(f"/repos/{self._full_name(project_id)}/contents/{path}",
                             {"ref": ref}, allow_404=True, accept="application/vnd.github.raw")
        except GitHubError:
            return None                     # too-large / transient -> treat as unreadable
        return resp.body_text if resp.status == 200 else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_github_files.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/github_provider.py tests/test_github_files.py
git commit -m "feat(source): GitHub get_tree + get_raw_file (raw contents)"
```

---

### Task 4: search_blobs (best-effort code search)

**Files:**
- Modify: `agent/lib/github_provider.py`
- Test: `tests/test_github_search.py`

**Interfaces:**
- Adds `search_blobs(project_id, query) -> list[dict]` — `GET /search/code?q={query} repo:{full_name}`; return `[{"path": item["path"]}]` from `items`. On ANY error (rate limit 403, 422 not-indexed, `GitHubError`) return `[]` (best-effort — GitHub code search is weaker than local grep; documented). This keeps presence detection non-fatal.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_github_search.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_github_search.py -v`
Expected: FAIL — `AttributeError: ... 'search_blobs'`

- [ ] **Step 3: Write minimal implementation**

Append to `GitHubProvider`:

```python
    def search_blobs(self, project_id, query) -> list:
        # GitHub code search is best-effort (rate-limited, default-branch, index-dependent):
        # on any error return [] so presence detection degrades gracefully.
        try:
            data = self._get("/search/code",
                             {"q": f"{query} repo:{self._full_name(project_id)}", "per_page": 10}).json() or {}
        except GitHubError:
            return []
        return [{"path": it["path"]} for it in (data.get("items") or []) if it.get("path")]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_github_search.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/github_provider.py tests/test_github_search.py
git commit -m "feat(source): GitHub search_blobs (best-effort code search)"
```

---

### Task 5: config `github` fields + factory branch + token-from-gh + README

**Files:**
- Modify: `agent/config.py`, `agent/lib/source.py`
- Create: `demo/github-config.yaml`
- Modify: `demo/README.md`
- Test: `tests/test_github_factory.py`

**Interfaces:**
- `agent/config.py`: `SourceConfig` gains `github_owner: str = ""`, `github_token_env: str = "GITHUB_TOKEN"`. `_source_from` accepts `type: github` (requires `owner`).
- `agent/lib/source.py`: `make_provider` gains a `github` branch → `GitHubProvider(cfg.source.github_owner, token)` where `token = env[github_token_env]` if set, else `_gh_token()` (subprocess `gh auth token`, `# pragma: no cover`); `SourceError` if neither yields a token.
- `demo/github-config.yaml` — a `source: {type: github, owner: <you>}` config + the runtime feeds; README "GitHub source" section: no PAT if `gh` is logged in; run `discover`/`inventory`/`classify-report` against all your repos without cloning.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_github_factory.py
import textwrap
import pytest
from agent.config import load_config, ConfigError
from agent.lib.source import make_provider, SourceError
from agent.lib.github_provider import GitHubProvider

FEEDS = "\nfeeds:\n  - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }\n"

def _cfg(tmp_path, body):
    p = tmp_path / "c.yaml"; p.write_text(textwrap.dedent(body) + FEEDS); return load_config(str(p))

def test_github_source_parsed(tmp_path):
    cfg = _cfg(tmp_path, "kb: { root: kb/ }\nsource: { type: github, owner: laxit-patel, tokenEnv: GH_TOKEN }")
    assert cfg.source.type == "github" and cfg.source.github_owner == "laxit-patel"
    assert cfg.source.github_token_env == "GH_TOKEN"

def test_github_requires_owner(tmp_path):
    with pytest.raises(ConfigError, match="owner"):
        _cfg(tmp_path, "kb: { root: kb/ }\nsource: { type: github }")

def test_make_github_provider_with_env_token(tmp_path):
    cfg = _cfg(tmp_path, "kb: { root: kb/ }\nsource: { type: github, owner: acme, tokenEnv: GH_TOKEN }")
    prov = make_provider(cfg, env={"GH_TOKEN": "tok"})
    assert isinstance(prov, GitHubProvider) and prov.owner == "acme"

def test_make_github_no_token_raises(tmp_path, monkeypatch):
    # env empty AND gh fallback stubbed to return "" -> SourceError
    import agent.lib.source as source_mod
    monkeypatch.setattr(source_mod, "_gh_token", lambda: "")
    cfg = _cfg(tmp_path, "kb: { root: kb/ }\nsource: { type: github, owner: acme, tokenEnv: GH_TOKEN }")
    with pytest.raises(SourceError):
        make_provider(cfg, env={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_github_factory.py -v`
Expected: FAIL — `ConfigError` on unknown type / `AttributeError`

- [ ] **Step 3: Write minimal implementation**

In `agent/config.py`, extend `SourceConfig` and `_source_from`:

```python
@dataclass
class SourceConfig:
    type: str = "gitlab"
    local_root: str = ""
    github_owner: str = ""
    github_token_env: str = "GITHUB_TOKEN"


def _source_from(raw: dict) -> "SourceConfig":
    s = raw.get("source") or {}
    t = s.get("type", "gitlab")
    if t not in ("gitlab", "local", "github"):
        raise ConfigError(f"source.type must be gitlab|local|github, got '{t}'")
    if t == "local" and not s.get("root"):
        raise ConfigError("source.type=local requires 'root'")
    if t == "github" and not s.get("owner"):
        raise ConfigError("source.type=github requires 'owner'")
    return SourceConfig(type=t, local_root=str(s.get("root", "")),
                        github_owner=str(s.get("owner", "")),
                        github_token_env=s.get("tokenEnv", "GITHUB_TOKEN"))
```

In `agent/lib/source.py`, add the `github` branch + token resolver:

```python
import subprocess
from agent.lib.github_provider import GitHubProvider


def _gh_token() -> str:  # pragma: no cover - shells out to the user's gh login
    try:
        p = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def make_provider(config, *, env=None):
    env = os.environ if env is None else env
    src = config.source
    if src is None:
        raise SourceError("config has no `source` (build it via load_config)")
    if src.type == "local":
        return LocalProvider(src.local_root)
    if src.type == "github":
        token = env.get(src.github_token_env) or _gh_token()
        if not token:
            raise SourceError(f"no GitHub token: set {src.github_token_env} or run `gh auth login`")
        return GitHubProvider(src.github_owner, token)
    # gitlab
    if config.gitlab is None:
        raise SourceError("source.type=gitlab but no `gitlab` config section")
    token = env.get(config.gitlab.token_env)
    if not token:
        raise SourceError(f"env var {config.gitlab.token_env} is not set")
    return GitLabClient(config.gitlab.base_url, token)
```

Create `demo/github-config.yaml`:

```yaml
# Scan your GitHub repos via the API (no cloning). If `gh auth login` is done,
# no PAT needed — the token is read from `gh auth token`. Or set GITHUB_TOKEN.
kb: { root: demo/out/kb }
source:
  type: github
  owner: laxit-patel            # your GitHub user or org
  tokenEnv: GITHUB_TOKEN        # optional; falls back to `gh auth token`
scan:
  activeWindowDays: 365         # repos with a commit in the last year
  maxRepos: 40                  # cap the scan (GitHub API is rate-limited)
delivery: { reportsProject: demo/reports, reviewHorizonMonths: 6 }
feeds:
  - { techKey: runtime:php,    label: PHP,     category: runtime, adapter: endoflife, url: php,    tier: 1 }
  - { techKey: runtime:node,   label: Node.js, category: runtime, adapter: endoflife, url: nodejs, tier: 1 }
  - { techKey: runtime:python, label: Python,  category: runtime, adapter: endoflife, url: python, tier: 1 }
```

Add a "GitHub source" section to `demo/README.md`: with `gh` logged in, no PAT is needed;
```bash
python -m agent.cli ingest        --config demo/github-config.yaml --now 2026-07-13
python -m agent.cli discover      --config demo/github-config.yaml --now 2026-07-13 --out demo/out/active-repos.json
python -m agent.cli inventory     --config demo/github-config.yaml --active demo/out/active-repos.json --out demo/out/inventory.json --patterns agent/patterns.yaml --now 2026-07-13
python -m agent.cli registry-scan --config demo/github-config.yaml --inventory demo/out/inventory.json --now 2026-07-13
python -m agent.cli classify-report --config demo/github-config.yaml --inventory demo/out/inventory.json --active demo/out/active-repos.json --prev - --out-report demo/out/report.md --out-findings demo/out/findings.json --now 2026-07-13
```
Note: scans repos without cloning; GitHub **code search** (integration presence) is best-effort/rate-limited; set `scan.maxRepos` to stay within rate limits.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_github_factory.py -v`
Expected: PASS (4 passed). Also `pytest -q` — existing config/source tests still green (gitlab/local unaffected; `source` still defaults to gitlab).

- [ ] **Step 5: Commit**

```bash
git add agent/config.py agent/lib/source.py demo/github-config.yaml demo/README.md tests/test_github_factory.py
git commit -m "feat(source): github config + make_provider github branch (token via env or gh) + demo"
```

---

## Self-Review

**Design goals:**
- Native GitHub provider implementing the 5-method seam over the REST API (no cloning) → Tasks 1–4 ✓
- `source.type: github` config + factory + token from env-or-`gh` → Task 5 ✓
- Additive: GitLab/Local + downstream untouched (they consume `active-repos.json`/`inventory.json` only) ✓
- CLI needs no change — `discover`/`inventory` already build the provider via `make_provider` (Plan 06), which now returns a `GitHubProvider` for github configs.

**Placeholder scan:** none — every step has runnable code. `_default_request`, `_gh_token`, and the raw-`requests` path are `# pragma: no cover`; unit tests inject fakes.

**Type consistency:** the five methods have identical signatures/return-shapes to `GitLabClient`/`LocalProvider` — `list_candidate_projects(since_iso)`→[{id,path_with_namespace,default_branch,last_activity_at}], `has_commit_since(id,since,ref=)`→str|None, `get_tree(id,ref)`→list[str], `get_raw_file(id,path,ref)`→str|None, `search_blobs(id,query)`→[{path}]. Reuses `HttpResponse` from `gitlab_read`. `make_provider(config, *, env=)` returns any of the three providers. `SourceConfig` gains github fields with safe defaults (existing configs/tests unaffected).

**Known limitations (documented):** (1) `list_candidate_projects` uses `/user/repos?affiliation=owner` (the authed token's own repos incl private), filtered by `owner` — org repos the user isn't an owner of need a different affiliation (follow-up). (2) `get_tree` is truncated for very large repos (GitHub caps recursive trees); accepted. (3) `get_raw_file` >1 MB via the contents API returns None; accepted (manifests are small). (4) GitHub **code search** (presence) is best-effort — rate-limited (~10/min), default-branch only, index-dependent — so integration presence on GitHub is weaker than local grep; `search_blobs` returns [] on error and this is documented. Set `scan.maxRepos` to bound API usage.
