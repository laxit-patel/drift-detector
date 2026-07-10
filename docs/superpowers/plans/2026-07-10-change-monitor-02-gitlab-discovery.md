# Change Monitor — Plan 02: GitLab Read Client + Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the read-only GitLab access layer and the discovery stage — authenticate to a self-hosted GitLab, list projects active in the last N days (verified by a real in-window commit), apply allow/deny/always-include rules and namespace reconciliation, and emit `active-repos.json`. All HTTP is injected so the whole plan is unit-testable with fixtures; the real base-URL/token are supplied at run time via config + env.

**Architecture:** A single `GitLabClient` owns all HTTP: auth header, pagination (via GitLab's `X-Next-Page` header), 429/`Retry-After` handling, and a typed error contract. It takes an injected `request` callable (default = `requests`), so tests drive it with canned responses and never touch the network. Discovery is a pure orchestration over the client + config that produces a serializable result. This extends Plan 01's config loader with `gitlab` and `scan` sections; it does not touch the KB.

**Tech Stack:** Python 3.11+, pytest, requests, python-dateutil (already in `requirements.txt` from Plan 01).

## Global Constraints

- Python **3.11+**. Use the project venv: `source .venv/bin/activate` before python/pytest (Python 3.12; system python is 3.10).
- **No network and no wall-clock in unit tests.** `GitLabClient` takes an injected `request` callable; discovery takes an injected `now` (ISO date string). Tests must never hit the network.
- **Read-only.** This layer only ever issues GET requests. No POST/PUT/DELETE anywhere. The token is read-only (`read_api`); nothing here writes.
- **Secrets come from the environment, never config or code.** `config.yaml` names the env var (`tokenEnv`); the value is read from `os.environ` at client construction.
- **Fail-loud on infra, coverage-gap on per-repo.** GitLab unreachable / 401 → abort the run with a typed error. A single repo's 403/404/500 → a coverage-gap record, discovery continues.
- **"active" = a real commit in the window.** `last_activity_at` over-includes (issues/wiki), so every candidate is verified with `commits?all=true&per_page=1`. Use `all=true` so feature-branch-only activity counts.
- Package root `agent/`; tests in `tests/`; `pytest.ini` already sets `pythonpath = .`. TDD throughout (failing test first). Explicit `git add` of only the files a task creates — never `git add -A`.
- Commit after every task. Conventional-commit messages.

**This is Plan 02 of the GitLab side** (03 = inventory/extractors/presence; 04 = classify→report→deliver). Build methods on `GitLabClient` only as this plan needs them — `get_tree`/`get_raw_file`/`search_blobs` are Plan 03, added to the same client then.

---

### Task 1: Extend config with `gitlab` + `scan` sections

**Files:**
- Modify: `agent/config.py`
- Test: `tests/test_config_gitlab.py`

**Interfaces:**
- Consumes: existing `load_config`/`Config`/`ConfigError` from Plan 01.
- Produces: `GitLabConfig(base_url, token_env, expected_namespaces: list[str])`; `ScanConfig(active_window_days: int, always_include: list[str], allow: list[str], deny: list[str], branch_overrides: dict[str,str], max_repos: int)`; `Config` gains `.gitlab: GitLabConfig | None` and `.scan: ScanConfig`. Missing `gitlab`/`scan` sections are allowed (they default) so Plan 01's KB-only configs still load; but if a `gitlab` section is present it must have `baseUrl` + `tokenEnv`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_gitlab.py
import textwrap
import pytest
from agent.config import load_config, ConfigError

def _write(tmp_path, body):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)

BASE_FEEDS = """
    feeds:
      - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }
"""

def test_gitlab_and_scan_parsed(tmp_path):
    cfg = load_config(_write(tmp_path, """
        kb: { root: kb/ }
        gitlab:
          baseUrl: https://gitlab.example.internal
          tokenEnv: GITLAB_READ_TOKEN
          expectedNamespaces: [clients, internal]
        scan:
          activeWindowDays: 90
          alwaysInclude: [clients/legacy]
          deny: [internal/sandbox]
          branchOverrides: { clients/acme: release }
          maxRepos: 50
    """ + BASE_FEEDS))
    assert cfg.gitlab.base_url == "https://gitlab.example.internal"
    assert cfg.gitlab.token_env == "GITLAB_READ_TOKEN"
    assert cfg.gitlab.expected_namespaces == ["clients", "internal"]
    assert cfg.scan.active_window_days == 90
    assert cfg.scan.always_include == ["clients/legacy"]
    assert cfg.scan.deny == ["internal/sandbox"]
    assert cfg.scan.branch_overrides == {"clients/acme": "release"}
    assert cfg.scan.max_repos == 50

def test_scan_defaults_when_absent(tmp_path):
    cfg = load_config(_write(tmp_path, "kb: { root: kb/ }\n" + BASE_FEEDS))
    assert cfg.gitlab is None
    assert cfg.scan.active_window_days == 90     # default
    assert cfg.scan.allow == [] and cfg.scan.deny == []

def test_gitlab_section_requires_baseurl_and_tokenenv(tmp_path):
    with pytest.raises(ConfigError, match="baseUrl"):
        load_config(_write(tmp_path, """
            kb: { root: kb/ }
            gitlab: { tokenEnv: GITLAB_READ_TOKEN }
        """ + BASE_FEEDS))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_config_gitlab.py -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'gitlab'`

- [ ] **Step 3: Write minimal implementation**

Add to `agent/config.py` (new dataclasses + parsing; keep existing code):

```python
# --- add these dataclasses near the top, after the existing imports ---
@dataclass
class GitLabConfig:
    base_url: str
    token_env: str
    expected_namespaces: list[str]


@dataclass
class ScanConfig:
    active_window_days: int = 90
    always_include: list[str] = None
    allow: list[str] = None
    deny: list[str] = None
    branch_overrides: dict = None
    max_repos: int = 50

    def __post_init__(self):
        self.always_include = self.always_include or []
        self.allow = self.allow or []
        self.deny = self.deny or []
        self.branch_overrides = self.branch_overrides or {}
```

Extend the `Config` dataclass to carry the new fields:

```python
@dataclass
class Config:
    kb_root: str
    feeds: list[FeedSpec]
    raw: dict
    gitlab: "GitLabConfig | None" = None
    scan: "ScanConfig" = None
```

Add parsing helpers and wire them into `load_config` just before it returns:

```python
def _gitlab_from(raw: dict) -> "GitLabConfig | None":
    g = raw.get("gitlab")
    if not g:
        return None
    for k in ("baseUrl", "tokenEnv"):
        if not g.get(k):
            raise ConfigError(f"gitlab section: missing required field '{k}'")
    return GitLabConfig(
        base_url=str(g["baseUrl"]).rstrip("/"),
        token_env=g["tokenEnv"],
        expected_namespaces=list(g.get("expectedNamespaces") or []),
    )


def _scan_from(raw: dict) -> "ScanConfig":
    s = raw.get("scan") or {}
    return ScanConfig(
        active_window_days=int(s.get("activeWindowDays", 90)),
        always_include=list(s.get("alwaysInclude") or []),
        allow=list(s.get("allow") or []),
        deny=list(s.get("deny") or []),
        branch_overrides=dict(s.get("branchOverrides") or {}),
        max_repos=int(s.get("maxRepos", 50)),
    )
```

In `load_config`, change the return to:

```python
    return Config(
        kb_root=kb_root,
        feeds=feeds,
        raw=raw,
        gitlab=_gitlab_from(raw),
        scan=_scan_from(raw),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_config_gitlab.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run full suite + commit**

Run: `pytest -q` → expected all green (34 + 3 new).
```bash
git add agent/config.py tests/test_config_gitlab.py
git commit -m "feat(gitlab): config gitlab + scan sections"
```

---

### Task 2: GitLab client core (auth, pagination, rate-limit, error contract)

**Files:**
- Create: `agent/lib/gitlab_read.py`
- Test: `tests/test_gitlab_client.py`

**Interfaces:**
- Produces:
  - `HttpResponse(status: int, headers: dict, body_text: str)` with `.json() -> object`.
  - Exceptions: `GitLabError` (base), `GitLabUnreachable`, `GitLabAuthError`, `GitLabForbidden` (per-repo, carries `.resource`).
  - `GitLabClient(base_url, token, *, request=_default_request, timeout=30)` with:
    - `get(path, params=None) -> HttpResponse` — adds `PRIVATE-TOKEN` header; on 401 raises `GitLabAuthError`; on 403 raises `GitLabForbidden`; on connection failure raises `GitLabUnreachable`; on 429 honours `Retry-After` once then retries, aborts on repeat.
    - `get_paginated(path, params=None) -> list` — follows GitLab's `X-Next-Page` header, concatenating JSON arrays.
  - `request` callable contract: `request(method: str, url: str, headers: dict, params: dict, timeout: int) -> HttpResponse`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gitlab_client.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_gitlab_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.gitlab_read'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/gitlab_read.py
"""Read-only GitLab REST v4 client. All HTTP goes through an injected `request`
callable so it is fully testable without the network. GET-only by construction."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass


class GitLabError(Exception):
    pass


class GitLabUnreachable(GitLabError):
    pass


class GitLabAuthError(GitLabError):
    pass


class GitLabForbidden(GitLabError):
    def __init__(self, resource: str):
        super().__init__(f"forbidden: {resource}")
        self.resource = resource


@dataclass
class HttpResponse:
    status: int
    headers: dict
    body_text: str

    def json(self):
        return json.loads(self.body_text or "null")


def _default_request(method, url, headers, params, timeout):  # pragma: no cover - thin HTTP shim
    import requests
    resp = requests.request(method, url, headers=headers, params=params, timeout=timeout)
    return HttpResponse(status=resp.status_code, headers=dict(resp.headers), body_text=resp.text)


class GitLabClient:
    def __init__(self, base_url: str, token: str, *, request=_default_request, timeout: int = 30):
        self._base = base_url.rstrip("/") + "/api/v4"
        self._token = token
        self._request = request
        self._timeout = timeout

    def get(self, path: str, params: dict | None = None) -> HttpResponse:
        url = self._base + path
        headers = {"PRIVATE-TOKEN": self._token, "User-Agent": "change-monitor/1.0"}
        try:
            resp = self._request("GET", url, headers, params or {}, self._timeout)
        except (ConnectionError, TimeoutError) as exc:
            raise GitLabUnreachable(str(exc)) from exc

        if resp.status == 429:
            wait = float(resp.headers.get("Retry-After", "1"))
            time.sleep(wait)
            resp = self._request("GET", url, headers, params or {}, self._timeout)
            if resp.status == 429:
                raise GitLabUnreachable("rate limited (429) after retry")

        if resp.status == 401:
            raise GitLabAuthError(f"401 on {path}")
        if resp.status == 403:
            raise GitLabForbidden(path)
        if resp.status >= 400:
            raise GitLabError(f"{resp.status} on {path}")
        return resp

    def get_paginated(self, path: str, params: dict | None = None) -> list:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        out: list = []
        page = 1
        while True:
            params["page"] = page
            resp = self.get(path, params)
            batch = resp.json() or []
            out.extend(batch)
            nxt = resp.headers.get("X-Next-Page", "")
            if not nxt:
                break
            page = int(nxt)
        return out
```

Note on `test_429_retries_once_then_succeeds`: `Retry-After: "0"` makes `time.sleep(0)` a no-op, so the test stays fast without mocking sleep.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_gitlab_client.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/gitlab_read.py tests/test_gitlab_client.py
git commit -m "feat(gitlab): read-only REST client core (auth, pagination, 429, error contract)"
```

---

### Task 3: `list_active_projects` + commits-strict verification

**Files:**
- Modify: `agent/lib/gitlab_read.py`
- Test: `tests/test_gitlab_projects.py`

**Interfaces:**
- Consumes: `GitLabClient.get`/`get_paginated` (Task 2).
- Produces (methods on `GitLabClient`):
  - `list_candidate_projects(since_iso: str) -> list[dict]` — `GET /projects?last_activity_after=<since_iso>&archived=false&simple=true` (paginated). Returns raw project dicts (`id`, `path_with_namespace`, `default_branch`, `last_activity_at`, `namespace`).
  - `has_commit_since(project_id: int, since_iso: str, ref: str | None = None) -> str | None` — `GET /projects/:id/repository/commits?all=true&per_page=1` (+ `ref_name` when `ref` given, `since=<since_iso>`); returns the top commit's `committed_date` (a real in-window commit exists) or `None`. A `GitLabForbidden` propagates to the caller (discovery records it as a coverage gap).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gitlab_projects.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_gitlab_projects.py -v`
Expected: FAIL — `AttributeError: 'GitLabClient' object has no attribute 'list_candidate_projects'`

- [ ] **Step 3: Write minimal implementation**

Append to `GitLabClient` in `agent/lib/gitlab_read.py`:

```python
    def list_candidate_projects(self, since_iso: str) -> list:
        return self.get_paginated("/projects", {
            "last_activity_after": since_iso,
            "archived": "false",
            "simple": "true",
            "order_by": "last_activity_at",
        })

    def has_commit_since(self, project_id: int, since_iso: str, ref: str | None = None) -> "str | None":
        params = {"all": "true", "per_page": 1, "since": since_iso}
        if ref:
            params["ref_name"] = ref
        commits = self.get(f"/projects/{project_id}/repository/commits", params).json() or []
        return commits[0]["committed_date"] if commits else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_gitlab_projects.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/gitlab_read.py tests/test_gitlab_projects.py
git commit -m "feat(gitlab): list_candidate_projects + commits-strict has_commit_since"
```

---

### Task 4: Discovery — compute the active set + `active-repos.json`

**Files:**
- Create: `agent/discover.py`
- Test: `tests/test_discover.py`

**Interfaces:**
- Consumes: `Config`/`GitLabConfig`/`ScanConfig` (Task 1), `GitLabClient` (Tasks 2–3), `GitLabForbidden`.
- Produces:
  - `since_iso(now: str, window_days: int) -> str` — pure date math (`now` is `YYYY-MM-DD`).
  - `discover(config, client, now: str) -> dict` — the `active-repos.json` structure:
    ```json
    {"runDate": now, "scanWindowDays": N, "namespacesCovered": [...],
     "active": [{"id","path_with_namespace","default_branch","scanned_ref","last_commit_date","reason"}],
     "excluded": [{"repo","reason"}]}
    ```
    Rules: start from `list_candidate_projects(since)`; keep a repo if `has_commit_since` returns a date (`reason:"active"`) OR it's in `always_include` (`reason:"always_include"`); if `allow` is non-empty keep only repos in `allow` ∪ `always_include`; drop repos matching `deny` (→ `excluded`); a `GitLabForbidden` while probing a repo → `excluded` with `reason:"forbidden"`; `scanned_ref` = `branch_overrides.get(path)` or `default_branch`. `namespacesCovered` = sorted set of top-level namespaces seen. Respect `max_repos` (cap the active list, and if capped add an `excluded` note `reason:"max_repos_cap"` for the dropped ones).
  - `write_active_repos(path, result) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discover.py
import json
from agent.config import GitLabConfig, ScanConfig, Config
from agent.lib.gitlab_read import GitLabClient, HttpResponse, GitLabForbidden
from agent import discover

def _cfg(**scan):
    return Config(kb_root="kb/", feeds=[], raw={},
                  gitlab=GitLabConfig("https://gl.test", "GITLAB_READ_TOKEN", ["clients"]),
                  scan=ScanConfig(**scan))

class FakeClient:
    """Stands in for GitLabClient: canned candidates + per-id commit results."""
    def __init__(self, candidates, commits, forbidden=()):
        self._cands = candidates
        self._commits = commits          # id -> committed_date or None
        self._forbidden = set(forbidden)
    def list_candidate_projects(self, since_iso):
        return self._cands
    def has_commit_since(self, pid, since_iso, ref=None):
        if pid in self._forbidden:
            raise GitLabForbidden(f"/projects/{pid}")
        return self._commits.get(pid)

def _proj(pid, path, branch="main"):
    return {"id": pid, "path_with_namespace": path, "default_branch": branch,
            "last_activity_at": "2026-07-01T00:00:00Z"}

def test_since_iso_math():
    assert discover.since_iso("2026-07-10", 90) == "2026-04-11"

def test_keeps_repos_with_real_commit():
    client = FakeClient([_proj(1, "clients/a"), _proj(2, "clients/b")],
                        {1: "2026-06-20T00:00:00Z", 2: None})   # 2 has no real in-window commit
    res = discover.discover(_cfg(), client, "2026-07-10")
    assert [r["path_with_namespace"] for r in res["active"]] == ["clients/a"]
    assert {"repo": "clients/b", "reason": "no_recent_commit"} in res["excluded"]
    assert res["active"][0]["scanned_ref"] == "main"
    assert res["namespacesCovered"] == ["clients"]

def test_always_include_overrides_no_commit():
    client = FakeClient([_proj(2, "clients/b")], {2: None})
    res = discover.discover(_cfg(always_include=["clients/b"]), client, "2026-07-10")
    assert res["active"][0]["reason"] == "always_include"

def test_deny_excludes():
    client = FakeClient([_proj(1, "internal/sandbox")], {1: "2026-06-01T00:00:00Z"})
    res = discover.discover(_cfg(deny=["internal/sandbox"]), client, "2026-07-10")
    assert res["active"] == []
    assert {"repo": "internal/sandbox", "reason": "deny"} in res["excluded"]

def test_forbidden_becomes_coverage_gap():
    client = FakeClient([_proj(7, "clients/secret")], {}, forbidden=[7])
    res = discover.discover(_cfg(), client, "2026-07-10")
    assert {"repo": "clients/secret", "reason": "forbidden"} in res["excluded"]

def test_branch_override_sets_scanned_ref():
    client = FakeClient([_proj(1, "clients/a")], {1: "2026-06-20T00:00:00Z"})
    res = discover.discover(_cfg(branch_overrides={"clients/a": "release"}), client, "2026-07-10")
    assert res["active"][0]["scanned_ref"] == "release"

def test_write_active_repos(tmp_path):
    out = tmp_path / "active-repos.json"
    discover.write_active_repos(str(out), {"active": [], "excluded": []})
    assert json.loads(out.read_text())["active"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_discover.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.discover'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/discover.py
"""Discovery: turn the GitLab project list into the definitive active-repo scan set."""
from __future__ import annotations

import json
from datetime import date, timedelta

from agent.lib.gitlab_read import GitLabForbidden


def since_iso(now: str, window_days: int) -> str:
    d = date.fromisoformat(now) - timedelta(days=window_days)
    return d.isoformat()


def _top_namespace(path: str) -> str:
    return path.split("/", 1)[0]


def discover(config, client, now: str) -> dict:
    scan = config.scan
    since = since_iso(now, scan.active_window_days)
    allow = set(scan.allow)
    deny = set(scan.deny)
    always = set(scan.always_include)

    candidates = client.list_candidate_projects(since)
    active: list[dict] = []
    excluded: list[dict] = []
    namespaces: set[str] = set()

    for p in candidates:
        path = p["path_with_namespace"]
        namespaces.add(_top_namespace(path))
        if path in deny:
            excluded.append({"repo": path, "reason": "deny"})
            continue
        if allow and path not in allow and path not in always:
            excluded.append({"repo": path, "reason": "not_in_allow"})
            continue
        ref = scan.branch_overrides.get(path) or p.get("default_branch")
        try:
            committed = client.has_commit_since(p["id"], since, ref=ref)
        except GitLabForbidden:
            excluded.append({"repo": path, "reason": "forbidden"})
            continue
        if committed:
            reason = "active"
        elif path in always:
            reason = "always_include"
        else:
            excluded.append({"repo": path, "reason": "no_recent_commit"})
            continue
        active.append({
            "id": p["id"], "path_with_namespace": path,
            "default_branch": p.get("default_branch"), "scanned_ref": ref,
            "last_commit_date": committed, "reason": reason,
        })

    if scan.max_repos and len(active) > scan.max_repos:
        for r in active[scan.max_repos:]:
            excluded.append({"repo": r["path_with_namespace"], "reason": "max_repos_cap"})
        active = active[:scan.max_repos]

    return {
        "runDate": now,
        "scanWindowDays": scan.active_window_days,
        "namespacesCovered": sorted(namespaces),
        "active": active,
        "excluded": excluded,
    }


def write_active_repos(path: str, result: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_discover.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/discover.py tests/test_discover.py
git commit -m "feat(gitlab): discovery (active set, allow/deny/always-include, branch override)"
```

---

### Task 5: CLI `discover` command + namespace reconciliation warning + README

**Files:**
- Modify: `agent/cli.py`
- Create: `docs/change-monitor-plan02-README.md`
- Test: `tests/test_cli_discover.py`

**Interfaces:**
- Consumes: `load_config` (Task 1), `GitLabClient` (Tasks 2–3), `discover`/`write_active_repos` (Task 4).
- Produces: a new `discover` subcommand: `discover --config <path> --now <YYYY-MM-DD> --out <path>`. It constructs a `GitLabClient` from `config.gitlab` (token read from `os.environ[config.gitlab.token_env]`), runs discovery, writes `active-repos.json`, prints a summary, and — namespace reconciliation — prints a `WARNING` line for any `expected_namespaces` entry NOT present in `namespacesCovered`. Returns 2 if `config.gitlab` is missing or the token env var is unset (fail-loud), else 0. To keep the smoke test network-free, `_cmd_discover` accepts an optional injected `client` (defaulting to None → build the real one); the test passes a fake.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_discover.py
import json, textwrap
from agent import cli
from agent.lib.gitlab_read import GitLabForbidden

class FakeClient:
    def __init__(self, cands, commits):
        self._c, self._m = cands, commits
    def list_candidate_projects(self, since):
        return self._c
    def has_commit_since(self, pid, since, ref=None):
        return self._m.get(pid)

def _cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        kb: { root: kb/ }
        gitlab: { baseUrl: https://gl.test, tokenEnv: GITLAB_READ_TOKEN, expectedNamespaces: [clients, missingns] }
        scan: { activeWindowDays: 90 }
        feeds:
          - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }
    """))
    return str(p)

def test_discover_writes_output_and_warns_missing_namespace(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITLAB_READ_TOKEN", "tok")
    out = tmp_path / "active-repos.json"
    client = FakeClient([{"id": 1, "path_with_namespace": "clients/a", "default_branch": "main",
                          "last_activity_at": "2026-07-01T00:00:00Z"}], {1: "2026-06-20T00:00:00Z"})
    rc = cli.main(["discover", "--config", _cfg(tmp_path), "--now", "2026-07-10",
                   "--out", str(out)], client=client)
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["active"][0]["path_with_namespace"] == "clients/a"
    err = capsys.readouterr().out
    assert "WARNING" in err and "missingns" in err        # expected namespace not covered

def test_discover_fails_loud_without_token(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITLAB_READ_TOKEN", raising=False)
    rc = cli.main(["discover", "--config", _cfg(tmp_path), "--now", "2026-07-10",
                   "--out", str(tmp_path / "o.json")], client=None)
    assert rc == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_cli_discover.py -v`
Expected: FAIL — `TypeError: main() got an unexpected keyword argument 'client'` (or missing subcommand)

- [ ] **Step 3: Write minimal implementation**

In `agent/cli.py`: add `import os`, add the `_cmd_discover` function, register the subparser, and thread an optional `client` kwarg through `main`.

```python
# add at top:
import os
from agent.lib.gitlab_read import GitLabClient
from agent import discover as discover_mod


def _cmd_discover(args, client=None) -> int:
    cfg = load_config(args.config)
    if cfg.gitlab is None:
        print("ERROR: config has no `gitlab` section; cannot discover.")
        return 2
    if client is None:
        token = os.environ.get(cfg.gitlab.token_env)
        if not token:
            print(f"ERROR: env var {cfg.gitlab.token_env} is not set.")
            return 2
        client = GitLabClient(cfg.gitlab.base_url, token)
    result = discover_mod.discover(cfg, client, args.now)
    discover_mod.write_active_repos(args.out, result)
    print(f"Discovered {len(result['active'])} active repos "
          f"({len(result['excluded'])} excluded). Namespaces: {result['namespacesCovered']}")
    covered = set(result["namespacesCovered"])
    for ns in cfg.gitlab.expected_namespaces:
        if ns not in covered:
            print(f"WARNING: expected namespace '{ns}' not present in scan — token may not see it.")
    return 0
```

Change `main` to accept and route the injected client:

```python
def main(argv: list[str], *, client=None) -> int:
    p = argparse.ArgumentParser(prog="change-monitor")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest"); pi.add_argument("--config", required=True); pi.add_argument("--now", required=True); pi.set_defaults(func=_cmd_ingest)
    pd = sub.add_parser("drift"); pd.add_argument("--config", required=True); pd.add_argument("--since", default=""); pd.set_defaults(func=_cmd_drift)
    pv = sub.add_parser("discover"); pv.add_argument("--config", required=True); pv.add_argument("--now", required=True); pv.add_argument("--out", required=True); pv.set_defaults(func=_cmd_discover)

    args = p.parse_args(argv)
    if args.func is _cmd_discover:
        return _cmd_discover(args, client=client)
    return args.func(args)
```

(Keep the existing `_cmd_ingest`/`_cmd_drift` unchanged.)

Create `docs/change-monitor-plan02-README.md`:

```markdown
# Change Monitor — Plan 02 (GitLab Read Client + Discovery)

Read-only GitLab access + active-repo discovery.

## Run
```bash
source .venv/bin/activate
export GITLAB_READ_TOKEN=<read_api token>
python -m agent.cli discover --config config.yaml --now 2026-07-12 --out active-repos.json
```
Add a `gitlab:` section (baseUrl, tokenEnv, expectedNamespaces) and a `scan:` section
(activeWindowDays, allow/deny/alwaysInclude, branchOverrides, maxRepos) to `config.yaml`.
"active" = a real commit in the window (verified via `commits?all=true`). GitLab-unreachable/401
aborts; a single repo's 403 becomes a coverage-gap. A missing expected namespace prints a WARNING.

## Next
- Plan 03: inventory (manifest/runtime extractors + integration-presence) → inventory.json.
- Plan 04: Claude classify + trust gate, delta, report, Chat, run.sh, dead-man's switch.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_cli_discover.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run full suite + commit**

Run: `pytest -q` → all green.
```bash
git add agent/cli.py tests/test_cli_discover.py docs/change-monitor-plan02-README.md
git commit -m "feat(gitlab): CLI discover command + namespace reconciliation warning"
```

---

## Self-Review

**Spec coverage (Plan 02 slice of the v2 spec):**
- §3.4 GitLab read client (auth, pagination, 429, error contract; read-only) → Tasks 2–3 ✓ (`get_tree`/`get_raw_file`/`search_blobs` are Plan 03, added to the same client when inventory needs them — stated in Global Constraints).
- §3.5 Discovery (commits-strict `all=true`, allow/deny/always-include, branch override, max_repos, namespace reconciliation, excluded reasons) → Task 4 + Task 5 ✓
- §5.4 config `gitlab`/`scan` sections → Task 1 ✓
- §12 secrets from env not config; read-only token → Task 5 (token from `os.environ`), Tasks 2–3 (GET-only) ✓
- §13 GitLab unreachable/401 → abort (typed error); 403/per-repo → coverage gap → Tasks 2 (errors) + 4 (forbidden→excluded) ✓
- Deferred (correctly): inventory/extractors/presence (§3.6), the LLM stage, report/deliver — later plans.

**Placeholder scan:** none — every step has complete, runnable code. The injected `client`/`request` seams are real test seams, not stubs; the production defaults (`_default_request` via `requests`, real `GitLabClient` construction in `_cmd_discover`) are wired.

**Type consistency:** `GitLabClient(base_url, token, *, request=..., timeout=...)`, `HttpResponse(status, headers, body_text).json()`, and the `request(method, url, headers, params, timeout) -> HttpResponse` contract are identical across Tasks 2, 3, and the test fakes. `discover(config, client, now) -> dict` and `since_iso(now, window_days)` names match between Task 4 and the Task 5 CLI caller. `Config.gitlab`/`Config.scan` field names (`base_url`, `token_env`, `expected_namespaces`, `active_window_days`, `always_include`, `allow`, `deny`, `branch_overrides`, `max_repos`) are consistent between Task 1 and their consumers in Tasks 4–5.

**Known limitation (documented, not a gap):** `has_commit_since` is one extra API call per candidate repo — fine at <25 repos; Plan 04's scaling notes cover batching this at 100+. The 429 handler retries once then aborts (fail-loud), matching §13 ("repeated 429 → abort").
