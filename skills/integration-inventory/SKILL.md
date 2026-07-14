---
name: integration-inventory
description: Use when the user wants to know which third-party APIs/SDKs their repos use (at code level) or what integration usage changed — scan a folder of cloned repos and report or query the inventory.
---

# Integration Inventory

Produce and query a **code-level third-party integration inventory** over a folder of cloned repos: which third-party APIs each repo calls (with `file:line` and version), which SDKs / frameworks / runtimes it declares, and what changed since the last scan. The scanning is **deterministic Python** (Opengrep static analysis) — cheap and token-free; your job is to run it and then narrate / query the result, never to read source files yourself to build the inventory.

## Running a scan
Prefer the `/integration-inventory <folder>` command. Or run the CLI directly, from the repo root with the venv active:

```bash
python -m agent.cli inventory-scan --root <folder> \
  --state <folder>/.integration-inventory \
  --out-json <folder>/.integration-inventory/inventory.json \
  --out-md   <folder>/.integration-inventory/INVENTORY.md \
  --out-diff <folder>/.integration-inventory/DIFF.md \
  --now $(date +%F)
```

`<folder>` is a directory whose immediate subdirectories are git clones. Requires `opengrep` or `semgrep` on PATH — the scan fails loud if neither is present.

## The IR is the queryable shape-map
The scan writes `inventory.json` — the intermediate representation (IR). **Answer follow-up questions by reading the IR, never by re-scanning or re-reading source.** Shape:
- per repo: `repos[].{ path, ref, head_sha, last_activity_at, runtimes{name:{range,techKey,parseQuality}}, frameworks{name:{ver,...}}, sdks[{eco,pkg,ver,file,techKey,parseQuality}], endpoints[{vendor,domain,version,techKey,example,file_count,files:[path:line]}] }`
- rollups: `unique_apis`, `unique_api_versions[{vendor,version}]`, `unique_packages[{eco,pkg}]`, `unique_package_versions`, `runtimes{product:[ranges]}`.
- coverage: `coverage.{reposScanned, reposErrored[{repo,reason}], manifestsUnparsed[]}`.

Query patterns:
- *"which repos use X"* → filter `repos[]` where an `endpoints[].techKey`/`vendor` matches X, list `path` + the `files[]` call-sites.
- *"who's on version Y / an old runtime"* → filter `endpoints[].version` or `sdks[].ver` / `runtimes[]`.
- *"what changed"* → read `DIFF.md` (or diff two `inventory.json` snapshots).

## Incremental & portable
Re-running is cheap: only repos whose git `HEAD` changed are re-analyzed (per-repo SHA cache under `<folder>/.integration-inventory/repos/`). The prior IR is the baseline for `DIFF.md`. Endpoint `files[]` are repo-relative, so the IR is portable and diff-stable.

## Honest limits (v1)
- Endpoint `version` is best-effort from the URL on the matched line; it is `None` when a repo builds the URL from a base constant with the version appended on a *different* line (that needs dataflow, out of scope for v1).
- Detects hard-coded endpoint usage + manifest-declared SDKs. An SDK used only via its client library (no hard-coded URL) shows up via the manifest (`sdks[]`), not as an endpoint call-site.
- The vendor catalog (`agent/vendors.yaml`) and framework catalog (`agent/frameworks.yaml`) are allowlists — extend them to cover new vendors/frameworks.
