# Drift Detector Dashboard — Design

**Date:** 2026-07-16
**Status:** approved for planning
**Scope:** a single self-contained `dashboard.html`, generated each run, rendering the latest scan as an interactive cockpit. "Layer 2" of the reporting work, after the ranked-markdown layer (`AUDIT.md`) shipped in commit 70629ea.

## Problem

The markdown report is now legible (ranked actions, "Do this first", copy-paste commands), but it is static text. The user asked for an interactive visual surface — "a dashboard... something that can directly show it online... like how an openapi schema renders." Two audiences need it at once: a PM who wants exposure-at-a-glance, and a developer who wants the fix queue with exact commands. And it is the first surface where **both halves of the product sit together**: the CVE/EOL fix queue, and the endpoint/vendor-sunset "moat" (SARIF is CVE-only; CycloneDX is package-only; neither shows "this code calls api.ebay.com/v1 at these 26 lines, retiring ⟨date⟩").

## Goals

- One `dashboard.html` per run, self-contained: inline CSS + vanilla JS, data embedded, no CDN, no build, no server. Opens from `file://`, emails as one attachment, hosts by copy.
- Deterministic, zero-LLM-token: pure Python renders it from `inventory.json` + `audit.json`. Same input → byte-identical output.
- Serve both audiences in one artifact: an exposure cockpit on top, a drill-down fix queue below, and the integrations/sunset story as a first-class half.
- Reuse the data already produced (`audit["actions"]`, `audit["counts"]`, `audit["delta"]`, `inventory["repos"][].endpoints[]`). No new scanning, no new analysis.

## Non-goals (explicitly deferred)

- **Run history / archive / trend-over-time chart.** Confirmed latest-run-only. Week-over-week movement is shown via the existing `audit["delta"]` (new/resolved/persisting), which needs no archiving. A multi-run archive is a separate future layer.
- **A local server** (`drift-scan serve`). The self-contained file is the whole delivery.
- **External assets** — no CDN scripts, fonts, or images. Everything inline.
- **Connectors** (Dependency-Track upload, SARIF push, GitLab). Later, unchanged by this.
- **The cognition/LLM layer.** Deterministic throughout.

## Layout — the cockpit

Decided visually (option C cockpit, tile-set B, reveal A, dark-default theme). Top to bottom:

1. **Exposure header** (one line): `🔴 50 fixes needed · 35 of 60 repos · ↓12 resolved ↑4 new this week`. The delta numbers come from `audit["delta"]` rolled up to actions (reuse the same action-rollup the markdown delta uses).

2. **Two tile-groups**, side by side, each tile a clickable filter:
   - **Security (packages):** Critical · Fixes · EOL
   - **Integrations (the moat):** APIs used · Sunsets · Unknown hosts
   Clicking a tile sets the panel's filter. "Critical" → the 10 critical actions. "Sunsets" → the panel switches to the endpoint/call-site view. "Unknown hosts" → the unclassified endpoints. An active tile is visually marked; clicking it again clears the filter.

3. **Search box**: free-text filter over the visible panel by repo path or package/vendor name (substring, case-insensitive).

4. **Drill-down panel**: a table of rows. In package mode, rows are ranked actions (worst-first, the `audit["actions"]` order). In endpoint mode, rows are endpoint groups. Clicking a row unfolds it **in place** (inline accordion):
   - **Action row** unfolds to: the `command` in a monospace box with a copy button, a one-line "clears N advisories (M critical)", the list of underlying CVE ids/titles (from the action's `fixes`), and the deduped `sources` as links.
   - **Sunset row** unfolds to: the retirement date, the `recommendation` (migrate-to prose), and the `files` list (`path:line` call-sites) — the "these lines break on ⟨date⟩" payload.

5. **Theme toggle**: dark default (security-tool feel), light mode for print/share. Choice persisted in `localStorage`. Both themes are inline CSS keyed off a `data-theme` attribute on the root; no external stylesheet.

## Architecture

One new renderer, mirroring `agent/lib/audit_render.py`:

```
agent/lib/dashboard_render.py   (new)   render_dashboard(inventory, audit, now) -> str
agent/run.py                    (edit)  one _write(... "dashboard.html" ...) after existing writes
agent/cli.py                    (edit)  optional --out-html flag on the `audit` subcommand
```

- **`render_dashboard(inventory: dict, audit: dict, now: str) -> str`** is a pure function returning the complete HTML document as a string. No file I/O (the caller writes it), no network. Matches the injected-seam style of every other renderer.
- **Wiring in `run.py`**: after the existing artifact writes (around line 67), add
  `_write(os.path.join(state_dir, "dashboard.html"), render_dashboard(doc, audit, now))`.
  `run.py` already holds `doc` (the inventory) and `audit` in scope — nothing new to plumb.
- **Wiring in `cli.py`**: add `pa.add_argument("--out-html")` to the `audit` subparser and, in `_cmd_audit`, write the dashboard when the flag is present — mirroring the existing optional `--out-bom`/`--out-sarif`/`--out-json` blocks. `_cmd_audit` already has both `doc` and `audit` in scope.

## Data flow

The two halves come from two sources already on disk per run:

- **Package half** (tiles Critical/Fixes/EOL, the fix-queue table) ← `audit["actions"]` (ranked list, each with `repo, ref, current_version, fix_version, command, worst, status, finding_count, critical_count, kind, fixes, sources, recommendation`), plus `audit["counts"]` and `audit["delta"]`.
- **Integration half** (tiles APIs/Sunsets/Unknown, the endpoint table) ← `inventory["repos"][].endpoints[]` (each with `domain, vendor, version, classified, file_count, files`), plus the sunset actions (`kind == "sunset"`, which carry `files`).

**The embedded blob is a minimal projection, not the raw audit.json.** `render_dashboard` builds one small dict — the actions with just the fields the UI reads, the endpoint rows, the counts/delta, the coverage note — and emits it as a single `<script id="drift-data" type="application/json">…</script>`. This keeps the file lean (the raw `audit.json` is ~850KB and mostly unused fields) and lets the vanilla JS read the data once and render tiles/table/filters client-side with no server round-trips.

**Tile counts are derived, not re-counted from findings.** Critical = actions where `worst == "CRITICAL"`; Fixes = actions where `status == "DEPRECATED"`; EOL = actions where `kind == "eol"`; Sunsets = actions where `kind == "sunset"`; APIs used = distinct classified vendors across endpoints; Unknown hosts = endpoints where `classified` is false (or `vendor == "Unknown"`). All computed in Python and embedded, so the JS never disagrees with the numbers.

**Tiles count ACTIONS, not findings — this is load-bearing.** On the real run, the 10 critical *advisories* roll up to **3** critical *actions* (torch + mongoose in two repos). The Critical tile therefore reads 3, because clicking it filters the panel to exactly those 3 action rows. A tile that said 10 while its drill-down showed 3 rows would resurrect the exact findings-vs-actions confusion the action model was built to remove. Every tile count must equal the number of rows its filter produces. Tiles are overlapping lenses, not a partition — a critical DEPRECATED eol action is counted by Critical, Fixes, and EOL alike; that is expected.

`render_dashboard` must tolerate an `audit` that lacks `actions` by falling back to `build_actions([f for f in audit["findings"] if not f.get("suppressed")])` — identical to the fallback already in `audit_render.render_audit_md`. This is not hypothetical: audits written before the action model shipped (including the real `~/drift-report-2026-07-15/audit.json`) carry only `findings`.

## Structure of the generated HTML

```
<!doctype html>
<html data-theme="dark">
<head><meta charset><title>Drift Detector — <now></title><style> …both themes, inline… </style></head>
<body>
  <header> exposure line + theme toggle </header>
  <section class="tiles"> two groups × three tiles </section>
  <input class="search">
  <table id="panel"> … rendered by JS from the blob … </table>
  <script id="drift-data" type="application/json"> {minimal projection} </script>
  <script> …vanilla JS: parse blob, render panel, wire tiles/search/accordion/theme… </script>
</body></html>
```

## Escaping & safety

Repo paths, package names, vendor names, and file paths are scan-derived strings and can contain `<`, `&`, `"`, `'`. Two injection surfaces, both must be handled:

- **HTML text** (anything interpolated into markup Python-side): escape with stdlib `html.escape(s, quote=True)`. Do **not** reuse `audit_render._esc` — that escapes markdown pipes, not HTML.
- **The JSON blob**: `json.dumps(..., ensure_ascii=False)` then defend the one HTML-in-JS hazard by replacing `<` with `<` in the serialized string before embedding, so a value containing `</script>` cannot close the script element. (Standard technique; the JS `JSON.parse` reads `<` back as `<`.)

No `innerHTML` with un-escaped scan data in the JS: the client builds rows via `textContent`/`createElement`, or escapes before `innerHTML`. Tested.

## Testing

Pure Python + string assertions on the generated HTML; no browser, no network.

**`tests/test_dashboard_render.py`**
- Output starts with `<!doctype html>` and contains exactly one `<script id="drift-data"`.
- The blob parses as valid JSON (extract it, `json.loads`) and its action count equals the number of non-suppressed actions in the audit.
- Every action's `command` string appears in the output (the dev can copy every fix).
- Tile counts embedded in the blob match independently-computed counts from the audit (critical/fixes/eol/sunset) and inventory (apis/unknown).
- A sunset action's `file:line` call-sites appear in the output (the moat payload renders).
- Determinism: `render_dashboard(inv, audit, now) == render_dashboard(inv, audit, now)`, byte-for-byte.
- Empty audit (no actions, no endpoints) renders a valid document with a visible "nothing found" state, no crash.
- **XSS/escaping:** an action whose `repo` is `a<script>alert(1)</script>&"x` produces output where that raw substring does **not** appear literally in HTML text, and where the JSON blob contains no unescaped `</script>`. Both surfaces asserted.
- No CDN/external reference: the output contains no `http://`/`https://` `src=`/`href=` to a script/style/font/image (source-link `href`s to osv.dev/GHSA are allowed — assert there is no `<script src`, `<link rel="stylesheet"`, `@import`, or `<img src="http`).

**`tests/test_run_pipeline.py` / CLI tests** (extend)
- A `run` writes `dashboard.html` into the state dir alongside `AUDIT.md`.
- `audit --out-html <path>` writes the dashboard; omitting the flag does not.

## Success criteria

Running the pipeline over the real `~/drift-report-2026-07-15` data (its `audit.json` predates the action model, so the renderer's `build_actions` fallback applies) produces a `dashboard.html` that opens from `file://` with: 90 actions / 50 urgent in the blob; the exposure header showing 50 fixes / 35 repos / the week delta; tile counts of **3 critical · 50 fixes · 34 EOL · 0 sunsets · 10 APIs used · 68 unknown hosts**; a fix queue whose first row is the `torch` action (`1.1.0 → 2.10.0`) expanding to the copy-paste command + CVEs; and clicking the APIs/Unknown tiles switches the panel to the endpoint/call-site view. No network access, no external file, works with the browser offline.

Note on the Sunsets tile reading 0: this is correct behaviour, not a gap. The eBay endpoints (13 groups) are detected and appear under the integration view; they become *sunset actions* only when a dated retirement entry exists in `vendor_sunsets.yaml`. Wiring that entry is a separate, already-teed-up follow-up — the dashboard must render 0 sunsets truthfully until then, and the test suite must cover both the 0-sunset and the has-sunset case (the latter with a fixture, since live data has none).
