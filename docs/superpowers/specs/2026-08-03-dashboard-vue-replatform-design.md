# Dashboard Vue re-platform + charts — design (spec ①+②)

> **Status:** approved design, pre-plan. This is the FIRST of two specs. Spec ③ (the AI
> two-plane cockpit + firewall) is a separate cycle, deliberately deferred.

**Goal:** Re-platform the existing deterministic `dashboard.html` from a 930-line Python
string-builder onto a vendored, zero-build Vue runtime, and add two hosted-surface wins —
deep-linkable filter state and a hand-rolled SVG *Retirement Timeline* chart — without
weakening the `verify` contract that certifies the report.

**Non-negotiable framing:** the dashboard is, and remains, a **verified projection of
`drift.json`**. `drift-scan verify` must stay green and must remain the *only* claim we make
that the report is correct. Every decision below is subordinate to that.

---

## Context — why now, and what already exists

- The dashboard's destination is **GitHub Pages** (a hosted surface), not email. That removes
  the *single-file-for-email* pressure — but we **keep** self-containment anyway because it
  costs nothing and preserves `file://`, offline, and one-attachment portability.
- The dashboard is **already a client-rendered app**: it ships a `<script id="drift-data">`
  JSON blob (== `drift.json`) and ~400 lines of hand-rolled vanilla JS hydrate the
  tiles/tables/filters from it. So "add a reactive framework" is **not** a rewrite of the
  trust model — the trust model already assumes client-side rendering.
- `agent/lib/verify.py` (416 lines) governs correctness via three mechanisms:
  1. `check_blob_matches_payload` — the embedded blob **==** the canonical payload,
     byte-for-byte. **The trust anchor.**
  2. `check_tile_counts` / `check_owner_split` / `check_row_labels_distinct` — replicate the
     page's filters **in Python** against the payload and assert self-consistency.
  3. `check_accessor_coverage` — greps the client JS for `a.field` / `e.field` / `p.field` /
     `cv.field` accesses and fails if the page reads a field the payload lacks
     (`_ACCESSOR = re.compile(r"\b(a|e|p|cv)\.([A-Za-z_]\w*)\b")`).
- Runtime dependency budget: **stdlib + PyYAML only** (`jsonschema` is test-only). The
  chosen approach adds **no runtime Python dependency** and **no Node/npm toolchain**.

## Toolchain decision (settled during brainstorming)

**Zero-build, no DaisyUI.** Vendored Vue **global build** (no bundler, no SFCs, no npm),
the existing CSS token system kept as-is, charts hand-rolled in SVG. Rationale: this is the
option most aligned with the tool's identity — deterministic, self-bootstrapping, no
toolchain, byte-stable output. DaisyUI was rejected because it forces Tailwind, which forces
either a build step or the not-for-production Tailwind Play CDN.

## Non-goals (explicitly out of scope for this spec)

- **The AI / probabilistic plane** (spec ③) — no `probabilistic.json`, no two-plane UI, no
  firewall work here. This spec is **deterministic data only**.
- **Week-over-week trend / burn-down charts** — these need a multi-run history store the tool
  does not have (`README` Limits: "the dashboard shows the latest run"). Faking a trend from
  one run would violate "never invent." Deferred to a real history layer.
- **Multi-file Pages output / a CDN** — rejected; we stay single-file, self-contained,
  vendored.
- **Any change to the scan/audit pipeline or the `drift.json` schema.** The data contract is
  frozen for this spec.

---

## Architecture

`dashboard.html` stays **one self-contained file**, still emitted by Python. The inlined
bundle gains the Vue runtime; the render logic moves from Python strings into an in-DOM Vue
template + a plain JS app object.

```
dashboard.html
├─ <style>                       existing CSS token system            (UNCHANGED)
├─ <div id="app"> … </div>       in-DOM Vue template (v-for/v-if/{{ }}) ← was string-built HTML
├─ <script id="drift-data" type="application/json"> … </script>   payload == drift.json (UNCHANGED)
├─ <script id="sbom-data">/<sarif-data>/<spdx-data>               existing blobs        (UNCHANGED)
├─ <script>  vue.global.prod.js  </script>   vendored + pinned, inlined from agent/assets/vendor/
└─ <script>  app.js (createApp({...}).mount('#app'))  </script>   ← was ~400 lines vanilla
```

- **Vue global build, in-DOM templates.** `Vue.createApp({ data, computed, methods })
  .mount('#app')`. No render functions, no build. Template lives in the `#app` markup;
  reactivity replaces the manual `state = {…}; render()` cycle.
- **`agent/lib/dashboard_render.py`** collapses from ~930 lines of HTML/CSS/JS string
  concatenation to a thin **shell-injector**: read the vendored Vue file, read the app
  JS/template, inject the JSON blob(s). The `_build_projection` / `build_payload` data code
  (the part that produces the payload) is **kept intact** — only the presentation layer
  changes.
- **Vendoring.** `agent/assets/vendor/vue.global.prod.js`, a pinned Vue 3.x release, committed
  to the repo. A short provenance note records the exact version + source URL + SHA (same
  discipline as the ast-grep pin). The renderer inlines its bytes; the runtime never fetches
  anything.

**Determinism:** output stays byte-stable for identical inputs — the only run-varying content
is the deterministic blob; Vue runtime + app.js + CSS are static committed bytes. No
`Date.now()` / wall-clock enters logic (the chart's "today" is the payload's `generated`
date).

## `verify` preservation — the load-bearing section

| verify check | Fate | Why |
|---|---|---|
| `check_blob_matches_payload` | **UNCHANGED** | Blob still embedded verbatim; the anchor holds. |
| `check_tile_counts`, `check_owner_split`, `check_row_labels_distinct` | **UNCHANGED** | They run against the *payload* in Python, not the DOM. Vue's computed filters must mirror the Python filter logic exactly — the same coupling the vanilla `actionsFor()` has today. |
| `check_accessor_coverage` | **EXTENDED** | In Vue, `a.field` accesses move from the JS into the in-DOM *template*. The grep must scan the template block too, or it silently goes blind. |
| Chart parity (new) | **ADDED** | The Retirement Timeline must plot exactly `counts.sunsets` points — a `tile-vs-chart` invariant so a chart can't disagree with its tile. |

**`check_accessor_coverage` extension is a "prove-a-guard-against-its-bug" item** (project
principle 5): the plan MUST first demonstrate the extended check *failing* on a template that
reads a bogus `a.doesNotExist`, then passing once the field is real. Writing the guard is not
enough; it must be shown to catch its bug.

**The Python↔page filter mirroring stays a hard invariant.** `verify` replicates the tile
filters in Python (`check_tile_counts`, lines ~117-150). The Vue computed properties
(`actionsFor`, `endpointsFor`, `privateFor`, `catalogFor`) must produce identical selections.
This is unchanged from today — we are porting the *same* filter predicates into computed
properties, verbatim in logic.

## Deep-linkable filter state (②)

URL query params ↔ Vue reactive state, **hand-rolled, no router library**:

- Params: `?repo=<key>&tile=<filter>&tab=<panel>&sub=<subpanel>` (only non-default values are
  written, so the "clean" view has a clean URL).
- On load: parse `location.search` → seed the reactive state (repo scope, active tile filter,
  active tab). Unknown/stale values fall back to defaults (never throw).
- On change: `history.replaceState` with the rebuilt query string (replace, not push — no
  history spam on every keystroke; the search box does not go in the URL).
- Payoff: a delivered GitLab issue can deep-link **straight to a filtered view** — e.g. a
  Developer issue links to `…/dashboard.html?repo=<theirs>&tile=sunsets`.

## Charts — hand-rolled SVG (②)

### Flagship: Retirement Timeline
Every sunset finding plotted on a horizontal **date axis**:
- x = the finding's `date` (present on 20/20 sunset actions in the sample payload).
- A vertical **"today" line** at the payload's `generated` date (deterministic; never
  `Date.now()`).
- **Past-due** (date < today) rendered ember-crimson to the left; **upcoming** to the right,
  shading toward its deadline.
- Hover/label shows vendor + operation (`unit`) + repo; respects the global repo scope (when a
  repo is selected, the timeline scopes to it — consistent with the rest of the cockpit).
- This is *"know before it breaks"* made visual, from data already in `drift.json`.

### Secondary (cheap, optional): Blast-radius bar
Findings-per-repo bar. Include only if it doesn't clutter; drop otherwise (YAGNI).

### Chart discipline
- Pure SVG generated in the Vue app from the blob — no chart library, no CDN.
- `prefers-reduced-motion` respected; theme-aware via the existing CSS tokens.
- The `tile-vs-chart` verify invariant (above) binds the timeline's point count to
  `counts.sunsets`.

## Testing strategy

Same discipline as today: **we do not execute the Vue JS in Python tests.**

- **Projection / data tests** (`_build_projection`, counts, coverage, unscannable, private,
  catalog) — **untouched**: the payload contract is identical, so these pass as-is and remain
  the substantive coverage.
- **HTML-structural tests** — reworked to the Vue shape: blob present + valid; `#app` mount
  point present; the vendored Vue runtime inlined; the template carries the expected
  `v-for`/bindings (repo filter, tiles, tables, timeline `<svg>`).
- **`verify` tests** — add the `check_accessor_coverage` template-scan case (prove-the-bug),
  and the `tile-vs-chart` parity case.
- **The correctness claim** comes from **`verify` green on a real render** of the demo fleet
  (`.drift-demo`), per project discipline — not from "it looks right" (we cannot see rendered
  HTML).

## Data contract (frozen for this spec)

Top-level `drift.json` keys consumed (all already present):
`actions, endpoints, private, catalog, counts, coverageGrades, coverageNotes, coveredDeps,
delta, generated, inventoryDrift, residueSamples, rootsUnscannable, schemaVersion,
sdkMediated, shapes`.

`counts`: `apis, byOwner, critical, eol, fixes, pastDue, private, reposAffected, reposScanned,
sunsets, unaudited, unknown, unscannable`.

Sunset action fields used by the timeline: `ref` (vendor), `unit` (operation/path), `status`,
`date`, `repo` / `repoLabel`, `worst`. The schema is **not** modified.

## Risks & decisions

- **Churn risk:** re-platforming working, tested code is only justified as the *foundation* for
  ② (charts, deep-links) and spec ③ (the AI plane). ② ships in this same spec precisely so the
  foundation lands with visible value; a pure re-plate would not be worth it.
- **Filter-logic drift:** the Vue computed filters and the Python `verify` filters must stay
  identical. Mitigation: port the predicates verbatim; `check_tile_counts` fails loudly if they
  diverge.
- **Accessor guard going blind:** mitigated by the template-scan extension, proven against its
  bug before the fix.
- **Vue version bumps:** treated like the ast-grep pin — a pinned, provenance-noted vendored
  file; a bump is a re-verification event, not a silent update.

## Success criteria

1. `./bin/drift-scan run --root ~/gitlab-fleet --state .drift-demo --now <date>` then
   `verify` → **green** ("drift.md, dashboard.html and drift.json all agree").
2. The rendered `dashboard.html` is a single self-contained file (Vue inlined; no external
   fetch), opens from `file://`, and its `#drift-data` blob still equals `drift.json`.
3. Deep-link round-trips: loading `?repo=…&tile=sunsets` reproduces that filtered view; changing
   filters updates the URL.
4. The Retirement Timeline renders exactly `counts.sunsets` points with a deterministic "today"
   line at `generated`, and the `tile-vs-chart` invariant passes.
5. `check_accessor_coverage` is demonstrated to catch a bogus template accessor (guard proven).
6. Full `pytest` suite green.
