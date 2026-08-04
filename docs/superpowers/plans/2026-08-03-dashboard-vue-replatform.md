# Dashboard Vue re-platform + charts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-platform `dashboard.html` from a 930-line Python string-builder onto a vendored,
zero-build Vue global runtime, and add deep-linkable filter state + a hand-rolled SVG
Retirement Timeline — with `drift-scan verify` staying green throughout.

**Architecture:** `dashboard.html` remains ONE self-contained file. `dashboard_render.py`
becomes a thin *injector* that reads static assets (`dashboard.css`, `dashboard.template.html`,
`dashboard.app.js`, vendored `vue.global.prod.js`) and injects the `drift.json` blob(s). The
page hydrates client-side via `Vue.createApp().mount('#app')` — the same client-render trust
model it already uses, now reactive. All dynamic content comes from the embedded blobs.

**Tech Stack:** Python (stdlib + PyYAML runtime only), Vue 3 global build (vendored, no
bundler/npm), hand-rolled SVG. Tests: pytest.

## Global Constraints

- **`dashboard.html` is ONE self-contained file** — Vue runtime + CSS + app JS all inlined; the
  page makes **no external fetch** (no CDN) and opens from `file://`.
- **The `#drift-data` blob stays `== drift.json` verbatim.** `check_blob_matches_payload` must
  pass unchanged. This is the trust anchor — never templated, never mutated.
- **Runtime deps: stdlib + PyYAML only.** No new Python runtime import. **No Node/npm/bundler**
  at scan or CI time.
- **Deterministic output.** No `Date.now()`/wall-clock in logic. The timeline's "today" is the
  payload's `generated` date. Identical inputs → identical bytes (static assets + deterministic
  blob).
- **Keep the existing CSS token system** (light-dark(), container queries, theme toggle, the
  recent density/top-right-filter fixes) — port it, don't redesign it.
- **The Vue computed filters must mirror `verify`'s Python filters exactly** (`check_tile_counts`
  replicates them in Python; divergence = a red verify).
- **Prove every new/changed guard against its bug** (project principle 5): show the guard FAIL
  on the defect it targets before it passes.
- **The correctness claim is `verify` green on a real render** of `.drift-demo` — never "looks
  right" (rendered HTML is not inspectable here).
- No change to the scan/audit pipeline or the `drift.json` schema.

---

## File Structure

- **Create** `agent/assets/vendor/vue.global.prod.js` — pinned Vue 3 global prod build (vendored).
- **Create** `agent/assets/vendor/PROVENANCE.md` — Vue version + source URL + sha256 (the pin record).
- **Create** `agent/assets/dashboard.css` — the CSS token system (moved verbatim from `_CSS`).
- **Create** `agent/assets/dashboard.template.html` — the in-DOM Vue template (the `#app` markup).
- **Create** `agent/assets/dashboard.app.js` — the Vue app (`createApp({...})`), porting the
  vanilla `_CLIENT_JS` logic into `data`/`computed`/`methods`, plus deep-link sync + the timeline.
- **Modify** `agent/lib/dashboard_render.py` — collapse `render_payload` to an asset-injector;
  keep ALL of `_build_projection`/`build_payload`/`build_bundle`/`_blob`/`_blob_script`; delete
  `_CSS`, `_CLIENT_JS`, `_tile_group`; expose `TEMPLATE_SRC` + `APP_JS_SRC` constants for verify.
- **Modify** `agent/lib/verify.py` — add `check_chart_parity`; wire it into `verify_payload`.
- **Modify** `tests/test_dashboard_render.py` — rework HTML/JS-structural assertions to the Vue shape.
- **Modify** `tests/test_verify.py` — point accessor tests at template+app.js; add the
  prove-the-bug template case; add `check_chart_parity` tests.

---

## Task 1: Vendor the Vue runtime (pinned + provenance)

**Files:**
- Create: `agent/assets/vendor/vue.global.prod.js`
- Create: `agent/assets/vendor/PROVENANCE.md`
- Test: `tests/test_dashboard_assets.py`

**Interfaces:**
- Produces: an on-disk vendored Vue global build the injector (Task 3) will inline.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_assets.py
from pathlib import Path
VENDOR = Path(__file__).resolve().parent.parent / "agent" / "assets" / "vendor"

def test_vue_runtime_is_vendored_and_pinned():
    js = (VENDOR / "vue.global.prod.js").read_text(encoding="utf-8")
    assert len(js) > 50_000                       # the real runtime, not a stub
    assert "Vue" in js                            # exposes the global
    prov = (VENDOR / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "vue" in prov.lower() and "http" in prov.lower()   # version + source URL recorded
    import re
    assert re.search(r"\b3\.\d+\.\d+\b", prov)    # a pinned 3.x version string
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_assets.py -q`
Expected: FAIL (files absent).

- [ ] **Step 3: Vendor the file**

Download the current Vue 3 **global production** build and record provenance (needs network,
dev-time only — this file is committed, never fetched at runtime):

```bash
mkdir -p agent/assets/vendor
VER=$(curl -fsSL https://registry.npmjs.org/vue/latest | python3 -c 'import sys,json;print(json.load(sys.stdin)["version"])')
URL="https://unpkg.com/vue@${VER}/dist/vue.global.prod.js"
curl -fsSL "$URL" -o agent/assets/vendor/vue.global.prod.js
SHA=$(sha256sum agent/assets/vendor/vue.global.prod.js | cut -d' ' -f1)
cat > agent/assets/vendor/PROVENANCE.md <<EOF
# Vendored third-party runtime

- **vue** \`${VER}\` — Vue 3 global production build
  - source: ${URL}
  - sha256: ${SHA}
  - fetched: 2026-08-03
  - why vendored: the dashboard is a single self-contained file with zero runtime fetches;
    bumping this is a re-verification event (re-run \`drift-scan verify\` on a real render).
EOF
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dashboard_assets.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/assets/vendor/vue.global.prod.js agent/assets/vendor/PROVENANCE.md tests/test_dashboard_assets.py
git commit -m "feat(dashboard): vendor pinned Vue 3 global runtime (zero-build, no CDN)"
```

---

## Task 2: Extract the CSS to an asset (no behavior change)

**Files:**
- Create: `agent/assets/dashboard.css`
- Modify: `agent/lib/dashboard_render.py` (replace the `_CSS` triple-string with an asset read)
- Test: `tests/test_dashboard_assets.py`

**Interfaces:**
- Produces: `_read_asset(name)` helper + a module-level `CSS_SRC` string, used by `render_payload`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

```python
def test_css_asset_loads_and_is_inlined():
    from agent.lib import dashboard_render as dr
    assert ".tile" in dr.CSS_SRC and "--accent" in dr.CSS_SRC     # the token system moved intact
    from tests.test_dashboard_render import _inv, _audit
    html = dr.render_dashboard(_inv(), _audit([]), "2026-07-15")
    assert "<style>" in html and ".tilegroups" in html           # still inlined into the page
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_assets.py::test_css_asset_loads_and_is_inlined -q`
Expected: FAIL (`CSS_SRC` undefined).

- [ ] **Step 3: Move the CSS + add the asset reader**

Cut the entire contents of the `_CSS = """ … """` block into a new file
`agent/assets/dashboard.css` (CSS only — drop the surrounding Python quotes). In
`dashboard_render.py`, near the top add:

```python
import os
_ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets")

def _read_asset(name: str) -> str:
    with open(os.path.join(_ASSETS, name), encoding="utf-8") as fh:
        return fh.read()

CSS_SRC = _read_asset("dashboard.css")
```

Delete the old `_CSS = """…"""` constant. In `render_payload`, change
`p.append("<style>" + _CSS + "</style></head><body>")` to
`p.append("<style>" + CSS_SRC + "</style></head><body>")`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dashboard_assets.py tests/test_dashboard_render.py -q`
Expected: PASS (CSS is byte-identical, so all existing render tests still pass).

- [ ] **Step 5: Commit**

```bash
git add agent/assets/dashboard.css agent/lib/dashboard_render.py tests/test_dashboard_assets.py
git commit -m "refactor(dashboard): move CSS to an asset file (no behavior change)"
```

---

## Task 3: The Vue shell + template + app skeleton (tiles + headline reactive)

This is the structural pivot. Replace the string-built body with an in-DOM Vue template and a
`createApp` skeleton that renders the **headline + tiles** reactively from the blob. Tables/charts
come in Tasks 4–6. The page must still `verify`-pass at the end of this task.

**Files:**
- Create: `agent/assets/dashboard.template.html`
- Create: `agent/assets/dashboard.app.js`
- Modify: `agent/lib/dashboard_render.py` (`render_payload` → injector; delete `_tile_group`; expose `TEMPLATE_SRC`, `APP_JS_SRC`, `VUE_SRC`)
- Test: `tests/test_dashboard_render.py`

**Interfaces:**
- Consumes: `_read_asset` + `CSS_SRC` (Task 2); `_blob`/`_blob_script` (existing).
- Produces: module constants `TEMPLATE_SRC`, `APP_JS_SRC`, `VUE_SRC`; a `render_payload` that emits
  `<style>CSS</style>` + the template + the 4 data blobs + `<script>VUE</script>` +
  `<script>APP_JS</script>`.

- [ ] **Step 1: Write the failing test** (replace `test_repo_filter_present_and_wired_across_panels`
      and the tile-structural assertions with the Vue shape)

```python
def test_dashboard_is_a_self_contained_vue_app():
    from agent.lib import dashboard_render as dr
    html = dr.render_dashboard(_inv(), _audit([_cve(repo="web")]), "2026-07-15")
    # single self-contained file: Vue inlined, no external fetch
    assert "createApp" in html and "cdn" not in html.lower() and "unpkg" not in html.lower()
    assert 'id="app"' in html                                  # the mount point
    assert "Vue" in html and len(html) > 80_000                # runtime is inlined
    # the trust anchor is intact
    import json, re
    m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>', html, re.S)
    blob = json.loads(m.group(1).replace("\\u003c", "<"))
    assert "counts" in blob and "actions" in blob
    # tiles + repo filter live in the template, bound to the payload (not string-built numbers)
    assert 'id="repo-filter"' in dr.TEMPLATE_SRC and 'class="repopick"' in dr.TEMPLATE_SRC
    assert 'v-for' in dr.TEMPLATE_SRC and "counts" in dr.TEMPLATE_SRC
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py::test_dashboard_is_a_self_contained_vue_app -q`
Expected: FAIL (`TEMPLATE_SRC` undefined; `createApp` absent).

- [ ] **Step 3: Write the template** `agent/assets/dashboard.template.html`

The `#app` markup. Port the existing header (brand + caps + `repopick` filter + theme button),
the reactive headline, and the tile groups. Bind numbers to `counts`/`ownership` instead of
server-rendered values. Tables/panels get placeholder containers filled in Tasks 4–6.

```html
<div id="app" v-cloak>
  <div class="sticky">
    <div class="brand">
      <span class="mark" aria-hidden="true"></span>
      <h1>Drift Detector</h1><span class="sub">DevSecOps Cockpit</span>
      <span class="meta">{{ counts.reposScanned }} repos · {{ generated }}</span>
      <span class="spacer"></span>
      <span class="caps" title="Supply-chain coverage in one pass">
        <span class="cap hot">SBOM</span><span class="cap hot">SCA</span>
        <span class="cap hot">VEX</span><span class="cap hot">SARIF</span>
        <span class="cap">CVE · EOL · sunsets</span></span>
      <select id="repo-filter" class="repopick" aria-label="Scope the report to one repo"
              :data-scoped="scope || null" v-model="scope">
        <option value="">All repos</option>
        <option v-for="r in repoOptions" :key="r.key" :value="r.key">{{ r.label }}</option>
      </select>
      <button class="themebtn" id="theme" @click="cycleTheme">{{ themeLabel }}</button>
    </div>
    <p class="headline"><span class="dot">●</span>
      <span class="big">{{ counts.fixes }} fixes needed</span> ·
      {{ counts.reposAffected }} of {{ counts.reposScanned }} repos affected</p>
    <div class="tilegroups">
      <div class="tg" v-for="g in tileGroups" :key="g.title">
        <span class="lbl">{{ g.title }}</span>
        <div class="tiles">
          <button v-for="t in g.tiles" :key="t.key" class="tile"
                  :data-sev="t.sev || null" :aria-pressed="filter === t.key"
                  @click="toggleTile(t.key)">
            <span class="n" :data-hot="t.sev === 'crit' || null">{{ t.n }}</span>
            <span class="t">{{ t.label }}</span>
          </button>
        </div>
      </div>
    </div>
    <div class="tabbar" role="tablist">
      <button v-for="tb in tabs" :key="tb.id" class="tab" :class="{active: tab === tb.id}"
              @click="tab = tb.id" role="tab">{{ tb.label }}</button>
    </div>
  </div>

  <div id="main">
    <section v-show="tab === 'summary'" class="panel active">
      <!-- Task 4 fills: toolbar search + the reactive summary table -->
      <div id="summary-mount"></div>
    </section>
    <section v-show="tab === 'timeline'" class="panel active">
      <!-- Task 6 fills: the Retirement Timeline SVG + undated lane -->
      <div id="timeline-mount"></div>
    </section>
    <!-- SBOM / SARIF panels ported in Task 5 -->
  </div>
</div>
```

Add `[v-cloak]{display:none}` to `dashboard.css` (hides the un-hydrated template on first paint).

- [ ] **Step 4: Write the app skeleton** `agent/assets/dashboard.app.js`

```javascript
(function(){
  function blob(id){ var el=document.getElementById(id); try{ return el?JSON.parse(el.textContent):{}; }catch(e){ return {}; } }
  var DATA = blob("drift-data");
  var C = DATA.counts || {}, OWN = (C.byOwner || {});

  Vue.createApp({
    data: function(){
      return {
        DATA: DATA, counts: C,
        generated: DATA.generated || "",
        scope: "",            // global repo scope ("" = all)
        filter: null,         // active tile filter
        tab: "summary",
        q: "",
        theme: "dark",
        tabs: [{id:"summary",label:"Summary"},{id:"timeline",label:"Retirement timeline"},
               {id:"sbom",label:"SBOM"},{id:"sarif",label:"SARIF"}]
      };
    },
    computed: {
      repoOptions: function(){
        var m = {};
        (this.DATA.actions||[]).forEach(function(a){ if(a.repo) m[a.repo]=a.repoLabel||a.repo; });
        (this.DATA.shapes||[]).forEach(function(s){ if(s.repo && !(s.repo in m)) m[s.repo]=s.repoLabel||s.repo; });
        return Object.keys(m).sort(function(a,b){ return m[a].localeCompare(m[b]); })
                     .map(function(k){ return {key:k, label:m[k]}; });
      },
      tileGroups: function(){
        var c=this.counts, o=OWN;
        var own=function(k){ var v=o[k]||{}; return (v.DEPRECATED||0)+(v.REVIEW||0); };
        return [
          {title:"Ownership", tiles:[
            {key:"devops",label:"DevOps",n:own("devops")},{key:"developer",label:"Developer",n:own("developer")}]},
          {title:"Security", tiles:[
            {key:"critical",label:"Critical",n:c.critical,sev:"crit"},{key:"fixes",label:"Fixes",n:c.fixes},
            {key:"eol",label:"EOL",n:c.eol}]},
          {title:"Integrations", tiles:[
            {key:"apis",label:"APIs",n:c.apis},{key:"sunsets",label:"Sunsets",n:c.sunsets},
            {key:"pastdue",label:"Past-due",n:c.pastDue,sev:"warn"},{key:"unknown",label:"Unknown",n:c.unknown},
            {key:"private",label:"Private",n:c.private},{key:"unaudited",label:"Unaudited",n:c.unaudited}]}
        ];
      },
      themeLabel: function(){ var m=this.theme; return (m==="dark"?"●":m==="light"?"○":"◐")+" Theme: "+m; }
    },
    methods: {
      toggleTile: function(k){ this.filter = (this.filter===k) ? null : k; this.tab="summary"; },
      cycleTheme: function(){ var m=["auto","light","dark"], i=(m.indexOf(this.theme)+1)%3; this.theme=m[i];
        document.documentElement.style.colorScheme = this.theme==="auto" ? "light dark" : this.theme;
        try{ localStorage.setItem("drift-theme", this.theme); }catch(e){} }
    },
    mounted: function(){
      try{ var s=localStorage.getItem("drift-theme"); if(s) this.theme=s; }catch(e){}
      document.documentElement.style.colorScheme = this.theme==="auto" ? "light dark" : this.theme;
      document.title = "Drift Detector — DevSecOps Cockpit · " + this.generated;
    }
  }).mount("#app");
})();
```

- [ ] **Step 5: Rewrite `render_payload` as the injector** (in `dashboard_render.py`)

Add the constants and collapse the body. Keep `_build_projection`, `build_payload`,
`build_bundle`, `_blob`, `_blob_script`, `render_dashboard` exactly. Delete `_tile_group` and the
old `_CLIENT_JS`/string-built HTML body.

```python
VUE_SRC      = _read_asset("vendor/vue.global.prod.js")
TEMPLATE_SRC = _read_asset("dashboard.template.html")
APP_JS_SRC   = _read_asset("dashboard.app.js")

def render_payload(projection: dict, now: str, *, bundle: dict | None = None) -> str:
    bundle = bundle or _empty_bundle()
    p = ['<!doctype html>', '<html lang="en">', '<head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         '<title>Drift Detector — DevSecOps Cockpit</title>',
         "<style>" + CSS_SRC + "</style></head><body>",
         TEMPLATE_SRC,
         '<script id="drift-data" type="application/json">' + _blob(projection) + "</script>",
         _blob_script("sbom-data", bundle["sbom"]),
         _blob_script("spdx-data", bundle["spdx"]),
         _blob_script("sarif-data", bundle["sarif"]),
         "<script>" + VUE_SRC + "</script>",
         "<script>" + APP_JS_SRC + "</script>",
         "</body></html>"]
    return "\n".join(p)
```

Note: `now` is now unused by the body (the page reads `projection.generated`); keep the param for
signature stability. Ensure `_build_projection` sets `generated` — it already emits a `generated`
key (confirmed in the sample payload); if it is not set from `now`, set
`projection["generated"] = now` inside `build_payload` so the header date is correct.

- [ ] **Step 6: Re-point the accessor-coverage guard at the Vue sources**

Deleting `_CLIENT_JS` breaks the three `test_verify.py` tests that import it
(`check_accessor_coverage(_CLIENT_JS, …)` at lines ~129/175/281). The guard is a pure regex over
a string, so no change to `check_accessor_coverage` itself is needed — feed it the Vue sources
instead. In `test_verify.py`, replace `from …dashboard_render import _CLIENT_JS` usage with:

```python
from agent.lib import dashboard_render as _dr
_CLIENT_SRC = _dr.TEMPLATE_SRC + "\n" + _dr.APP_JS_SRC   # accessors now live in template AND app
```

and pass `_CLIENT_SRC` to `check_accessor_coverage(...)`. The `a.field` accesses now appear in the
in-DOM template (`{{ a.ref }}`) and the app computeds — both are scanned. Keep the existing sample
dicts (they assert the payload carries the fields the page reads).

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py tests/test_dashboard_assets.py tests/test_verify.py -q`
Expected: the new self-contained-app test PASSES; the accessor tests PASS against the Vue sources;
delete/rework any now-obsolete string-HTML assertions (tile numbers, repobar, `_CLIENT_JS`) flagged
as failures — port each to assert on `TEMPLATE_SRC`/`APP_JS_SRC` or the blob instead. The
**projection/data tests must remain untouched and green**.

- [ ] **Step 8: Real render + verify (the correctness gate)**

Run:
```bash
./bin/drift-scan run --root ~/gitlab-fleet --state .drift-demo --now 2026-08-03
./bin/drift-scan verify --state .drift-demo
```
Expected: `✓ … drift.md, dashboard.html and drift.json all agree`. Reload the browser tab to eyeball.

- [ ] **Step 9: Commit**

```bash
git add agent/assets/dashboard.template.html agent/assets/dashboard.app.js agent/lib/dashboard_render.py tests/test_dashboard_render.py tests/test_verify.py
git commit -m "feat(dashboard): re-platform shell onto vendored Vue (headline+tiles reactive)"
```

---

## Task 4: Port the Summary table + filters + repo scope (reactive)

Port the vanilla `actionsFor`/`endpointsFor`/`privateFor`/`catalogFor`/`renderActions`… logic
(current `_CLIENT_JS`, `dashboard_render.py:519-690` in the pre-refactor file, recoverable from
git) into Vue `computed`/`methods`. **The repo scope must apply in EVERY mode** (the bug fixed
earlier — `matchesRepo` in actions AND endpoints AND private).

**Files:**
- Modify: `agent/assets/dashboard.template.html` (the summary table markup)
- Modify: `agent/assets/dashboard.app.js` (filter computeds + row drill-down)
- Test: `tests/test_dashboard_render.py`

**Interfaces:**
- Consumes: `this.scope`, `this.filter`, `this.q`, `DATA.actions/endpoints/private/catalog`.
- Produces: computed `rows` (the mode-dispatched, scope+query-filtered, current selection).

- [ ] **Step 1: Write the failing test** (structural — the filter predicates live in the app source)

```python
def test_repo_scope_and_tile_filters_are_wired_in_all_modes():
    from agent.lib import dashboard_render as dr
    js = dr.APP_JS_SRC
    # the four filter predicates ported from the vanilla engine
    for hook in ("DEPRECATED", "sunset", 'owner', "classified"):
        assert hook in js, hook
    # the repo scope applies to actions, endpoints AND private (the earlier bug)
    assert js.count("matchesRepo") >= 3
    assert "a.repo" in js and "e.repo" in js and "p.repo" in js
    tmpl = dr.TEMPLATE_SRC
    assert 'id="panel"' in tmpl and "v-for" in tmpl        # the table renders rows reactively
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py::test_repo_scope_and_tile_filters_are_wired_in_all_modes -q`
Expected: FAIL.

- [ ] **Step 3: Add the filter computeds + table** (app.js)

Add a `matchesRepo(repo)` method (`return !this.scope || repo === this.scope`), a `matchesQ(text)`
method, and a `rows` computed that dispatches on a `mode` derived from `filter` (mirror the vanilla
map: `apis|unknown → endpoints`, `private → private`, `unaudited → catalog`, else `actions`), then
applies `matchesRepo` + `matchesQ`. Port the predicate bodies **verbatim** from the pre-refactor
`actionsFor`/`endpointsFor`/`privateFor`/`catalogFor` (git history). Add the row drill-down as a
per-row `expanded` flag with an `actionDetail(a)` method (port `actionDetail`, keeping the
`target="_blank"` call-site links + copy buttons + `safeUrl` scheme allow-list).

Template: a `<table id="panel">` with `<template v-for="r in rows">` emitting a row + a
conditional detail row. Keep `esc`/`escA`/`safeUrl` semantics — Vue's `{{ }}` auto-escapes text
(replaces `esc`); for the few `v-html` detail blocks, sanitize via the ported `safeUrl` + escape
helpers (never `v-html` raw scan strings — same XSS discipline as today).

- [ ] **Step 4: Run tests + real verify**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q` → PASS.
Run: `./bin/drift-scan run --root ~/gitlab-fleet --state .drift-demo --now 2026-08-03 && ./bin/drift-scan verify --state .drift-demo` → green. Reload; click each tile + pick a repo; confirm filtering.

- [ ] **Step 5: Commit**

```bash
git add agent/assets/dashboard.template.html agent/assets/dashboard.app.js tests/test_dashboard_render.py
git commit -m "feat(dashboard): reactive summary table + repo scope in all modes"
```

---

## Task 5: Port SBOM / SARIF panels + the drift.json / coverage footer

Port the remaining panels (SBOM preview + CycloneDX/SPDX/SARIF JSON views, the drift.json raw
view, the coverage/changed-since/methodology footer) into the Vue template + app, reading
`SBOM`/`SPDX`/`SARIF` blobs and `DATA` sections. Repo scope applies to SBOM/SARIF as today.

**Files:**
- Modify: `agent/assets/dashboard.template.html`, `agent/assets/dashboard.app.js`
- Test: `tests/test_dashboard_render.py`

**Interfaces:**
- Consumes: `blob("sbom-data")`, `blob("spdx-data")`, `blob("sarif-data")`, `DATA.coverage*`,
  `DATA.inventoryDrift`, `DATA.rootsUnscannable`, `DATA.private`, `DATA.shapes`, `DATA.coverageGrades`.

- [ ] **Step 1: Write the failing test**

```python
def test_sbom_sarif_and_coverage_footer_present():
    from agent.lib import dashboard_render as dr
    tmpl, js = dr.TEMPLATE_SRC, dr.APP_JS_SRC
    for id_ in ("sbom-table", "sarif-groups", "json-drift", "coverage"):
        assert id_ in tmpl, id_
    for src in ("sbom-data", "sarif-data", "spdx-data"):
        assert src in js, src
    # unscannable roots are still surfaced honestly ("cannot see ≠ clean")
    assert "rootsUnscannable" in js
```

- [ ] **Step 2: Run it to verify it fails** → FAIL.

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py::test_sbom_sarif_and_coverage_footer_present -q`

- [ ] **Step 3: Port the panels** — move the SBOM/SARIF/coverage rendering (pre-refactor
`renderSbom`/`renderSarif` + the footer IIFEs) into computeds + template `v-for`s. Keep the
"couldn't scan N sources" honest-blindness block and the coverage-grade list verbatim in meaning.

- [ ] **Step 4: Run tests + real verify** — `pytest tests/test_dashboard_render.py -q` PASS;
`run` + `verify` on `.drift-demo` green.

- [ ] **Step 5: Commit**

```bash
git add agent/assets/dashboard.template.html agent/assets/dashboard.app.js tests/test_dashboard_render.py
git commit -m "feat(dashboard): port SBOM/SARIF panels + coverage footer to Vue"
```

---

## Task 6: The Retirement Timeline (SVG) + tile-vs-chart parity guard

**Files:**
- Modify: `agent/assets/dashboard.template.html`, `agent/assets/dashboard.app.js`
- Modify: `agent/lib/verify.py` (add `check_chart_parity` + wire into `verify_payload`)
- Test: `tests/test_verify.py`, `tests/test_dashboard_render.py`

**Interfaces:**
- Consumes: `DATA.actions` (sunset actions with `date`), `DATA.generated` (the "today" line),
  `this.scope`, `C.sunsets`.
- Produces: computed `timeline = {dated:[...], undated:[...]}`; `verify.check_chart_parity(payload)`.

**Design invariant:** every sunset action is accounted for — dated ones on the axis, undated ones
(`deprecated-no-date`) in a labeled "undated" lane. NONE silently dropped. `dated + undated ==
counts.sunsets`. "Today" = `generated` (never `Date.now()`).

- [ ] **Step 1: Write the failing verify test (prove the guard against its bug)**

```python
# tests/test_verify.py
def test_chart_parity_flags_a_dropped_sunset():
    from agent.lib import verify
    # 2 sunset actions but the tile claims 3 → the timeline would silently omit one
    payload = {"counts": {"sunsets": 3},
               "actions": [{"kind":"sunset","date":"2026-01-01"},
                           {"kind":"sunset","date":None}]}
    try:
        verify.check_chart_parity(payload)
        assert False, "expected a Violation for the dropped sunset"
    except verify.Violation as v:
        assert v.check == "chart-parity"

def test_chart_parity_passes_when_all_sunsets_accounted():
    from agent.lib import verify
    payload = {"counts": {"sunsets": 2},
               "actions": [{"kind":"sunset","date":"2026-01-01"},{"kind":"sunset","date":None}]}
    verify.check_chart_parity(payload)     # dated(1)+undated(1)==2 → no raise
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_verify.py -k chart_parity -q`
Expected: FAIL (`check_chart_parity` undefined).

- [ ] **Step 3: Implement `check_chart_parity`** (verify.py) + wire into `verify_payload`

```python
def check_chart_parity(payload: dict) -> None:
    """The Retirement Timeline must account for EVERY sunset the tile counts — dated points on
    the axis plus undated ones in the labeled lane. A mismatch means the chart silently drops a
    finding (the visual analog of a miscounting tile)."""
    sunsets = [a for a in payload.get("actions", []) if a.get("kind") == "sunset"]
    dated = [a for a in sunsets if a.get("date")]
    undated = [a for a in sunsets if not a.get("date")]
    claimed = (payload.get("counts") or {}).get("sunsets", 0)
    if len(dated) + len(undated) != claimed:
        raise Violation("chart-parity",
                        f"timeline accounts for {len(dated)}+{len(undated)} sunsets but the tile "
                        f"says {claimed} — a finding would be dropped from the chart")
```

Add `(check_chart_parity, (payload,))` to the tuple in `verify_payload`.

- [ ] **Step 4: Run the verify tests** → PASS.

Run: `.venv/bin/python -m pytest tests/test_verify.py -q`

- [ ] **Step 5: Write the timeline** (app.js computed + template SVG)

`timeline` computed: filter sunset actions by `matchesRepo`; split dated/undated; map dated to
x-positions across [min(date, generated) … max(date, generated)] with a vertical line at
`generated`; past-due (date < generated) in `--crit`, upcoming in `--sun`/`--high`. Build an
inline `<svg>` in the template (`v-for` over points; `<title>` for hover with vendor+unit+repo).
Undated ones render as a labeled chip lane below the axis. Respect `prefers-reduced-motion`
(no entrance animation when set). Add a structural test asserting `<svg` + `timeline` in the
sources:

```python
def test_timeline_chart_is_svg_and_scope_aware():
    from agent.lib import dashboard_render as dr
    assert "timeline" in dr.APP_JS_SRC and "matchesRepo" in dr.APP_JS_SRC
    assert "<svg" in dr.TEMPLATE_SRC and "generated" in dr.APP_JS_SRC   # today-line from generated, not Date.now
    assert "Date.now" not in dr.APP_JS_SRC                              # determinism
```

- [ ] **Step 6: Run tests + real verify** — full `pytest -q` green; `run` + `verify` on
`.drift-demo` green; reload and eyeball the timeline (past-due left of today, upcoming right,
undated lane present).

- [ ] **Step 7: Commit**

```bash
git add agent/assets/dashboard.template.html agent/assets/dashboard.app.js agent/lib/verify.py tests/test_verify.py tests/test_dashboard_render.py
git commit -m "feat(dashboard): SVG retirement timeline + tile-vs-chart parity guard"
```

---

## Task 7: Deep-linkable filter state (URL ↔ Vue state)

**Files:**
- Modify: `agent/assets/dashboard.app.js`
- Test: `tests/test_dashboard_render.py`

**Interfaces:**
- Consumes: `location.search`, `this.scope/filter/tab`.
- Produces: URL sync on load (seed state) + on change (`history.replaceState`).

- [ ] **Step 1: Write the failing test** (structural — the sync logic is present)

```python
def test_deep_link_state_sync_is_wired():
    from agent.lib import dashboard_render as dr
    js = dr.APP_JS_SRC
    assert "location.search" in js or "URLSearchParams" in js
    assert "replaceState" in js                     # updates URL without history spam
    for key in ("repo", "tile", "tab"):
        assert key in js, key                        # the three round-tripped params
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py::test_deep_link_state_sync_is_wired -q`

- [ ] **Step 3: Implement the sync** — in `mounted`, parse `new URLSearchParams(location.search)`
→ set `scope` (repo), `filter` (tile), `tab` if present and valid (unknown values fall back to
defaults, never throw). Add a `watch` on `scope`/`filter`/`tab` (or a `syncUrl` method called from
setters) that rebuilds the query string (only non-default values) and calls
`history.replaceState(null, "", url)`. The search box `q` is NOT written to the URL.

- [ ] **Step 4: Run tests + real verify** — `pytest -q` green; `run` + `verify` green; load
`dashboard.html?repo=<key>&tile=sunsets`, confirm it opens scoped+filtered; change filters and
confirm the URL updates.

- [ ] **Step 5: Commit**

```bash
git add agent/assets/dashboard.app.js tests/test_dashboard_render.py
git commit -m "feat(dashboard): deep-linkable filter state (?repo=&tile=&tab=)"
```

---

## Final verification (whole branch)

- [ ] Full suite green: `.venv/bin/python -m pytest -q`
- [ ] Real end-to-end: `./bin/drift-scan run --root ~/gitlab-fleet --state .drift-demo --now 2026-08-03`
      then `./bin/drift-scan verify --state .drift-demo` → `✓ … all agree`.
- [ ] `dashboard.html` is one self-contained file, no external fetch (grep: no `unpkg`/`cdn`/`http`
      script src), opens from `file://`.
- [ ] Deep-link round-trip works; timeline renders with a deterministic today-line; every tile
      filters + repo scope applies in every mode.
- [ ] Byte-stability spot check: two runs on unchanged inputs produce identical `dashboard.html`.
