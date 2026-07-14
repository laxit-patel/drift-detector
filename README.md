# Drift Detector

A Claude Code plugin that builds a **code-level inventory of the third-party
integrations** your repos use — which APIs/SDKs/runtimes each project calls, with
`file:line` and versions — and reports **what changed since the last scan**
(drift). The scanning is a **deterministic static-analysis pipeline** (Opengrep /
semgrep AST matching + manifest parsing) — it runs locally and costs **zero LLM
tokens**; Claude only narrates the result and answers follow-ups.

## Install

```
/plugin marketplace add https://github.com/laxit-patel/drift-detector
/plugin install drift-detector@tops-tools
```

Prerequisite: **`uv`** (recommended — https://docs.astral.sh/uv/) *or* Python ≥ 3.11
with `venv`, plus internet on the first run. The bundled runner provisions its own
venv + scan engine — no manual Python or Opengrep/semgrep install.

Check your machine any time:

```
/drift-detector doctor
```

## Use

```
/drift-detector <folder>              # scan one folder of repos (recursive)
/drift-detector ~/work ~/personal     # or several folders at once
```

- Git repos are discovered **recursively** at any depth (skipping `node_modules`,
  `vendor`, etc.), across every folder you pass.
- The **first run** is a baseline; **later runs lead with what drifted** — new/removed
  APIs, version bumps (e.g. SP-API v0→v2), SDK and runtime changes.
- Ask follow-ups in chat (*"which repos use Amazon SP-API?"*) — answered from the
  saved inventory, without re-scanning.

## Outputs (written to `<folder>/.drift-detector/`)

| File | What |
|---|---|
| `inventory.json` | The IR — per-repo `{runtimes, frameworks, sdks, endpoints[{vendor, domain, version, file_count, files:[path:line]}]}` + rollups + coverage. The queryable shape-map. |
| `INVENTORY.md` | Human report: third-party APIs, frameworks, runtimes, SDKs, coverage. |
| `DRIFT.md` | What changed vs the previous scan. |

Re-runs are cheap: only repos whose git `HEAD` changed are re-analyzed (per-repo
commit-SHA cache).

## How it works

`bin/drift-scan` (self-bootstrapping runner) → `python -m agent.cli inventory-scan`.
The scanner ([`agent/`](agent/)) walks each repo, runs the engine with a generated
rule pack over the vendor catalog ([`agent/vendors.yaml`](agent/vendors.yaml)),
parses manifests, and aggregates everything into the superset IR. Extend
`agent/vendors.yaml` (vendors) and `agent/frameworks.yaml` (frameworks) as your
stack grows.

See [docs/PLUGIN.md](docs/PLUGIN.md) for details, and run the test suite with
`pytest` (needs `pip install -r requirements.txt`).

## Limits (v1)

- Endpoint **version** is best-effort from the URL on the matched line — `None` when a
  repo builds the URL from a base constant with the version appended elsewhere
  (needs dataflow; a future Opengrep taint rule).
- Detects hard-coded endpoints + manifest-declared SDKs. An SDK used only via its
  client library (no hard-coded URL) shows via the manifest, not as a call-site.
