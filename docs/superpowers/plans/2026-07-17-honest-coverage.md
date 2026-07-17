# Spec B — Honest Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface what the scanner honestly can't see — a distinct "Private / unreachable sources" dashboard view over data already collected, and a per-repo "SDK calls may undercount" signal.

**Architecture:** One additive coverage signal in the scanner (`coverage.sdkMediated`); everything else is render — the dashboard projection flattens `coverage.privateSources` into rows + adds a tile/panel-mode + a Coverage footer that finally renders coverage notes; the inventory report gets a per-repo ⚠ line. No `audit.py`, no detection change.

**Tech Stack:** Python 3.12 stdlib; vanilla inline browser JS. pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-honest-coverage-design.md` — the source of truth.

## Global Constraints

- Python 3.12 in `.venv` (uv-managed). Run tests with `.venv/bin/python -m pytest -q`. **NO pip** — stdlib + existing deps (pyyaml) only. NO new dependency.
- **DETERMINISTIC, ZERO-LLM-TOKEN.** Same inputs → byte-identical `dashboard.html` + `INVENTORY.md`. **NO network in any unit test.**
- **ADDITIVE ONLY:** `coverage.sdkMediated` is new; existing coverage keys (`privateSources`, `endpoints`, `packages`, `repos`) unchanged; existing artifacts (SARIF/BOM/AUDIT.md/audit.json) unchanged; **`audit.py` NOT touched**. The `private` projection + `counts.private` + `projection.sdkMediated` are additive.
- The dashboard stays a **SELF-CONTAINED** file: inline CSS+JS+embedded JSON, no CDN, opens `file://`. `safeUrl` scheme allow-list stays **http(s)-ONLY** (private ssh/scp repo URLs render as **TEXT**, not links). Scan strings escaped via `esc`/`escA`; the `<`-escaped JSON blob unchanged.
- The undercount condition is exactly **"repo declares ≥1 SDK package"** — no threshold, no SDK→vendor mapping.
- `coverageNotes` in the projection come from `audit.coverage.notes` (unchanged source); the NEW **Coverage section** renders those (currently projected-but-never-rendered) PLUS the `sdkMediated` summary from `inventory.coverage.sdkMediated`.
- The tile count must equal the rows its filter yields (`counts.private` = total private sources = one row per source).
- Backward compatibility: the eval harness (`bin/drift-eval run ebay` = 5/5) is the regression net; additive coverage must NOT perturb detection/recall.
- TDD, frequent commits, DRY, YAGNI. **NON-GOALS:** reachability probing, SDK→vendor mapping, SDK-session/dataflow resolution (cognition tier), pinning the private `rushikesh/ebayapi`, the Unknown↔private-repo cross-tag (deferred; Task 5 only DECIDES it). #1/#3 are done (Spec A).

---

## File Structure

| File | Change |
|---|---|
| `agent/inventory_scan.py` | `_rollup_coverage` adds `coverage.sdkMediated` (Task 1). |
| `agent/lib/inventory_render.py` | `_per_repo_section` adds the per-repo ⚠ line (Task 2). |
| `agent/lib/dashboard_render.py` | `_build_projection` projects private rows + sdkMediated + `counts.private` (Task 3); the tile + panel mode + Coverage section (Task 4). |
| `tests/test_inventory_scan.py`, `tests/test_inventory_render.py`, `tests/test_dashboard_render.py` | extend. |

**Ordering:** Task 1 (the coverage signal) → Task 2 (inventory render, independent) → Task 3 (projection, consumes Task 1's signal) → Task 4 (dashboard tile/JS, consumes Task 3) → Task 5 (controller verification + cross-tag decision).

---

## Task 1: `coverage.sdkMediated` in `_rollup_coverage`

**Files:**
- Modify: `agent/inventory_scan.py` (`_rollup_coverage`, after `coverage["privateSources"] = private`)
- Test: `tests/test_inventory_scan.py`

**Interfaces:**
- Produces: `inventory.coverage.sdkMediated` = `list[{repo, sdkCount, endpointCount}]` for repos with ≥1 SDK. Task 3 reads it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_inventory_scan.py` (match the file's existing style for building a `repos`/coverage fixture; if it tests `_rollup_coverage` directly, call it; else assert on a scan doc's `coverage`):

```python
def test_coverage_sdkmediated_lists_repos_with_sdks():
    from agent.inventory_scan import _rollup_coverage
    repos = [
        {"path": "a", "sdks": [{"eco": "composer", "pkg": "dts/ebay-sdk-php"}],
         "endpoints": [{"classified": True}, {"classified": False}]},
        {"path": "b", "sdks": [], "endpoints": [{"classified": True}]},          # no SDKs -> absent
        {"path": "c", "sdks": [{"eco": "npm", "pkg": "x"}, {"eco": "npm", "pkg": "y"}],
         "endpoints": []},
    ]
    # _rollup_coverage MUTATES the coverage dict in place and returns None. The dict must be
    # pre-seeded with the keys it reads (reposScanned/reposErrored), matching how scan_folder seeds it.
    coverage = {"reposScanned": 3, "reposErrored": [], "manifestsUnparsed": []}
    _rollup_coverage(coverage, repos, discovered_count=3)
    sm = coverage["sdkMediated"]
    assert {m["repo"] for m in sm} == {"a", "c"}                       # b (0 SDKs) absent
    a = next(m for m in sm if m["repo"] == "a")
    assert a["sdkCount"] == 1 and a["endpointCount"] == 1              # 1 classified of 2 endpoints
    c = next(m for m in sm if m["repo"] == "c")
    assert c["sdkCount"] == 2 and c["endpointCount"] == 0
    assert "privateSources" in coverage                               # existing key unchanged
```

Signature (verified): `_rollup_coverage(coverage: dict, repos: list, *, discovered_count: int) -> None` — mutates `coverage`, returns None.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_inventory_scan.py -q -k sdkmediated`
Expected: FAIL — `KeyError: 'sdkMediated'`

- [ ] **Step 3: Implement**

In `agent/inventory_scan.py` `_rollup_coverage`, immediately after `coverage["privateSources"] = private`:

```python
    coverage["sdkMediated"] = [
        {"repo": r.get("path"),
         "sdkCount": len(r.get("sdks", [])),
         "endpointCount": sum(1 for e in r.get("endpoints", []) if e.get("classified"))}
        for r in repos if len(r.get("sdks", [])) >= 1
    ]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_inventory_scan.py -q`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add agent/inventory_scan.py tests/test_inventory_scan.py
git commit -m "feat(scan): coverage.sdkMediated — flag SDK-using repos

Additive coverage signal: any repo with >=1 SDK package may undercount
endpoints (SDK-mediated calls have no URL literal). Records {repo, sdkCount,
endpointCount}. No detection change; existing coverage keys untouched."
```

---

## Task 2: per-repo ⚠ undercount line in `INVENTORY.md`

**Files:**
- Modify: `agent/lib/inventory_render.py` (`_per_repo_section`, inside the `if sdks:` block)
- Test: `tests/test_inventory_render.py`

**Interfaces:**
- Consumes: a repo doc's `sdks` list.
- Produces: a per-repo ⚠ markdown line for SDK-using repos.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_inventory_render.py`:

```python
def test_per_repo_flags_sdk_undercount():
    from agent.lib.inventory_render import render_inventory_md
    doc = {"generated": "2026-07-17", "repos": [
        {"path": "with-sdk", "sdks": [{"eco": "composer", "pkg": "dts/ebay-sdk-php", "ver": "^18"}],
         "endpoints": [], "runtimes": {}, "frameworks": {}},
        {"path": "no-sdk", "sdks": [], "endpoints": [
            {"vendor": "eBay", "version": "v1", "files": ["a.php:1"], "domain": "svcs.ebay.com"}],
         "runtimes": {}, "frameworks": {}},
    ]}
    md = render_inventory_md(doc)
    # the SDK repo carries the undercount caveat; the no-SDK repo does not
    assert "may not be listed as endpoints" in md
    with_block = md.split("### with-sdk")[1].split("### no-sdk")[0]
    no_block = md.split("### no-sdk")[1]
    assert "⚠" in with_block and "SDK-mediated" in with_block
    assert "⚠" not in no_block
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_inventory_render.py -q -k sdk_undercount`
Expected: FAIL — the ⚠ line isn't rendered.

- [ ] **Step 3: Implement**

In `agent/lib/inventory_render.py` `_per_repo_section`, inside the existing `if sdks:` block, after the `- **SDKs:** …` line (currently the `out.append(f"- **SDKs:** {shown}{more}")` line), add:

```python
            out.append(f"- ⚠ **{len(sdks)} SDK package(s)** — SDK-mediated calls (no URL "
                       f"literal) may not be listed as endpoints.")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_inventory_render.py -q`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/inventory_render.py tests/test_inventory_render.py
git commit -m "feat(report): per-repo SDK-undercount caveat in INVENTORY.md

Each SDK-using repo gets a ⚠ line under its SDKs: SDK-mediated calls have no
URL literal and may not be listed as endpoints. Honest coverage for the
getCategoryFeatures-style ceiling (no detection change)."
```

---

## Task 3: project private-sources + sdkMediated in `_build_projection`

**Files:**
- Modify: `agent/lib/dashboard_render.py` (`_build_projection`)
- Test: `tests/test_dashboard_render.py`

**Interfaces:**
- Consumes: `inventory.coverage.privateSources` (existing) + `inventory.coverage.sdkMediated` (Task 1).
- Produces: `projection["private"]` = `list[{repo, source, kind, via}]`; `counts["private"]` = total private sources; `projection["sdkMediated"]` = the Task-1 list. Task 4's JS reads all three.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dashboard_render.py`:

```python
def _inv_with_private(private, sdkmediated=()):
    return {"repos": [], "coverage": {"privateSources": list(private),
                                      "sdkMediated": list(sdkmediated)}}


def test_projection_flattens_private_sources_and_counts():
    from agent.lib.dashboard_render import _build_projection
    inv = _inv_with_private([
        {"repo": "r", "packages": [{"pkg": "@acme/secret", "via": "git+ssh://x"}],
         "repositories": ["https://git.internal/pkg.git"]},
    ], sdkmediated=[{"repo": "r", "sdkCount": 2, "endpointCount": 0}])
    proj = _build_projection(inv, {"actions": []})
    assert proj["counts"]["private"] == 2                               # 1 package + 1 repo
    rows = proj["private"]
    assert {r["kind"] for r in rows} == {"package", "repo"}
    pkg = next(r for r in rows if r["kind"] == "package")
    assert pkg == {"repo": "r", "source": "@acme/secret", "kind": "package", "via": "git+ssh://x"}
    repo = next(r for r in rows if r["kind"] == "repo")
    assert repo["source"] == "https://git.internal/pkg.git" and repo["via"] == ""
    assert proj["sdkMediated"] == [{"repo": "r", "sdkCount": 2, "endpointCount": 0}]


def test_projection_private_empty_when_no_private_sources():
    from agent.lib.dashboard_render import _build_projection
    proj = _build_projection({"repos": [], "coverage": {}}, {"actions": []})
    assert proj["counts"]["private"] == 0 and proj["private"] == [] and proj["sdkMediated"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q -k "flattens_private or private_empty"`
Expected: FAIL — `counts["private"]`/`projection["private"]` absent.

- [ ] **Step 3: Implement**

In `agent/lib/dashboard_render.py` `_build_projection`, after the `endpoints = _endpoints_of(inventory)` line, add the private flatten; add `"private"` to the `counts` dict; and add `private`/`sdkMediated` to the returned projection:

```python
    cov = inventory.get("coverage") or {}
    private = []
    for p in cov.get("privateSources", []):
        for pkg in p.get("packages", []):
            private.append({"repo": p.get("repo"), "source": pkg.get("pkg"),
                            "kind": "package", "via": pkg.get("via", "")})
        for url in p.get("repositories", []):
            private.append({"repo": p.get("repo"), "source": url, "kind": "repo", "via": ""})
```

Add to the `counts` dict (beside `"unknown"`):

```python
        "private": len(private),
```

Add to the returned dict (beside `"endpoints": endpoints,`):

```python
        "private": private,
        "sdkMediated": cov.get("sdkMediated", []),
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/dashboard_render.py tests/test_dashboard_render.py
git commit -m "feat(dashboard): project private sources + sdkMediated

_build_projection flattens coverage.privateSources into {repo,source,kind,via}
rows (counts.private = total sources) and carries coverage.sdkMediated through.
Additive; the JS consumes them next."
```

---

## Task 4: the "Private / unreachable" tile + panel mode + Coverage section

**Files:**
- Modify: `agent/lib/dashboard_render.py` (the Integrations `_tile_group`, the body HTML, the `_CSS`, the `_CLIENT_JS`)
- Test: `tests/test_dashboard_render.py`

**Interfaces:**
- Consumes: `projection.private`, `counts.private`, `projection.sdkMediated`, `projection.coverageNotes` (Task 3 + existing).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dashboard_render.py` (reuse `_inv_with_private` from Task 3; build a minimal audit):

```python
def test_dashboard_has_private_tile_mode_and_coverage_section():
    from agent.lib.dashboard_render import render_dashboard
    inv = _inv_with_private(
        [{"repo": "r", "packages": [{"pkg": "@acme/secret", "via": "git+ssh://x"}],
          "repositories": ["https://git.internal/pkg.git"]}],
        sdkmediated=[{"repo": "svc", "sdkCount": 3, "endpointCount": 1}])
    audit = {"generated": "2026-07-17", "actions": [],
             "coverage": {"notes": ["Sources: OSV.dev + endoflife.date."]}}
    html = render_dashboard(inv, audit, "2026-07-17")
    js = html.split("<script>")[-1]
    # tile present in the Integrations group
    assert 'data-filter="private"' in html and "Private / unreachable" in html
    # a private panel mode exists in the JS
    assert '"private"' in js and "renderPrivate" in js and "privateFor" in js
    # the private source strings are embedded (rendered on click)
    assert "@acme/secret" in html and "git.internal/pkg.git" in html
    # the Coverage section renders the coverage note AND names the sdkMediated repo
    assert 'id="coverage"' in html
    assert "OSV.dev" in html                                    # coverageNotes now rendered
    assert "svc" in html and "may undercount" in html.lower() or "undercount" in js.lower()


def test_private_source_xss_escaped():
    from agent.lib.dashboard_render import render_dashboard
    evil = 'a<script>alert(1)</script>&"x'
    inv = _inv_with_private([{"repo": evil, "packages": [{"pkg": evil, "via": evil}],
                              "repositories": []}])
    out = render_dashboard(inv, {"actions": [], "coverage": {}}, "2026-07-17")
    assert "<script>alert(1)</script>" not in out               # not literal in HTML
    blob = out.split('id="drift-data" type="application/json">')[1].split("</script>")[0]
    assert "</script>" not in blob                              # blob can't break out


def test_safeurl_still_http_only():
    from agent.lib.dashboard_render import render_dashboard
    html = render_dashboard({"repos": [], "coverage": {}}, {"actions": [], "coverage": {}}, "2026-07-17")
    js = html.split("<script>")[-1]
    assert "/^https?:\\/\\//i" in js                            # safeUrl allow-list unchanged
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q -k "private_tile or private_source_xss or safeurl_still"`
Expected: FAIL — no private tile / mode / coverage section.

- [ ] **Step 3: Implement the tile + HTML + CSS**

Add the tile to the Integrations `_tile_group` call (after the `unknown` tile):

```python
    parts.append(_tile_group("Integrations", [
        ("apis", "APIs used", c["apis"]),
        ("sunsets", "Sunsets", c["sunsets"]),
        ("unknown", "Unknown hosts", c["unknown"]),
        ("private", "Private / unreachable", c["private"])]))
```

Add the Coverage section to the body, immediately after the `<p id="empty" …>` line:

```python
    parts.append('<section id="coverage" class="coverage"></section>')
```

Add CSS to `_CSS`:

```css
.coverage{margin:16px 18px;color:var(--muted,#8a8f98);font-size:12px}
.coverage h2{font-size:13px;margin:0 0 6px}
.coverage .note{padding:2px 0}
.intro{color:var(--muted,#8a8f98);font-style:italic;padding:6px 0}
```

- [ ] **Step 4: Implement the JS (panel mode + Coverage population)**

In `_CLIENT_JS`, add `privateFor` + `renderPrivate` (after `renderEndpoints`):

```javascript
  function privateFor(){
    return (DATA.private||[]).filter(function(p){ return matchesQ((p.repo||"")+" "+(p.source||"")); });
  }
  function renderPrivate(list){
    var intro=document.createElement("tr"), itd=document.createElement("td");
    itd.colSpan=5; itd.className="intro";
    itd.textContent="Sub-dependencies the scan couldn't crawl — private or unreachable.";
    intro.appendChild(itd); body.appendChild(intro);
    list.forEach(function(p){
      var tr=document.createElement("tr"); tr.className="row";
      var src=esc(p.source);
      if(p.kind==="repo"){ var u=safeUrl(p.source); if(u){ src='<a href="'+escA(u)+'" rel="noopener">'+esc(p.source)+'</a>'; } }
      tr.innerHTML='<td>'+esc(p.repo)+'</td><td>'+src+'</td><td>'+esc(p.kind)+
        '</td><td>'+esc(p.via||"")+'</td><td></td>';
      body.appendChild(tr);
    });
  }
```

Extend `render()` to handle the private mode:

```javascript
  function render(){
    body.innerHTML="";
    if(state.mode==="endpoints"){ renderEndpoints(endpointsFor()); }
    else if(state.mode==="private"){ renderPrivate(privateFor()); }
    else { renderActions(actionsFor()); }
    empty.hidden = body.children.length>0;
  }
```

Update the tile-click mode selection (the `state.mode=…` line) to route `private` to its mode:

```javascript
      else { state.filter=f;
             state.mode = (f==="apis"||f==="unknown") ? "endpoints"
                        : (f==="private") ? "private"
                        : "actions";
             t.setAttribute("aria-pressed","true"); }
```

Populate the Coverage section on load (add just before the final `render();` call):

```javascript
  (function(){
    var cov=document.getElementById("coverage"); if(!cov) return;
    var h="<h2>Coverage</h2>";
    (DATA.coverageNotes||[]).forEach(function(n){ h+='<div class="note">'+esc(n)+'</div>'; });
    var sm=DATA.sdkMediated||[];
    if(sm.length){
      h+='<div class="note">'+esc(sm.length)+' repo(s) use SDK client(s) — calls routed through an '
        +'SDK have no URL literal and aren’t listed as endpoints, so the endpoint count may '
        +'undercount:</div><ul>';
      sm.forEach(function(m){ h+='<li>'+esc(m.repo)+' ('+esc(m.sdkCount)+' SDKs, '
        +esc(m.endpointCount)+' endpoints)</li>'; });
      h+='</ul>';
    }
    cov.innerHTML=h;
  })();
```

- [ ] **Step 5: Run tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q`
Expected: PASS.
Then: `.venv/bin/python -m pytest -q`
Expected: PASS, no regressions (full suite ~6 min — use a generous timeout).

- [ ] **Step 6: Commit**

```bash
git add agent/lib/dashboard_render.py tests/test_dashboard_render.py
git commit -m "feat(dashboard): Private/unreachable tile + panel + Coverage section

New Integrations tile 'Private / unreachable' (count = private sources) with a
panel mode listing each private package/repo the scan couldn't crawl, distinct
from Unknown hosts. A Coverage footer finally renders the coverage notes (long
projected, never shown) + the sdkMediated undercount summary. safeUrl stays
http(s)-only (ssh private URLs render as text); scan strings esc/escA'd."
```

---

## Task 5: verify on real data + the cross-tag decision (CONTROLLER-run, live)

**This is a verification checkpoint** — the controller runs it (live scan). No new production code unless the fallback fires.

- [ ] **Step 1: Render a real dashboard that exercises both signals**

The eBay corpus SDKs are public composer packages, so `privateSources` may be **empty** there — but `sdkMediated` will be populated (e.g. `ebay-sdk-examples`). Run:

```bash
DRIFT_GITLAB_HOSTS=git.topsdemo.in ./bin/drift-eval run ebay --now 2026-07-17 --no-clone
# inspect the produced dashboard for the corpus scan (~/.drift/eval/runs/2026-07-17/ebay/)
```

Confirm the **Coverage section** names the SDK-using repos (e.g. `ebay-sdk-examples (… SDKs, 1 endpoints)`). If the eval runner doesn't emit a dashboard, render one from its `inventory.json`+`audit.json` with `render_dashboard` (as done for prior demos).

- [ ] **Step 2: Exercise the private-sources section on real data**

The corpus likely has **no** private composer sources. To prove the private tile/panel renders, scan a set that does — e.g. `~/gitlab-fleet/rushikesh/ebayapi` (a real repo that may declare a private composer `repositories` entry) or another synced repo. Render its dashboard and confirm the **"Private / unreachable"** tile shows a non-zero count and clicking it lists the private package/repo rows, distinct from "Unknown hosts".

**Fallback if no real repo in reach has a private source:** add a committed unit-level fixture proving the render path end to end — a hand-built `inventory` whose `coverage.privateSources` has one package + one repo, asserting the rendered dashboard shows the tile count `2` and both source strings (this is essentially Task 4's `test_dashboard_has_private_tile_mode_and_coverage_section`, so it's already covered — note that the real-data render was empty and the unit fixture is the proof).

- [ ] **Step 3: The cross-tag decision (deferred-or-not)**

From the same real scan, check whether the cross-tag would ever fire:

```bash
# does any Unknown endpoint host match a privateSources.repositories host?
.venv/bin/python - <<'PY'
import json, os
# load a real inventory that has both unknown endpoints and privateSources
inv = json.load(open(os.path.expanduser("~/.drift/eval/runs/2026-07-17/ebay/inventory.json")))
from urllib.parse import urlparse
unknown_hosts = {e["domain"] for r in inv["repos"] for e in r.get("endpoints", []) if e.get("vendor")=="Unknown"}
priv_hosts = set()
for r in inv["repos"]:
    for u in (r.get("privateSources") or {}).get("repositories", []):
        priv_hosts.add(urlparse(u if "://" in u else "ssh://"+u.replace(":","/",1)).hostname or "")
overlap = unknown_hosts & priv_hosts
print("unknown hosts:", len(unknown_hosts), "| private repo hosts:", len(priv_hosts), "| OVERLAP:", overlap)
PY
```

- If **OVERLAP is empty** (expected): record in the commit/report that the cross-tag was **correctly deferred** — it doesn't fire on real data.
- If **OVERLAP is non-empty**: record it as a **follow-up** for a small cross-tag (re-badge those Unknown endpoints as private) — do **not** build it in this plan; note it for a future spec.

- [ ] **Step 4: The regression net**

```bash
DRIFT_GITLAB_HOSTS=git.topsdemo.in ./bin/drift-eval run ebay --now 2026-07-17 --no-clone
```
Expected: `RECALL 5/5 … [PASS]` — the additive coverage must not have moved recall. If it dropped, stop and fix.

- [ ] **Step 5: Record the verification (commit note or ledger)**

No code commit unless the fallback fixture was needed. Record: what the Coverage section showed (which repos flagged), whether the private tile rendered on real data (or that the unit fixture is the proof), the cross-tag OVERLAP result, and `drift-eval` 5/5.

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `coverage.sdkMediated` (condition = ≥1 SDK) | 1 |
| per-repo ⚠ undercount in INVENTORY.md | 2 |
| projection: private rows + counts.private + sdkMediated | 3 |
| "Private / unreachable" tile (Integrations) | 4 |
| private panel mode (distinct from Unknown) | 4 |
| Coverage section renders coverageNotes + sdkMediated | 4 |
| safeUrl unchanged (http(s)-only; ssh → text) | 4 |
| XSS on private strings | 4 |
| tile count == rows | 3 (count) + 4 (render) |
| no audit.py change; additive | all |
| eval 5/5 regression net; real-data render | 5 |
| cross-tag decision (deferred unless it fires) | 5 |

No gaps.

**Placeholder scan:** none — every code step has complete code; Task 5's "concrete result" is a live verification (values discovered at run time, not invented) with a committed-fixture fallback.

**Type consistency:** `coverage.sdkMediated` = `list[{repo, sdkCount, endpointCount}]` (T1) → read by `_build_projection` as `projection.sdkMediated` (T3) → consumed by the JS Coverage section as `m.repo`/`m.sdkCount`/`m.endpointCount` (T4). `projection.private` = `list[{repo, source, kind, via}]` (T3) → consumed by `renderPrivate` as `p.repo`/`p.source`/`p.kind`/`p.via` (T4). `counts.private` (T3) → tile `c["private"]` (T4). Cross-checked field-by-field. `_rollup_coverage`'s exact signature is verified in Task 1 Step 1 before the test is written (the plan flags it).
