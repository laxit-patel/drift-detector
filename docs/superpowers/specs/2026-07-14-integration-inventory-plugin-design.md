# Code-Level Integration Inventory + Plugin — Design Spec

**Date:** 2026-07-14
**Status:** Approved design (brainstorm complete), ready for implementation planning
**Supersedes the *direction* of:** `docs/superpowers/specs/2026-07-10-api-deprecation-agent-design.md` (the deprecation agent). That work is **kept and reframed as a secondary layer** — see §10.

## Why (the re-scope)

A PM shared his vision (`docs/results/INVENTORY-2026-07-10.md` + `inventory-2026-07-10.json`),
produced by his own **autonomous Claude agent**. Two shifts land from it:

1. **Primary deliverable → a code-level third-party integration inventory.** For each
   of N projects: which third-party APIs it uses, **at code level** — *where* (`file:line`),
   the actual endpoint/example, the **API version parsed from the URL** (`googleapis.com/…/v3`,
   `mws.amazonservices/2010-10-01`), and SDK/runtime/framework usage. Deprecation/contract-drift
   becomes the secondary "Step 3 Research" layer on top of this inventory.
2. **Delivery → a Claude Code plugin**, not an autonomous scheduled agent. The PM's agent
   burned LLM tokens doing everything itself; the fix is **cheap deterministic tooling does the
   scanning, Claude only orchestrates + narrates in-chat.** Weekly-cron / Google-Chat delivery is
   **parked** (a later add-on the same CLI supports).

The current system already nails the scanning skeleton the PM praised (paginated `discover` via
`last_activity_after`, *not* the broken GitLab MCP `list_projects`) and has the whole deprecation
engine. The gap is **depth of code-level extraction** + a **delivery repackage**. This is an
extension, not a rebuild.

## Goals / non-goals

**Goals (v1)**
- Scan a **local folder of already-cloned repos** → a **superset inventory** (per-repo:
  runtimes/frameworks/SDKs/endpoints with `file:line`, version, example) + rollups + coverage.
- Do it with **best-in-class deterministic analysis** (Opengrep), **zero LLM tokens** for scanning.
- Persist the inventory as a **queryable IR** (the "shape map"); answer all questions from the IR,
  never re-crawling the filesystem; **incremental** re-scan (only changed repos).
- Deliver via a **Claude Code plugin** (skill + slash command) that runs the CLI and narrates in-chat.
- Keep the deprecation/contract-drift engine usable on the *same* inventory via a `techKey` join.

**Non-goals (v1)**
- Clone orchestration / at-scale GitLab crawling (input is a local folder; cloning is deferred).
- Branch-aware "scan the non-default branch" logic (we scan whatever is checked out; record the ref).
- Weekly cron + Google Chat delivery (parked; the CLI already supports scheduled use later).
- Deep interprocedural vuln *research* (Joern) — documented escape hatch, not built (§9).
- LLM-based code extraction (the expensive thing we are explicitly avoiding).

## Core principles

- **IR-first.** The scan is an *IR compiler*. Its output — the superset `inventory.json` — is the
  persistent, queryable **shape map** of all projects. Claude (and any consumer) queries the IR;
  the filesystem is touched only to (re)build it.
- **One best engine, no lite dial.** For anything approaching vuln/drift detection we use the best
  available approach, not a speed dial. The single engine is **Opengrep**.
- **Deterministic = token-free.** Opengrep is a standalone static analyzer; scanning costs
  wall-clock/CPU, **zero LLM tokens** — fully compatible with the low-cost plugin model. Wall-clock
  is bounded by **incremental, commit-SHA-keyed caching**.
- **Injected seams / no external deps in unit tests** (our existing discipline): Opengrep is invoked
  through an injected runner so unit tests use canned Opengrep JSON, never the real binary.

## Engine decision: Opengrep

**Opengrep** (the fully-OSS fork of Semgrep's standalone engine) is the single analysis engine.

- **Covers the stack incl. PHP.** The firm is PHP/Laravel-heavy; **CodeQL was rejected — it has no
  PHP**. Opengrep parses PHP + JS/TS + Python + Go + … in one engine.
- **Standalone, no server, bundlable.** A single binary / `pip`-installable; **no JVM**, no hosted
  service, runs offline against local rules. (Joern — the deeper Code-Property-Graph alternative —
  needs a JVM + per-repo graph builds; too heavy to bundle and to run across hundreds of repos. It
  is recorded as a future max-depth escape hatch only, §9.)
- **One tool does both jobs.** Structural rules → the inventory (endpoints/SDKs/imports, *more
  accurate than the PM's grep*, same schema); taint rules → the deprecation/drift/vuln layer later.
- **Ecosystem.** Inherits the large Semgrep/GitLab-SAST ruleset rather than authoring from scratch;
  GitLab-SAST is Opengrep/Semgrep-based, so it is familiar to the firm.

If Opengrep is absent at run time, the tool **fails loudly with install guidance** (no silent
regex fallback — a lite fallback contradicts the "best approach" principle). The plugin pins/bundles
a known Opengrep version.

## Architecture

```
/integration-inventory <folder>                 (plugin slash command → skill)
        │  runs the deterministic CLI (zero LLM tokens)
        ▼
  Scanner (IR compiler) over the folder of clones
    for each repo:
      ref, HEAD sha  ─►  cache hit? (repo@sha unchanged) ─► reuse cached record
                         else compute:
        ├─ manifest extractors (composer.json/package.json/requirements.txt/Dockerfile)
        │     → runtimes{} · frameworks{} · sdks[]   (+ techKey + parseQuality)
        └─ Opengrep run (our rule pack)  over source (.php/.js/.ts/.py/…)
              → endpoints[{vendor,domain,version,techKey,example,file_count,files[path:line]}]
                + SDK/import call-sites
    assemble → superset inventory.json  +  render INVENTORY.md
        │  persist IR + per-repo cache; diff vs prior IR (baseline)
        ▼
  Claude reads the IR/MD → narrates a summary in chat, answers follow-ups from the IR
    ("which repos still call MWS?", "who's on SP-API v0?")  — no re-crawl
```

### Components (focused, independently testable units)

1. **`agent/lib/opengrep.py`** — a thin wrapper that runs Opengrep via an **injected `run` callable**
   (`run(args) -> stdout`), points it at a repo + our rule pack, and parses its JSON output into
   normalized match records `{ruleId, vendor?, path, line, match, captures{}}`. Unit tests inject a
   fake `run` returning canned Opengrep JSON.
2. **`rules/`** — the Opengrep rule pack (YAML). v1 rules: **endpoint URLs** (per-vendor domain,
   metavariable-capture the version segment) and **SDK/import usage** (`use Stripe\…`, `import stripe`,
   `new \Stripe\StripeClient()`, `require('...')`). Extensible with taint rules for the drift/vuln
   layer later. Rules carry the `vendor` + `techKey` in metadata so matches map to the catalog.
3. **`agent/vendors.yaml`** — vendor catalog: `{vendor, techKey, domain(s), version-capture}` for the
   ~27 vendors in the PM's inventory (extends the 9 in `agent/patterns.yaml`).
4. **Manifest extractors** (reuse `agent/lib/extractors/*`) — enriched to emit `techKey` + `parseQuality`
   on every record, and a **framework catalog** routes framework packages (laravel/react/next/vue/
   express/nestjs/celery…) to `frameworks{}` vs `sdks[]`. Manifests are parsed by these deterministic
   parsers (JSON/TOML), **not** by Opengrep (Opengrep is for source code).
5. **`agent/lib/ir_store.py`** — persist the superset `inventory.json` under a state dir
   (`<state>/inventory.json`) + per-repo cache `<state>/repos/<repo>@<sha>.json`; `load_prev(state)`
   for the baseline; SHA-keyed cache lookup/save.
6. **`agent/inventory_scan.py`** — the orchestrator: walk the folder (reuse `LocalProvider` walker for
   repo discovery + git ref/sha), run manifest + Opengrep per changed repo, assemble the superset doc,
   build rollups, write JSON + MD. New CLI `inventory-scan`.
7. **`agent/lib/rollups.py`** — `unique_apis / unique_api_versions / unique_packages /
   unique_package_versions / runtimes` dedup builders.
8. **`agent/lib/inventory_render.py`** — superset doc → `INVENTORY.md` (the PM's report shape).
9. **The plugin** — a Claude Code plugin dir: a **skill** (run the scan, read the IR, narrate a
   summary + answer follow-ups from the IR) + a **slash command** `/integration-inventory <folder>`
   that shells to `python -m agent.cli inventory-scan …`. No MCP, no server.

## The superset schema (best of both, §comparison locked in brainstorm)

Per-repo record — the PM's nested shape, **enriched** (bold = ours):
```
{ id, path, ref, ref_is_default, last_activity_at, head_sha,          ← head_sha (cache key)
  runtimes:   { php:  {range, techKey, parseQuality} },               ← techKey + parseQuality
  frameworks: { "laravel/framework": {ver, techKey, parseQuality} },  ← split from sdks
  sdks:       [ {eco, pkg, ver, file, techKey, parseQuality} ],       ← techKey + parseQuality
  endpoints:  [ {vendor, domain, version, techKey, example,           ← techKey
                 file_count, files:[path:line]} ],
  provenance: { engine:"opengrep", engineVersion, rulesetVersion },   ← how it was derived
  tree_walk_truncated }
```
Top-level: `generated, scope, repos[], unique_apis, unique_api_versions, unique_packages,
unique_package_versions, runtimes, coverage`. Coverage keeps **our structured model**
(`reposScanned, reposErrored[{repo,reason}], filesUnparsed[…], opengrepUnavailable`).

The `techKey` on every entry (`lib:npm/axios`, `api:amazon-sp-api`, `runtime:php`) is the **join key
to the deprecation KB / contract engine** — what makes this the *same* inventory that can drive
deprecation. It is why the merged schema is strictly superior to the PM's (his has no join key) and
to ours (ours had no code-level endpoint detail).

## The IR: persistence, incrementality, baseline diff

- **Persist** the superset doc + a per-repo cache keyed `repo@head_sha`.
- **Incremental:** each run, for each repo compare current `HEAD` sha to the cached record's sha —
  **unchanged → reuse cached record; changed → re-scan that repo.** Rollups/coverage recompute from
  the (cheap) per-repo set each run.
- **Baseline diff:** the prior `inventory.json` is the baseline; a diff surfaces *new endpoint*,
  *version bump* (SP-API v0→v2), *SDK added/removed*, *MWS still present*. This reuses the existing
  `compute_delta` pattern and is the natural bridge to the deprecation layer.

## The plugin (delivery)

Claude Code plugin directory bundling: (a) our Python package + the pinned Opengrep binary; (b) a
**skill** instructing Claude to run `inventory-scan`, read the IR, narrate a summary, and answer
follow-ups **by querying the IR JSON** (never re-crawling); (c) a **slash command**
`/integration-inventory <folder>`. Cost model: the scan is deterministic (token-free); Claude spends
tokens only on the summary + interactive Q&A. Weekly-cron + Google-Chat stay parked — the same CLI is
schedulable later (the existing dockerized-ephemeral deploy already demonstrates this).

## Deprecation / drift layer (secondary, rides on `techKey`)

Because every inventory entry carries `techKey`, the existing `candidates → findings → severity →
report/delta` path (Change KB, feeds, SP-API contract engine, ACTION findings) works on the *same*
IR with no new plumbing. Surfaced as a report section, not the headline. Deeper drift/vuln detection
(Opengrep **taint** rules) is the natural next layer on the chosen engine — designed for, not built in v1.

## What we keep / add / change

- **Keep:** `LocalProvider` (folder walk + git ref/sha), manifest extractors, `discover` concepts,
  the entire deprecation engine (KB/feeds/contract-scan/Finding/delta/report), Google-Chat + commit
  delivery, the dockerized-ephemeral deploy (for the parked scheduled mode).
- **Add:** `opengrep.py` runner + `rules/` pack + `vendors.yaml`, framework catalog, `ir_store.py`,
  `rollups.py`, `inventory_render.py`, `inventory_scan.py` orchestrator + `inventory-scan` CLI, and
  the plugin (skill + slash command).
- **Change:** manifest extractor records gain `techKey`/`parseQuality`; presence detection is replaced
  by Opengrep endpoint/SDK rules (richer than the boolean `usedTechs`).

## Error handling

- Opengrep missing → fail loud with install/bundle guidance (no lite fallback).
- A repo Opengrep-errors or is unparseable → recorded in structured `coverage`, never aborts the batch.
- A file Opengrep can't parse → coverage note; other files/repos continue.
- No git repo / detached / no HEAD sha → scan without caching (still produces a record), note it.

## Testing

- **Opengrep runner:** injected fake `run` returns canned Opengrep JSON → assert normalized records
  (no real binary in unit tests). A separate **live smoke** runs real Opengrep over the 12 cloned
  marketplace repos (+ the `backup/Projects` folder).
- **Rule pack:** golden fixtures — small source files → expected matches (endpoint+version, SDK import),
  run against real Opengrep in an opt-in integration test.
- **Extractors/framework routing/parseQuality/rollups/render:** deterministic unit tests.
- **IR store / incrementality:** save→load round-trip; unchanged-sha reuses cache; changed-sha re-scans;
  baseline diff surfaces new/bumped/removed.
- **Plugin skill:** smoke run of `/integration-inventory` over the marketplace repos.

## Scope & sequencing (for planning)

Natural plan boundaries (each independently testable/shippable):
1. **Opengrep runner + rule pack + `vendors.yaml`** — code-level endpoint/SDK extraction (the core new
   capability), unit-tested with canned JSON + a live rule smoke.
2. **Manifest enrichment + framework catalog** — `techKey`/`parseQuality` on records; framework routing.
3. **Superset assembler + IR store (incremental, SHA-cache) + rollups + markdown render** — produce the
   PM-comparable `inventory.json` + `INVENTORY.md`; `inventory-scan` CLI.
4. **Baseline diff** — prior IR vs current → new/bumped/removed (bridge to the deprecation layer).
5. **The plugin** — skill + slash command + in-chat narration; live over the marketplace repos.
6. **(Later)** deprecation layer wiring on the IR; Opengrep taint rules for drift/vuln; Joern
   escape-hatch; clone orchestration; scheduled/Chat delivery.

## Deferred / documented follow-ups

- Joern (max-depth CPG) as an optional deep-dive on a specific repo/finding — not a general dial.
- Clone orchestration + at-scale GitLab discovery (v1 input is a local folder).
- Branch-aware non-default-branch scanning.
- Weekly cron + Google-Chat delivery (parked).
- Opengrep **taint** rules for drift/vuln (the deep layer the engine choice enables).
