---
name: drift-detector
description: Use when the user wants to detect third-party integration drift — which APIs/SDKs/runtimes their repos use (code level) and what changed since the last scan. Scan a folder of cloned repos and report or query the result.
---

# Drift Detector

Detect **third-party integration drift** across a folder of cloned repos: which third-party APIs each repo calls (with `file:line` and version), which SDKs / frameworks / runtimes it declares, and **what changed since the last scan**. The scanning is **deterministic Python** (Opengrep static analysis) — cheap and token-free; your job is to run it, then narrate / query the result — never read source files yourself to build the inventory.

## Running a scan
Prefer the `/drift-detector <folder>` command. Under the hood it calls the bundled **self-bootstrapping runner** `bin/drift-scan`, which works from any directory:

```bash
<plugin>/bin/drift-scan --root <folder> \
  --state <folder>/.drift-detector \
  --out-json <folder>/.drift-detector/inventory.json \
  --out-md   <folder>/.drift-detector/INVENTORY.md \
  --out-diff <folder>/.drift-detector/DRIFT.md \
  --now $(date +%F)
```

On first use `drift-scan` creates a plugin-local venv and installs the engine (semgrep) — needs `uv` (recommended) or python≥3.11 + internet, one-time; later runs reuse it. It resolves the vendor/framework catalogs package-relative and puts the `agent` package on `PYTHONPATH`, so **cwd doesn't matter**. `<folder>` is any directory; git repos are discovered **recursively** at any depth (skipping `node_modules`/`vendor`/etc, and not descending into a found repo). `--root` is **repeatable** — pass it once per folder to scan several trees in one inventory (repos are deduped by real path; identities stay stable and collision-free).

(For local development from the repo with the dev venv active, you can still run `python -m agent.cli inventory-scan …` directly.)

## Drift = the diff since last scan
`DRIFT.md` (`--out-diff`) is the drift report: **new/removed third-party APIs, API version bumps (SP-API v0→v2), SDK version changes, runtime changes**, per repo. It is computed against the *previous* scan's `inventory.json`, so:
- **First run** = a baseline (everything is "added"; no drift yet).
- **Later runs** = only the actual changes. Lead your chat summary with these.

## The IR is the queryable shape-map
The scan writes `inventory.json` — the intermediate representation (IR). **Answer follow-up questions by reading the IR, never by re-scanning or re-reading source.** Shape:
- per repo: `repos[].{ path, ref, head_sha, last_activity_at, runtimes{name:{range,techKey,parseQuality}}, frameworks{name:{ver,...}}, sdks[{eco,pkg,ver,file,techKey,parseQuality}], endpoints[{vendor,domain,version,techKey,example,file_count,files:[path:line]}] }`
- rollups: `unique_apis`, `unique_api_versions[{vendor,version}]`, `unique_packages[{eco,pkg}]`, `unique_package_versions`, `runtimes{product:[ranges]}`.
- coverage: `coverage.{reposScanned, reposErrored[{repo,reason}], manifestsUnparsed[]}`.

Query patterns:
- *"which repos use X"* → filter `repos[]` where an `endpoints[].techKey`/`vendor` matches X; list `path` + the `files[]` call-sites.
- *"who drifted onto version Y / an old runtime"* → filter `endpoints[].version` or `sdks[].ver` / `runtimes[]`.
- *"what changed"* → read `DRIFT.md` (or diff two `inventory.json` snapshots).

## Incremental & portable
Re-running is cheap: only repos whose git `HEAD` changed are re-analyzed (per-repo SHA cache under `<folder>/.drift-detector/repos/`). The prior IR is the drift baseline. Endpoint `files[]` are repo-relative, so the IR is portable and diff-stable.

## Honest limits (v1)
- Endpoint `version` is best-effort from the URL on the matched line; it is `None` when a repo builds the URL from a base constant with the version appended on a *different* line (needs dataflow, out of scope for v1 — a future Opengrep taint rule).
- Detects hard-coded endpoint usage + manifest-declared SDKs. An SDK used only via its client library (no hard-coded URL) shows up via the manifest (`sdks[]`), not as an endpoint call-site.
- The vendor catalog (`agent/vendors.yaml`) and framework catalog (`agent/frameworks.yaml`) are allowlists — extend them to cover new vendors/frameworks.
