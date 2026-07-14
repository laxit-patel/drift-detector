# Integration Inventory — Unit 3a: Superset Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure data layer of the inventory IR — assemble a per-repo superset record from partitioned manifest records + endpoints, compute the top-level rollups, persist the IR with a per-repo commit-SHA cache, and render the `INVENTORY.md`. No scanning here (Unit 3b wires the real folder scan on top).

**Architecture:** Four focused, pure/deterministic units. `superset.py` maps Unit 2's partitioned `InventoryRecord`s + Unit 1's endpoint dicts into one per-repo superset record (the PM's nested shape + our `techKey`/`parseQuality`). `rollups.py` dedups across repos into `unique_apis/api_versions/packages/package_versions/runtimes`. `ir_store.py` persists `inventory.json` and per-repo cache files keyed `repo@head_sha` (the incrementality substrate). `inventory_render.py` renders the markdown. Everything is tested with crafted inputs — no filesystem walk, no engine.

**Tech Stack:** Python 3.12 (project `.venv`, uv-managed — `source .venv/bin/activate`; system python is 3.10, do NOT use it). Tests: `python -m pytest -q`. Stdlib (`json`, `pathlib`).

## Global Constraints

- **TDD**: failing test first, watch it fail, then implement. Frequent commits.
- **Pure & deterministic**: every function takes dicts/lists and returns dicts/strings. No filesystem walk, no git, no engine (that's Unit 3b). `ir_store` is the only I/O and uses `tmp_path` in tests.
- **Superset per-repo record** (the spec's shape — use these exact keys): `{id, path, ref, ref_is_default, last_activity_at, head_sha, runtimes{name:{range,techKey,parseQuality}}, frameworks{name:{ver,techKey,parseQuality}}, sdks[{eco,pkg,ver,file,techKey,parseQuality}], endpoints[...], provenance{}, tree_walk_truncated}`.
- **parse_quality precedence** for runtime dedup: `exact` > `unlocked` > `best_effort`.
- **Deterministic JSON**: `sort_keys=True, indent=2` for stable git diffs (matches `snapshot_store`).
- Match existing style (`agent/lib/` dataclasses/JSON, injected seams).

---

## File Structure

- **Create** `agent/lib/superset.py` — `to_superset_repo(meta, partitioned, endpoints)`. (Task 1)
- **Create** `agent/lib/inv_rollups.py` — `build_rollups(repos)`. (Task 2)
- **Create** `agent/lib/ir_store.py` — `save_ir`/`load_ir` + per-repo `repo@sha` cache. (Task 3)
- **Create** `agent/lib/inventory_render.py` — `render_inventory_md(doc)`. (Task 4)
- **Create** tests: `tests/test_superset.py`, `tests/test_inv_rollups.py`, `tests/test_ir_store.py`, `tests/test_inventory_render.py`.

Reference (read-only): `agent/lib/inventory_models.py` (`InventoryRecord`), `agent/lib/record_routing.py` (`partition_records` output shape), `agent/lib/endpoints.py` (endpoint dict shape), `docs/results/INVENTORY-2026-07-10.md` (the target markdown + rollup shapes).

---

## Task 1: Per-repo superset record

**Files:**
- Create: `agent/lib/superset.py`
- Test: `tests/test_superset.py`

**Interfaces:**
- Consumes: `InventoryRecord` (Unit 2 partition output); endpoint dicts (Unit 1 `build_endpoints`).
- Produces:
  - `to_superset_repo(meta: dict, partitioned: dict, endpoints: list) -> dict` — `meta` = `{id, path, ref, ref_is_default, last_activity_at, head_sha, provenance?, tree_walk_truncated?}`; `partitioned` = `{"runtimes":[rec], "frameworks":[rec], "sdks":[rec]}` (Unit 2). Returns the per-repo superset record.
    - `runtimes`: `{rec.name: {"range": rec.version_hint or rec.declared_range, "techKey": rec.tech_key, "parseQuality": rec.parse_quality}}`, deduped by name keeping the best `parseQuality` (`exact`>`unlocked`>`best_effort`).
    - `frameworks`: `{rec.name: {"ver": rec.declared_range, "techKey": rec.tech_key, "parseQuality": rec.parse_quality}}`.
    - `sdks`: `[{"eco": rec.ecosystem, "pkg": rec.name, "ver": rec.declared_range, "file": rec.manifest_path, "techKey": rec.tech_key, "parseQuality": rec.parse_quality} ...]`.
    - `endpoints`: the passed-in list unchanged.
    - `provenance` / `tree_walk_truncated` from `meta` (defaults `{}` / `False`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_superset.py`:

```python
from agent.lib.inventory_models import InventoryRecord
from agent.lib.superset import to_superset_repo


def _rt(product, hint, quality="unlocked"):
    return InventoryRecord(repo="r", manifest_path="composer.json", ecosystem="composer",
                           tech_key=f"runtime:{product}", name=product, kind="runtime",
                           version_hint=hint, parse_quality=quality)


def _lib(eco, name, rng, path="package.json", quality="unlocked"):
    return InventoryRecord(repo="r", manifest_path=path, ecosystem=eco,
                           tech_key=f"lib:{eco}/{name.lower()}", name=name, kind="library",
                           declared_range=rng, parse_quality=quality)


_META = {"id": 7, "path": "acme/web", "ref": "main", "ref_is_default": True,
         "last_activity_at": "2026-07-10T00:00:00Z", "head_sha": "abc123",
         "provenance": {"engine": "opengrep"}}


def test_assembles_all_buckets():
    part = {"runtimes": [_rt("php", "^8.2")],
            "frameworks": [_lib("composer", "laravel/framework", "^12.0")],
            "sdks": [_lib("npm", "axios", "^1.6", "package.json")]}
    eps = [{"vendor": "Stripe", "domain": "api.stripe.com", "version": "v1",
            "techKey": "api:stripe", "example": "...", "file_count": 1, "files": ["a.php:2"]}]
    rec = to_superset_repo(_META, part, eps)
    assert rec["id"] == 7 and rec["head_sha"] == "abc123" and rec["ref_is_default"] is True
    assert rec["runtimes"] == {"php": {"range": "^8.2", "techKey": "runtime:php", "parseQuality": "unlocked"}}
    assert rec["frameworks"]["laravel/framework"] == {"ver": "^12.0", "techKey": "lib:composer/laravel/framework", "parseQuality": "unlocked"}
    assert rec["sdks"][0] == {"eco": "npm", "pkg": "axios", "ver": "^1.6", "file": "package.json",
                              "techKey": "lib:npm/axios", "parseQuality": "unlocked"}
    assert rec["endpoints"] == eps
    assert rec["provenance"] == {"engine": "opengrep"} and rec["tree_walk_truncated"] is False


def test_runtime_dedup_keeps_best_quality(tmp_path):
    part = {"runtimes": [_rt("php", "18", "best_effort"), _rt("php", "^8.2", "exact")],
            "frameworks": [], "sdks": []}
    rec = to_superset_repo(_META, part, [])
    assert rec["runtimes"]["php"]["parseQuality"] == "exact" and rec["runtimes"]["php"]["range"] == "^8.2"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_superset.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.superset'`.

- [ ] **Step 3: Implement**

Create `agent/lib/superset.py`:

```python
"""Assemble one per-repo superset record from partitioned manifest records + endpoints."""
from __future__ import annotations

_QUALITY_RANK = {"exact": 3, "unlocked": 2, "best_effort": 1}


def _runtimes(records: list) -> dict:
    out: dict = {}
    for r in records:
        entry = {"range": r.version_hint or r.declared_range,
                 "techKey": r.tech_key, "parseQuality": r.parse_quality}
        cur = out.get(r.name)
        if cur is None or _QUALITY_RANK.get(r.parse_quality, 0) > _QUALITY_RANK.get(cur["parseQuality"], 0):
            out[r.name] = entry
    return out


def to_superset_repo(meta: dict, partitioned: dict, endpoints: list) -> dict:
    return {
        "id": meta.get("id"), "path": meta.get("path"),
        "ref": meta.get("ref"), "ref_is_default": meta.get("ref_is_default"),
        "last_activity_at": meta.get("last_activity_at"), "head_sha": meta.get("head_sha"),
        "runtimes": _runtimes(partitioned.get("runtimes", [])),
        "frameworks": {r.name: {"ver": r.declared_range, "techKey": r.tech_key,
                                "parseQuality": r.parse_quality}
                       for r in partitioned.get("frameworks", [])},
        "sdks": [{"eco": r.ecosystem, "pkg": r.name, "ver": r.declared_range,
                  "file": r.manifest_path, "techKey": r.tech_key, "parseQuality": r.parse_quality}
                 for r in partitioned.get("sdks", [])],
        "endpoints": endpoints,
        "provenance": meta.get("provenance", {}),
        "tree_walk_truncated": meta.get("tree_walk_truncated", False),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_superset.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/superset.py tests/test_superset.py
git commit -m "feat(inventory): per-repo superset record assembler"
```

---

## Task 2: Top-level rollups

**Files:**
- Create: `agent/lib/inv_rollups.py`
- Test: `tests/test_inv_rollups.py`

**Interfaces:**
- Consumes: a list of per-repo superset records (Task 1 output).
- Produces:
  - `build_rollups(repos: list) -> dict` — `{"unique_apis": [...], "unique_api_versions": [...], "unique_packages": [...], "unique_package_versions": [...], "runtimes": {...}}`:
    - `unique_apis`: sorted distinct vendor names across all `endpoints`.
    - `unique_api_versions`: sorted distinct `{"vendor", "version"}` dicts where `version` is truthy.
    - `unique_packages`: sorted distinct `{"eco", "pkg"}` across `sdks` + `frameworks` (frameworks contribute `{eco derived from techKey prefix `lib:<eco>/`, pkg name}`).
    - `unique_package_versions`: sorted distinct `{"eco", "pkg", "ver"}`.
    - `runtimes`: `{product: sorted(distinct range strings)}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_inv_rollups.py`:

```python
from agent.lib.inv_rollups import build_rollups


def _repo(**kw):
    base = {"runtimes": {}, "frameworks": {}, "sdks": [], "endpoints": []}
    base.update(kw)
    return base


def test_rollups_dedup_and_sort():
    repos = [
        _repo(runtimes={"php": {"range": "^8.2", "techKey": "runtime:php", "parseQuality": "unlocked"}},
              frameworks={"laravel/framework": {"ver": "^12.0", "techKey": "lib:composer/laravel/framework", "parseQuality": "unlocked"}},
              sdks=[{"eco": "npm", "pkg": "axios", "ver": "^1.6", "file": "p", "techKey": "lib:npm/axios", "parseQuality": "unlocked"}],
              endpoints=[{"vendor": "Stripe", "version": "v1", "techKey": "api:stripe"}]),
        _repo(runtimes={"php": {"range": "^8.3", "techKey": "runtime:php", "parseQuality": "unlocked"}},
              sdks=[{"eco": "npm", "pkg": "axios", "ver": "^1.6", "file": "p", "techKey": "lib:npm/axios", "parseQuality": "unlocked"}],
              endpoints=[{"vendor": "Stripe", "version": "v2", "techKey": "api:stripe"},
                         {"vendor": "eBay", "version": None, "techKey": "api:ebay"}]),
    ]
    r = build_rollups(repos)
    assert r["unique_apis"] == ["Stripe", "eBay"] or r["unique_apis"] == sorted(["Stripe", "eBay"])
    assert {"vendor": "Stripe", "version": "v1"} in r["unique_api_versions"]
    assert {"vendor": "Stripe", "version": "v2"} in r["unique_api_versions"]
    assert all(v["version"] for v in r["unique_api_versions"])                # None dropped (eBay)
    assert {"eco": "npm", "pkg": "axios"} in r["unique_packages"]             # deduped across repos
    assert len([p for p in r["unique_packages"] if p["pkg"] == "axios"]) == 1
    assert {"eco": "composer", "pkg": "laravel/framework"} in r["unique_packages"]  # framework eco from techKey
    assert r["runtimes"]["php"] == ["^8.2", "^8.3"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_inv_rollups.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.inv_rollups'`.

- [ ] **Step 3: Implement**

Create `agent/lib/inv_rollups.py`:

```python
"""Top-level rollups: dedup APIs / API versions / packages / package versions / runtimes across repos."""
from __future__ import annotations


def _eco_from_techkey(tk: str) -> str:
    # "lib:composer/laravel/framework" -> "composer"
    return tk.split(":", 1)[1].split("/", 1)[0] if tk.startswith("lib:") else ""


def build_rollups(repos: list) -> dict:
    apis: set = set()
    api_versions: set = set()
    packages: set = set()
    package_versions: set = set()
    runtimes: dict = {}

    for repo in repos:
        for ep in repo.get("endpoints", []):
            v = ep.get("vendor", "")
            if v:
                apis.add(v)
            if ep.get("version"):
                api_versions.add((v, ep["version"]))
        for pkg in repo.get("sdks", []):
            packages.add((pkg["eco"], pkg["pkg"]))
            package_versions.add((pkg["eco"], pkg["pkg"], pkg.get("ver", "")))
        for name, fw in repo.get("frameworks", {}).items():
            eco = _eco_from_techkey(fw.get("techKey", ""))
            packages.add((eco, name))
            package_versions.add((eco, name, fw.get("ver", "")))
        for product, rt in repo.get("runtimes", {}).items():
            runtimes.setdefault(product, set()).add(rt.get("range", ""))

    return {
        "unique_apis": sorted(apis),
        "unique_api_versions": [{"vendor": v, "version": ver} for v, ver in sorted(api_versions)],
        "unique_packages": [{"eco": e, "pkg": p} for e, p in sorted(packages)],
        "unique_package_versions": [{"eco": e, "pkg": p, "ver": vr} for e, p, vr in sorted(package_versions)],
        "runtimes": {p: sorted(cs) for p, cs in sorted(runtimes.items())},
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_inv_rollups.py -q`
Expected: PASS (1 passed). (Note: `unique_apis` is `sorted(...)` so it is `["Stripe", "eBay"]` sorted alphabetically = `["Stripe", "eBay"]`? `sorted(["Stripe","eBay"])` == `["Stripe","eBay"]`? No — capital E < capital S, so `["eBay","Stripe"]` is wrong; sorted gives `["Stripe","eBay"]`? Actually `"Stripe" < "eBay"` because uppercase 'S'(83) < lowercase 'e'(101). So sorted == `["Stripe","eBay"]`. The test's `or` clause accepts either; it passes.)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/inv_rollups.py tests/test_inv_rollups.py
git commit -m "feat(inventory): top-level rollups (unique apis/versions/packages/runtimes)"
```

---

## Task 3: IR store (persist + per-repo SHA cache)

**Files:**
- Create: `agent/lib/ir_store.py`
- Test: `tests/test_ir_store.py`

**Interfaces:**
- Produces:
  - `save_ir(state_dir: str, doc: dict) -> None` — writes `<state_dir>/inventory.json` (`sort_keys=True, indent=2`).
  - `load_ir(state_dir: str) -> dict | None` — reads it or `None`.
  - `save_repo_cache(state_dir: str, path: str, head_sha: str, record: dict) -> None` — writes `<state_dir>/repos/<path with "/"→"_">@<head_sha>.json`.
  - `load_repo_cache(state_dir: str, path: str, head_sha: str) -> dict | None` — reads that exact `repo@sha` file or `None` (a different sha ⇒ miss ⇒ re-scan).

- [ ] **Step 1: Write the failing test**

Create `tests/test_ir_store.py`:

```python
from agent.lib import ir_store


def test_ir_round_trip_and_missing(tmp_path):
    assert ir_store.load_ir(str(tmp_path)) is None
    doc = {"repos": [{"path": "a/b"}], "unique_apis": ["Stripe"]}
    ir_store.save_ir(str(tmp_path), doc)
    assert ir_store.load_ir(str(tmp_path)) == doc


def test_repo_cache_keyed_by_sha(tmp_path):
    rec = {"path": "acme/web", "head_sha": "abc", "sdks": []}
    assert ir_store.load_repo_cache(str(tmp_path), "acme/web", "abc") is None   # first run
    ir_store.save_repo_cache(str(tmp_path), "acme/web", "abc", rec)
    assert ir_store.load_repo_cache(str(tmp_path), "acme/web", "abc") == rec     # unchanged sha -> hit
    assert ir_store.load_repo_cache(str(tmp_path), "acme/web", "def") is None    # changed sha -> miss (re-scan)


def test_repo_path_with_slashes_is_file_safe(tmp_path):
    rec = {"path": "group/sub/proj"}
    ir_store.save_repo_cache(str(tmp_path), "group/sub/proj", "s1", rec)
    assert ir_store.load_repo_cache(str(tmp_path), "group/sub/proj", "s1") == rec
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_ir_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.ir_store'`.

- [ ] **Step 3: Implement**

Create `agent/lib/ir_store.py`:

```python
"""Persist the inventory IR + a per-repo cache keyed repo@head_sha (the incrementality substrate).
A cache hit (same sha) lets the scanner reuse a repo's record; a changed sha misses -> re-scan."""
from __future__ import annotations

import json
from pathlib import Path


def _ir_path(state_dir: str) -> Path:
    return Path(state_dir) / "inventory.json"


def _repo_path(state_dir: str, path: str, head_sha: str) -> Path:
    safe = path.replace("/", "_")
    return Path(state_dir) / "repos" / f"{safe}@{head_sha}.json"


def _write(p: Path, doc: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _read(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_ir(state_dir: str, doc: dict) -> None:
    _write(_ir_path(state_dir), doc)


def load_ir(state_dir: str):
    return _read(_ir_path(state_dir))


def save_repo_cache(state_dir: str, path: str, head_sha: str, record: dict) -> None:
    _write(_repo_path(state_dir, path, head_sha), record)


def load_repo_cache(state_dir: str, path: str, head_sha: str):
    return _read(_repo_path(state_dir, path, head_sha))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_ir_store.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/ir_store.py tests/test_ir_store.py
git commit -m "feat(inventory): IR store (inventory.json + per-repo repo@sha cache)"
```

---

## Task 4: Markdown render

**Files:**
- Create: `agent/lib/inventory_render.py`
- Test: `tests/test_inventory_render.py`

**Interfaces:**
- Consumes: the assembled superset doc `{generated, scope, repos[], unique_apis, unique_api_versions, unique_packages, unique_package_versions, runtimes, coverage}`.
- Produces:
  - `render_inventory_md(doc: dict) -> str` — a markdown report (the PM's `INVENTORY.md` shape) with: a title, a Scope table (from `doc["scope"]`), a **Third-party APIs** table (vendor → repo count, from `repos[].endpoints`), a **Pinned API versions** table (`doc["unique_api_versions"]` with repo counts), a **Runtimes** section (`doc["runtimes"]`), a **Frameworks** count line, an **SDKs (top 30 by repo count)** table, and a **Coverage** section (`doc["coverage"]`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_inventory_render.py`:

```python
from agent.lib.inventory_render import render_inventory_md


_DOC = {
    "generated": "2026-07-14",
    "scope": {"reposScanned": 2},
    "repos": [
        {"path": "acme/orders", "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^1.6"}],
         "endpoints": [{"vendor": "Amazon SP-API", "version": "v0"}]},
        {"path": "acme/web", "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^1.6"}],
         "endpoints": [{"vendor": "Amazon SP-API", "version": "v0"},
                       {"vendor": "Stripe", "version": "v1"}]},
    ],
    "unique_api_versions": [{"vendor": "Amazon SP-API", "version": "v0"}, {"vendor": "Stripe", "version": "v1"}],
    "runtimes": {"php": ["^8.2", "^8.3"]},
    "unique_packages": [{"eco": "npm", "pkg": "axios"}],
    "coverage": {"reposScanned": 2, "reposErrored": []},
}


def test_render_has_key_sections_and_counts():
    md = render_inventory_md(_DOC)
    assert "# " in md and "Scope" in md
    assert "Third-party APIs" in md
    assert "Amazon SP-API" in md and "| 2 |" in md          # SP-API used by 2 repos
    assert "Stripe" in md                                    # used by 1 repo
    assert "Runtimes" in md and "php" in md
    assert "axios" in md                                     # SDKs section
    assert "Coverage" in md


def test_render_empty_doc_does_not_crash():
    md = render_inventory_md({"repos": [], "coverage": {}})
    assert isinstance(md, str) and "Third-party APIs" in md
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_render.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.inventory_render'`.

- [ ] **Step 3: Implement**

Create `agent/lib/inventory_render.py`:

```python
"""Render the superset inventory doc into the PM's INVENTORY.md shape."""
from __future__ import annotations

from collections import Counter


def _vendor_repo_counts(repos: list) -> Counter:
    c: Counter = Counter()
    for r in repos:
        for v in {ep.get("vendor", "") for ep in r.get("endpoints", []) if ep.get("vendor")}:
            c[v] += 1
    return c


def _pkg_repo_counts(repos: list) -> Counter:
    c: Counter = Counter()
    for r in repos:
        for pkg in {(s["eco"], s["pkg"]) for s in r.get("sdks", [])}:
            c[pkg] += 1
    return c


def render_inventory_md(doc: dict) -> str:
    repos = doc.get("repos", [])
    out = [f"# Tech-Stack Inventory — {doc.get('generated', '')}".rstrip(), ""]

    out += ["## Scope", "", "| | Count |", "|---|---|"]
    for k, v in (doc.get("scope") or {}).items():
        out.append(f"| {k} | {v} |")
    out.append("")

    out += ["## Third-party APIs (by repo count)", "", "| Vendor | Repos |", "|---|---|"]
    for vendor, n in _vendor_repo_counts(repos).most_common():
        out.append(f"| {vendor} | {n} |")
    out.append("")

    out += ["## Pinned API versions", "", "| Vendor | Version |", "|---|---|"]
    for av in doc.get("unique_api_versions", []):
        out.append(f"| {av.get('vendor', '')} | {av.get('version', '')} |")
    out.append("")

    out += ["## Runtimes", ""]
    for product, ranges in (doc.get("runtimes") or {}).items():
        out.append(f"- **{product}**: {', '.join(ranges)}")
    out.append("")

    out += ["## SDKs / libraries (top 30 by repo count)", "", "| Ecosystem | Package | Repos |", "|---|---|---|"]
    for (eco, pkg), n in _pkg_repo_counts(repos).most_common(30):
        out.append(f"| {eco} | {pkg} | {n} |")
    out.append("")

    cov = doc.get("coverage") or {}
    out += ["## Coverage", ""]
    out.append(f"- Repos scanned: {cov.get('reposScanned', len(repos))}")
    out.append(f"- Repos errored: {len(cov.get('reposErrored', []))}")
    out.append("")

    return "\n".join(out)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_render.py -q`
Expected: PASS (2 passed).

Then the full suite (Unit 2 ended at 282; this adds superset(2) + rollups(1) + ir_store(3) + render(2) = 8):
Run: `source .venv/bin/activate && python -m pytest -q`
Expected: PASS — 290 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/inventory_render.py tests/test_inventory_render.py
git commit -m "feat(inventory): INVENTORY.md renderer (superset doc -> markdown)"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-07-14-integration-inventory-plugin-design.md`, the "superset assembler / rollups / IR store / render" parts of Unit 3):
- "superset assembler (per-repo nested {runtimes,frameworks,sdks,endpoints} with techKey/parseQuality)" → Task 1 `to_superset_repo` ✓ (exact schema keys)
- "rollups (unique_apis/api_versions/packages/package_versions/runtimes)" → Task 2 `build_rollups` ✓
- "IR store … per-repo cache keyed by commit SHA … incremental" → Task 3 `ir_store` (`repo@sha` cache; a changed sha misses ⇒ Unit 3b re-scans) ✓
- "markdown render (INVENTORY.md, PM shape)" → Task 4 `render_inventory_md` ✓
- Out of scope for 3a and deferred to **Unit 3b**: the folder walk + git metadata (`head_sha`/`ref`/`last_activity_at`), running the extractors + Opengrep per repo, the incremental orchestration loop, coverage collection, drop-empty-domain-endpoints, fail-loud-if-opengrep-missing, `inventory-scan` CLI, live smoke.

**Placeholder scan:** none — every code/test step is complete and runnable.

**Type consistency:** `to_superset_repo -> dict` (per-repo record) feeds `build_rollups(repos: list)` and `render_inventory_md(doc)`. Record keys (`runtimes/frameworks/sdks/endpoints`) are produced by Task 1 and consumed by Tasks 2/4 identically. `ir_store` round-trips plain dicts. Endpoint dict keys (`vendor/version/techKey`) match `agent/lib/endpoints.py`. `InventoryRecord` fields (`version_hint/declared_range/tech_key/parse_quality/ecosystem/name/manifest_path`) match `agent/lib/inventory_models.py`.

**Known 3a simplifications (intentional):** the render covers the high-value sections (APIs, versions, runtimes, SDKs, coverage) — full fidelity to every PM table is a later polish; `runtimes` rollup is distinct constraints (not per-constraint repo counts).
