# Integration Inventory — Unit 2: Framework Catalog + Record Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split a repo's manifest records into the superset schema's three buckets — `runtimes` / `frameworks` / `sdks` — using a framework catalog, so the assembler (Unit 3) can emit the PM's `frameworks{}` section separately from generic `sdks[]`.

**Architecture:** The existing manifest extractors already emit `InventoryRecord` with `tech_key` and `parse_quality` (verified), so no extractor changes are needed. Unit 2 adds a `frameworks.yaml` catalog (framework package names per ecosystem) + a pure classifier `is_framework(ecosystem, name)` and a `partition_records(records, ...)` router. Both are non-disruptive pure functions — the frozen `InventoryRecord` and the existing deprecation pipeline are untouched.

**Tech Stack:** Python 3.12 (project `.venv`, uv-managed — `source .venv/bin/activate`; system python is 3.10, do NOT use it). Tests: `python -m pytest -q`. `PyYAML` (already a dep).

## Global Constraints

- **TDD**: failing test first, watch it fail, then implement. Frequent commits.
- **Non-disruptive**: do NOT modify `InventoryRecord` (frozen dataclass) or the extractors; framework classification is a separate pure function. The existing deprecation pipeline (which reads `kind` = library/runtime) must keep working unchanged.
- **Match names to reality**: framework package identifiers use the same lowercased `ecosystem` + `name` the extractors produce — composer names like `laravel/framework`, npm scoped names like `@nestjs/core`, python names like `django`. Classification is case-insensitive on the package name.
- **Catalog reflects the PM's inventory**: the Frameworks section of `docs/results/INVENTORY-2026-07-10.md` lists `laravel/framework`, `react`, `next`, `express`, `vue`, `@nestjs/core`, `celery` — these MUST classify as frameworks.
- Match existing `agent/lib/` style (YAML catalog + loader, like `agent/vendors.yaml`).

---

## File Structure

- **Create** `agent/frameworks.yaml` — framework catalog: package names per ecosystem. (Task 1)
- **Create** `agent/lib/frameworks.py` — `load_frameworks()` + `is_framework(ecosystem, name)`. (Task 1)
- **Create** `agent/lib/record_routing.py` — `partition_records(records, frameworks=None)` → `{"runtimes", "frameworks", "sdks"}`. (Task 2)
- **Create** tests: `tests/test_frameworks.py` (T1), `tests/test_record_routing.py` (T2).

Reference (read-only): `agent/lib/inventory_models.py` (`InventoryRecord` fields: `repo, manifest_path, ecosystem, tech_key, name, kind, declared_range, version_hint, parse_quality, notes`), `docs/results/INVENTORY-2026-07-10.md` (the Frameworks + SDKs tables).

---

## Task 1: Framework catalog + classifier

**Files:**
- Create: `agent/frameworks.yaml`
- Create: `agent/lib/frameworks.py`
- Test: `tests/test_frameworks.py`

**Interfaces:**
- Produces:
  - `load_frameworks(path: str = "agent/frameworks.yaml") -> dict[str, set[str]]` — parses the YAML (`{ecosystem: [names]}`) into `{ecosystem: {lowercased names}}`.
  - `is_framework(ecosystem: str, name: str, catalog: dict | None = None) -> bool` — `True` iff `name.lower()` is in `catalog[ecosystem]`. If `catalog` is `None`, it loads the default once (module-level cache).

- [ ] **Step 1: Write the failing test**

Create `tests/test_frameworks.py`:

```python
from agent.lib.frameworks import load_frameworks, is_framework


def test_catalog_has_expected_frameworks_per_ecosystem():
    cat = load_frameworks()
    assert "laravel/framework" in cat["composer"]
    assert "react" in cat["npm"] and "next" in cat["npm"] and "@nestjs/core" in cat["npm"]
    assert "django" in cat["python"] and "celery" in cat["python"]


def test_is_framework_case_insensitive_and_scoped_by_ecosystem():
    cat = load_frameworks()
    assert is_framework("composer", "Laravel/Framework", cat) is True     # case-insensitive
    assert is_framework("npm", "@nestjs/core", cat) is True
    assert is_framework("npm", "axios", cat) is False                     # a library, not a framework
    assert is_framework("composer", "react", cat) is False               # react is npm, not composer


def test_is_framework_loads_default_catalog_when_none():
    assert is_framework("npm", "express") is True                        # no catalog arg -> default
    assert is_framework("python", "requests") is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_frameworks.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.frameworks'`.

- [ ] **Step 3: Create the framework catalog**

Create `agent/frameworks.yaml`:

```yaml
# Framework catalog — packages classified as frameworks (vs generic SDKs) in the inventory.
# Names match the extractors' lowercased ecosystem + package name. Reflects the PM's
# Frameworks table (laravel/framework, react, next, express, vue, @nestjs/core, celery).
composer:
  - laravel/framework
  - symfony/symfony
  - symfony/framework-bundle
  - cakephp/cakephp
  - yiisoft/yii2
  - codeigniter4/framework
  - laminas/laminas-mvc
npm:
  - react
  - next
  - vue
  - nuxt
  - "@angular/core"
  - "@nestjs/core"
  - express
  - koa
  - fastify
  - svelte
  - "@remix-run/react"
  - gatsby
python:
  - django
  - flask
  - fastapi
  - celery
  - tornado
  - pyramid
  - sanic
```

- [ ] **Step 4: Implement the loader + classifier**

Create `agent/lib/frameworks.py`:

```python
"""Framework catalog: which packages are frameworks (vs generic SDKs) in the inventory."""
from __future__ import annotations

import yaml

_CACHE: dict | None = None


def load_frameworks(path: str = "agent/frameworks.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {eco: {str(n).lower() for n in (names or [])} for eco, names in raw.items()}


def is_framework(ecosystem: str, name: str, catalog: dict | None = None) -> bool:
    global _CACHE
    if catalog is None:
        if _CACHE is None:
            _CACHE = load_frameworks()
        catalog = _CACHE
    return name.lower() in catalog.get(ecosystem, set())
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_frameworks.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add agent/frameworks.yaml agent/lib/frameworks.py tests/test_frameworks.py
git commit -m "feat(inventory): framework catalog + is_framework classifier"
```

---

## Task 2: Record router (runtimes / frameworks / sdks)

**Files:**
- Create: `agent/lib/record_routing.py`
- Test: `tests/test_record_routing.py`

**Interfaces:**
- Consumes: `InventoryRecord` (its `kind`, `ecosystem`, `name` fields); `is_framework` (Task 1).
- Produces:
  - `partition_records(records: list, catalog: dict | None = None) -> dict` — returns `{"runtimes": [...], "frameworks": [...], "sdks": [...]}` where each list holds the `InventoryRecord`s: `runtimes` = `kind == "runtime"`; `frameworks` = `kind == "library"` and `is_framework(ecosystem, name)`; `sdks` = `kind == "library"` and not a framework. Records with any other `kind` are ignored. Input order is preserved within each bucket.

- [ ] **Step 1: Write the failing test**

Create `tests/test_record_routing.py`:

```python
from agent.lib.inventory_models import InventoryRecord
from agent.lib.record_routing import partition_records


def _lib(eco, name):
    return InventoryRecord(repo="r", manifest_path="m", ecosystem=eco,
                           tech_key=f"lib:{eco}/{name.lower()}", name=name, kind="library",
                           declared_range="^1.0")


def _rt(product, hint):
    return InventoryRecord(repo="r", manifest_path="m", ecosystem="composer",
                           tech_key=f"runtime:{product}", name=product, kind="runtime",
                           version_hint=hint)


def test_partitions_into_runtimes_frameworks_sdks():
    records = [
        _rt("php", "^8.2"),
        _lib("composer", "laravel/framework"),   # framework
        _lib("composer", "guzzlehttp/guzzle"),   # sdk
        _lib("npm", "react"),                     # framework
        _lib("npm", "axios"),                     # sdk
    ]
    part = partition_records(records)
    assert [r.name for r in part["runtimes"]] == ["php"]
    assert {r.name for r in part["frameworks"]} == {"laravel/framework", "react"}
    assert {r.name for r in part["sdks"]} == {"guzzlehttp/guzzle", "axios"}


def test_empty_and_unknown_kinds():
    assert partition_records([]) == {"runtimes": [], "frameworks": [], "sdks": []}
    weird = InventoryRecord(repo="r", manifest_path="m", ecosystem="npm",
                            tech_key="x", name="x", kind="mystery")
    assert partition_records([weird]) == {"runtimes": [], "frameworks": [], "sdks": []}


def test_order_preserved_within_bucket():
    records = [_lib("npm", "axios"), _lib("npm", "lodash"), _lib("npm", "moment")]
    assert [r.name for r in partition_records(records)["sdks"]] == ["axios", "lodash", "moment"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_record_routing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.record_routing'`.

- [ ] **Step 3: Implement the router**

Create `agent/lib/record_routing.py`:

```python
"""Route InventoryRecords into the superset buckets: runtimes / frameworks / sdks."""
from __future__ import annotations

from agent.lib.frameworks import is_framework


def partition_records(records: list, catalog: dict | None = None) -> dict:
    out = {"runtimes": [], "frameworks": [], "sdks": []}
    for r in records:
        if r.kind == "runtime":
            out["runtimes"].append(r)
        elif r.kind == "library":
            bucket = "frameworks" if is_framework(r.ecosystem, r.name, catalog) else "sdks"
            out[bucket].append(r)
        # any other kind is ignored
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_record_routing.py -q`
Expected: PASS (3 passed).

Then the full suite (Unit 1 ended at 276; this adds frameworks(3) + routing(3) = 6):
Run: `source .venv/bin/activate && python -m pytest -q`
Expected: PASS — 282 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/record_routing.py tests/test_record_routing.py
git commit -m "feat(inventory): partition_records router (runtimes/frameworks/sdks)"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-07-14-integration-inventory-plugin-design.md`, Unit 2 of the sequencing — "manifest enrichment + framework catalog"):
- "techKey/parseQuality on records" → **already present** on `InventoryRecord` (verified in the extractors: `tech_key` + `parse_quality` emitted by npm/composer/python/runtime_pins) → no work needed; noted here so a reviewer doesn't expect an extractor change ✓
- "a framework catalog routes framework packages (laravel/react/next/vue/express/nestjs/celery) → `frameworks{}` vs `sdks[]`" → Task 1 (`frameworks.yaml` + `is_framework`) + Task 2 (`partition_records`) ✓
- Non-disruptive: `InventoryRecord` and the extractors and the deprecation pipeline are untouched → classification is a separate pure function ✓
- Out of scope for Unit 2 and correctly deferred: mapping records → the PM's `{eco, pkg, ver, file}` sdk dicts and assembling the per-repo nested doc (Unit 3 assembler), the IR store / rollups / render / CLI (Unit 3), baseline diff (Unit 4), the plugin (Unit 5).

**Placeholder scan:** none — every code/test step is complete and runnable; the catalog is concrete data.

**Type consistency:** `load_frameworks -> dict[str, set[str]]` consumed by `is_framework(ecosystem, name, catalog)` (Task 1), which `partition_records` (Task 2) calls with the `InventoryRecord`'s `.ecosystem`/`.name`. `partition_records -> {"runtimes","frameworks","sdks"}` of `InventoryRecord` lists. `InventoryRecord` field names (`kind`, `ecosystem`, `name`) match `agent/lib/inventory_models.py` exactly.

**Note (intentional):** `react`/`vue` are technically libraries but the PM's inventory lists them under Frameworks — the catalog follows the PM's framing so our output matches his for comparison.
