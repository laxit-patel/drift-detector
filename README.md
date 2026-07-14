# Drift Detector

A Claude Code plugin that builds a **code-level inventory of the third-party
integrations** your repos use — which APIs/SDKs/runtimes each project calls, with
`file:line` and versions — reports **what changed since the last scan** (drift),
and **audits** those dependencies for known vulnerabilities (OSV) and end-of-life
runtimes (endoflife.date). Everything runs locally as a **deterministic pipeline**
(Opengrep/semgrep AST matching + manifest parsing + public API lookups) — **zero
LLM tokens**; Claude only narrates the result and answers follow-ups.

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

### Audit — what's risky / what to mend

```
/drift-detector audit <folder>        # after a scan of that folder
```

Reads the folder's existing `inventory.json` and checks it against **OSV.dev**
(known CVEs per package version) and **endoflife.date** (EOL runtimes/frameworks),
classifying each finding **DEPRECATED** (act now) / **REVIEW** (assess) with a cited
source. Needs network on the run (still zero LLM tokens); degrades gracefully offline.
Versions checked are the **declared manifest floor** — verify against your lockfile
before acting (conservative: it may over-report, never under-reports).

## Outputs (written to `<folder>/.drift-detector/`)

| File | What |
|---|---|
| `inventory.json` | The IR — per-repo `{runtimes, frameworks, sdks, endpoints[{vendor, domain, version, file_count, files:[path:line]}]}` + rollups + coverage. The queryable shape-map. |
| `INVENTORY.md` | The report to read — a comprehensive, **drift-first** Markdown doc (open in a Markdown preview): what changed, then the summary, the APIs/frameworks/runtimes/SDKs tables, and a per-repo section with each endpoint at `file:line`. |
| `DRIFT.md` | Just the diff vs the previous scan (standalone). |
| `AUDIT.md` | *(audit)* Vulnerability + EOL findings, ranked by severity, per repo, each with a cited source and fix version. |
| `bom.json` | *(audit)* [CycloneDX 1.6](https://cyclonedx.org/) SBOM — components (PURLs) + vulnerabilities. Ingestible by Dependency-Track, Grype, GitHub, etc. |
| `findings.sarif` | *(audit)* [SARIF 2.1.0](https://sarifweb.azurewebsites.net/) — uploadable to GitHub's Security tab. |

Re-runs are cheap: only repos whose git `HEAD` changed are re-analyzed (per-repo
commit-SHA cache).

## How it works

`bin/drift-scan` (self-bootstrapping runner) → `python -m agent.cli inventory-scan`.
The scanner ([`agent/`](agent/)) walks each repo, runs the engine with a generated
rule pack over the vendor catalog ([`agent/vendors.yaml`](agent/vendors.yaml)),
parses manifests, and aggregates everything into the superset IR. Extend
`agent/vendors.yaml` (vendors) and `agent/frameworks.yaml` (frameworks) as your
stack grows. The **audit** (`agent/audit.py`) reads that IR and enriches it via
OSV.dev + endoflife.date over stdlib HTTP (no extra dependency).

See [docs/PLUGIN.md](docs/PLUGIN.md) for details, and run the test suite with
`pytest` (needs `pip install -r requirements.txt`).

## Limits (v1)

- Endpoint **version** is best-effort from the URL on the matched line — `None` when a
  repo builds the URL from a base constant with the version appended elsewhere
  (needs dataflow; a future Opengrep taint rule).
- Detects hard-coded endpoints + manifest-declared SDKs. An SDK used only via its
  client library (no hard-coded URL) shows via the manifest, not as a call-site.
- The audit checks the **declared manifest floor**, not the lockfile-resolved version
  — conservative (may over-report). Sources are Tier 1 (OSV + endoflife.date); "package
  abandoned/deprecated" (Tier 2) and community/early-warning (Tier 3) signals are not
  yet included.
