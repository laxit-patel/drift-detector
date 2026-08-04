<p align="center">
  <img src="art/drift-detector.png" alt="Ashen Oracle — Drift Detector" width="160">
</p>

# Drift Detector

> 🔮 **Ashen Oracle** — *Know before it breaks.*
> The TOPS relic that reads the ashes: it names the dying, sunset, and end-of-life
> third-party APIs in your repos — with dates — before they break in production.

**A DevSecOps supply-chain scanner for third-party integrations.** In one deterministic,
zero-LLM-token pass it does **SBOM + SCA** — a CycloneDX **SBOM** of every component, **SCA**
against **OSV** CVEs and **endoflife.date** EOL — *plus* the layer no SBOM or CVE scanner has:
which third-party **APIs your code calls, at `file:line`**, and when the vendor **retires**
them (**vendor-API sunsets**). Every finding is dated and sourced; every report is
`verify`-certified; where it's blind, it says so.

A Claude Code plugin — a **goal-driven agent** for keeping third-party API integrations
green. It builds a **code-level inventory** of the integrations your repos use (which
APIs/SDKs/runtimes, with `file:line` and versions), reports **what changed since the last
scan** (drift), **audits** those dependencies for known vulnerabilities (OSV) and
end-of-life runtimes (endoflife.date), rolls the findings up into a **ranked list of fix
actions**, renders a **self-contained interactive dashboard**, and can **run itself on a
schedule**. Everything runs locally as a
**deterministic pipeline** (ast-grep AST matching + manifest parsing + public API
lookups) — **zero LLM tokens**; Claude only orchestrates, narrates, and sets things up.

It emits a standard **CycloneDX SBOM** (components + CVE vulnerabilities — SBOM + VEX) like
any SCA tool, then adds the one thing no SBOM or CVE scanner can: the **endpoint layer** — it
knows *which third-party APIs your code calls, at which `file:line`*, and flags when a vendor
**retires** one (e.g. *"eBay's Finding API — called at `src/Ebay/…:37` — was decommissioned
2025-02-05; migrate to Browse API"*). Packages are the demo; **retired-API detection is the
point**.

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

### SBOM — CycloneDX export (SBOM + SCA + VEX)

```
drift-scan sbom --state <dir>          # writes <state>/sbom.json (CycloneDX 1.5)
```

A standard **CycloneDX** Software Bill of Materials for the whole fleet: every component
(packages, runtimes, frameworks, each with a **PURL** and the repos it appears in) plus the
**OSV CVE** findings as `vulnerabilities` — i.e. **SBOM + SCA + VEX** in one file, for your
DevSecOps / supply-chain compliance needs (EO 14028, EU CRA). It is a **verified projection**
of `inventory.json` + `audit.json`: `drift-scan verify` re-derives it and fails if the SBOM is
stale or hand-edited, so it can never quietly disagree with the scan. The scheduled pipeline
emits `sbom.json` alongside every run.

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

### Deliver — a per-repo issue to the right owner

```
drift-scan deliver --state <dir> --config drift.yml     # add --dry-run to preview, write nothing
```

Every flagged repo gets up to **two comprehensive, idempotent GitLab issues, filed in the repo's
own tracker** (the ticket lives with the code):

- a **DevOps issue** — the repo's package CVEs + runtime EOL — assigned to a configured **DevOps
  account**, labelled `drift:devops`;
- a **Developer issue** — the repo's vendor sunsets + framework EOL — auto-assigned to the **repo
  owner** (resolved from GitLab, with a config fallback), labelled `drift:developer`.

Re-runs **update in place** (fingerprinted — never a duplicate, never a notification storm); a
resolved finding **closes its own issue**. Aggregation is **native GitLab**: a group issue board on
the `drift:devops` label — or simply *"issues assigned to the DevOps account"* — is the DevOps queue,
with nothing custom to build. Findings are **issues only, no MRs**. (Teaching the scanner a new
integration shape stays a *reviewed catalog MR* on the private ops repo — that's the review gate,
not a finding.) Configure it in `drift.yml`:

```yaml
delivery:
  mode: create                          # dry-run | create (file issues) | off
  devops:    { assignee: ops-bot }      # every DevOps issue is assigned here (required to write)
  developer: { fallbackAssignee: lead } # a Developer issue assigns to the repo owner; this is the fallback
```

### Probabilistic (AI) cross-check — an opt-in second opinion

The deterministic scan is trustworthy but bounded — it flags only what it can *certify*. After it
runs, you can **opt into an AI pass** that reads every repo and surfaces integrations the rules
can't see (config-driven URLs, exotic wrappers). Its output is a **separate, clearly-labelled
`AI · unverified` report** (`probabilistic.html`) — **leads, not findings** — that never touches the
certified dashboard or the `verify` contract. Any lead can be **promoted through the deterministic
absorb gate** to become certified on the next scan. **AI proposes; the gate certifies;** nothing
unverified is ever presented as certified. It's off by default and costs tokens only when you say yes.

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
| `drift.json` | **The one contract** — the canonical, schema'd report. `dashboard.html` and `drift.md` are *verified projections* of it; `drift-scan verify` re-derives them and fails if they disagree. |
| `dashboard.html` | **The report** — self-contained interactive dashboard: tiles, drill-down fix queue, the endpoint/sunset view, "Changed since last scan", and the per-repo **coverage grade**. Call-site links open in GitLab at the exact line (pinned to the commit). No server, opens from `file://`. |
| `drift.md` | The primary agent/CLI-readable view of the same report. |
| `probabilistic.html` | **Only when you run the opt-in AI cross-check** — a separate, `AI · unverified` second-opinion report. Leads, not certified findings; outside the `verify` contract. |

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

<p align="center">
  <img src="https://media1.tenor.com/m/1QMJcmOppoYAAAAd/mahoraga-makora.gif" alt="Mahoraga — the wheel of adaptation" width="320">
  <br><em>The scanner <b>adapts</b> to every integration shape it's shown — codename <b>Mahoraga, the Wheel</b>
  (<a href="docs/ARCHITECTURE.md">architecture</a>).</em>
</p>

**→ For the full picture — topology, the pipeline, the `verify` contract, delivery, the Cockpit,
what's built and what's next — read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (the core reference,
with diagrams).**

See [docs/PLUGIN.md](docs/PLUGIN.md) for details, and run the test suite with
`pytest` (needs `pip install -r requirements.txt`). Contributors improving the
scanner can measure it against real public repos with the evaluation harness —
see [docs/EVAL.md](docs/EVAL.md) (`bin/drift-eval`).

## Limits

- Endpoint **version** is best-effort from the URL on the matched line — `None` when a
  repo builds the URL from a base constant with the version appended elsewhere
  (needs dataflow; out of scope).
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
