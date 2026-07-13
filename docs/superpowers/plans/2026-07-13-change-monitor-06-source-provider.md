# Change Monitor — Plan 06: Source Provider Abstraction + Local Provider

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the project source pluggable. Extract the read-side contract the discovery + inventory stages already depend on into a `SourceProvider` seam, add a **Local-folder provider** (scan a directory of git repos on disk — no token, no network), and add a `source:` config selector + `make_provider` factory so `discover`/`inventory` work against GitLab *or* a local folder. Everything downstream of inventory is already source-agnostic and is untouched.

**Architecture:** `discover(config, client, now)` and `build_inventory(client, ...)` already take an injected `client` and only ever call five methods: `list_candidate_projects`, `has_commit_since`, `get_tree`, `get_raw_file`, `search_blobs`. `GitLabClient` already implements all five. This plan (1) documents that as a `SourceProvider` Protocol, (2) implements the same five for a local folder (filesystem for tree/file/search; `git log` — behind an injected runner — for activity dates), and (3) adds a `make_provider(config)` factory the CLI uses instead of hardcoding `GitLabClient`. No changes to the KB, candidates, classify, delta, report, or delivery.

**Tech Stack:** Python 3.11+, pytest. Local provider uses stdlib (`subprocess` for `git`, `os`/`pathlib`); no new dependencies.

## Global Constraints

- Python **3.11+**. Use the project venv: `source .venv/bin/activate` before python/pytest.
- **No network in unit tests.** The GitLab path already injects `request`; the Local provider injects its `git` command runner (`run`) and reads a `tmp_path` folder. Tests never shell out to a real remote.
- **Read-only on sources.** The Local provider only reads the working tree / runs read-only `git log`/`git grep`-equivalent; it never writes to scanned repos. (Delivery to the reports repo is unchanged and out of scope here.)
- **The five-method contract is the seam.** A provider MUST implement: `list_candidate_projects(since_iso) -> list[dict]`, `has_commit_since(project_id, since_iso, ref=None) -> str|None`, `get_tree(project_id, ref) -> list[str]`, `get_raw_file(project_id, path, ref) -> str|None`, `search_blobs(project_id, query) -> list[dict]`. `GitLabClient` already conforms — do not change it.
- **Never silent-OK carries through.** The Local provider surfaces per-repo problems the same way (a missing repo / unreadable file → the existing coverage-gap paths in `discover`/`inventory` handle it).
- Package root `agent/`; tests in `tests/`. TDD throughout (failing test first). Explicit `git add` of only a task's files. Commit after every task.

**This is Plan 06** (additive; GitLab path unchanged). GitHub is a clean follow-up: add a `GitHubProvider` implementing the same five methods + a `source.type: github` branch in the factory — no other change.

---

### Task 1: Local provider — filesystem reads (tree / raw file / blob search)

**Files:**
- Create: `agent/lib/local_provider.py`
- Test: `tests/test_local_provider_fs.py`

**Interfaces:**
- Produces `LocalProvider(root, *, run=<git>)` (the `run` seam is added in Task 2; for now accept and ignore it) with:
  - `_repo_path(project_id) -> pathlib.Path` — resolve an int project id to its repo dir via an index built at construction (scan `root` for immediate subdirectories containing a `.git`; sort by path; 1-based ids). Expose `projects` = the ordered list of `(id, rel_path, abs_path)`.
  - `get_tree(project_id, ref) -> list[str]` — walk the repo, return file paths relative to the repo root, skipping `.git`, `node_modules`, `vendor`, `.venv`, `dist`, `build`, `target`. `ref` ignored (working tree).
  - `get_raw_file(project_id, path, ref) -> str|None` — read `<repo>/<path>` as text; `None` if missing or unreadable.
  - `search_blobs(project_id, query) -> list[dict]` — walk text files (skip the same dirs + files >1 MB), return `[{"path": rel}]` for each file whose content contains `query` (literal substring). Binary/undecodable files skipped.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_local_provider_fs.py
from agent.lib.local_provider import LocalProvider

def _make_repo(root, name, files):
    d = root / name
    (d / ".git").mkdir(parents=True)          # marks it a repo
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d

def test_discovers_git_repos_and_ids(tmp_path):
    _make_repo(tmp_path, "acme", {"package.json": "{}"})
    _make_repo(tmp_path, "beta", {"composer.json": "{}"})
    (tmp_path / "not-a-repo").mkdir()          # no .git -> ignored
    p = LocalProvider(str(tmp_path))
    paths = sorted(rel for _id, rel, _abs in p.projects)
    assert paths == ["acme", "beta"]
    assert all(isinstance(i, int) for i, _, _ in p.projects)

def test_get_tree_skips_junk(tmp_path):
    _make_repo(tmp_path, "acme", {"package.json": "{}", "src/app.js": "x",
                                  "node_modules/dep/i.js": "y"})
    p = LocalProvider(str(tmp_path))
    pid = p.projects[0][0]
    tree = set(p.get_tree(pid, "main"))
    assert "package.json" in tree and "src/app.js" in tree
    assert not any("node_modules" in t for t in tree)

def test_get_raw_file(tmp_path):
    _make_repo(tmp_path, "acme", {"package.json": '{"name":"acme"}'})
    p = LocalProvider(str(tmp_path)); pid = p.projects[0][0]
    assert p.get_raw_file(pid, "package.json", "main") == '{"name":"acme"}'
    assert p.get_raw_file(pid, "missing.txt", "main") is None

def test_search_blobs_substring(tmp_path):
    _make_repo(tmp_path, "acme", {"src/Amazon.php": "use sellingpartnerapi client",
                                  "README.md": "nothing here"})
    p = LocalProvider(str(tmp_path)); pid = p.projects[0][0]
    hits = p.search_blobs(pid, "sellingpartnerapi")
    assert len(hits) == 1 and hits[0]["path"] == "src/Amazon.php"
    assert p.search_blobs(pid, "nonexistent") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_local_provider_fs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.local_provider'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/local_provider.py
"""Local-folder SourceProvider: scan a directory of git repos on disk. No token, no network.
Implements the same five read methods as GitLabClient (the SourceProvider seam)."""
from __future__ import annotations

from pathlib import Path

_SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "dist", "build", "target", "__pycache__"}
_MAX_BYTES = 1_000_000


class LocalProvider:
    def __init__(self, root: str, *, run=None):
        self.root = Path(root)
        self._run = run                     # git runner, wired in Task 2
        repos = sorted(d for d in self.root.iterdir()
                       if d.is_dir() and (d / ".git").exists())
        self.projects = [(i + 1, d.name, d) for i, d in enumerate(repos)]
        self._by_id = {pid: abs_ for pid, _rel, abs_ in self.projects}

    def _repo_path(self, project_id: int) -> Path:
        return self._by_id[project_id]

    def _walk_files(self, base: Path):
        for p in base.rglob("*"):
            if p.is_dir():
                continue
            if any(part in _SKIP_DIRS for part in p.relative_to(base).parts):
                continue
            yield p

    def get_tree(self, project_id: int, ref: str) -> list:
        base = self._repo_path(project_id)
        return [str(p.relative_to(base)) for p in self._walk_files(base)]

    def get_raw_file(self, project_id: int, path: str, ref: str) -> "str | None":
        f = self._repo_path(project_id) / path
        try:
            return f.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, UnicodeDecodeError, OSError):
            return None

    def search_blobs(self, project_id: int, query: str) -> list:
        base = self._repo_path(project_id)
        hits = []
        for p in self._walk_files(base):
            try:
                if p.stat().st_size > _MAX_BYTES:
                    continue
                if query in p.read_text(encoding="utf-8"):
                    hits.append({"path": str(p.relative_to(base))})
            except (UnicodeDecodeError, OSError):
                continue
        return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_local_provider_fs.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/local_provider.py tests/test_local_provider_fs.py
git commit -m "feat(source): LocalProvider filesystem reads (tree/raw-file/blob-search)"
```

---

### Task 2: Local provider — git activity (discover-side methods)

**Files:**
- Modify: `agent/lib/local_provider.py`
- Test: `tests/test_local_provider_git.py`

**Interfaces:**
- Adds to `LocalProvider`:
  - a default git runner `_default_run(args: list[str]) -> str` (`subprocess.run(["git", ...], capture_output, text)`, returns stdout stripped; empty string on non-zero) — `# pragma: no cover`.
  - `list_candidate_projects(since_iso) -> list[dict]` — for each repo, `git -C <path> log -1 --format=%cI` for `last_activity_at` and `git -C <path> rev-parse --abbrev-ref HEAD` for `default_branch`; return `[{id, path_with_namespace, default_branch, last_activity_at}]` for ALL repos (the discover stage applies the window; here `since_iso` is accepted for signature parity but not used to pre-filter — matches how GitLab returns candidates then discover verifies).
  - `has_commit_since(project_id, since_iso, ref=None) -> str|None` — `git -C <path> log -1 --since=<since_iso> --format=%cI [ref]`; return the committed date string, or `None` if empty.
  - The constructor's `run` param (default `_default_run`) is the injected seam; tests pass a fake `run`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_local_provider_git.py
from agent.lib.local_provider import LocalProvider

def _make_repo(root, name):
    (root / name / ".git").mkdir(parents=True)
    (root / name / "f.txt").write_text("x")
    return root / name

class FakeGit:
    """Scripts git output by matching a substring of the joined command."""
    def __init__(self, rules): self.rules = rules; self.calls = []
    def __call__(self, args):
        joined = " ".join(args); self.calls.append(joined)
        for key, out in self.rules.items():
            if key in joined:
                return out
        return ""

def test_list_candidate_projects(tmp_path):
    _make_repo(tmp_path, "acme")
    run = FakeGit({"rev-parse --abbrev-ref HEAD": "main",
                   "log -1 --format=%cI": "2026-07-01T10:00:00+00:00"})
    p = LocalProvider(str(tmp_path), run=run)
    got = p.list_candidate_projects("2026-04-14")
    assert got[0]["path_with_namespace"] == "acme"
    assert got[0]["default_branch"] == "main"
    assert got[0]["last_activity_at"].startswith("2026-07-01")
    assert isinstance(got[0]["id"], int)

def test_has_commit_since_returns_date_or_none(tmp_path):
    _make_repo(tmp_path, "acme")
    p1 = LocalProvider(str(tmp_path), run=FakeGit({"--since": "2026-06-20T00:00:00+00:00"}))
    pid = p1.projects[0][0]
    assert p1.has_commit_since(pid, "2026-04-14").startswith("2026-06-20")
    p2 = LocalProvider(str(tmp_path), run=FakeGit({}))   # empty -> no commit in window
    assert p2.has_commit_since(p2.projects[0][0], "2026-04-14") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_local_provider_git.py -v`
Expected: FAIL — `AttributeError: 'LocalProvider' object has no attribute 'list_candidate_projects'`

- [ ] **Step 3: Write minimal implementation**

Add to `agent/lib/local_provider.py` — a module-level default runner and the two methods, and default the constructor's `run`:

```python
import subprocess


def _default_run(args: list) -> str:  # pragma: no cover - real git subprocess
    proc = subprocess.run(["git"] + args, capture_output=True, text=True, timeout=30)
    return proc.stdout.strip() if proc.returncode == 0 else ""
```

Change `__init__` signature to `def __init__(self, root, *, run=_default_run):` and keep `self._run = run`. Add:

```python
    def list_candidate_projects(self, since_iso: str) -> list:
        out = []
        for pid, rel, abs_ in self.projects:
            branch = self._run(["-C", str(abs_), "rev-parse", "--abbrev-ref", "HEAD"]) or "main"
            last = self._run(["-C", str(abs_), "log", "-1", "--format=%cI"])
            out.append({"id": pid, "path_with_namespace": rel,
                        "default_branch": branch, "last_activity_at": last})
        return out

    def has_commit_since(self, project_id: int, since_iso: str, ref=None) -> "str | None":
        abs_ = self._repo_path(project_id)
        args = ["-C", str(abs_), "log", "-1", f"--since={since_iso}", "--format=%cI"]
        if ref:
            args.append(ref)
        out = self._run(args)
        return out or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_local_provider_git.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/local_provider.py tests/test_local_provider_git.py
git commit -m "feat(source): LocalProvider git activity (list_candidate_projects + has_commit_since)"
```

---

### Task 3: `source:` config + `make_provider` factory

**Files:**
- Modify: `agent/config.py`
- Create: `agent/lib/source.py`
- Test: `tests/test_source_factory.py`

**Interfaces:**
- `agent/config.py`: `SourceConfig(type: str, local_root: str = "")` parsed from a `source:` section; `Config.source: SourceConfig` (default `SourceConfig(type="gitlab")` when absent, so existing GitLab configs are unchanged). `type` ∈ {`gitlab`, `local`}; `local` requires `root`.
- `agent/lib/source.py`: `make_provider(config, *, env=os.environ) -> provider` — returns a `GitLabClient(config.gitlab.base_url, env[config.gitlab.token_env])` for `type="gitlab"` (raising `SourceError` if the gitlab section or token is missing), or `LocalProvider(config.source.local_root)` for `type="local"`. `SourceError(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_source_factory.py
import textwrap
import pytest
from agent.config import load_config
from agent.lib.source import make_provider, SourceError
from agent.lib.local_provider import LocalProvider
from agent.lib.gitlab_read import GitLabClient

def _cfg(tmp_path, body):
    p = tmp_path / "config.yaml"; p.write_text(textwrap.dedent(body)); return load_config(str(p))

FEEDS = "\nfeeds:\n  - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }\n"

def test_default_source_is_gitlab(tmp_path):
    cfg = _cfg(tmp_path, "kb: { root: kb/ }" + FEEDS)
    assert cfg.source.type == "gitlab"

def test_make_local_provider(tmp_path):
    (tmp_path / "repos").mkdir()
    cfg = _cfg(tmp_path, f"kb: {{ root: kb/ }}\nsource: {{ type: local, root: {tmp_path}/repos }}" + FEEDS)
    prov = make_provider(cfg)
    assert isinstance(prov, LocalProvider)

def test_make_gitlab_provider(tmp_path):
    cfg = _cfg(tmp_path, "kb: { root: kb/ }\nsource: { type: gitlab }\n"
               "gitlab: { baseUrl: https://gl.test, tokenEnv: GITLAB_READ_TOKEN }" + FEEDS)
    prov = make_provider(cfg, env={"GITLAB_READ_TOKEN": "tok"})
    assert isinstance(prov, GitLabClient)

def test_gitlab_without_token_raises(tmp_path):
    cfg = _cfg(tmp_path, "kb: { root: kb/ }\ngitlab: { baseUrl: https://gl.test, tokenEnv: GITLAB_READ_TOKEN }" + FEEDS)
    with pytest.raises(SourceError):
        make_provider(cfg, env={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_source_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.source'` / `AttributeError: ... 'source'`

- [ ] **Step 3: Write minimal implementation**

In `agent/config.py` add:

```python
@dataclass
class SourceConfig:
    type: str = "gitlab"
    local_root: str = ""


def _source_from(raw: dict) -> "SourceConfig":
    s = raw.get("source") or {}
    t = s.get("type", "gitlab")
    if t not in ("gitlab", "local"):
        raise ConfigError(f"source.type must be gitlab or local, got '{t}'")
    if t == "local" and not s.get("root"):
        raise ConfigError("source.type=local requires 'root'")
    return SourceConfig(type=t, local_root=str(s.get("root", "")))
```

Add `source: "SourceConfig" = None` to `Config`, and in `load_config` set `source=_source_from(raw)`.

```python
# agent/lib/source.py
"""Factory selecting a SourceProvider (gitlab | local) from config. The provider is any object
implementing list_candidate_projects/has_commit_since/get_tree/get_raw_file/search_blobs."""
from __future__ import annotations

import os

from agent.lib.gitlab_read import GitLabClient
from agent.lib.local_provider import LocalProvider


class SourceError(Exception):
    pass


def make_provider(config, *, env=None):
    env = os.environ if env is None else env
    src = config.source
    if src.type == "local":
        return LocalProvider(src.local_root)
    # gitlab
    if config.gitlab is None:
        raise SourceError("source.type=gitlab but no `gitlab` config section")
    token = env.get(config.gitlab.token_env)
    if not token:
        raise SourceError(f"env var {config.gitlab.token_env} is not set")
    return GitLabClient(config.gitlab.base_url, token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_source_factory.py -v`
Expected: PASS (4 passed). Also `pytest -q` — existing config tests still green (`source` defaults).

- [ ] **Step 5: Commit**

```bash
git add agent/config.py agent/lib/source.py tests/test_source_factory.py
git commit -m "feat(source): source config section + make_provider factory (gitlab|local)"
```

---

### Task 4: Wire the factory into the CLI (`discover` + `inventory`)

**Files:**
- Modify: `agent/cli.py`
- Test: `tests/test_cli_source.py`

**Interfaces:**
- `_cmd_discover` and `_cmd_inventory` build their provider via `make_provider(cfg)` instead of hardcoding `GitLabClient` — but ONLY when no `client` is injected (the test seam stays). For `source.type=local` there is no token to check; for `gitlab` the `SourceError` (missing section/token) maps to the existing rc-2 fail-loud. The injected-`client` dispatch path is unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_source.py
import json, textwrap
from agent import cli

def _local_repo(root, name, files):
    d = root / name; (d / ".git").mkdir(parents=True)
    for rel, content in files.items():
        p = d / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)

def test_discover_and_inventory_local_source(tmp_path, monkeypatch):
    repos = tmp_path / "repos"; repos.mkdir()
    _local_repo(repos, "acme", {"package.json": '{"dependencies":{"stripe":"12.0.0"}}',
                                "src/Amazon.php": "sellingpartnerapi client"})
    # git activity is read via subprocess; stub it so no real git/commits are needed.
    from agent.lib import local_provider
    monkeypatch.setattr(local_provider, "_default_run",
                        lambda args: ("main" if "rev-parse" in " ".join(args)
                                      else "2026-07-01T00:00:00+00:00"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent(f"""
        kb: {{ root: {tmp_path}/kb }}
        source: {{ type: local, root: {repos} }}
        scan: {{ activeWindowDays: 3650 }}
        feeds:
          - {{ techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }}
    """))
    active = tmp_path / "active.json"; inv = tmp_path / "inv.json"
    pats = tmp_path / "patterns.yaml"; pats.write_text("- {techKey: api:amazon-sp-api, query: sellingpartnerapi, label: SP-API}\n")

    rc = cli.main(["discover", "--config", str(cfg), "--now", "2026-07-13", "--out", str(active)])
    assert rc == 0
    data = json.loads(active.read_text())
    assert data["active"] and data["active"][0]["path_with_namespace"] == "acme"

    rc = cli.main(["inventory", "--config", str(cfg), "--active", str(active),
                   "--out", str(inv), "--patterns", str(pats), "--now", "2026-07-13"])
    assert rc == 0
    d = json.loads(inv.read_text())
    assert any(r["tech_key"] == "lib:npm/stripe" for r in d["records"])          # manifest parsed from disk
    assert any(u["tech_key"] == "api:amazon-sp-api" for u in d["usedTechs"])     # presence via local grep
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_cli_source.py -v`
Expected: FAIL — discover builds a GitLab client / requires a token, so local source errors.

- [ ] **Step 3: Write minimal implementation**

In `agent/cli.py`, add `from agent.lib.source import make_provider, SourceError`. In `_cmd_discover`, replace the `cfg.gitlab is None` / token / `GitLabClient(...)` construction block (when `client is None`) with:

```python
    if client is None:
        try:
            client = make_provider(cfg)
        except SourceError as exc:
            print(f"ERROR: {exc}")
            return 2
```

Do the same substitution in `_cmd_inventory`. (Leave the `discover_mod.discover(...)` / `inventory_mod.build_inventory(...)` calls, the injected-client dispatch, and everything else unchanged. `make_provider` returns a `GitLabClient` for gitlab configs, so existing behavior is preserved; for local it returns a `LocalProvider`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_cli_source.py -v`
Expected: PASS (1 passed). Also `pytest -q` — existing discover/inventory CLI tests still green (they inject a `client`, bypassing `make_provider`; the gitlab-config tests still hit the SourceError→rc2 path for missing token).

- [ ] **Step 5: Commit**

```bash
git add agent/cli.py tests/test_cli_source.py
git commit -m "feat(source): discover/inventory select provider via make_provider (gitlab|local)"
```

---

### Task 5: Local demo config + README + end-to-end offline local run

**Files:**
- Create: `demo/demo-config-local.yaml`, `demo/run_local_demo.sh`
- Modify: `demo/README.md`
- Test: `tests/test_local_e2e.py`

**Interfaces:**
- `demo/demo-config-local.yaml` — a `source: {type: local, root: <dir>}` config + the same feeds as the offline demo.
- `demo/run_local_demo.sh` — creates a couple of throwaway git repos under `demo/out/repos/` (with a `package.json`/`Dockerfile`/an SP-API reference), then runs `ingest → discover → inventory → registry-scan → classify-report` against the LOCAL source and prints the report. No token, no network beyond `ingest`/`registry-scan` (which can be skipped offline).
- `tests/test_local_e2e.py` — a hermetic end-to-end: build a temp local repo, seed a KB entry the repo's tech matches, run `discover` + `inventory` (git stubbed) + `classify-report`, assert a real finding in the report. Proves the whole GitLab-free path works.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_local_e2e.py
import json, textwrap
from agent.lib.models import ChangeEntry
from agent.lib import kb_store
from agent import cli

def test_local_source_end_to_end(tmp_path, monkeypatch):
    repos = tmp_path / "repos"; repos.mkdir()
    acme = repos / "acme"; (acme / ".git").mkdir(parents=True)
    (acme / "Dockerfile").write_text("FROM php:8.0-alpine\n")
    from agent.lib import local_provider
    monkeypatch.setattr(local_provider, "_default_run",
                        lambda args: ("main" if "rev-parse" in " ".join(args) else "2026-07-01T00:00:00+00:00"))
    kb_root = str(tmp_path / "kb")
    kb_store.append_entries(kb_root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="deprecation", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://endoflife.date/php", sourceTier=1,
        evidence="PHP 8.0 EOL 2023-11-26", affectedArea="cycle 8.0")])
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent(f"""
        kb: {{ root: {kb_root} }}
        source: {{ type: local, root: {repos} }}
        scan: {{ activeWindowDays: 3650 }}
        feeds:
          - {{ techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }}
    """))
    active = tmp_path / "a.json"; inv = tmp_path / "i.json"
    pats = tmp_path / "p.yaml"; pats.write_text("- {techKey: api:x, query: zzz, label: X}\n")
    outr = tmp_path / "r.md"; outf = tmp_path / "f.json"

    assert cli.main(["discover", "--config", str(cfg), "--now", "2026-07-13", "--out", str(active)]) == 0
    assert cli.main(["inventory", "--config", str(cfg), "--active", str(active), "--out", str(inv),
                     "--patterns", str(pats), "--now", "2026-07-13"]) == 0
    assert cli.main(["classify-report", "--config", str(cfg), "--inventory", str(inv), "--active", str(active),
                     "--prev", "-", "--out-report", str(outr), "--out-findings", str(outf), "--now", "2026-07-13"]) == 0
    doc = json.loads(outf.read_text())
    assert doc["counts"]["action"] == 1        # PHP 8.0 EOL on a repo running php 8.0, all from LOCAL disk
    assert "acme" in outr.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_local_e2e.py -v`
Expected: FAIL (until Tasks 1–4 are in; if run after them, it should pass — but write it now and confirm green).

- [ ] **Step 3: Write the demo artifacts**

```yaml
# demo/demo-config-local.yaml
kb: { root: demo/out/kb }
source:
  type: local
  root: demo/out/repos          # run_local_demo.sh creates sample repos here
scan:
  activeWindowDays: 3650
delivery: { reportsProject: demo/reports, reviewHorizonMonths: 6 }
feeds:
  - { techKey: runtime:php,    label: PHP,     category: runtime, adapter: endoflife, url: php,    tier: 1 }
  - { techKey: runtime:node,   label: Node.js, category: runtime, adapter: endoflife, url: nodejs, tier: 1 }
  - { techKey: api:shopify,    label: Shopify, category: integration, adapter: rss, url: https://shopify.dev/changelog/feed.xml, tier: 1 }
```

```bash
#!/usr/bin/env bash
# Offline demo against a LOCAL folder of git repos — no GitLab, no token.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
R=demo/out/repos
rm -rf "$R"; mkdir -p "$R"
for name in acme-shop biz-portal; do
  mkdir -p "$R/$name"; ( cd "$R/$name" && git init -q && git config user.email d@d && git config user.name d )
done
printf 'FROM php:8.0-alpine\n' > "$R/acme-shop/Dockerfile"
printf '{"dependencies":{"stripe":"12.0.0","request":"^2.88"}}\n' > "$R/acme-shop/package.json"
printf 'use "sellingpartnerapi" client for amazon\n' > "$R/acme-shop/src.php"
printf 'FROM node:16-alpine\n' > "$R/biz-portal/Dockerfile"
( cd "$R/acme-shop" && git add -A && git commit -qm init )
( cd "$R/biz-portal" && git add -A && git commit -qm init )

CFG=demo/demo-config-local.yaml; NOW=$(date +%F); mkdir -p demo/out
python -m agent.cli ingest        --config "$CFG" --now "$NOW" || echo "(ingest needs internet; skipping is fine offline)"
python -m agent.cli discover      --config "$CFG" --now "$NOW" --out demo/out/active-repos.json
python -m agent.cli inventory     --config "$CFG" --active demo/out/active-repos.json --out demo/out/inventory.json --patterns agent/patterns.yaml --now "$NOW"
python -m agent.cli registry-scan --config "$CFG" --inventory demo/out/inventory.json --now "$NOW" || echo "(registry-scan needs internet; skipping)"
python -m agent.cli classify-report --config "$CFG" --inventory demo/out/inventory.json --active demo/out/active-repos.json \
  --prev - --out-report demo/out/report.md --out-findings demo/out/findings.json --now "$NOW"
echo "==== report ===="; cat demo/out/report.md
```

Append a "Local source" section to `demo/README.md` documenting: `bash demo/run_local_demo.sh` scans real git repos on disk (no token); point `source.root` at any directory of your cloned repos to scan your real code offline; the same pipeline runs, just with `source.type: local` instead of GitLab.

- [ ] **Step 4: Run tests + make the script executable**

Run: `source .venv/bin/activate && pytest tests/test_local_e2e.py -v && pytest -q`
Expected: all green. Then `chmod +x demo/run_local_demo.sh` and optionally run it to eyeball the report.

- [ ] **Step 5: Commit**

```bash
chmod +x demo/run_local_demo.sh
git add demo/demo-config-local.yaml demo/run_local_demo.sh demo/README.md tests/test_local_e2e.py
git commit -m "feat(source): local-source demo (scan a folder of git repos, no token) + e2e test"
```

---

## Self-Review

**Spec coverage / design goals:**
- Provider seam extracted (the five-method contract; GitLabClient already conforms, unchanged) → Tasks 1–3 ✓
- Local-folder provider (filesystem tree/file/search + git activity) → Tasks 1–2 ✓
- `source:` config selector + factory → Task 3 ✓
- CLI wired to select provider; GitLab path preserved → Task 4 ✓
- Real GitLab-free end-to-end (discover→inventory→report against local disk) → Task 5 ✓
- Downstream (KB, candidates, classify, delta, report, deliver) untouched — confirmed: they consume `active-repos.json`/`inventory.json` only.
- GitHub is a documented additive follow-up (same five methods + a `type: github` factory branch).

**Placeholder scan:** none — every step has runnable code. `_default_run`/`_default_request` production paths are `# pragma: no cover` and exercised only via supervised runs; unit tests inject fakes.

**Type consistency:** the five provider methods have identical signatures on `LocalProvider` (Tasks 1–2) and `GitLabClient` (existing), and match how `discover.py`/`inventory.py` call them (`list_candidate_projects(since_iso)`, `has_commit_since(pid, since, ref=)`, `get_tree(pid, ref)`, `get_raw_file(pid, path, ref)`, `search_blobs(pid, query)`). `make_provider(config, *, env=)` returns objects satisfying that contract. `Config.source: SourceConfig` defaults so all existing configs/tests are unaffected.

**Known limitations (documented):** (1) Local `search_blobs` is a substring scan over decodable text files ≤1 MB — good enough for presence detection; not regex. (2) Local activity uses `git log` on the default branch (not `--all`); a follow-up can add `--all` parity with the GitLab `commits?all=true` behavior. (3) Delivery (commit to reports repo) is unchanged and still GitLab/token-based; a local run just writes `report.md`/`findings.json` to disk (no commit), which is the intended offline behavior.
