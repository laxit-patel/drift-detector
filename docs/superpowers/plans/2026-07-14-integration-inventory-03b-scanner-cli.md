# Integration Inventory — Unit 3b: Scanner + Orchestrator + CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the inventory runnable end-to-end — walk a folder of clones, extract manifests + Opengrep endpoints per repo (cache-aware), assemble the superset IR via the Unit 3a data layer, and write `inventory.json` + `INVENTORY.md` from an `inventory-scan` CLI.

**Architecture:** Four units on top of everything built so far. `scan_util.py` gets git metadata (`head_sha`/`ref`/`last_activity_at`, injected) and resolves the Opengrep/Semgrep engine (fail-loud if absent). `manifest_scan.py` walks a repo's working tree (reusing the skip-dir set) and runs the existing extractors → `InventoryRecord`s. `repo_scan.py` combines git meta + manifests (→ Unit 2 `partition_records`) + Opengrep endpoints (Unit 1, dropping empty-domain) → one superset record (Unit 3a `to_superset_repo`). `inventory_scan.py` orchestrates over the folder with the `repo@sha` cache (Unit 3a `ir_store`), builds rollups + coverage, persists the IR, renders the markdown, and exposes the `inventory-scan` CLI. Engine and git are injected callables so unit tests use fakes; a live smoke runs the real engine over cloned repos.

**Tech Stack:** Python 3.12 (project `.venv`, uv-managed — `source .venv/bin/activate`; system python is 3.10, do NOT use it). Tests: `python -m pytest -q`. Engine: `opengrep` (prod) / `semgrep` (in `.venv`, dev proxy).

## Global Constraints

- **TDD**: failing test first, watch it fail, then implement. Frequent commits.
- **Injected seams / no external tools in unit tests**: the Opengrep engine and git are injected callables (`run` / `git`). Unit tests inject fakes (canned Opengrep JSON, canned git output) and use `tmp_path` repos with real manifest/source files. A **live smoke** (opt-in, skips if no engine) runs the real engine + real git over cloned repos.
- **Fail-loud on missing engine** (spec §Error handling): `resolve_engine()` raises a clear install-guidance error if neither `opengrep` nor `semgrep` is found. No silent zero-endpoint scans.
- **Drop empty-domain endpoints** (Unit 1 deferral): an endpoint whose `domain` is `""` (unknown vendor / unresolved) is excluded from the repo record.
- **Incremental**: per repo, `load_repo_cache(state, path, head_sha)` — a hit (unchanged sha) reuses the cached record; a miss re-scans and saves. `git clean`-style: a repo with no git HEAD is scanned but not cached.
- **Never abort the batch**: a repo that errors is recorded in `coverage.reposErrored` and the scan continues.
- **Reuse, don't reinvent**: `_SKIP_DIRS` (from `local_provider`), `extractor_for` + extractors, `partition_records` (U2), `run_scan`/`load_vendors`/`write_ruleset`/`build_endpoints` (U1), `to_superset_repo`/`build_rollups`/`ir_store`/`render_inventory_md` (U3a).

---

## File Structure

- **Create** `agent/lib/scan_util.py` — `git_meta` + `resolve_engine`. (Task 1)
- **Create** `agent/lib/manifest_scan.py` — `extract_manifest_records`. (Task 2)
- **Create** `agent/lib/repo_scan.py` — `scan_repo`. (Task 3)
- **Create** `agent/inventory_scan.py` — `scan_folder` orchestrator. **Modify** `agent/cli.py` — add `inventory-scan`. (Task 4)
- **Create** tests: `tests/test_scan_util.py` (T1), `tests/test_manifest_scan.py` (T2), `tests/test_repo_scan.py` (T3), `tests/test_inventory_scan.py` + `tests/test_inventory_scan_live.py` (T4).

Reference (read-only): `agent/lib/local_provider.py` (`_SKIP_DIRS`, repo enumeration), `agent/lib/extractors/__init__.py` (`extractor_for`), Unit 1/2/3a modules named above.

---

## Task 1: Scan utilities — git metadata + engine resolution

**Files:**
- Create: `agent/lib/scan_util.py`
- Test: `tests/test_scan_util.py`

**Interfaces:**
- Produces:
  - `_default_git(args: list) -> str` — `subprocess.run(["git"] + args, capture_output=True, text=True, timeout=30).stdout.strip()`; `# pragma: no cover`.
  - `git_meta(repo_abs: str, *, run=_default_git) -> dict` — `{"head_sha", "ref", "last_activity_at", "ref_is_default": True}` from `rev-parse HEAD`, `rev-parse --abbrev-ref HEAD`, `log -1 --format=%cI` (each via `run(["-C", repo_abs, ...])`). Missing/empty → `""`. (`ref_is_default` is `True` best-effort locally — a documented v1 simplification.)
  - `resolve_engine(engine: str = "opengrep") -> str` — returns a path to `opengrep`, else `semgrep`, checking `shutil.which` and the running interpreter's bin dir; raises `RuntimeError("No opengrep/semgrep engine found — install opengrep (or semgrep) to scan code endpoints.")` if neither exists.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_util.py`:

```python
import pytest
from agent.lib.scan_util import git_meta, resolve_engine


def test_git_meta_from_injected_run():
    calls = []

    def fake(args):
        calls.append(args)
        return {"rev-parse HEAD": "abc123",
                "rev-parse --abbrev-ref HEAD": "main",
                "log -1 --format=%cI": "2026-07-10T00:00:00Z"}[" ".join(args[2:])]

    meta = git_meta("/repo", run=fake)
    assert meta == {"head_sha": "abc123", "ref": "main",
                    "last_activity_at": "2026-07-10T00:00:00Z", "ref_is_default": True}
    assert calls[0][:2] == ["-C", "/repo"]                      # git -C <repo> ...


def test_git_meta_empty_when_no_git():
    meta = git_meta("/repo", run=lambda args: "")
    assert meta["head_sha"] == "" and meta["ref"] == ""


def test_resolve_engine_raises_when_absent(monkeypatch):
    import agent.lib.scan_util as su
    monkeypatch.setattr(su.shutil, "which", lambda name: None)
    monkeypatch.setattr(su.os.path, "exists", lambda p: False)
    with pytest.raises(RuntimeError, match="engine"):
        resolve_engine()


def test_resolve_engine_finds_on_path(monkeypatch):
    import agent.lib.scan_util as su
    monkeypatch.setattr(su.shutil, "which", lambda name: "/usr/bin/semgrep" if name == "semgrep" else None)
    assert resolve_engine() == "/usr/bin/semgrep"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_scan_util.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.scan_util'`.

- [ ] **Step 3: Implement**

Create `agent/lib/scan_util.py`:

```python
"""Git metadata + engine resolution for the inventory scanner. Git is injected for tests."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def _default_git(args: list) -> str:  # pragma: no cover - real git subprocess
    proc = subprocess.run(["git"] + args, capture_output=True, text=True, timeout=30)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def git_meta(repo_abs: str, *, run=_default_git) -> dict:
    def g(*a):
        return run(["-C", repo_abs, *a]) or ""
    return {
        "head_sha": g("rev-parse", "HEAD"),
        "ref": g("rev-parse", "--abbrev-ref", "HEAD"),
        "last_activity_at": g("log", "-1", "--format=%cI"),
        "ref_is_default": True,          # best-effort locally (v1 simplification)
    }


def resolve_engine(engine: str = "opengrep") -> str:
    for name in (engine, "opengrep", "semgrep"):
        p = shutil.which(name)
        if p:
            return p
        cand = os.path.join(os.path.dirname(sys.executable), name)
        if os.path.exists(cand):
            return cand
    raise RuntimeError("No opengrep/semgrep engine found — install opengrep "
                       "(or semgrep) to scan code endpoints.")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_scan_util.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/scan_util.py tests/test_scan_util.py
git commit -m "feat(inventory): scan_util — git metadata + engine resolution (fail-loud)"
```

---

## Task 2: Manifest extraction over a working tree

**Files:**
- Create: `agent/lib/manifest_scan.py`
- Test: `tests/test_manifest_scan.py`

**Interfaces:**
- Consumes: `extractor_for` + the extractors (self-registered), `_SKIP_DIRS` pattern.
- Produces:
  - `extract_manifest_records(repo_abs: str, repo_name: str) -> tuple[list, list]` — walks `repo_abs` (skipping `_SKIP_DIRS`), and for each file whose basename has an extractor, reads it and runs the extractor with the repo-relative path. Returns `(records, unparsed)` where `records` is `list[InventoryRecord]` and `unparsed` is `list[{"path", "reason"}]` (a read error or an extractor `ValueError` is a per-file coverage gap, never a crash).

- [ ] **Step 1: Write the failing test**

Create `tests/test_manifest_scan.py`:

```python
from pathlib import Path
from agent.lib.manifest_scan import extract_manifest_records


def _w(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_extracts_from_manifests_and_skips_vendor_dirs(tmp_path):
    _w(tmp_path, "composer.json", '{"require": {"php": "^8.2", "laravel/framework": "^12.0"}}')
    _w(tmp_path, "package.json", '{"dependencies": {"axios": "^1.6"}}')
    _w(tmp_path, "vendor/pkg/composer.json", '{"require": {"evil/dep": "1.0"}}')   # MUST be skipped
    _w(tmp_path, "src/app.php", 'not a manifest')
    records, unparsed = extract_manifest_records(str(tmp_path), "acme/web")
    names = {r.name for r in records}
    assert "php" in names and "laravel/framework" in names and "axios" in names
    assert "evil/dep" not in names                              # vendor/ skipped
    assert unparsed == []
    assert all(r.repo == "acme/web" for r in records)
    php = next(r for r in records if r.name == "php")
    assert php.manifest_path == "composer.json"                 # repo-relative path


def test_invalid_manifest_is_unparsed_not_crash(tmp_path):
    _w(tmp_path, "composer.json", '{invalid json')
    _w(tmp_path, "package.json", '{"dependencies": {"axios": "^1.6"}}')
    records, unparsed = extract_manifest_records(str(tmp_path), "r")
    assert {r.name for r in records} == {"axios"}               # good one still parsed
    assert len(unparsed) == 1 and unparsed[0]["path"] == "composer.json"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_manifest_scan.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.manifest_scan'`.

- [ ] **Step 3: Implement**

Create `agent/lib/manifest_scan.py`:

```python
"""Walk a repo working tree and run the manifest extractors -> InventoryRecords."""
from __future__ import annotations

from pathlib import Path

from agent.lib.extractors import extractor_for
# Import extractors so they self-register:
from agent.lib.extractors import npm, composer, python, runtime_pins  # noqa: F401

_SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "dist", "build", "target", "__pycache__"}


def _walk(root: Path):
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


def extract_manifest_records(repo_abs: str, repo_name: str):
    root = Path(repo_abs)
    records: list = []
    unparsed: list = []
    for p in _walk(root):
        fn = extractor_for(p.name)
        if not fn:
            continue
        rel = str(p.relative_to(root))
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unparsed.append({"path": rel, "reason": f"read error: {exc}"})
            continue
        try:
            records.extend(fn(repo_name, rel, content))
        except ValueError as exc:
            unparsed.append({"path": rel, "reason": str(exc)})
    return records, unparsed
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_manifest_scan.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/manifest_scan.py tests/test_manifest_scan.py
git commit -m "feat(inventory): manifest extraction over a working tree (skip vendor dirs)"
```

---

## Task 3: Per-repo scan (git + manifests + endpoints → superset record)

**Files:**
- Create: `agent/lib/repo_scan.py`
- Test: `tests/test_repo_scan.py`

**Interfaces:**
- Consumes: `git_meta` (T1), `extract_manifest_records` (T2), `partition_records` (U2), `run_scan`/`build_endpoints` (U1), `to_superset_repo` (U3a).
- Produces:
  - `scan_repo(repo_abs, repo_name, repo_id, vendors, rules_path, *, engine, run, git=_default_git) -> tuple[dict, dict]` — returns `(record, note)`. `record` = the superset per-repo record (via `to_superset_repo`); `meta` includes `id=repo_id, path=repo_name, provenance={"engine":"opengrep"}` plus git fields. `endpoints` = `build_endpoints(...)` filtered to `e["domain"]` truthy (drop empty-domain). `note` = `{"unparsed": [...], "opengrepErrors": [...]}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_repo_scan.py`:

```python
import json
from pathlib import Path
from agent.lib.vendors import Vendor
from agent.lib.repo_scan import scan_repo


def _w(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


_VENDORS = [Vendor("Stripe", "api:stripe", ("api.stripe.com",), r'/(v\d+)')]


def _fake_opengrep(canned):
    return lambda args: canned


def test_scan_repo_assembles_manifests_and_endpoints(tmp_path):
    _w(tmp_path, "composer.json", '{"require": {"php": "^8.2", "laravel/framework": "^12.0"}}')
    _w(tmp_path, "pay.php", '$u = "https://api.stripe.com/v1/charges";\n')
    canned = json.dumps({"results": [
        {"check_id": "x.stripe-endpoint", "path": "pay.php", "start": {"line": 1},
         "extra": {"metadata": {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"}}}],
        "errors": [], "paths": {"scanned": ["pay.php"]}})
    git = lambda args: {"rev-parse HEAD": "sha1", "rev-parse --abbrev-ref HEAD": "main",
                        "log -1 --format=%cI": "2026-07-10"}[" ".join(args[2:])]

    record, note = scan_repo(str(tmp_path), "acme/web", 1, _VENDORS, "/rules.yaml",
                             engine="semgrep", run=_fake_opengrep(canned), git=git)
    assert record["id"] == 1 and record["path"] == "acme/web" and record["head_sha"] == "sha1"
    assert record["runtimes"]["php"]["range"] == "^8.2"
    assert "laravel/framework" in record["frameworks"]
    assert record["endpoints"][0]["techKey"] == "api:stripe" and record["endpoints"][0]["version"] == "v1"
    assert note["opengrepErrors"] == []


def test_scan_repo_drops_empty_domain_endpoints(tmp_path):
    _w(tmp_path, "x.php", 'nothing matches a known domain here\n')
    canned = json.dumps({"results": [
        {"check_id": "x.stripe-endpoint", "path": "x.php", "start": {"line": 1},
         "extra": {"metadata": {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"}}}],
        "errors": [], "paths": {"scanned": ["x.php"]}})
    record, _ = scan_repo(str(tmp_path), "r", 1, _VENDORS, "/r.yaml", engine="semgrep",
                          run=_fake_opengrep(canned), git=lambda a: "")
    assert record["endpoints"] == []                           # domain unresolved -> dropped
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_repo_scan.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.repo_scan'`.

- [ ] **Step 3: Implement**

Create `agent/lib/repo_scan.py`:

```python
"""Scan one repo: git metadata + manifests + Opengrep endpoints -> a superset record."""
from __future__ import annotations

from agent.lib.scan_util import git_meta, _default_git
from agent.lib.manifest_scan import extract_manifest_records
from agent.lib.record_routing import partition_records
from agent.lib.opengrep import run_scan
from agent.lib.endpoints import build_endpoints
from agent.lib.superset import to_superset_repo


def scan_repo(repo_abs, repo_name, repo_id, vendors, rules_path, *,
              engine, run, git=_default_git):
    meta = git_meta(repo_abs, run=git)
    meta.update({"id": repo_id, "path": repo_name, "provenance": {"engine": "opengrep"}})

    records, unparsed = extract_manifest_records(repo_abs, repo_name)
    partitioned = partition_records(records)

    scan = run_scan(repo_abs, rules_path, engine=engine, run=run)
    endpoints = [e for e in build_endpoints(scan["matches"], repo_abs, vendors) if e.get("domain")]

    record = to_superset_repo(meta, partitioned, endpoints)
    return record, {"unparsed": unparsed, "opengrepErrors": scan["errors"]}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_repo_scan.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/repo_scan.py tests/test_repo_scan.py
git commit -m "feat(inventory): scan_repo (git + manifests + endpoints -> superset record)"
```

---

## Task 4: Orchestrator + `inventory-scan` CLI + live smoke

**Files:**
- Create: `agent/inventory_scan.py`
- Modify: `agent/cli.py`
- Test: `tests/test_inventory_scan.py`, `tests/test_inventory_scan_live.py`

**Interfaces:**
- Consumes: `scan_repo` (T3), `resolve_engine` (T1), `git_meta` (T1), `load_vendors`/`write_ruleset` (U1), `ir_store` (U3a), `build_rollups`/`render_inventory_md` (U3a).
- Produces:
  - `scan_folder(root, state_dir, now, *, engine=None, run=opengrep._default_run, git=scan_util._default_git) -> dict` — returns `{"doc", "report_md"}`. Resolves the engine (fail-loud) unless one is passed; writes the generated ruleset to `<state_dir>/rules.generated.yaml`; enumerates immediate subdirs containing `.git`; per repo: compute `head_sha`, on a cache hit reuse `load_repo_cache`, else `scan_repo` + `save_repo_cache`; collects `coverage` (`reposScanned`, `reposErrored[{repo,reason}]`, `manifestsUnparsed[]`); builds the doc `{generated, scope, repos, coverage} + build_rollups(repos)`; `save_ir`; renders. A per-repo exception → `reposErrored`, batch continues.
  - CLI `inventory-scan --root <folder> --state <dir> --out-json <path> --out-md <path> --now <date>`.

- [ ] **Step 1: Write the failing test (orchestrator)**

Create `tests/test_inventory_scan.py`:

```python
import json
import subprocess
from pathlib import Path
from agent.inventory_scan import scan_folder


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def _canned_stripe(path):
    return json.dumps({"results": [
        {"check_id": "x.stripe-endpoint", "path": path, "start": {"line": 1},
         "extra": {"metadata": {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"}}}],
        "errors": [], "paths": {"scanned": [path]}})


def test_scan_folder_end_to_end(tmp_path):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}',
                             "pay.php": '"https://api.stripe.com/v1/x";\n'})
    state = tmp_path / "state"
    out = scan_folder(str(root), str(state), "2026-07-14",
                      engine="semgrep", run=lambda args: _canned_stripe("pay.php"))
    doc = out["doc"]
    assert doc["scope"]["reposScanned"] == 1
    repo = doc["repos"][0]
    assert repo["path"] == "web" and repo["runtimes"]["php"]["range"] == "^8.2"
    assert repo["endpoints"][0]["techKey"] == "api:stripe"
    assert doc["unique_apis"] == ["Stripe"]
    assert (state / "inventory.json").exists()                 # IR persisted
    assert "Stripe" in out["report_md"]


def test_scan_folder_incremental_cache_reused(tmp_path):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    state = tmp_path / "state"
    calls = {"n": 0}

    def counting_run(args):
        calls["n"] += 1
        return json.dumps({"results": [], "errors": [], "paths": {"scanned": []}})

    scan_folder(str(root), str(state), "2026-07-14", engine="semgrep", run=counting_run)
    assert calls["n"] == 1                                      # scanned once
    scan_folder(str(root), str(state), "2026-07-21", engine="semgrep", run=counting_run)
    assert calls["n"] == 1                                      # unchanged sha -> cache hit, engine NOT re-run
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_scan.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.inventory_scan'`.

- [ ] **Step 3: Implement the orchestrator**

Create `agent/inventory_scan.py`:

```python
"""Scan a folder of clones -> the superset inventory IR (inventory.json) + INVENTORY.md."""
from __future__ import annotations

import os
from pathlib import Path

from agent.lib import ir_store, opengrep, scan_util
from agent.lib.vendors import load_vendors
from agent.lib.vendor_rules import write_ruleset
from agent.lib.repo_scan import scan_repo
from agent.lib.inv_rollups import build_rollups
from agent.lib.inventory_render import render_inventory_md


def scan_folder(root, state_dir, now, *, engine=None,
                run=opengrep._default_run, git=scan_util._default_git) -> dict:
    engine = engine or scan_util.resolve_engine()      # fail-loud if absent
    os.makedirs(state_dir, exist_ok=True)
    vendors = load_vendors()
    rules_path = os.path.join(state_dir, "rules.generated.yaml")
    write_ruleset(vendors, rules_path)

    repo_dirs = sorted(d for d in Path(root).iterdir() if d.is_dir() and (d / ".git").exists())
    repos: list = []
    coverage = {"reposScanned": 0, "reposErrored": [], "manifestsUnparsed": []}
    for i, d in enumerate(repo_dirs):
        name = d.name
        abs_ = str(d.resolve())
        coverage["reposScanned"] += 1
        try:
            sha = scan_util.git_meta(abs_, run=git)["head_sha"]
            cached = ir_store.load_repo_cache(state_dir, name, sha) if sha else None
            if cached is not None:
                repos.append(cached)
                continue
            record, note = scan_repo(abs_, name, i + 1, vendors, rules_path,
                                     engine=engine, run=run, git=git)
            repos.append(record)
            if sha:
                ir_store.save_repo_cache(state_dir, name, sha, record)
            coverage["manifestsUnparsed"] += [{"repo": name, **u} for u in note["unparsed"]]
        except Exception as exc:            # no single repo aborts the scan
            coverage["reposErrored"].append({"repo": name, "reason": str(exc)})

    doc = {"generated": now, "scope": {"reposScanned": coverage["reposScanned"]},
           "repos": repos, "coverage": coverage}
    doc.update(build_rollups(repos))
    ir_store.save_ir(state_dir, doc)
    return {"doc": doc, "report_md": render_inventory_md(doc)}
```

- [ ] **Step 4: Run the orchestrator test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_scan.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Write the failing CLI test**

Append to `tests/test_inventory_scan.py`:

```python
from agent import cli


def test_cli_inventory_scan_writes_json_and_md(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}',
                             "pay.php": '"https://api.stripe.com/v1/x";\n'})
    # stub the engine so no real binary is needed
    import agent.inventory_scan as inv
    monkeypatch.setattr(inv.scan_util, "resolve_engine", lambda engine="opengrep": "semgrep")
    monkeypatch.setattr(inv.opengrep, "_default_run", lambda args: _canned_stripe("pay.php"), raising=False)

    out_json = tmp_path / "inv.json"
    out_md = tmp_path / "INVENTORY.md"
    rc = cli.main(["inventory-scan", "--root", str(root), "--state", str(tmp_path / "state"),
                   "--out-json", str(out_json), "--out-md", str(out_md), "--now", "2026-07-14"])
    assert rc == 0
    doc = json.loads(out_json.read_text())
    assert doc["repos"][0]["path"] == "web" and doc["unique_apis"] == ["Stripe"]
    assert "Stripe" in out_md.read_text()
```

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_scan.py::test_cli_inventory_scan_writes_json_and_md -q`
Expected: FAIL — `inventory-scan` is not a registered subcommand (argparse SystemExit).

- [ ] **Step 6: Wire the CLI**

In `agent/cli.py`, add the import near the others:

```python
from agent import inventory_scan as inventory_scan_mod
```

Add the handler beside the other `_cmd_*` functions:

```python
def _cmd_inventory_scan(args) -> int:
    out = inventory_scan_mod.scan_folder(args.root, args.state, args.now)
    with open(args.out_json, "w", encoding="utf-8") as fh:
        json.dump(out["doc"], fh, ensure_ascii=False, indent=2, sort_keys=True)
    with open(args.out_md, "w", encoding="utf-8") as fh:
        fh.write(out["report_md"])
    d = out["doc"]
    print(f"inventory-scan {args.now}: {len(d['repos'])} repos · "
          f"{len(d.get('unique_apis', []))} APIs · {len(d.get('unique_packages', []))} packages · "
          f"{len(d['coverage']['reposErrored'])} errored")
    return 0
```

Register the subparser beside the other `sub.add_parser(...)` calls:

```python
    pis = sub.add_parser("inventory-scan")
    for a in ("--root", "--state", "--out-json", "--out-md", "--now"):
        pis.add_argument(a, required=True)
    pis.set_defaults(func=_cmd_inventory_scan)
```

(`main()` dispatches this via the generic `return args.func(args)` tail.)

- [ ] **Step 7: Run the CLI test + full suite**

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_scan.py -q`
Expected: PASS (3 passed).

Run the full suite (Unit 3a ended at 292; this adds scan_util(4) + manifest(2) + repo_scan(2) + orchestrator/CLI(3) = 11):
Run: `source .venv/bin/activate && python -m pytest -q`
Expected: PASS — 303 passed.

- [ ] **Step 8: Write the LIVE smoke (opt-in, real engine + git over cloned repos)**

Create `tests/test_inventory_scan_live.py`:

```python
import os
import shutil
import sys
import pytest

from agent.inventory_scan import scan_folder

_ENGINE = (shutil.which("opengrep") or shutil.which("semgrep")
           or next((p for p in [os.path.join(os.path.dirname(sys.executable), n)
                                 for n in ("opengrep", "semgrep")] if os.path.exists(p)), None))
_CORPUS = ("/tmp/claude-1000/-home-tops-Projects-tops-deprication-agent/"
           "fa30e593-ae4a-40f9-876e-558d40625a62/scratchpad/marketplace-repos")


@pytest.mark.skipif(_ENGINE is None or not os.path.isdir(_CORPUS),
                    reason="no engine or no cloned corpus")
def test_live_scan_marketplace_repos(tmp_path):
    out = scan_folder(_CORPUS, str(tmp_path / "state"), "2026-07-14", engine=_ENGINE)
    doc = out["doc"]
    assert doc["scope"]["reposScanned"] >= 10                  # the 12 cloned repos
    # these SDK repos hard-code marketplace endpoints -> real APIs detected
    assert "Amazon SP-API" in doc["unique_apis"] or "eBay" in doc["unique_apis"]
    assert (tmp_path / "state" / "inventory.json").exists()
    assert "Third-party APIs" in out["report_md"]
```

- [ ] **Step 9: Run the live smoke**

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_scan_live.py -v`
Expected: PASS (real semgrep + git scan the 12 cloned repos, detect marketplace APIs, write the IR). Skips if the corpus/engine is absent.

- [ ] **Step 10: Commit**

```bash
git add agent/inventory_scan.py agent/cli.py tests/test_inventory_scan.py tests/test_inventory_scan_live.py
git commit -m "feat(inventory): inventory-scan orchestrator + CLI + live folder smoke"
```

---

## Self-Review

**Spec coverage** (against the spec's Unit 3 scanner/orchestrator/CLI parts + the Unit 1/2/3a deferrals):
- "walk folder … git metadata (head_sha/ref/last_activity_at)" → Task 1 `git_meta` ✓
- "run the extractors per repo" → Task 2 `extract_manifest_records` (reuses `extractor_for` + `_SKIP_DIRS`) ✓
- "run Opengrep per repo … drop empty-domain endpoints (Unit 1 deferral)" → Task 3 `scan_repo` (filters `e["domain"]`) ✓
- "incremental orchestration (per-repo SHA cache)" → Task 4 `scan_folder` (`load_repo_cache`/`save_repo_cache`; test proves the engine is NOT re-run on an unchanged sha) ✓
- "coverage collection; never abort the batch" → Task 4 `coverage` + per-repo try/except ✓
- "fail-loud if opengrep missing (Unit 1 deferral)" → Task 1 `resolve_engine` raises; called by `scan_folder` ✓
- "`inventory-scan --root <folder>` CLI + inventory.json + INVENTORY.md" → Task 4 ✓
- "live smoke over the marketplace repos" → Task 4 `test_inventory_scan_live.py` ✓
- Deferred to later units (correctly absent): baseline diff (Unit 4), the plugin (Unit 5), catalog-path-relative-to-`__file__` (only bites when the CLI runs from another cwd — the CLI test runs from the repo root; harden in Unit 5's plugin packaging).

**Placeholder scan:** none — every code/test step is complete, runnable code.

**Type consistency:** `git_meta -> dict` consumed by `scan_repo`/`scan_folder`. `extract_manifest_records -> (records, unparsed)` consumed by `scan_repo`. `scan_repo -> (record, note)` where `record` is a Unit 3a superset dict consumed by `build_rollups`/`ir_store`/`render`. `run_scan(repo_path, ruleset_path, *, engine, run)` matches Unit 1's signature (engine threaded through). `load_repo_cache(state, path, sha)` / `save_repo_cache` match Unit 3a. CLI dispatch via `set_defaults(func=...)` matches the confirmed pattern.

**Known 3b simplifications (intentional):** `ref_is_default=True` best-effort locally (no remote default known); the generated ruleset is rewritten each run (cheap); a repo with no git HEAD is scanned but not cached.
