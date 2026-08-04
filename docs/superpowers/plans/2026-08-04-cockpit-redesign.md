# Cockpit redesign (mockup → real dashboard) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Restructure the (already-Vue) dashboard to match the approved layout mockup:
full-width, the metric tiles become the **primary tab strip**, a **hero chart region** (a
per-operation Retirement Timeline) sits where the cards were, and Summary/SBOM/SARIF become
**sub-tabs** — all without weakening `drift-scan verify`.

**Design reference (read it — it is the visual spec):**
`docs/design/2026-08-04-cockpit-mockup.html` — a self-contained, real-data mockup of the target
layout, interactions, palette, and the per-operation timeline. Match its structure and CSS; it
already uses the project's token palette.

**Tech Stack:** existing vendored Vue global runtime, the existing CSS token system, hand-rolled
CSS/SVG charts (NO chart library — the mockup's per-operation layout is the approved look).

## Global Constraints

- **No chart library.** Hand-rolled CSS/HTML/SVG, matching the mockup. (Reversible later.)
- **The `#drift-data` blob stays `== drift.json`.** The data layer (`_build_projection`/
  `build_payload`) is UNTOUCHED; this is presentation-only. `check_blob_matches_payload` must pass.
- **`check_tile_counts` must keep passing** — the tiles (now tab headers) still display counts
  bound to the payload; the Python-replicated filters are unchanged.
- **`check_timeline_lanes` must keep passing** — the new per-operation timeline still renders BOTH
  the dated axis AND the undated lane; update the guard's markers to match the new template, and
  keep it proven against its bug (delete-the-undated-lane raises).
- **`check_accessor_coverage` must keep passing** — the summary table's `row` var + `a|e|p|cv`
  accessors stay tracked; feed `TEMPLATE_SRC + APP_JS_SRC`. New timeline reads are `a.` (action)
  fields — already tracked.
- **XSS structural discipline:** all scan-controlled data via Vue `{{ }}`/`:attr` (auto-escaped),
  URLs via `safeUrl()`. ZERO `v-html`/`innerHTML`. The tooltip content binds via text, not v-html.
- **Determinism:** the timeline "today" line = the payload's `generated` date (reuse the existing
  pure `dayOrdinal`); NO `Date.now`/`Math.random`/`new Date(wall-clock)` in shipped app.js.
- **Honesty surfaces preserved:** zero-count dimensions show the "zero is only meaningful because
  we could read these repos" empty-state; the coverage/unscannable/unaudited footer stays.
- **Correctness claim = `verify` green on a real render** of `.drift-demo` (rendered HTML is not
  inspectable). Every task ends on a green verify.
- Single self-contained file; no external fetch; runtime stdlib + PyYAML only.

## State model (the reconciliation)

Current app.js state `{scope, filter, tab, q, …}` becomes:
- `scope` — repo filter (unchanged; the top-right picker).
- `tab` — the active PRIMARY metric dimension (replaces `filter`). `null` = **overview** default
  (no dimension scope → Summary shows the full ranked queue). Clicking a tile-tab sets it; clicking
  the active one again clears to `null` (toggle — preserves today's filter semantics).
- `sub` — the active SUB-tab: `summary` (default) | `sbom` | `sarif`.
- `mode` (computed from `tab`) — unchanged mapping: `apis|unknown→endpoints`, `private→private`,
  `unaudited→catalog`, else `actions`.
- `q`, `expanded`, `theme` — unchanged.

The old top-level `tab` values (summary/timeline/sbom/sarif) are gone: **timeline → the hero
region**; summary/sbom/sarif → `sub`.

---

## File Structure

- **Modify** `agent/assets/dashboard.css` — remove `max-width:1240px;margin:0 auto` (full-width,
  fluid padding); add the tabstrip / hero / sub-tab / timeline-row / tooltip styles from the mockup.
- **Modify** `agent/assets/dashboard.template.html` — restructure: brand+picker header, the
  primary tab strip (tiles-as-tabs, grouped), the hero region, the sub-tab bar + sub-panel; the
  summary table moves under the sub-panel; drop the old tile-grid + old tab bar + old timeline tab.
- **Modify** `agent/assets/dashboard.app.js` — the new state model, the `tab`/`sub` wiring, the
  contextual hero (timeline vs vendor-bars vs empty-state), the per-operation timeline computed +
  tooltip, deep-link param reconciliation.
- **Modify** `agent/lib/verify.py` — update `check_timeline_lanes` markers for the new template.
- **Modify** `tests/test_dashboard_render.py`, `tests/test_verify.py` — rework the structural
  assertions to the new IA; keep projection/data tests untouched.

---

## Task 1: Full-width + primary-tab-strip + sub-tab shell

Restructure the shell: tiles become the primary tab strip, add the hero region + sub-tab bar, move
the summary table under the sub-panel. Reuse the existing filter/mode/table logic. The hero stays
a placeholder mount this task (Task 2/3 fill it). Ends verify-green.

**Files:** modify `dashboard.css`, `dashboard.template.html`, `dashboard.app.js`, `tests/test_dashboard_render.py`.

**Interfaces:**
- Produces: `state.tab` (null|tile-key), `state.sub` ('summary'|'sbom'|'sarif'); `toggleTab(key)`;
  the summary `rows` computed now reads `state.tab` (null → all actions) instead of `state.filter`.
- Consumes: existing `rows`/`mode`/`matchesRepo`/`matchesQ`/`actionsFor`… (rename `filter`→`tab`).

- [ ] **Step 1: Write the failing test**

```python
def test_cockpit_ia_tiles_are_tabs_hero_and_subtabs():
    from agent.lib import dashboard_render as dr
    tmpl = dr.TEMPLATE_SRC
    assert 'class="tabstrip"' in tmpl                 # tiles-as-tabs primary nav
    assert 'class="hero"' in tmpl or 'id="hero' in tmpl
    assert 'class="subbar"' in tmpl and 'class="subtab"' in tmpl
    # full-width: the centered column is gone from the CSS
    assert "max-width:1240px" not in dr.CSS_SRC
    js = dr.APP_JS_SRC
    assert "toggleTab" in js and "state" in js
    # the summary rows scope to the active primary tab (null => all actions)
    assert "this.tab" in js
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py::test_cockpit_ia_tiles_are_tabs_hero_and_subtabs -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Follow `docs/design/2026-08-04-cockpit-mockup.html` for the exact markup + CSS of `.tabstrip`,
`.tgroup`/`.mtab` (tile-as-tab, count + label, `[data-on]` active state, `[data-zero]` dimming),
`.hero`, `.subbar`/`.subtab`, `.panel`. In `dashboard.css` remove `max-width:1240px;margin:0 auto`
from `body` and set the wrapper to full-width fluid padding (`padding:0 clamp(16px,3vw,40px) 60px`).
In `dashboard.app.js`: rename `filter`→`tab`, add `sub`, add `toggleTab(key)` (set/clear), point the
summary `rows` computed at `this.tab` (null → all actions; else the same predicate as the old
`filter`). Keep `mode` derivation. The hero region is an empty `<div id="hero-body">` placeholder
(Task 2/3). The tiles-as-tabs bind their counts to the payload exactly as the old tiles did.

- [ ] **Step 4: Rework structural tests + run**

Update any test asserting the old tile-grid / old tab bar / `state.filter` to the new IA. Keep all
projection/data tests untouched. **Also: the existing deep-link sync (prior plan's Task 7) and its
`test_deep_link_state_sync_is_wired` reference `state.filter` and the `tile`/`tab` params** — renaming
`filter`→`tab` and dropping the old top-level tab breaks them. Keep the suite green by updating the
deep-link references + that test to the interim `repo`/`tab` params now (unknown values still fall
back, no throw); the FULL `?repo=&tab=&sub=` reconciliation lands in Task 4. Run
`.venv/bin/python -m pytest tests/test_dashboard_render.py tests/test_verify.py -q` → green.

- [ ] **Step 5: Real render + verify**

```bash
./bin/drift-scan run --root ~/gitlab-fleet --state .drift-demo --now 2026-08-04
./bin/drift-scan verify --state .drift-demo
```
Expected: `✓ … all agree`. Reload the browser to eyeball the new shell.

- [ ] **Step 6: Commit**

```bash
git add agent/assets/dashboard.css agent/assets/dashboard.template.html agent/assets/dashboard.app.js tests/test_dashboard_render.py
git commit -m "feat(dashboard): full-width cockpit — tiles become primary tabs + sub-tab shell"
```

---

## Task 2: Per-operation Retirement Timeline in the hero

Replace the old single-line timeline with the mockup's per-operation rows (grouped by vendor,
date on the axis, a `generated`-anchored TODAY line, hover tooltip), rendered in the hero region
for sunset-driven tabs (and the overview default). Update `check_timeline_lanes` to the new markers.

**Files:** modify `dashboard.template.html`, `dashboard.app.js`, `dashboard.css`, `agent/lib/verify.py`, `tests/test_verify.py`, `tests/test_dashboard_render.py`.

**Interfaces:**
- Consumes: `DATA.actions` (sunset actions: `ref`,`unit`,`date`,`repo`/`repoLabel`,`status`),
  `DATA.generated`, `this.scope`, the existing pure `dayOrdinal`.
- Produces: `timeline` computed `{dated:[{...,pct,kind}], undated:[...], byVendor}`; the hero renders it.

**Design invariant (unchanged):** every sunset accounted for — dated on the axis, undated in the
labeled lane, none dropped. `kind`: past-due (`date < generated`) / soon (≤183 days) / upcoming.

- [ ] **Step 1: Write the failing verify test (prove-the-guard)** — update `check_timeline_lanes`
      to assert the NEW template renders both lanes. First write a test that a template missing the
      undated lane RAISES, and the real `TEMPLATE_SRC` passes:

```python
def test_timeline_lanes_guard_matches_the_new_per_operation_markup():
    from agent.lib import dashboard_render as dr
    from agent.lib import verify
    verify.check_timeline_lanes(dr.TEMPLATE_SRC)                 # real template passes
    bad = dr.TEMPLATE_SRC.replace("timeline.undated", "timeline.dated")  # drop the undated lane
    try:
        verify.check_timeline_lanes(bad); assert False, "expected a Violation"
    except verify.Violation as v:
        assert v.check == "timeline-lanes"
```

- [ ] **Step 2: Run it to verify it fails** → adjust markers so it's meaningful.

Run: `.venv/bin/python -m pytest tests/test_verify.py -k timeline_lanes -q`

- [ ] **Step 3: Implement the timeline** — per `docs/design/2026-08-04-cockpit-mockup.html`
      (`timelineHTML`, `.axis`/`.trk`/`.pt`/`.today`/`.tip` CSS, `wireTips`). Port it into the Vue
      template as a `timeline` computed + `v-for` rows (NOT string-concatenated), with the tooltip
      shown via reactive state + `{{ }}` bindings (no `v-html`). "Today" position uses `dayOrdinal(this.generated)`
      — never `Date.now()`. Scope by `this.scope`. Group by vendor; undated (`!a.date`) render in the
      labeled undated lane. Update `check_timeline_lanes` in verify.py to grep the new markers
      (`timeline.dated` axis + `timeline.undated` lane).

- [ ] **Step 4: Add the structural test + run**

```python
def test_hero_timeline_is_per_operation_and_deterministic():
    from agent.lib import dashboard_render as dr
    assert "timeline" in dr.APP_JS_SRC and "dayOrdinal" in dr.APP_JS_SRC
    assert "Date.now" not in dr.APP_JS_SRC
    assert "byVendor" in dr.APP_JS_SRC or "vgroup" in dr.TEMPLATE_SRC   # grouped per operation
```

Run full: `.venv/bin/python -m pytest -q` → green.

- [ ] **Step 5: Real render + verify** — `run` + `verify` on `.drift-demo` → green (exercises
      `check_timeline_lanes` on real data). Reload; confirm per-operation rows + hover identity + today line.

- [ ] **Step 6: Commit**

```bash
git add agent/assets/dashboard.template.html agent/assets/dashboard.app.js agent/assets/dashboard.css agent/lib/verify.py tests/test_verify.py tests/test_dashboard_render.py
git commit -m "feat(dashboard): per-operation retirement timeline as the hero (identity + hover)"
```

---

## Task 3: Contextual hero for non-timeline tabs + honest empty-states

When the active primary tab is APIs/Unknown, the hero shows the vendor/endpoint breakdown (mockup
`.mini`/`.bar`); for zero-count dimensions it shows the honest empty-state ("zero is only meaningful
because the scan could read these repos"); sunset-driven tabs + overview keep the timeline.

**Files:** modify `dashboard.template.html`, `dashboard.app.js`, `dashboard.css`, `tests/test_dashboard_render.py`.

**Interfaces:**
- Consumes: `DATA.endpoints`, `DATA.counts`, `this.tab`.
- Produces: a `heroMode` computed ('timeline'|'vendors'|'empty') driving the hero; a `vendorBars` computed.

- [ ] **Step 1: Write the failing test**

```python
def test_hero_is_contextual_with_honest_empty_state():
    from agent.lib import dashboard_render as dr
    js, tmpl = dr.APP_JS_SRC, dr.TEMPLATE_SRC
    assert "heroMode" in js                                   # timeline | vendors | empty
    # honest empty-state copy for a zero dimension (cannot see != clean)
    assert "could read" in tmpl or "cannot see" in tmpl.lower() or "unaudited" in js.lower()
    assert "endpoints" in js                                  # vendor breakdown reads endpoints
```

- [ ] **Step 2: Run it to verify it fails** → FAIL.

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py::test_hero_is_contextual_with_honest_empty_state -q`

- [ ] **Step 3: Implement** — add `heroMode` (timeline for sunset/pastdue/fixes/developer/overview;
      vendors for apis/unknown; empty otherwise) and `vendorBars` (endpoints grouped by vendor, from
      the mockup `.mini`/`.bar`). Template: `v-if`/`v-else-if` in the hero body. The empty-state must
      carry the honesty message verbatim in spirit. XSS: vendor names via `{{ }}`.

- [ ] **Step 4: Run tests + real verify** — `pytest -q` green; `run` + `verify` on `.drift-demo`
      green. Reload; click APIs/Unknown (bars) and a zero tile (empty-state).

- [ ] **Step 5: Commit**

```bash
git add agent/assets/dashboard.template.html agent/assets/dashboard.app.js agent/assets/dashboard.css tests/test_dashboard_render.py
git commit -m "feat(dashboard): contextual hero — vendor bars + honest empty-states per tab"
```

---

## Task 4: Deep-link reconciliation (repo / tab / sub) + polish

Update the deep-link params to the new IA and finish the sub-tab content nesting.

**Files:** modify `agent/assets/dashboard.app.js`, `tests/test_dashboard_render.py`.

**Interfaces:**
- Consumes/Produces: URL `?repo=&tab=<tile>&sub=<subtab>` ↔ `state.scope/tab/sub`.

- [ ] **Step 1: Write the failing test**

```python
def test_deep_links_use_the_new_tab_and_sub_params():
    from agent.lib import dashboard_render as dr
    js = dr.APP_JS_SRC
    assert "replaceState" in js and "URLSearchParams" in js
    for key in ("repo", "tab", "sub"):
        assert key in js, key
```

- [ ] **Step 2: Run it to verify it fails** → FAIL.

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py::test_deep_links_use_the_new_tab_and_sub_params -q`

- [ ] **Step 3: Implement** — seed `scope`/`tab`/`sub` from `URLSearchParams` on mount (validate
      `tab` against the tile keys, `sub` against sub-ids; unknown → default, no throw); on change,
      `history.replaceState` writing only non-default `repo`/`tab`/`sub`. `q` is NOT URL-synced.
      Ensure the SBOM/SARIF sub-panels render the existing (Task 5 of the prior plan) content, now
      nested under `sub`.

- [ ] **Step 4: Run tests + real verify** — full `pytest -q` green; `run` + `verify` green; load
      `dashboard.html?tab=sunsets&sub=summary`, confirm it reproduces the scoped view; change tabs and
      confirm the URL updates.

- [ ] **Step 5: Commit**

```bash
git add agent/assets/dashboard.app.js tests/test_dashboard_render.py
git commit -m "feat(dashboard): deep-links for the new IA (?repo=&tab=&sub=)"
```

---

## Final verification (whole branch)

- [ ] Full suite green: `.venv/bin/python -m pytest -q`
- [ ] Real end-to-end: `run` + `verify` on `.drift-demo` → `✓ … all agree`.
- [ ] Matches the mockup: full-width, tiles-as-tabs, per-operation timeline hero with hover
      identity + today line, sub-tabs, honest empty-states. Reload and compare to
      `docs/design/2026-08-04-cockpit-mockup.html`.
- [ ] No external fetch; no `Date.now`/wall-clock in app.js; byte-identical output across two runs.
- [ ] Whole-branch review (most capable model) over the redesign commits.
