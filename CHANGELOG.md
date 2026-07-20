# Changelog

All notable changes to the Drift Detector plugin. Dates are YYYY-MM-DD.

## v0.5.0-beta — 2026-07-20

**The release that answers the demo.** The PM asked why the scan "skipped"
`getCategoryFeatures`. The answer was structural: our detection unit was the *host*,
and eBay retires *operations* — one host, one path, ~19 calls on independent
lifecycles. There was no way to express "GetCategories is dead, GetItem is alive."
This release adds that axis, and then makes the tool say plainly where it still
cannot see.

### ⚠️ Breaking — read before upgrading

- **Reports are now ONE file: `dashboard.html`.** `AUDIT.md`, `INVENTORY.md`,
  `DRIFT.md`, `bom.json` (CycloneDX) and `findings.sarif` are **no longer written**.
  The drift delta and the ranked fix queue those carried now live *in* the dashboard.
  If you had a bookmark or a pipeline reading one of those files, it will find nothing.
- **Removed surfaces:** the MCP server (`bin/drift-mcp`), the GitLab sync connector,
  and the GitHub Action (`action.yml`). **CI still works** — `bin/drift-scan run
  --fail-on-deprecated` and its exit codes (0 ok / 2 error / 3 gate-tripped /
  4 couldn't-verify) are unchanged and are the interface for any runner.
- **Engine swapped: semgrep/Opengrep → ast-grep**, a static binary the runner fetches
  automatically on first scan. No action needed; a leftover semgrep in an old venv is
  ignored, not used. Scans get substantially faster.
- **Caches invalidate on upgrade** (schema 3 → 4), so the first scan after upgrading
  re-reads every repo. Old `repos_v3/` directories are inert and can be deleted.

### Added

- **The operation axis.** Endpoints carry `operation`, sunsets can be scoped to one,
  and the audit join is operation > domain > version. This is what makes
  `GetCategoryFeatures` (decommissioned 2026-06-04) reportable at its exact
  `file:line` while `GetItem` on the same host stays quiet.
- **Coverage verdicts — KNOWN / UNKNOWN with reasons.** Derived from what the ruleset
  can actually see per language. A Go-only repo can no longer report a confident
  grade off zero signal; it reports `UNKNOWN (no-egress-signal)` and routes to a
  manual pass. **This will look like a regression and is not** — it is the tool
  admitting a blindness it previously hid.
- **Residue** — versioned paths and egress calls we matched but could not attribute,
  listed with `file:line`. The scanner's own conscience; it is what a scout pass reads.
- **`observed` vs `inferred` attribution.** When only one vendor is present, a bare
  path is attributed to it — a guess about the *repo*, not evidence from the *line*.
  That is now labelled. Worth knowing: `amazonspapi` is 2 observed / 18 inferred.
- **`/drift-deepen <folder>`** — the scout. Investigates only what the scan admits it
  cannot read, and must pass a deterministic gate (`drift-scan absorb`) that re-scans
  and rejects any proposal that does not hold up. Dates without a fetched source are
  refused outright.
- **`drift-scan recommend`** — per-repo scan profile (auto / hybrid / manual) with a
  one-line why.
- **10 dated, sourced vendor sunsets** — 6 eBay Trading operations plus the LMS
  retirements, each deep-linked to the release note that announced it.

### Fixed

- Seven bugs from a deliberate adversarial self-audit — malformed engine output
  reading as a clean scan; heredoc URLs lost; orphan operation markers dropped;
  an unreadable repo reporting KNOWN; the absorb gate passing an over-attributing
  proposal; attestations bleeding between same-named repos; a grade that could read
  HIGH beside a verdict of UNKNOWN. Every one was reproduced before it was fixed.

## v0.4.0-beta — 2026-07-17

A measurement instrument for the scanner: run it against real code and see what it catches.

### Added
- **Evaluation / regression harness** (`bin/drift-eval`, contributor tool — see
  [docs/EVAL.md](docs/EVAL.md)). Clones a **pinned** corpus of real public repos grouped by the
  integration they use (`eval/corpus.yaml`), scans them, and scores the scanner: **recall is a
  hard gate** (a repo in `sandbox/ebay/` must detect eBay), plus informational
  noise / version / sunset metrics. Every miss is tagged by a failure-mode enum so the scorecard
  doubles as an improvement backlog. Deterministic, zero-LLM; clones and run artifacts live under
  `~/.drift/` and `~/Projects/sandbox/`, never committed.
- **Corpus:** eBay (5 repos), Amazon SP-API (5), Walmart (4) — all real, SHA-pinned. First scores:
  eBay 5/5 recall + the `svcs.ebay.com` Finding-API sunset fired on a real legacy repo; SP-API 5/5;
  Walmart 4/4.
- **`~/.drift/` home** for eval + central/demo run artifacts (honors `$DRIFT_HOME`). The plugin's
  in-place `<folder>/.drift-detector/` behavior is unchanged.

### Fixed / changed
- **Honest version-rate metric.** Version-extraction rate is now measured only over endpoints whose
  URL actually carries a version, with a separate "no URL version" count — so the scanner isn't
  scored down for APIs that have no URL version (a vendor's design choice, not a scanner failure).

### Notes
- The harness quantified a real boundary: a scanner miss where the API version lives only in SDK
  code (a class constant assembled at runtime) is deterministically unreachable — it marks where a
  future cognition layer would earn its place, rather than something to chase with AST rules.

## v0.3.0-beta — 2026-07-16

The report you actually act on, plus a visual surface and sharper detection.

### Added
- **Ranked fix actions.** Findings now roll up into `(repo, package)` **actions** — 30 CVEs
  against one package are one job (*upgrade `torch` to `2.10.0`*), not 30 rows. `AUDIT.md`
  opens with **"Do this first"** (ranked by severity, then blast radius, each with the exact
  upgrade command), then the full fix queue, then per-repo.
- **Interactive dashboard.** Every scan writes a self-contained **`dashboard.html`** — inline
  CSS + JS, no server, no CDN, opens from `file://`. Clickable tiles (Critical · Fixes · EOL ·
  Sunsets · APIs used · Unknown hosts) over a drill-down fix queue; dark/light theme. Also
  available on demand via `audit --out-html <path>`.
- **Domain-scoped vendor sunsets.** Catalog entries can target a specific host, so a dead
  legacy API is flagged without false-flagging a live one that shares its version string.
  Ships the real **eBay Finding API** (`svcs.ebay.com`) and **Shopping API**
  (`open.api.ebay.com`) retirements (decommissioned 2025-02-05 → migrate to Browse API).
- **Read-only GitLab connector** (`gitlab-sync`). Clone/pull your GitLab fleet with a
  read-only PAT (`read_api` + `read_repository`) into a folder, then scan it — so private
  and in-house wrapper repos get covered. The token is env-only and stripped from every
  repo's `.git/config`. See [docs/GITLAB.md](docs/GITLAB.md). (No GitLab MCP required.)
- **Coverage honesty + `doctor`.** The scan now reports what it *couldn't* see — private/
  unresolvable package sources, unknown external hosts, floor-only vs lockfile-exact versions
  — and `drift-detector doctor <folder>` runs a scan-readiness preflight.
- **Discover-then-classify detection.** Inverted the old allow-list: one broad URL rule
  catches every outbound endpoint, then classifies against a ~40-vendor catalog (now
  including Amazon AWS). Unknown external hosts are surfaced instead of silently dropped.

### Fixed
- **Report ranking bug.** "Most urgent" took the first 15 findings unsorted, burying every
  CRITICAL (including remote-code-execution advisories) under "…and N more". Now genuinely
  ranked.
- **Git-SHA fix versions.** OSV returns some `fixed` values as commit hashes; the version
  sort ranked those above real versions and recommended a git SHA. Now filtered to real
  version strings.
- **Dashboard XSS hardening.** Scan-derived strings are escaped on both surfaces
  (HTML text + the embedded JSON blob), attribute contexts get quote-safe escaping, and
  source links are restricted to `http(s)` schemes.
- **Substring host mis-attribution** (`ups.com` matching `startups.com`) — matching is now
  registrable-domain / boundary-anchored.
- **Stale scan cache** silently omitted new fields; the per-repo cache is now schema-versioned.

### Notes
- The dashboard shows the latest run; week-over-week movement comes from the finding delta,
  not a multi-run archive (a future layer).
- The Google Chat webhook and any GitLab token are **per-install** configuration held by each
  user, never committed. Teammates who install the plugin get their own notifications and
  point at their own repos.

## v0.2.0-beta — 2026-07-15

- Lockfile-exact versions + finding lifecycle (fingerprints, `first_seen`, baseline mute,
  delta-first digest).
- Curated vendor-API-sunset catalog joined against the endpoint inventory.
- Read-only MCP facade (`bin/drift-mcp`) for generation-time prevention from any assistant.
- Deterministic CI: `run --fail-on-deprecated` + composite GitHub Action + SARIF upload.

## v0.1.0-beta — 2026-07-14

- Initial public beta: code-level integration inventory (Opengrep), drift vs last scan,
  OSV + endoflife.date audit, Google Chat delivery, self-scheduling cron, Claude Code plugin.
