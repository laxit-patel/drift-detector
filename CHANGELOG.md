# Changelog

All notable changes to the Drift Detector plugin. Dates are YYYY-MM-DD.

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
