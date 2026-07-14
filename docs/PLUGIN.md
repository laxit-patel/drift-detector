# Drift Detector — Claude Code Plugin

A Claude Code plugin that scans a folder of cloned repos for **code-level third-party
integration usage** (which APIs/SDKs each project uses, `file:line`, versions) and reports it
**in chat** — with the heavy work done by cheap, deterministic Python (Opengrep), not by an
expensive autonomous LLM agent.

## What it is

- **Slash command** `/drift-detector <folder>` — runs a scan and summarizes it in chat.
- **Skill** `drift-detector` — teaches Claude to run/interpret the scan and answer
  follow-up questions by querying the produced inventory (the "IR"), never by re-scanning.

The cost model: the scan is a deterministic static-analysis run (**zero LLM tokens**); Claude
spends tokens only on the summary + interactive Q&A. Contrast with an autonomous agent doing the
whole scan itself.

## Prerequisites

1. **Python env** — the plugin drives `python -m agent.cli inventory-scan` from this repo.
   Activate the project venv (`source .venv/bin/activate`; uv-managed, Python 3.12).
2. **Opengrep (or Semgrep)** on `PATH` — the static-analysis engine.
   - Opengrep: install the standalone binary (fully OSS, no server/JVM).
   - Or a drop-in dev proxy: `uv pip install semgrep`.
   The scan **fails loud** if neither is found — no silent empty inventory.

## Use

```
/drift-detector /path/to/folder-of-cloned-repos
```

`<folder>`'s immediate subdirectories must be git clones. The command:
1. checks the engine,
2. runs the scan (only repos whose git `HEAD` changed since last time are re-analyzed — a
   per-repo commit-SHA cache makes re-runs fast),
3. writes `<folder>/.drift-detector/{inventory.json, INVENTORY.md, DRIFT.md}`,
4. narrates a summary (top APIs by repo count, runtimes/frameworks, what changed since last scan),
5. answers follow-ups (*"which repos use SP-API?"*, *"who's on an old Node?"*) from
   `inventory.json` — the queryable shape-map — without re-scanning.

## Outputs

- **`inventory.json`** — the IR: per-repo `{runtimes, frameworks, sdks, endpoints[{vendor,domain,
  version,file_count,files:[path:line]}]}` + rollups (`unique_apis`, `unique_api_versions`,
  `unique_packages`, `runtimes`) + coverage.
- **`INVENTORY.md`** — the human report (third-party APIs, frameworks, runtimes, SDKs, coverage).
- **`DRIFT.md`** — what changed vs the previous scan (new/removed APIs, SDK version bumps, runtime
  changes).

## Notes & limits (v1)

- **Local folder** input (clone orchestration is out of scope). Point it at a directory of clones.
- Endpoint **version** is best-effort from the URL on the matched line — `None` when a repo builds
  the URL from a base constant with the version appended elsewhere (needs dataflow).
- Detects hard-coded endpoints + manifest-declared SDKs; an SDK used only via its client library
  (no hard-coded URL) shows via the manifest, not as a call-site.
- Extend `agent/vendors.yaml` (vendors) and `agent/frameworks.yaml` (frameworks) as your stack grows.
- Deferred: weekly-cron / Google-Chat delivery (the same CLI is schedulable), and Opengrep **taint**
  rules for drift/vulnerability detection (the engine choice already supports it).
