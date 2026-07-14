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

## Install (teammates)

The plugin is distributed as a Claude Code **marketplace** (this git repo). To install:

```
/plugin marketplace add <git-url-of-this-repo>
/plugin install drift-detector@tops-tools
```

Then run `/drift-detector <folder>` (see Use below). The first run bootstraps itself.

## Prerequisites

Just **`uv`** (recommended — https://docs.astral.sh/uv/) **or** python ≥ 3.11 with `venv`, and internet access on the first run. The bundled runner `bin/drift-scan` creates a plugin-local venv and installs the scan engine (semgrep) itself — **no separate Opengrep/Semgrep install, no manual Python setup**. Later runs reuse the venv. The scan **fails loud** if it can't provision the engine — no silent empty inventory.

## Use

```
/drift-detector /path/to/folder-of-cloned-repos
```

Git repos under `<folder>` are discovered **recursively** (at any depth). Pass multiple space-separated folders to scan several trees at once. The command:
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

- **Local folder(s)** input (clone orchestration is out of scope). Point it at one or more directories; repos are found recursively and multiple roots are deduped by real path.
- Endpoint **version** is best-effort from the URL on the matched line — `None` when a repo builds
  the URL from a base constant with the version appended elsewhere (needs dataflow).
- Detects hard-coded endpoints + manifest-declared SDKs; an SDK used only via its client library
  (no hard-coded URL) shows via the manifest, not as a call-site.
- Extend `agent/vendors.yaml` (vendors) and `agent/frameworks.yaml` (frameworks) as your stack grows.
- Deferred: weekly-cron / Google-Chat delivery (the same CLI is schedulable), and Opengrep **taint**
  rules for drift/vulnerability detection (the engine choice already supports it).
