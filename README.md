# Drift Detector

A Claude Code plugin — a **goal-driven agent** for keeping third-party API integrations
green. It builds a **code-level inventory** of the integrations your repos use (which
APIs/SDKs/runtimes, with `file:line` and versions), reports **what changed since the last
scan** (drift), **audits** those dependencies for known vulnerabilities (OSV) and
end-of-life runtimes (endoflife.date), rolls the findings up into a **ranked list of fix
actions**, renders a **self-contained interactive dashboard**, and can **run itself on a
schedule**. Everything runs locally as a
**deterministic pipeline** (Opengrep/semgrep AST matching + manifest parsing + public API
lookups) — **zero LLM tokens**; Claude only orchestrates, narrates, and sets things up.

Its one thing no CVE scanner or SBOM can do: the **endpoint layer** — it knows *which
third-party APIs your code calls, at which `file:line`*, and flags when a vendor **retires**
one (e.g. *"eBay's Finding API — called at `src/Ebay/…:37` — was decommissioned 2025-02-05;
migrate to Browse API"*). Packages are the demo; **retired-API detection is the point**.

## Install

```
/plugin marketplace add https://github.com/laxit-patel/drift-detector
/plugin install drift-detector@tops-tools
```

Prerequisite: **`uv`** (recommended — https://docs.astral.sh/uv/) *or* Python ≥ 3.11
with `venv`, plus internet on the first run. The bundled runner provisions its own
venv + scan engine — no manual Python or ast-grep install.

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

Reads the folder's existing `inventory.json` and checks it against three sources,
classifying each finding **DEPRECATED** (act now) / **REVIEW** (assess), with a cited source:
- **OSV.dev** — known CVEs per package version (**lockfile-exact** where a lockfile exists, else the declared floor);
- **endoflife.date** — EOL runtimes/frameworks;
- **`agent/vendor_sunsets.yaml`** — a **curated vendor-API-sunset catalog** joined against your
  endpoint inventory, so it flags *"eBay Finding API (`svcs.ebay.com`) decommissioned 2025-02-05 — called at these `file:line`"* —
  the thing package/CVE scanners can't see. Entries can be **domain-scoped** so a dead legacy
  host is flagged without false-flagging a live one that shares its version string. Extend it
  with your vendors' announcements (each entry cites a source).

**Findings roll up into actions.** Thirty CVEs against one package are **one** job —
*upgrade `torch` to `2.10.0`* — so the report doesn't drown you in 300 rows. The dashboard
opens with the tiles and a **ranked fix queue** (severity, then blast radius, each with the
exact upgrade command). It also **leads with the delta** (🆕 new · ✅ resolved since last scan); accepted
findings can be muted. Needs network on the run (still zero LLM tokens); degrades gracefully offline.

### Dashboard — the interactive view

Every scan also writes **`dashboard.html`** — one self-contained file (inline CSS + JS, no
server, no CDN, opens straight from `file://`, emails as one attachment). A cockpit of
clickable tiles — **Critical · Fixes · EOL · Sunsets · APIs used · Unknown hosts** — over a
drill-down fix queue: click a row for the upgrade command and the CVEs it clears, or a
sunset for its `file:line` call-sites. Dark/light theme. Tiles count **actions**, so a
tile's number always matches the rows it filters to.

### Autonomous & scheduled

`/drift-detector <folder>` runs the full **scan → audit** pipeline and then offers to make
it autonomous. On your OK it installs a **cron job on this machine** (default Sundays 7am)
that re-runs the deterministic pipeline — **no Claude, no tokens**.

```
/drift-detector schedule <folder>      # install the weekly cron (shows the crontab line first)
/drift-detector unschedule <folder>    # remove it
```

The scheduled run is the `run` subcommand (`scan → audit → dashboard`); logs land in
`<folder>/.drift-detector/cron.log`. The agent always shows the exact crontab line and asks
before touching your crontab. (Cron = Linux/macOS.)

## Outputs (written to `<folder>/.drift-detector/`)

| File | What |
|---|---|
| `inventory.json` | The IR — per-repo `{runtimes, frameworks, sdks, endpoints[{vendor, domain, version, file_count, files:[path:line]}]}` + rollups + coverage. The queryable shape-map. |
| `audit.json` | The findings + ranked actions + delta, as data. |
| `dashboard.html` | **The report** — self-contained interactive dashboard: tiles, drill-down fix queue, the endpoint/sunset view, "Changed since last scan", and the per-repo **coverage grade**. No server, opens from `file://`. |

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
`pytest` (needs `pip install -r requirements.txt`). Contributors improving the
scanner can measure it against real public repos with the evaluation harness —
see [docs/EVAL.md](docs/EVAL.md) (`bin/drift-eval`).

## Limits

- Endpoint **version** is best-effort from the URL on the matched line — `None` when a
  repo builds the URL from a base constant with the version appended elsewhere
  (needs dataflow; a future Opengrep taint rule).
- Detects hard-coded endpoints + manifest-declared SDKs. An SDK used only via its
  client library (no hard-coded URL) shows via the manifest, not as a call-site.
- Versions are **lockfile-exact where a lockfile exists**, else the declared manifest floor
  (marked as such). Only **direct** (manifest-declared) dependencies are audited; transitive
  dependencies resolved in lockfiles are not queried.
- Vulnerability/EOL sources are Tier 1 (OSV + endoflife.date); the vendor-sunset catalog is
  **curated** (you extend it). "Package abandoned/deprecated" (Tier 2) and community/early-warning
  (Tier 3) signals are not yet included.
- The dashboard shows the **latest** run; week-over-week movement comes from the finding delta,
  not a multi-run archive (that's a future layer).
