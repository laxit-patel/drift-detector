# Integration Inventory — Unit 4: Baseline Diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface *what integration/dependency usage changed* since the last scan — new/removed endpoints, SDK add/remove/version-bump, runtime changes, repos added/removed — by diffing the new IR against the prior persisted IR, and render it as a `DIFF.md`.

**Architecture:** Two units. `inventory_diff.py` is a pure function diffing two superset docs into a structured change set (per-repo, keyed by repo path; endpoints by exact `(techKey,domain,version)`, SDKs/runtimes by identity with version-change detection). `inventory_scan.scan_folder` loads the prior IR *before* it overwrites it, computes the diff against the new doc, and returns it; the `inventory-scan` CLI writes an optional `--out-diff`. This is the bridge to the (secondary) deprecation layer — a version bump or a newly-appeared API is exactly what change-monitoring watches.

**Tech Stack:** Python 3.12 (project `.venv`, uv-managed — `source .venv/bin/activate`; system python is 3.10, do NOT use it). Tests: `python -m pytest -q`. Stdlib.

## Global Constraints

- **TDD**: failing test first, watch it fail, then implement. Frequent commits.
- **Pure diff**: `diff_inventories(prev, curr)` takes two docs and returns a dict — no I/O. The orchestrator wiring loads/returns; the CLI writes.
- **Diff is deterministic + sorted** (stable output for the human doc / any downstream delta).
- **First run has no baseline**: if there is no prior IR, the diff is empty (everything is "the baseline", not "added").
- Reuse the shipped IR shape (Unit 3a) — repos with `path`, `endpoints[{techKey,domain,version}]`, `sdks[{eco,pkg,ver}]`, `runtimes{name:{range}}`.

---

## File Structure

- **Create** `agent/lib/inventory_diff.py` — `diff_inventories(prev, curr)` + `render_diff_md(diff)`. (Task 1 = diff; Task 2 = render + wiring)
- **Modify** `agent/inventory_scan.py` — load prior IR before save, compute + return the diff. **Modify** `agent/cli.py` — optional `--out-diff`. (Task 2)
- **Create** tests: `tests/test_inventory_diff.py` (T1), `tests/test_inventory_scan_diff.py` (T2).

Reference (read-only): `agent/lib/ir_store.py` (`load_ir`), `agent/inventory_scan.py` (the orchestrator), the Unit 3a IR shape.

---

## Task 1: The structured diff

**Files:**
- Create: `agent/lib/inventory_diff.py`
- Test: `tests/test_inventory_diff.py`

**Interfaces:**
- Produces:
  - `diff_inventories(prev: dict, curr: dict) -> dict` — `{"reposAdded": [path...], "reposRemoved": [path...], "changes": [per-repo]}`. Repos matched by `path`. A per-repo change entry (only included if something changed):
    - `endpointsAdded` / `endpointsRemoved`: `[{"techKey","domain","version"}]` — set difference on the exact `(techKey,domain,version)` tuple (a version bump appears as one removed + one added).
    - `sdksAdded` / `sdksRemoved`: `[{"eco","pkg","ver"}]` — by `(eco,pkg)` identity.
    - `sdkVersionChanges`: `[{"eco","pkg","from","to"}]` — same `(eco,pkg)`, different `ver`.
    - `runtimeChanges`: `[{"product","from","to"}]` — same runtime name, different `range`.
  - All lists deterministically sorted.

- [ ] **Step 1: Write the failing test**

Create `tests/test_inventory_diff.py`:

```python
from agent.lib.inventory_diff import diff_inventories


def _repo(path, endpoints=None, sdks=None, runtimes=None):
    return {"path": path, "endpoints": endpoints or [], "sdks": sdks or [], "runtimes": runtimes or {}}


def _ep(tk, dom, ver):
    return {"techKey": tk, "domain": dom, "version": ver}


def _sdk(eco, pkg, ver):
    return {"eco": eco, "pkg": pkg, "ver": ver}


def test_repos_added_and_removed():
    prev = {"repos": [_repo("a"), _repo("gone")]}
    curr = {"repos": [_repo("a"), _repo("new")]}
    d = diff_inventories(prev, curr)
    assert d["reposAdded"] == ["new"] and d["reposRemoved"] == ["gone"]


def test_endpoint_and_version_and_sdk_and_runtime_changes():
    prev = {"repos": [_repo("web",
                            endpoints=[_ep("api:amazon-sp-api", "sellingpartnerapi", "v0"),
                                       _ep("api:stripe", "api.stripe.com", "v1")],
                            sdks=[_sdk("npm", "axios", "^1.6"), _sdk("npm", "gone", "^1.0")],
                            runtimes={"php": {"range": "^8.2"}})]}
    curr = {"repos": [_repo("web",
                            endpoints=[_ep("api:amazon-sp-api", "sellingpartnerapi", "v2"),  # bump v0->v2
                                       _ep("api:stripe", "api.stripe.com", "v1"),             # unchanged
                                       _ep("api:ebay", "api.ebay.com", "v1")],                # new API
                            sdks=[_sdk("npm", "axios", "^1.7"),                                # bump
                                  _sdk("npm", "added", "^2.0")],                              # new
                            runtimes={"php": {"range": "^8.3"}})]}                            # runtime change
    d = diff_inventories(prev, curr)
    ch = d["changes"][0]
    assert ch["repo"] == "web"
    assert {"techKey": "api:ebay", "domain": "api.ebay.com", "version": "v1"} in ch["endpointsAdded"]
    assert {"techKey": "api:amazon-sp-api", "domain": "sellingpartnerapi", "version": "v2"} in ch["endpointsAdded"]
    assert {"techKey": "api:amazon-sp-api", "domain": "sellingpartnerapi", "version": "v0"} in ch["endpointsRemoved"]
    assert {"eco": "npm", "pkg": "added", "ver": "^2.0"} in ch["sdksAdded"]
    assert {"eco": "npm", "pkg": "gone", "ver": "^1.0"} in ch["sdksRemoved"]
    assert {"eco": "npm", "pkg": "axios", "from": "^1.6", "to": "^1.7"} in ch["sdkVersionChanges"]
    assert {"product": "php", "from": "^8.2", "to": "^8.3"} in ch["runtimeChanges"]


def test_unchanged_repo_not_listed():
    prev = {"repos": [_repo("web", sdks=[_sdk("npm", "axios", "^1.6")])]}
    curr = {"repos": [_repo("web", sdks=[_sdk("npm", "axios", "^1.6")])]}
    assert diff_inventories(prev, curr)["changes"] == []


def test_empty_baseline_yields_no_changes():
    curr = {"repos": [_repo("web", endpoints=[_ep("api:stripe", "api.stripe.com", "v1")])]}
    d = diff_inventories({}, curr)
    assert d["reposAdded"] == ["web"] and d["changes"] == []      # first run: baseline, not "added" endpoints
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_diff.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.inventory_diff'`.

- [ ] **Step 3: Implement the diff**

Create `agent/lib/inventory_diff.py`:

```python
"""Diff two superset inventory docs into a structured change set (what usage changed since last scan)."""
from __future__ import annotations


def _endpoints(repo) -> set:
    return {(e.get("techKey", ""), e.get("domain", ""), e.get("version"))
            for e in repo.get("endpoints", [])}


def _sdks(repo) -> dict:
    return {(s.get("eco", ""), s.get("pkg", "")): s.get("ver", "") for s in repo.get("sdks", [])}


def _runtimes(repo) -> dict:
    return {name: (rt or {}).get("range", "") for name, rt in (repo.get("runtimes") or {}).items()}


def _fmt_eps(tuples) -> list:
    return [{"techKey": tk, "domain": d, "version": v}
            for tk, d, v in sorted(tuples, key=lambda x: (x[0], x[1], str(x[2])))]


def _diff_repo(path, pr, cr) -> dict:
    pe, ce = _endpoints(pr), _endpoints(cr)
    ps, cs = _sdks(pr), _sdks(cr)
    prt, crt = _runtimes(pr), _runtimes(cr)
    return {
        "repo": path,
        "endpointsAdded": _fmt_eps(ce - pe),
        "endpointsRemoved": _fmt_eps(pe - ce),
        "sdksAdded": [{"eco": e, "pkg": p, "ver": cs[(e, p)]} for e, p in sorted(set(cs) - set(ps))],
        "sdksRemoved": [{"eco": e, "pkg": p, "ver": ps[(e, p)]} for e, p in sorted(set(ps) - set(cs))],
        "sdkVersionChanges": [{"eco": e, "pkg": p, "from": ps[(e, p)], "to": cs[(e, p)]}
                              for e, p in sorted(set(ps) & set(cs)) if ps[(e, p)] != cs[(e, p)]],
        "runtimeChanges": [{"product": n, "from": prt[n], "to": crt[n]}
                           for n in sorted(set(prt) & set(crt)) if prt[n] != crt[n]],
    }


def diff_inventories(prev: dict, curr: dict) -> dict:
    p = {r["path"]: r for r in prev.get("repos", [])}
    c = {r["path"]: r for r in curr.get("repos", [])}
    changes = []
    for path in sorted(set(p) & set(c)):
        ch = _diff_repo(path, p[path], c[path])
        if any(ch[k] for k in ch if k != "repo"):
            changes.append(ch)
    return {"reposAdded": sorted(set(c) - set(p)),
            "reposRemoved": sorted(set(p) - set(c)),
            "changes": changes}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_diff.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/inventory_diff.py tests/test_inventory_diff.py
git commit -m "feat(inventory): structured baseline diff (endpoints/sdks/runtimes changes)"
```

---

## Task 2: Diff render + wire into the scan

**Files:**
- Modify: `agent/lib/inventory_diff.py` (add `render_diff_md`)
- Modify: `agent/inventory_scan.py` (compute the diff vs the prior IR)
- Modify: `agent/cli.py` (optional `--out-diff`)
- Test: `tests/test_inventory_scan_diff.py`

**Interfaces:**
- Produces:
  - `render_diff_md(diff: dict) -> str` — a markdown "Changes since last scan" report: repos added/removed, and per-repo sections listing new/removed APIs, version-bumped SDKs, runtime changes. Empty diff → a "no changes" line.
  - `scan_folder(...)` now returns `{"doc", "report_md", "diff"}` where `diff = diff_inventories(prior_ir or {}, doc)` (`prior_ir` = `ir_store.load_ir(state_dir)` captured **before** `save_ir`).
  - CLI `inventory-scan` gains an optional `--out-diff <path>` (default unset); when set, writes `render_diff_md(out["diff"])`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_inventory_scan_diff.py`:

```python
import json
import subprocess
from pathlib import Path
from agent.inventory_scan import scan_folder
from agent.lib.inventory_diff import render_diff_md


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (d / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "c"], cwd=d, check=True)


def _canned(sdks):
    # opengrep finds no endpoints; the diff comes from manifest (sdk) changes
    return json.dumps({"results": [], "errors": [], "paths": {"scanned": []}})


def test_scan_returns_diff_vs_prior_ir(tmp_path):
    root = tmp_path / "repos"
    web = root / "web"
    _git_init(web, {"package.json": '{"dependencies": {"axios": "^1.6"}}'})
    state = tmp_path / "state"

    run1 = scan_folder(str(root), str(state), "2026-07-14", engine="semgrep",
                       run=lambda a: _canned(None))
    assert run1["diff"]["changes"] == [] and run1["diff"]["reposAdded"] == ["web"]  # first run: baseline

    # bump axios + a NEW commit (so head_sha changes -> cache miss -> re-scan)
    (web / "package.json").write_text('{"dependencies": {"axios": "^1.7"}}')
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "-q", "-am", "bump"], cwd=web, check=True)

    run2 = scan_folder(str(root), str(state), "2026-07-21", engine="semgrep",
                       run=lambda a: _canned(None))
    ch = run2["diff"]["changes"][0]
    assert ch["repo"] == "web"
    assert {"eco": "npm", "pkg": "axios", "from": "^1.6", "to": "^1.7"} in ch["sdkVersionChanges"]
    md = render_diff_md(run2["diff"])
    assert "axios" in md and "^1.7" in md


def test_render_diff_empty():
    assert "no changes" in render_diff_md({"reposAdded": [], "reposRemoved": [], "changes": []}).lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_scan_diff.py -q`
Expected: FAIL — `ImportError: cannot import name 'render_diff_md'` (and `scan_folder` result has no `"diff"`).

- [ ] **Step 3: Add `render_diff_md` to `agent/lib/inventory_diff.py`**

Append:

```python
def render_diff_md(diff: dict) -> str:
    out = ["# Changes since last scan", ""]
    added, removed, changes = diff.get("reposAdded", []), diff.get("reposRemoved", []), diff.get("changes", [])
    if not (added or removed or changes):
        out += ["_no changes_", ""]
        return "\n".join(out)
    if added:
        out += [f"**Repos added:** {', '.join(added)}", ""]
    if removed:
        out += [f"**Repos removed:** {', '.join(removed)}", ""]
    for ch in changes:
        out.append(f"## {ch['repo']}")
        for e in ch.get("endpointsAdded", []):
            out.append(f"- 🆕 API {e['techKey']} {e.get('version') or ''} ({e['domain']})")
        for e in ch.get("endpointsRemoved", []):
            out.append(f"- ❌ API removed {e['techKey']} {e.get('version') or ''} ({e['domain']})")
        for s in ch.get("sdkVersionChanges", []):
            out.append(f"- ⬆️ {s['eco']} {s['pkg']}: {s['from']} → {s['to']}")
        for s in ch.get("sdksAdded", []):
            out.append(f"- 🆕 dep {s['eco']} {s['pkg']} {s['ver']}")
        for s in ch.get("sdksRemoved", []):
            out.append(f"- ❌ dep removed {s['eco']} {s['pkg']}")
        for r in ch.get("runtimeChanges", []):
            out.append(f"- 🔧 runtime {r['product']}: {r['from']} → {r['to']}")
        out.append("")
    return "\n".join(out)
```

- [ ] **Step 4: Wire the diff into `agent/inventory_scan.py`**

Add the import at the top:

```python
from agent.lib.inventory_diff import diff_inventories
```

In `scan_folder`, capture the prior IR before overwriting and compute the diff before returning. Change the end of the function:

```python
    prior = ir_store.load_ir(state_dir)                # BEFORE save_ir overwrites it
    doc = {"generated": now, "scope": {"reposScanned": coverage["reposScanned"]},
           "repos": repos, "coverage": coverage}
    doc.update(build_rollups(repos))
    ir_store.save_ir(state_dir, doc)
    return {"doc": doc, "report_md": render_inventory_md(doc),
            "diff": diff_inventories(prior or {}, doc)}
```

(Note: `load_ir` must be called **before** `save_ir`. Place the `prior = ir_store.load_ir(state_dir)` line just before building `doc`.)

- [ ] **Step 5: Run the scan-diff test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_scan_diff.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Add the optional `--out-diff` to the CLI**

Add `from agent.lib.inventory_diff import render_diff_md` near the top of `cli.py`. Then in `_cmd_inventory_scan`, after writing the report md, add:

```python
    if getattr(args, "out_diff", None):
        with open(args.out_diff, "w", encoding="utf-8") as fh:
            fh.write(render_diff_md(out["diff"]))
```

And register the optional arg on the `inventory-scan` subparser (alongside the required ones):

```python
    pis.add_argument("--out-diff", required=False)
```

- [ ] **Step 7: Run the full suite**

Run the CLI test + full suite (excluding the slow live tests for speed, then note the total):
Run: `source .venv/bin/activate && python -m pytest -q --ignore=tests/test_opengrep_live.py --ignore=tests/test_inventory_scan_live.py`
Expected: PASS — 305 (Unit 3b non-live total) + diff(4) + scan-diff(2) = 311 passed.

- [ ] **Step 8: Commit**

```bash
git add agent/lib/inventory_diff.py agent/inventory_scan.py agent/cli.py tests/test_inventory_scan_diff.py
git commit -m "feat(inventory): render diff + wire baseline diff into inventory-scan (--out-diff)"
```

---

## Self-Review

**Spec coverage** (against the spec's Unit 4 "baseline diff" + the IR-first "prior IR = baseline" principle):
- "diff vs prior IR — new endpoint, version bump (SP-API v0→v2), SDK added/removed, MWS still present" → Task 1 `diff_inventories` (endpoints exact-tuple add/remove captures v0→v2 as remove+add; sdk add/remove/version-change; runtime change) ✓
- "the prior `inventory.json` is the baseline" → Task 2 loads `ir_store.load_ir` BEFORE `save_ir` ✓
- "first run has no baseline → empty diff" → `diff_inventories({}, curr)` yields `reposAdded` only, no per-repo `changes` (tested) ✓
- "bridge to the deprecation/delta layer" → the structured diff is the input a later deprecation pass consumes (out of scope here; documented) ✓
- Out of scope, deferred: pairing remove(v0)+add(v2) into a single "version bump" line (the render lists them separately — clear enough); the plugin (Unit 5); Google-Chat/scheduled delivery of the diff.

**Placeholder scan:** none — complete code + tests; the CLI wiring shows the clean `from ... import render_diff_md` form.

**Type consistency:** `diff_inventories(prev, curr) -> {reposAdded, reposRemoved, changes}` consumed by `render_diff_md` and returned by `scan_folder` as `out["diff"]`. Endpoint tuples `(techKey, domain, version)` and sdk `(eco, pkg): ver` / runtime `name: range` match the Unit 3a IR shape exactly. `load_ir(state_dir)` matches `ir_store`. CLI `--out-diff` optional via `getattr`.

**Known Unit-4 simplifications (intentional):** a version bump is a remove+add pair in `endpoints*` (rather than a paired "change" record) — multi-version-safe and clear in the render; SDK/runtime changes ARE paired (single-value per identity).
