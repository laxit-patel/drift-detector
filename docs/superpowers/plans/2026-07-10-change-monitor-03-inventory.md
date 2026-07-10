# Change Monitor — Plan 03: Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the inventory stage — for each active repo (from Plan 02's `active-repos.json`), walk its tree, parse dependency manifests + runtime pins into normalized records, detect *presence* of tracked third-party integrations (SP-API/eBay/Walmart/… even without an SDK), and emit `inventory.json` mapping each repo to KB techKeys — plus explicit coverage records so a repo that couldn't be parsed never silently reads as clean.

**Architecture:** Extractors are **pure functions over one file's text** (`extract(repo, path, content) -> [InventoryRecord]`), registered by filename in a registry (mirroring Plan 01's feed-adapter registry). Integration presence uses the GitLab blob-search API through the Plan-02 `GitLabClient`. Orchestration reads files via the client and dispatches to extractors; all GitLab I/O is injected so the whole plan is unit-testable with fakes. This extends `GitLabClient` with read methods (`get_tree`/`get_raw_file`/`search_blobs`) and consumes `active-repos.json`; it does not touch the KB or discovery logic.

**Tech Stack:** Python 3.11+, pytest, PyYAML (for the presence pattern table + `.tool-versions`), tomllib (stdlib, for pyproject). No new dependencies.

## Global Constraints

- Python **3.11+** (uses stdlib `tomllib`). Use the project venv: `source .venv/bin/activate` before python/pytest (Python 3.12; system python is 3.10).
- **No network in unit tests.** Extractors are pure over `content: str`. Orchestration + presence take an injected `GitLabClient` (tests pass a fake). No wall-clock in modules (`now` passed in where needed).
- **Direct dependencies only** — production deps (`dependencies`/`require`), NOT dev deps. **v1 is manifest-only:** record the *declared range* as the version-in-use, `parse_quality="unlocked"` when it's a range; reading lockfiles for exact locked versions is a documented Plan-04+ enhancement, not this plan.
- **Never silent-OK.** A repo with an unparseable manifest → a `manifestsUnparsed` coverage record. A repo with no recognized manifests and no integration hits → a `reposNoManifests` record. A per-repo GitLab error → a `reposErrored` record. Orchestration continues past any single repo's failure.
- **techKey scheme (must match the KB / feed registry):** libraries → `lib:<ecosystem>/<name-lowercased>`; runtimes → `runtime:<product>` (`node`/`php`/`python`/`dotnet`); integrations → the `api:*`/`fw:*` techKey from the pattern table. Presence-level join is by techKey; the version-in-use is a separate field.
- Package root `agent/`; tests in `tests/`; `pytest.ini` sets `pythonpath = .`. TDD throughout (failing test first). Explicit `git add` of only the files a task creates — never `git add -A`. Commit after every task (conventional-commit messages).

**This is Plan 03 of the pipeline** (04 = classify → report → deliver, which also adds the `registry` feed adapter fed by these package techKeys, and the LLM `html-changelog` structurer). Keep boundaries clean so Plan 04 consumes `inventory.json` without editing this code.

---

### Task 1: GitLab client read extensions (`get_tree`, `get_raw_file`, `search_blobs`)

**Files:**
- Modify: `agent/lib/gitlab_read.py`
- Test: `tests/test_gitlab_read_files.py`

**Interfaces:**
- Consumes: existing `GitLabClient.get`/`get_paginated`/`HttpResponse` (Plan 02).
- Produces (methods on `GitLabClient`):
  - `get(path, params=None, *, allow_404=False)` — gains a keyword-only `allow_404`; when true, a 404 returns the `HttpResponse` (status 404) instead of raising. Default false = unchanged behavior. 401/403 still raise.
  - `get_tree(project_id, ref) -> list[str]` — `GET /projects/:id/repository/tree?recursive=true&ref=<ref>` (paginated); returns blob paths only (`type == "blob"`).
  - `get_raw_file(project_id, path, ref) -> str | None` — `GET /projects/:id/repository/files/<url-encoded>/raw?ref=<ref>`; returns text, or `None` on 404.
  - `search_blobs(project_id, query) -> list[dict]` — `GET /projects/:id/search?scope=blobs&search=<query>` (paginated).

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_gitlab_read_files.py -v`
Expected: FAIL — `AttributeError: 'GitLabClient' object has no attribute 'get_tree'`

- [ ] **Step 3: Write minimal implementation**

In `agent/lib/gitlab_read.py`, add `from urllib.parse import quote` at the top. Change `get`'s signature and add the 404 branch:

```python
    def get(self, path: str, params: dict | None = None, *, allow_404: bool = False) -> HttpResponse:
        url = self._base + path
        headers = {"PRIVATE-TOKEN": self._token, "User-Agent": "change-monitor/1.0"}
        resp = self._do_get(url, headers, params)
        if resp.status == 429:
            try:
                wait = float(resp.headers.get("Retry-After", "1"))
            except ValueError:
                wait = 1.0
            time.sleep(wait)
            resp = self._do_get(url, headers, params)
            if resp.status == 429:
                raise GitLabUnreachable("rate limited (429) after retry")
        if resp.status == 401:
            raise GitLabAuthError(f"401 on {path}")
        if resp.status == 403:
            raise GitLabForbidden(path)
        if resp.status == 404 and allow_404:
            return resp
        if resp.status >= 400:
            raise GitLabError(f"{resp.status} on {path}")
        return resp
```

Append these methods to `GitLabClient`:

```python
    def get_tree(self, project_id: int, ref: str) -> list:
        items = self.get_paginated(
            f"/projects/{project_id}/repository/tree",
            {"recursive": "true", "ref": ref},
        )
        return [it["path"] for it in items if it.get("type") == "blob"]

    def get_raw_file(self, project_id: int, path: str, ref: str) -> "str | None":
        enc = quote(path, safe="")
        resp = self.get(
            f"/projects/{project_id}/repository/files/{enc}/raw",
            {"ref": ref}, allow_404=True,
        )
        return resp.body_text if resp.status == 200 else None

    def search_blobs(self, project_id: int, query: str) -> list:
        return self.get_paginated(
            f"/projects/{project_id}/search",
            {"scope": "blobs", "search": query},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_gitlab_read_files.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run full suite + commit**

Run: `pytest -q` → all green (65 + 5). Existing `get(...)` callers unaffected (new kwarg defaults false).
```bash
git add agent/lib/gitlab_read.py tests/test_gitlab_read_files.py
git commit -m "feat(inventory): GitLab client read methods (tree, raw file, blob search)"
```

---

### Task 2: Inventory models + extractor registry + techKey helpers

**Files:**
- Create: `agent/lib/inventory_models.py`, `agent/lib/extractors/__init__.py`
- Test: `tests/test_inventory_models.py`

**Interfaces:**
- Produces:
  - `InventoryRecord(repo, manifest_path, ecosystem, tech_key, name, kind, declared_range="", version_hint="", parse_quality="exact", notes="")` (frozen), `to_dict()`.
  - `UsedTech(repo, tech_key, evidence)` (frozen), `to_dict()`.
  - `library_techkey(ecosystem, name) -> str` = `f"lib:{ecosystem}/{name.strip().lower()}"`.
  - In `extractors/__init__.py`: `register(*basenames)` decorator; `extractor_for(path) -> callable | None` (matches on the path's basename); `registered_basenames() -> set`. Extractor contract: `extract(repo, path, content) -> list[InventoryRecord]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_inventory_models.py
from agent.lib.inventory_models import InventoryRecord, UsedTech, library_techkey
from agent.lib import extractors

def test_library_techkey_normalizes():
    assert library_techkey("npm", "AWS-SDK") == "lib:npm/aws-sdk"

def test_inventory_record_to_dict():
    r = InventoryRecord(repo="clients/a", manifest_path="package.json", ecosystem="npm",
                        tech_key="lib:npm/aws-sdk", name="aws-sdk", kind="library",
                        declared_range="^2.1.0", parse_quality="unlocked")
    d = r.to_dict()
    assert d["tech_key"] == "lib:npm/aws-sdk" and d["kind"] == "library"

def test_used_tech_to_dict():
    u = UsedTech(repo="clients/a", tech_key="api:amazon-sp-api", evidence="src/x.php: sellingpartnerapi")
    assert u.to_dict()["tech_key"] == "api:amazon-sp-api"

def test_registry_matches_by_basename():
    @extractors.register("frobfile.json")
    def fake(repo, path, content):
        return []
    assert extractors.extractor_for("a/b/frobfile.json") is fake
    assert extractors.extractor_for("a/b/other.json") is None
    assert "frobfile.json" in extractors.registered_basenames()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_inventory_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.inventory_models'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/inventory_models.py
"""Inventory data models + techKey helper. Pure data, no I/O."""
from __future__ import annotations

from dataclasses import dataclass, asdict


def library_techkey(ecosystem: str, name: str) -> str:
    return f"lib:{ecosystem}/{name.strip().lower()}"


@dataclass(frozen=True)
class InventoryRecord:
    repo: str
    manifest_path: str
    ecosystem: str            # npm | composer | python | docker
    tech_key: str             # lib:<eco>/<name>  or  runtime:<product>
    name: str
    kind: str                 # library | runtime
    declared_range: str = ""
    version_hint: str = ""    # for runtimes (e.g. Dockerfile FROM node:18 -> "18")
    parse_quality: str = "exact"   # exact | unlocked | best_effort
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UsedTech:
    repo: str
    tech_key: str             # api:* / fw:* from the pattern table
    evidence: str

    def to_dict(self) -> dict:
        return asdict(self)
```

```python
# agent/lib/extractors/__init__.py
"""Manifest/runtime extractor registry. Extractors are pure functions:
extract(repo, path, content) -> list[InventoryRecord], registered by filename basename."""
from __future__ import annotations

_BY_NAME: dict = {}


def register(*basenames: str):
    def deco(fn):
        for n in basenames:
            _BY_NAME[n] = fn
        return fn
    return deco


def extractor_for(path: str):
    return _BY_NAME.get(path.split("/")[-1])


def registered_basenames() -> set:
    return set(_BY_NAME)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_inventory_models.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/inventory_models.py agent/lib/extractors/__init__.py tests/test_inventory_models.py
git commit -m "feat(inventory): record models + extractor registry + techKey helper"
```

---

### Task 3: npm extractor (`package.json`)

**Files:**
- Create: `agent/lib/extractors/npm.py`
- Test: `tests/test_extractor_npm.py`

**Interfaces:**
- Consumes: `register` (Task 2), `InventoryRecord`, `library_techkey`.
- Produces: registered extractor for `"package.json"` — `extract(repo, path, content) -> list[InventoryRecord]`. Emits one `library` record per key in `dependencies` (production only; NOT `devDependencies`), `tech_key = library_techkey("npm", name)`, `declared_range` = the version string, `parse_quality = "unlocked"` if the range has a range operator (`^ ~ >= < * x || -` or space), else `"exact"`. Also emits a `runtime` record `runtime:node` if `engines.node` is present (`version_hint` = that value). Invalid JSON → returns a single `best_effort` record with `notes` and `tech_key="parse_error:npm"`? No — instead raise `ValueError` so orchestration records a coverage gap (see Task 8). Empty/absent `dependencies` → `[]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractor_npm.py
import pytest
from agent.lib.extractors import npm, extractor_for

PKG = '''{
  "name": "shop", "engines": {"node": ">=18"},
  "dependencies": {"aws-sdk": "^2.1500.0", "stripe": "12.0.0"},
  "devDependencies": {"jest": "^29.0.0"}
}'''

def test_npm_extracts_production_deps_and_runtime():
    recs = npm.extract("clients/a", "package.json", PKG)
    by_key = {r.tech_key: r for r in recs}
    assert "lib:npm/aws-sdk" in by_key and "lib:npm/stripe" in by_key
    assert "lib:npm/jest" not in by_key                 # devDependencies excluded
    assert by_key["lib:npm/aws-sdk"].declared_range == "^2.1500.0"
    assert by_key["lib:npm/aws-sdk"].parse_quality == "unlocked"    # has ^
    assert by_key["lib:npm/stripe"].parse_quality == "exact"        # pinned
    rt = by_key["runtime:node"]
    assert rt.kind == "runtime" and rt.version_hint == ">=18"

def test_npm_no_deps_returns_empty():
    assert npm.extract("clients/a", "package.json", '{"name":"x"}') == []

def test_npm_invalid_json_raises_valueerror():
    with pytest.raises(ValueError):
        npm.extract("clients/a", "package.json", "{ not json")

def test_npm_registered():
    assert extractor_for("a/package.json") is npm.extract
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_extractor_npm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.extractors.npm'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/extractors/npm.py
"""npm package.json extractor: production dependencies + node runtime."""
from __future__ import annotations

import json
import re

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register

_RANGE = re.compile(r"[\^~<>*x|\-\s]")


def _quality(spec: str) -> str:
    return "unlocked" if _RANGE.search(spec or "") else "exact"


@register("package.json")
def extract(repo: str, path: str, content: str) -> list:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid package.json: {exc}") from exc
    out: list = []
    for name, spec in (data.get("dependencies") or {}).items():
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="npm",
            tech_key=library_techkey("npm", name), name=name, kind="library",
            declared_range=str(spec), parse_quality=_quality(str(spec)),
        ))
    node = (data.get("engines") or {}).get("node")
    if node:
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="npm",
            tech_key="runtime:node", name="node", kind="runtime",
            version_hint=str(node), parse_quality=_quality(str(node)),
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_extractor_npm.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/extractors/npm.py tests/test_extractor_npm.py
git commit -m "feat(inventory): npm package.json extractor"
```

---

### Task 4: composer extractor (`composer.json`)

**Files:**
- Create: `agent/lib/extractors/composer.py`
- Test: `tests/test_extractor_composer.py`

**Interfaces:**
- Produces: registered extractor for `"composer.json"`. Emits a `library` record per key in `require` EXCEPT: `php` → a `runtime:php` record (`version_hint` = the constraint); any `ext-*` / `lib-*` / `composer-*` platform key → skipped. `tech_key = library_techkey("composer", name)`. `parse_quality` via the same range heuristic. `require-dev` skipped. Invalid JSON → `ValueError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractor_composer.py
import pytest
from agent.lib.extractors import composer, extractor_for

COMPOSER = '''{
  "require": {"php": "^8.1", "laravel/framework": "^10.0", "ext-json": "*", "stripe/stripe-php": "13.0.0"},
  "require-dev": {"phpunit/phpunit": "^10.0"}
}'''

def test_composer_extracts_require_and_php_runtime():
    recs = composer.extract("clients/b", "composer.json", COMPOSER)
    keys = {r.tech_key for r in recs}
    assert "lib:composer/laravel/framework" in keys
    assert "lib:composer/stripe/stripe-php" in keys
    assert "runtime:php" in keys
    assert not any("ext-json" in k for k in keys)                 # platform req skipped
    assert not any("phpunit" in k for k in keys)                  # require-dev skipped
    php = next(r for r in recs if r.tech_key == "runtime:php")
    assert php.kind == "runtime" and php.version_hint == "^8.1"

def test_composer_invalid_json_raises():
    with pytest.raises(ValueError):
        composer.extract("clients/b", "composer.json", "nope")

def test_composer_registered():
    assert extractor_for("x/composer.json") is composer.extract
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_extractor_composer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/extractors/composer.py
"""composer.json extractor: production require + php runtime; skips platform reqs."""
from __future__ import annotations

import json
import re

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register

_RANGE = re.compile(r"[\^~<>*|\-\s]")
_PLATFORM = re.compile(r"^(ext-|lib-|composer|composer-)")


def _quality(spec: str) -> str:
    return "unlocked" if _RANGE.search(spec or "") else "exact"


@register("composer.json")
def extract(repo: str, path: str, content: str) -> list:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid composer.json: {exc}") from exc
    out: list = []
    for name, spec in (data.get("require") or {}).items():
        low = name.lower()
        if low == "php":
            out.append(InventoryRecord(
                repo=repo, manifest_path=path, ecosystem="composer",
                tech_key="runtime:php", name="php", kind="runtime",
                version_hint=str(spec), parse_quality=_quality(str(spec)),
            ))
            continue
        if _PLATFORM.match(low):
            continue
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="composer",
            tech_key=library_techkey("composer", name), name=name, kind="library",
            declared_range=str(spec), parse_quality=_quality(str(spec)),
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_extractor_composer.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/extractors/composer.py tests/test_extractor_composer.py
git commit -m "feat(inventory): composer.json extractor"
```

---

### Task 5: python extractor (`requirements.txt` + `pyproject.toml`)

**Files:**
- Create: `agent/lib/extractors/python.py`
- Test: `tests/test_extractor_python.py`

**Interfaces:**
- Produces: registered extractors for `"requirements.txt"` and `"pyproject.toml"` (same module, two `register` decorators on two functions, or one function registered for both — the dispatcher passes the path so the function can branch on basename). Implement one `extract(repo, path, content)` registered for both names that branches on the basename.
  - `requirements.txt`: one `library` record per non-comment, non-`-r`/`-e`/`--flag` line; split on the first of `==`, `>=`, `<=`, `~=`, `!=`, `>`, `<` to get name + declared_range; a bare `name` (no operator) → `declared_range=""`, `parse_quality="unlocked"`. Skip blank lines and lines starting with `#` or `-`.
  - `pyproject.toml`: parse with `tomllib`; read `[project].dependencies` (list of PEP 508 strings) → library records; `[project].requires-python` → `runtime:python`. If `[project]` absent, try `[tool.poetry.dependencies]` (a table: name→constraint; skip the `python` key → `runtime:python`). Invalid TOML → `ValueError`.
  - `tech_key = library_techkey("python", <name-lowercased, extras/markers stripped>)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractor_python.py
import pytest
from agent.lib.extractors import python as py, extractor_for

REQS = """# prod deps
boto3==1.34.0
requests>=2.31
django
-r other.txt
"""

PYPROJECT = '''
[project]
requires-python = ">=3.11"
dependencies = ["boto3>=1.34", "stripe==8.0.0"]
'''

def test_requirements_txt():
    recs = py.extract("clients/c", "requirements.txt", REQS)
    by = {r.tech_key: r for r in recs}
    assert by["lib:python/boto3"].declared_range == "==1.34.0"
    assert by["lib:python/boto3"].parse_quality == "exact"
    assert by["lib:python/requests"].declared_range == ">=2.31"
    assert by["lib:python/django"].parse_quality == "unlocked"   # bare name
    assert not any("other.txt" in k for k in by)                 # -r line skipped

def test_pyproject_project_table():
    recs = py.extract("clients/c", "pyproject.toml", PYPROJECT)
    keys = {r.tech_key for r in recs}
    assert "lib:python/boto3" in keys and "lib:python/stripe" in keys
    assert "runtime:python" in keys
    rt = next(r for r in recs if r.tech_key == "runtime:python")
    assert rt.version_hint == ">=3.11"

def test_pyproject_invalid_raises():
    with pytest.raises(ValueError):
        py.extract("clients/c", "pyproject.toml", "not = = toml")

def test_python_registered_for_both():
    assert extractor_for("x/requirements.txt") is py.extract
    assert extractor_for("x/pyproject.toml") is py.extract
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_extractor_python.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/extractors/python.py
"""Python extractor: requirements.txt + pyproject.toml (project or poetry)."""
from __future__ import annotations

import re
import tomllib

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register

_OPS = ["==", ">=", "<=", "~=", "!=", ">", "<"]
_NAME = re.compile(r"^[A-Za-z0-9._-]+")


def _split_req(line: str):
    """('name', 'declared_range') from a PEP 508-ish string; range '' if bare."""
    core = line.split(";", 1)[0].split("#", 1)[0].strip()
    core = re.split(r"\[", core, 1)[0].strip()          # drop extras: name[extra]
    for op in _OPS:
        i = core.find(op)
        if i != -1:
            return core[:i].strip(), core[i:].strip()
    m = _NAME.match(core)
    return (m.group(0) if m else core.strip()), ""


def _lib(repo, path, name, rng):
    return InventoryRecord(
        repo=repo, manifest_path=path, ecosystem="python",
        tech_key=library_techkey("python", name), name=name, kind="library",
        declared_range=rng, parse_quality=("exact" if rng.startswith("==") else "unlocked"),
    )


def _from_requirements(repo, path, content):
    out = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name, rng = _split_req(line)
        if name:
            out.append(_lib(repo, path, name, rng))
    return out


def _from_pyproject(repo, path, content):
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid pyproject.toml: {exc}") from exc
    out = []
    project = data.get("project") or {}
    if project:
        for dep in project.get("dependencies") or []:
            name, rng = _split_req(dep)
            if name:
                out.append(_lib(repo, path, name, rng))
        rp = project.get("requires-python")
        if rp:
            out.append(InventoryRecord(repo=repo, manifest_path=path, ecosystem="python",
                       tech_key="runtime:python", name="python", kind="runtime",
                       version_hint=str(rp), parse_quality="unlocked"))
        return out
    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    for name, spec in poetry.items():
        if name.lower() == "python":
            out.append(InventoryRecord(repo=repo, manifest_path=path, ecosystem="python",
                       tech_key="runtime:python", name="python", kind="runtime",
                       version_hint=str(spec), parse_quality="unlocked"))
        else:
            out.append(_lib(repo, path, name, str(spec) if isinstance(spec, str) else ""))
    return out


@register("requirements.txt", "pyproject.toml")
def extract(repo: str, path: str, content: str) -> list:
    base = path.split("/")[-1]
    if base == "pyproject.toml":
        return _from_pyproject(repo, path, content)
    return _from_requirements(repo, path, content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_extractor_python.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/extractors/python.py tests/test_extractor_python.py
git commit -m "feat(inventory): python requirements.txt + pyproject.toml extractor"
```

---

### Task 6: Docker + runtime-pin extractor (`Dockerfile`, `.nvmrc`, `.python-version`, `.tool-versions`)

**Files:**
- Create: `agent/lib/extractors/runtime_pins.py`
- Test: `tests/test_extractor_runtime_pins.py`

**Interfaces:**
- Produces: registered extractor for `"Dockerfile"`, `".nvmrc"`, `".python-version"`, `".tool-versions"`. All emit `runtime` records only.
  - `Dockerfile`: each `FROM <image>[:tag]` line → map image → product via `_IMAGE_PRODUCT` (`node`→node, `php`→php, `python`→python, `mcr.microsoft.com/dotnet/*`→dotnet); `version_hint` = the tag (before any `-` variant, e.g. `18-alpine` → `18`). Unknown images → skipped (not an error). Multi-stage → one record per recognized FROM.
  - `.nvmrc` → `runtime:node`, hint = file text stripped (strip leading `v`).
  - `.python-version` → `runtime:python`, hint = text stripped.
  - `.tool-versions` → one record per line `"<tool> <version>"` where tool ∈ {nodejs→node, python, php}.
  - Never raises (these are best-effort text formats); unrecognized content → `[]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractor_runtime_pins.py
from agent.lib.extractors import runtime_pins as rp, extractor_for

DOCKER = """FROM node:18-alpine AS build
RUN npm ci
FROM nginx:1.25
FROM mcr.microsoft.com/dotnet/sdk:8.0
"""

def test_dockerfile_from_lines():
    recs = rp.extract("clients/a", "Dockerfile", DOCKER)
    by = {r.tech_key: r for r in recs}
    assert by["runtime:node"].version_hint == "18"        # 18-alpine -> 18
    assert by["runtime:dotnet"].version_hint == "8.0"
    assert "runtime:nginx" not in by                       # unknown image skipped

def test_nvmrc():
    recs = rp.extract("clients/a", ".nvmrc", "v20.11.0\n")
    assert recs[0].tech_key == "runtime:node" and recs[0].version_hint == "20.11.0"

def test_python_version():
    recs = rp.extract("clients/a", ".python-version", "3.11.6\n")
    assert recs[0].tech_key == "runtime:python" and recs[0].version_hint == "3.11.6"

def test_tool_versions():
    recs = rp.extract("clients/a", ".tool-versions", "nodejs 18.19.0\npython 3.11.6\nterraform 1.5\n")
    keys = {r.tech_key: r.version_hint for r in recs}
    assert keys.get("runtime:node") == "18.19.0" and keys.get("runtime:python") == "3.11.6"
    assert "runtime:terraform" not in keys

def test_registered():
    for f in ("Dockerfile", ".nvmrc", ".python-version", ".tool-versions"):
        assert extractor_for("a/" + f) is rp.extract
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_extractor_runtime_pins.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/extractors/runtime_pins.py
"""Runtime pins: Dockerfile FROM lines + .nvmrc/.python-version/.tool-versions."""
from __future__ import annotations

import re

from agent.lib.inventory_models import InventoryRecord
from agent.lib.extractors import register

_FROM = re.compile(r"^\s*FROM\s+(\S+)", re.IGNORECASE)
_TOOLMAP = {"nodejs": "node", "node": "node", "python": "python", "php": "php"}


def _runtime(repo, path, product, hint):
    return InventoryRecord(repo=repo, manifest_path=path, ecosystem="docker",
                           tech_key=f"runtime:{product}", name=product, kind="runtime",
                           version_hint=hint, parse_quality="best_effort")


def _image_product(image: str):
    low = image.lower()
    if low.startswith("mcr.microsoft.com/dotnet"):
        return "dotnet"
    base = low.rsplit("/", 1)[-1]           # strip registry/org
    for prod in ("node", "php", "python"):
        if base == prod:
            return prod
    return None


def _tag(image: str) -> str:
    if ":" not in image:
        return ""
    tag = image.rsplit(":", 1)[1]
    return tag.split("-", 1)[0]             # 18-alpine -> 18


@register("Dockerfile", ".nvmrc", ".python-version", ".tool-versions")
def extract(repo: str, path: str, content: str) -> list:
    base = path.split("/")[-1]
    out: list = []
    if base == "Dockerfile":
        for line in content.splitlines():
            m = _FROM.match(line)
            if not m:
                continue
            product = _image_product(m.group(1))
            if product:
                out.append(_runtime(repo, path, product, _tag(m.group(1))))
    elif base == ".nvmrc":
        v = content.strip().lstrip("v")
        if v:
            out.append(_runtime(repo, path, "node", v))
    elif base == ".python-version":
        v = content.strip()
        if v:
            out.append(_runtime(repo, path, "python", v))
    elif base == ".tool-versions":
        for line in content.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].lower() in _TOOLMAP:
                out.append(_runtime(repo, path, _TOOLMAP[parts[0].lower()], parts[1]))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_extractor_runtime_pins.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/extractors/runtime_pins.py tests/test_extractor_runtime_pins.py
git commit -m "feat(inventory): Dockerfile + runtime-pin extractor"
```

---

### Task 7: Integration-presence detector (blob search)

**Files:**
- Create: `agent/lib/presence.py`, `agent/patterns.yaml`
- Test: `tests/test_presence.py`

**Interfaces:**
- Consumes: `GitLabClient.search_blobs` (Task 1), `GitLabError` (Plan 02), `UsedTech` (Task 2).
- Produces:
  - `load_patterns(path) -> list[dict]` — reads `patterns.yaml`: a list of `{techKey, query, label}` (query = the literal blob-search string; techKey = the KB integration key).
  - `detect_presence(client, project_id, repo, patterns) -> tuple[list[UsedTech], str | None]` — for each pattern, `client.search_blobs(project_id, query)`; on any hit, emit ONE `UsedTech(repo, techKey, evidence="<path>: <query>")` (first hit only, dedupe by techKey). Returns `(used, None)` normally; if `search_blobs` raises `GitLabError` (search disabled/unavailable on the instance), returns `([], "<reason>")` so the caller records a coverage note (search-unavailable) rather than silently reporting "no integrations".

- [ ] **Step 1: Write the failing test**

```python
# tests/test_presence.py
from agent.lib.presence import detect_presence, load_patterns
from agent.lib.gitlab_read import GitLabError

PATTERNS = [
    {"techKey": "api:amazon-sp-api", "query": "sellingpartnerapi", "label": "Amazon SP-API"},
    {"techKey": "api:walmart-marketplace", "query": "marketplace.walmartapis.com", "label": "Walmart"},
]

class FakeClient:
    def __init__(self, hits, raise_exc=None):
        self._hits = hits            # query -> list of blob dicts
        self._raise = raise_exc
    def search_blobs(self, project_id, query):
        if self._raise:
            raise self._raise
        return self._hits.get(query, [])

def test_detect_presence_emits_used_tech_on_hit():
    client = FakeClient({"sellingpartnerapi": [{"path": "src/Amazon.php", "data": "...sellingpartnerapi..."}]})
    used, note = detect_presence(client, 1, "clients/a", PATTERNS)
    assert note is None
    assert len(used) == 1
    assert used[0].tech_key == "api:amazon-sp-api"
    assert "src/Amazon.php" in used[0].evidence

def test_detect_presence_no_hits():
    used, note = detect_presence(FakeClient({}), 1, "clients/a", PATTERNS)
    assert used == [] and note is None

def test_detect_presence_search_unavailable_returns_note():
    used, note = detect_presence(FakeClient({}, raise_exc=GitLabError("404 search")), 1, "clients/a", PATTERNS)
    assert used == [] and note is not None      # coverage note, not silent

def test_load_patterns(tmp_path):
    p = tmp_path / "patterns.yaml"
    p.write_text("- {techKey: api:ebay, query: api.ebay.com, label: eBay}\n")
    pats = load_patterns(str(p))
    assert pats[0]["techKey"] == "api:ebay"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_presence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.presence'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/presence.py
"""Integration-presence detection via GitLab blob search. Presence-level only:
'this repo uses SP-API', not which endpoint."""
from __future__ import annotations

import yaml

from agent.lib.inventory_models import UsedTech
from agent.lib.gitlab_read import GitLabError


def load_patterns(path: str) -> list:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def detect_presence(client, project_id: int, repo: str, patterns: list):
    used: list = []
    seen: set = set()
    for pat in patterns:
        tk = pat["techKey"]
        if tk in seen:
            continue
        try:
            hits = client.search_blobs(project_id, pat["query"])
        except GitLabError as exc:
            return [], f"blob search unavailable: {exc}"
        if hits:
            path = hits[0].get("path", "?")
            used.append(UsedTech(repo=repo, tech_key=tk, evidence=f"{path}: {pat['query']}"))
            seen.add(tk)
    return used, None
```

```yaml
# agent/patterns.yaml — integration presence queries (literal blob-search strings).
# Seeded from spec §3.6 verified feed set; extend as new integrations appear.
- { techKey: api:amazon-sp-api,        query: sellingpartnerapi,            label: Amazon SP-API }
- { techKey: api:amazon-sp-api,        query: mws.amazonservices,           label: Amazon MWS (legacy) }
- { techKey: api:ebay,                 query: api.ebay.com,                 label: eBay }
- { techKey: api:walmart-marketplace,  query: marketplace.walmartapis.com,  label: Walmart Marketplace }
- { techKey: api:shopify,              query: myshopify.com/admin/api,      label: Shopify Admin API }
- { techKey: api:stripe,               query: api.stripe.com,               label: Stripe }
- { techKey: api:paypal,               query: api.paypal.com,               label: PayPal }
- { techKey: api:twilio,               query: api.twilio.com,               label: Twilio }
- { techKey: api:meta-graph,           query: graph.facebook.com,           label: Meta Graph API }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_presence.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/presence.py agent/patterns.yaml tests/test_presence.py
git commit -m "feat(inventory): integration-presence detector (blob search) + pattern table"
```

---

### Task 8: Inventory orchestration → `inventory.json`

**Files:**
- Create: `agent/inventory.py`
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: `GitLabClient` (`get_tree`/`get_raw_file`, Task 1), `extractor_for` (Task 2), `detect_presence`/`load_patterns` (Task 7), `GitLabError`/`GitLabForbidden` (Plan 02), models (Task 2).
- Produces:
  - `inventory_repo(client, repo_entry, patterns) -> dict` — for one `active-repos.json` entry `{id, path_with_namespace, scanned_ref, ...}`: `get_tree`; for each path whose basename has a registered extractor, `get_raw_file` + run it (a `ValueError` from an extractor → a `manifestsUnparsed` note; a `None` file → skip); run `detect_presence`. Returns `{"records": [...], "usedTechs": [...], "notes": {"unparsed": [...], "noManifest": bool, "presenceNote": str|None, "repoError": str|None}}`. A `GitLabForbidden`/`GitLabError` from `get_tree` → `{"records": [], "usedTechs": [], "notes": {"repoError": "<reason>", ...}}` (repo becomes a coverage gap, never raises).
  - `build_inventory(client, active_repos: dict, patterns, now: str) -> dict` — iterates `active_repos["active"]`, aggregates all records + usedTechs, and builds the `coverage` block (`reposScanned`, `reposNoManifests`, `manifestsUnparsed`, `reposErrored`, `presenceUnavailable`). Never raises on a single repo.
  - `write_inventory(path, inv) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_inventory.py
import json
from agent import inventory
from agent.lib.gitlab_read import GitLabForbidden

PATTERNS = [{"techKey": "api:amazon-sp-api", "query": "sellingpartnerapi", "label": "SP-API"}]

class FakeClient:
    def __init__(self, trees, files, hits=None, tree_error=None):
        self._trees = trees          # id -> [paths]
        self._files = files          # (id, path) -> content or None
        self._hits = hits or {}      # query -> blobs
        self._tree_error = tree_error
    def get_tree(self, pid, ref):
        if self._tree_error:
            raise self._tree_error
        return self._trees.get(pid, [])
    def get_raw_file(self, pid, path, ref):
        return self._files.get((pid, path))
    def search_blobs(self, pid, query):
        return self._hits.get(query, [])

def _entry(pid, path, ref="main"):
    return {"id": pid, "path_with_namespace": path, "scanned_ref": ref}

def test_inventory_repo_parses_manifest_and_presence():
    client = FakeClient(
        trees={1: ["package.json", "README.md"]},
        files={(1, "package.json"): '{"dependencies":{"stripe":"12.0.0"}}'},
        hits={"sellingpartnerapi": [{"path": "src/A.php"}]},
    )
    res = inventory.inventory_repo(client, _entry(1, "clients/a"), PATTERNS)
    assert any(r.tech_key == "lib:npm/stripe" for r in res["records"])
    assert any(u.tech_key == "api:amazon-sp-api" for u in res["usedTechs"])
    assert res["notes"]["noManifest"] is False

def test_inventory_repo_no_manifests_flagged():
    client = FakeClient(trees={1: ["README.md", "LICENSE"]}, files={})
    res = inventory.inventory_repo(client, _entry(1, "clients/a"), PATTERNS)
    assert res["records"] == [] and res["notes"]["noManifest"] is True

def test_inventory_repo_unparsable_manifest_flagged():
    client = FakeClient(trees={1: ["package.json"]}, files={(1, "package.json"): "{ broken"})
    res = inventory.inventory_repo(client, _entry(1, "clients/a"), PATTERNS)
    assert res["records"] == []
    assert res["notes"]["unparsed"] and "package.json" in res["notes"]["unparsed"][0]["path"]

def test_inventory_repo_tree_forbidden_is_coverage_gap():
    client = FakeClient(trees={}, files={}, tree_error=GitLabForbidden("/projects/1"))
    res = inventory.inventory_repo(client, _entry(1, "clients/secret"), PATTERNS)
    assert res["notes"]["repoError"] is not None and res["records"] == []

def test_build_inventory_aggregates_and_covers(tmp_path):
    client = FakeClient(
        trees={1: ["package.json"], 2: ["README.md"]},
        files={(1, "package.json"): '{"dependencies":{"stripe":"12.0.0"}}'},
    )
    active = {"active": [_entry(1, "clients/a"), _entry(2, "clients/b")]}
    inv = inventory.build_inventory(client, active, PATTERNS, "2026-07-12")
    assert inv["coverage"]["reposScanned"] == 2
    assert any(r["tech_key"] == "lib:npm/stripe" for r in inv["records"])
    assert {"repo": "clients/b", "reason": "no manifests detected"} in inv["coverage"]["reposNoManifests"]
    out = tmp_path / "inventory.json"
    inventory.write_inventory(str(out), inv)
    assert json.loads(out.read_text())["coverage"]["reposScanned"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_inventory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.inventory'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/inventory.py
"""Inventory orchestration: per active repo, parse manifests + detect integrations,
aggregate into inventory.json with explicit coverage records."""
from __future__ import annotations

import json

from agent.lib.extractors import extractor_for
# Import extractors so they self-register:
from agent.lib.extractors import npm, composer, python, runtime_pins  # noqa: F401
from agent.lib.presence import detect_presence
from agent.lib.gitlab_read import GitLabError, GitLabForbidden


def inventory_repo(client, repo_entry: dict, patterns: list) -> dict:
    repo = repo_entry["path_with_namespace"]
    pid = repo_entry["id"]
    ref = repo_entry.get("scanned_ref") or repo_entry.get("default_branch")
    notes = {"unparsed": [], "noManifest": False, "presenceNote": None, "repoError": None}
    try:
        paths = client.get_tree(pid, ref)
    except (GitLabForbidden, GitLabError) as exc:
        notes["repoError"] = str(exc)
        return {"records": [], "usedTechs": [], "notes": notes}

    records: list = []
    matched_any = False
    for path in paths:
        fn = extractor_for(path)
        if not fn:
            continue
        matched_any = True
        content = client.get_raw_file(pid, path, ref)
        if content is None:
            continue
        try:
            records.extend(fn(repo, path, content))
        except ValueError as exc:
            notes["unparsed"].append({"path": path, "reason": str(exc)})

    used, presence_note = detect_presence(client, pid, repo, patterns)
    notes["presenceNote"] = presence_note
    notes["noManifest"] = (not matched_any) and (not used)
    return {"records": records, "usedTechs": used, "notes": notes}


def build_inventory(client, active_repos: dict, patterns: list, now: str) -> dict:
    all_records: list = []
    all_used: list = []
    cov = {"reposScanned": 0, "reposNoManifests": [], "manifestsUnparsed": [],
           "reposErrored": [], "presenceUnavailable": []}
    for entry in active_repos.get("active", []):
        repo = entry["path_with_namespace"]
        cov["reposScanned"] += 1
        res = inventory_repo(client, entry, patterns)
        all_records.extend(r.to_dict() for r in res["records"])
        all_used.extend(u.to_dict() for u in res["usedTechs"])
        n = res["notes"]
        if n["repoError"]:
            cov["reposErrored"].append({"repo": repo, "reason": n["repoError"]})
        if n["noManifest"]:
            cov["reposNoManifests"].append({"repo": repo, "reason": "no manifests detected"})
        for u in n["unparsed"]:
            cov["manifestsUnparsed"].append({"repo": repo, "path": u["path"], "reason": u["reason"]})
        if n["presenceNote"]:
            cov["presenceUnavailable"].append({"repo": repo, "reason": n["presenceNote"]})
    return {"runDate": now, "records": all_records, "usedTechs": all_used, "coverage": cov}


def write_inventory(path: str, inv: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(inv, fh, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_inventory.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/inventory.py tests/test_inventory.py
git commit -m "feat(inventory): orchestration -> inventory.json with coverage records"
```

---

### Task 9: CLI `inventory` command + README

**Files:**
- Modify: `agent/cli.py`
- Create: `docs/change-monitor-plan03-README.md`
- Test: `tests/test_cli_inventory.py`

**Interfaces:**
- Consumes: `load_config`, `GitLabClient`, `inventory.build_inventory`/`write_inventory`, `presence.load_patterns`.
- Produces: an `inventory` subcommand: `inventory --config <path> --active <active-repos.json> --out <inventory.json> [--patterns agent/patterns.yaml]`. Reads the active-repos file, builds a `GitLabClient` from `config.gitlab` (token from env; rc 2 if missing config/token), runs `build_inventory`, writes output, prints a summary (records, usedTechs, coverage counts). Accepts an injected `client` kwarg via `main(argv, *, client=None)` (the same DI seam Plan 02 added) so the smoke test is network-free.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_inventory.py
import json, textwrap
from agent import cli

class FakeClient:
    def get_tree(self, pid, ref): return ["package.json"]
    def get_raw_file(self, pid, path, ref): return '{"dependencies":{"stripe":"12.0.0"}}'
    def search_blobs(self, pid, query): return []

def _files(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        kb: { root: kb/ }
        gitlab: { baseUrl: https://gl.test, tokenEnv: GITLAB_READ_TOKEN, expectedNamespaces: [clients] }
        feeds:
          - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }
    """))
    active = tmp_path / "active-repos.json"
    active.write_text(json.dumps({"active": [{"id": 1, "path_with_namespace": "clients/a", "scanned_ref": "main"}]}))
    pats = tmp_path / "patterns.yaml"
    pats.write_text("- {techKey: api:stripe, query: api.stripe.com, label: Stripe}\n")
    return str(cfg), str(active), str(pats)

def test_inventory_cli_writes_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITLAB_READ_TOKEN", "tok")
    cfg, active, pats = _files(tmp_path)
    out = tmp_path / "inventory.json"
    rc = cli.main(["inventory", "--config", cfg, "--active", active, "--out", str(out),
                   "--patterns", pats], client=FakeClient())
    assert rc == 0
    data = json.loads(out.read_text())
    assert any(r["tech_key"] == "lib:npm/stripe" for r in data["records"])
    assert data["coverage"]["reposScanned"] == 1
    assert "clients/a" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_cli_inventory.py -v`
Expected: FAIL — `SystemExit: 2` (unknown subcommand `inventory`) or an assertion error

- [ ] **Step 3: Write minimal implementation**

In `agent/cli.py`, add `from agent import inventory as inventory_mod` and `from agent.lib.presence import load_patterns`. Add `_cmd_inventory`, register the subparser, and route it (mirroring `_cmd_discover`'s injected-client pattern):

```python
def _cmd_inventory(args, client=None) -> int:
    cfg = load_config(args.config)
    if cfg.gitlab is None:
        print("ERROR: config has no `gitlab` section; cannot build inventory.")
        return 2
    if client is None:
        token = os.environ.get(cfg.gitlab.token_env)
        if not token:
            print(f"ERROR: env var {cfg.gitlab.token_env} is not set.")
            return 2
        client = GitLabClient(cfg.gitlab.base_url, token)
    with open(args.active, "r", encoding="utf-8") as fh:
        active = json.load(fh)
    patterns = load_patterns(args.patterns)
    inv = inventory_mod.build_inventory(client, active, patterns, args.now)
    inventory_mod.write_inventory(args.out, inv)
    cov = inv["coverage"]
    print(f"Inventory: {len(inv['records'])} dep/runtime records, {len(inv['usedTechs'])} integrations "
          f"across {cov['reposScanned']} repos.")
    for repo in {r['repo'] for r in inv['records']} | {u['repo'] for u in inv['usedTechs']}:
        print(f"  {repo}")
    return 0
```

Add `import json` at the top if not already present, add the subparser and routing in `main`:

```python
    pn = sub.add_parser("inventory")
    pn.add_argument("--config", required=True)
    pn.add_argument("--active", required=True)
    pn.add_argument("--out", required=True)
    pn.add_argument("--patterns", default="agent/patterns.yaml")
    pn.add_argument("--now", default="")
    pn.set_defaults(func=_cmd_inventory)
```

and in `main`'s dispatch, extend the injected-client routing:

```python
    args = p.parse_args(argv)
    if args.func in (_cmd_discover, _cmd_inventory):
        return args.func(args, client=client)
    return args.func(args)
```

Create `docs/change-monitor-plan03-README.md`:

```markdown
# Change Monitor — Plan 03 (Inventory)

Turns active-repos.json into inventory.json: manifest/runtime records + integration presence.

## Run
```bash
source .venv/bin/activate
export GITLAB_READ_TOKEN=<read_api token>
python -m agent.cli discover  --config config.yaml --now 2026-07-12 --out active-repos.json
python -m agent.cli inventory --config config.yaml --active active-repos.json --out inventory.json --now 2026-07-12
```
v1 is manifest-only (declared ranges, `parse_quality="unlocked"` for ranges); lockfile-exact
versions are a Plan-04+ enhancement. Extractors: npm/composer/python/Docker+pin-files. Integration
presence uses GitLab blob search; if search is disabled on the instance, affected repos are recorded
under `coverage.presenceUnavailable` (never silently "no integrations"). Repos with no manifests /
unparseable manifests / GitLab errors land in explicit `coverage.*` records.

## Next
- Plan 04: Claude classify (severity + used-tech match) + trust gate, delta, report, Chat, run.sh,
  dead-man's switch; plus the `registry` feed adapter fed by these `lib:*` techKeys.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_cli_inventory.py -v`
Expected: PASS (1 passed). Also run `pytest -q` — full suite green; confirm `discover`/`ingest`/`drift` still pass.

- [ ] **Step 5: Commit**

```bash
git add agent/cli.py tests/test_cli_inventory.py docs/change-monitor-plan03-README.md
git commit -m "feat(inventory): CLI inventory command + Plan 03 README"
```

---

## Self-Review

**Spec coverage (Plan 03 slice of the v2 spec):**
- §3.4 GitLab read client: `get_tree`/`get_raw_file`/`search_blobs` → Task 1 ✓ (completes the read client begun in Plan 02).
- §3.5 Manifest/runtime parser (registry pattern, per-ecosystem extractors, direct deps only, runtime precedence, unparseable → coverage gap) → Tasks 2–6, 8 ✓ (npm/composer/python/Docker first, per the decided v1 set; lockfile precedence documented as a deferred trim).
- §3.6 Integration presence (SP-API/eBay/Walmart/… even without an SDK, via search) → Task 7 ✓ (`patterns.yaml` seeded from the verified feed set).
- §5.2 inventory join carries KB techKeys (`lib:*`, `runtime:*`, `api:*`) → Task 2 helpers + all extractors + presence ✓
- §13 never-silent-OK (no-manifest / unparsed / repo-error / search-unavailable coverage records) → Task 8 ✓
- Deferred (correctly, stated): lockfile-exact versions; go/ruby/dotnet-nuget/java extractors (add when a real run shows them); the `registry` feed adapter and the classify/report/deliver stage → Plan 04.

**Placeholder scan:** none — every step has complete, runnable code. The injected `client` seams are real DI (matching Plan 02's `_cmd_discover`), not stubs; production defaults construct a real `GitLabClient`.

**Type consistency:** `InventoryRecord`/`UsedTech` field names (`repo`, `manifest_path`, `ecosystem`, `tech_key`, `name`, `kind`, `declared_range`, `version_hint`, `parse_quality`, `notes`) are identical across Tasks 2–8. The extractor contract `extract(repo, path, content) -> list[InventoryRecord]` is uniform across Tasks 3–6 and dispatched via `extractor_for(path)` in Task 8. `detect_presence(client, project_id, repo, patterns) -> (list[UsedTech], str|None)` matches between Task 7 and its Task 8 caller. `build_inventory(client, active_repos, patterns, now)` / `inventory_repo(client, repo_entry, patterns)` names match between Task 8 and the Task 9 CLI. `library_techkey`, `search_blobs`, and the `active-repos.json` entry shape (`id`, `path_with_namespace`, `scanned_ref`) are consumed consistently with how Plan 02 produced them.

**Known limitations (documented, not gaps):** (1) manifest-only versions — a repo pinning via lockfile only will show the declared range, flagged `unlocked`; acceptable at presence-level, Plan 04+ can read lockfiles. (2) Presence depends on GitLab blob search being enabled; when it isn't, repos are recorded under `presenceUnavailable` (a visible coverage gap), and a future fallback (`git clone --depth 1` + local grep, per spec §3.6) can fill it. (3) `dependencies` only (not `devDependencies`/`require-dev`) — deliberate, to focus on production integrations.
