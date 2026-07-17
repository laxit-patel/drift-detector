# Spec B — Honest Coverage (private/unreachable sources + SDK-undercount)

**Date:** 2026-07-17
**Status:** approved for planning
**Scope:** two PM-demo fixes — #4 (the "Unknown hosts" list conflates real unknown endpoints with private/unreachable sub-dependencies) and #2-surfacing (tell the user *why* SDK-mediated calls aren't listed). Strategy by Fable 5, with two corrections confirmed this session.

## Problem

The dashboard shows what the scanner *found* but not honestly what it *couldn't see*:
1. **#4:** every uncatalogued outbound host lands in "Unknown hosts" — mixing genuine unknown third-party APIs with **private/unreachable sub-dependencies** the scanner couldn't crawl. The PM wants those flagged distinctly ("subpackages we couldn't crawl because private or unreachable").
2. **#2-surfacing:** a real eBay call (`getCategoryFeatures`) wasn't listed. It's the deterministic ceiling — an SDK-mediated call (`$session->sendHttpRequest`, no URL literal). The honest response is to *tell the user* the endpoint list undercounts wherever calls route through an SDK client, not to chase it.

Both are the same theme: **surface what the scanner honestly can't see.** The data mostly already exists — this is a render/coverage job, not new detection.

## Goals

- A distinct **"Private / unreachable sources"** dashboard surface, separate from "Unknown hosts", fed from the `coverage.privateSources` the scanner already collects.
- A deterministic **per-repo "may undercount"** signal for SDK-using repos, surfaced on the dashboard and the inventory report.
- Deterministic, zero-LLM; the dashboard stays a self-contained `file://` document.

## Non-goals

- **#1/#3** (citations + permalinks) — done in Spec A.
- **Reachability probing** — a network call breaks the hermetic, deterministic scan.
- **SDK→vendor mapping** for the undercount note — no fuzzy per-vendor attribution; the note is repo-level.
- **SDK-session / dataflow resolution** — the cognition tier; the undercount note is the honest stand-in.
- **Pinning the private `rushikesh/ebayapi`** into the eval corpus — it's a private GitLab repo; can't go in the public `corpus.yaml`. The existing public eBay corpus already exercises SDK-only detection (`ebay-sdk-examples` is SDK-heavy / endpoint-light).
- **The Unknown↔private-repo cross-tag** — deferred (Correction 2): private composer repo URLs are manifest package sources, not code URL literals, so they seldom appear as endpoints. Verify on real data during build; add *only* if it genuinely fires.

## #4 — "Private / unreachable sources" (dashboard render over existing data)

The scanner already emits `inventory.coverage.privateSources`: a list of `{repo, packages: [{pkg, via}], repositories: [private composer VCS urls]}`. No scanner change — this surfaces it.

- **New tile** in the **Integrations** tile-group, beside "Unknown hosts": **"Private / unreachable"**. Count = **total private sources** across all repos (sum of `len(packages)` + `len(repositories)`), so the tile number equals the rows its filter yields.
- **New panel mode** (a third mode alongside `actions` and `endpoints`): clicking the tile switches the drill-down to **private-source rows**, one per source: `repo · source (package name or repo URL) · kind (package | repo) · via (the reason, e.g. the private-dep spec)`. Header: *"Sub-dependencies the scan couldn't crawl — private or unreachable. Their transitive endpoints/packages aren't in this inventory."*
- `_build_projection` (which already receives `inventory`) reads `inventory.coverage.privateSources` and emits a `private` projection list + the `private` count. XSS: package names / repo URLs are scan-derived → `esc`/`escA` like every other row; a private repo URL rendered as a link goes through `safeUrl` (http(s) only) — but many private sources are ssh/scp and won't be links (rendered as text), which is fine.

## #2-surfacing — per-repo "may undercount" (data-driven)

**Computed at scan time.** In `agent/inventory_scan.py` `_rollup_coverage`, add:

```python
coverage["sdkMediated"] = [
    {"repo": r.get("path"), "sdkCount": len(r.get("sdks", [])),
     "endpointCount": sum(1 for e in r.get("endpoints", []) if e.get("classified"))}
    for r in repos if len(r.get("sdks", [])) >= 1
]
```

Condition is simply **"the repo declares ≥1 SDK package"** — no threshold guessing, no vendor mapping. The signal is honest: *any* SDK client can make calls whose URL is assembled inside the SDK (no literal to match), so its endpoint list may undercount.

**Surfaced in two places:**
- **Dashboard — a new "Coverage" section** (footer). The dashboard currently *projects* `coverageNotes` but never renders them; Spec B adds a small Coverage section that renders (a) the existing `coverageNotes` (finally visible) and (b) the SDK-undercount summary: *"N repo(s) use SDK client(s) — calls routed through an SDK have no URL literal and aren't listed as endpoints, so the endpoint count may undercount: `<repo>` (K SDKs, M endpoints), …"*.
- **`INVENTORY.md` per-repo section** (`agent/lib/inventory_render.py` `_per_repo_section`): a per-repo `⚠` line for each SDK-using repo — *"⚠ K SDK package(s); SDK-mediated calls (no URL literal) may not be listed as endpoints."* This is the natural per-repo home.

`AUDIT.md` is action-ranked, not coverage-detailed, so it is **not** changed for #2 (keeps `audit.py` untouched).

## Data flow

```
inventory_scan._rollup_coverage → inventory.coverage.privateSources (exists)
                                 → inventory.coverage.sdkMediated    (NEW)
dashboard_render._build_projection (has inventory) → projection.private (rows) + counts.private
                                                    → projection.coverageNotes (already) + projection.sdkMediated (NEW)
dashboard JS → "private" tile + panel mode; a Coverage footer section
inventory_render._per_repo_section → per-repo ⚠ undercount line
```

No `audit.py` change. `coverage.sdkMediated` and the `private` projection are additive; existing consumers (SARIF/BOM/markdown) read other fields and are unaffected.

## Testing

- **`tests/test_inventory_scan.py`** (extend): `coverage.sdkMediated` lists exactly the repos with ≥1 SDK, each with correct `sdkCount`/`endpointCount`; a repo with zero SDKs is absent; `privateSources` unchanged.
- **`tests/test_dashboard_render.py`** (extend): the `private` count = total private sources; the projection emits `private` rows `{repo, source, kind, via}`; the "Private / unreachable" tile is present in the Integrations group; the panel-mode JS has a `private` filter; the Coverage section renders both the coverage notes and the SDK-undercount summary naming the repos; XSS — a private package/repo string with `"`/`<`/`</script>` doesn't break out; determinism.
- **`tests/test_inventory_render.py`** (extend): an SDK-using repo gets the `⚠ … may not be listed` line; a repo with no SDKs does not.
- **Eval harness = the regression net, not a new metric.** `coverage.sdkMediated` is an inventory-coverage signal, not something the scorecard scores — so the eval's only role is: `bin/drift-eval run ebay` must still pass recall **5/5** (the additive coverage must not perturb detection). The `sdkMediated` logic itself is unit-tested in `test_inventory_scan.py` with hand-built repo fixtures (SDK-heavy/endpoint-light, and zero-SDK). No new corpus repo, no network, and **not** the private ebayapi.
- No network in any unit test.

## Success criteria

Re-rendering a real scan that has both private composer sources and SDK-using repos yields a dashboard with: a **"Private / unreachable"** tile whose count equals its drill-down rows (each a private package/repo, distinct from "Unknown hosts"); a **Coverage** section that names the SDK-using repos as possible endpoint-undercounts; and `INVENTORY.md` showing the `⚠` undercount line on those repos. On the eBay corpus, `ebay-sdk-examples` (1 endpoint, has `dts/ebay-sdk-php`) is flagged as a possible undercount, and `drift-eval run ebay` still passes 5/5. Same input → byte-identical dashboard.
