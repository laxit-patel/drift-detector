# Change Monitor — Plan 05 (Classify + Orchestration)

Completes the agent: registry deprecation check, trust-gate validator, Claude classify stage
(LLM judges changeType + evidence; severity stays deterministic), html-changelog structurer,
the run orchestrator, and the dead-man's switch.

## LLM seams
`agent/llm_classify.claude_classify_fn` and `agent/lib/feeds/html_changelog._llm_structure` shell out
to `claude --bare -p` with a secret-scrubbed env. To wire the LIVE classify path, pass the real
`claude_classify_fn` into `run_pipeline` (the CLI uses the deterministic/`--dry-classify` seam for
offline/testing). Prereqs to run live: Anthropic key on the host, reports repo + REPORTS_TOKEN,
GCHAT_WEBHOOK_URL, HEALTHCHECK_URL.

## Run (host cron)
`run.sh` is the weekly entrypoint (Sun 07:00 via crontab). It runs ingest -> discover -> inventory ->
registry-scan -> classify-report, writing `report.md` and `state/findings.json` locally. `registry-scan`
is non-fatal (`|| echo "registry-scan skipped"`) since it needs internet access the cron host may not
always have. If both `REPORTS_TOKEN` and `GCHAT_WEBHOOK_URL` are set in the environment, it then runs
the `deliver` CLI command (wiring `run_mod.deliver`), which commits the report + findings to the reports
repo and posts the Chat summary; if either env var is missing, delivery is skipped and the run stays
local-only (this is logged, not silent). It then pings the healthcheck regardless; any failure earlier
in the pipeline posts a Chat notice + exit 1 (the Chat post itself degrades gracefully if
`GCHAT_WEBHOOK_URL` is unset — the exit 1 still fires). A separate Monday cron runs
`liveness.check_report_fresh` and alerts if no report landed (the out-of-band dead-man's switch, since a
dead host cannot report itself).

## Wiring status

**WIRED and running in the pipeline:**
- `rss` and `endoflife` feeds (plus `github-releases`) ingest into the KB via `agent.cli ingest`.
- Registry deprecation checks run via the standalone `registry-scan` CLI command (`agent/registry_scan.py`),
  invoked after `inventory` in `run.sh`. It reads the inventory's `lib:*` techKeys, calls
  `agent.lib.registry_check.check_package` for each, and appends any deprecation `ChangeEntry` to the KB
  — from there it flows into candidates/report exactly like a feed-sourced entry. It is a run step, not a
  feed adapter: `registry` is rejected if used as a `feeds:` entry in `config.yaml` (see below).
- The full classify -> validate -> delta -> report -> deliver spine (`agent/run.py`, `agent/validator.py`,
  `agent/delta.py`, `agent/report.py`).

**Implemented but NOT yet wired into ingest (follow-up):**
- The `html-changelog` LLM structurer (`agent/lib/feeds/html_changelog.py`). Its adapter returns
  `(entries, page_hash)` — a shape `agent.kb_ingest.ingest_feed` cannot consume (it expects a plain list),
  because threading the prior page-hash through the ingest loop and KB watermark is not yet built. Until
  that's done, `agent/config.py` rejects `adapter: html-changelog` in any feed with a `ConfigError`
  ("... not yet wired into ingest ...") instead of accepting a feed that would silently fail to ingest.

**Trust gate honesty:** the "cited-URL-must-be-fetched" check in `agent/validator.py`
(`f.sourceUrl not in fetched_urls`) is a DEFENSIVE INVARIANT, not a check that fires in normal operation
today. In the current design no component injects an unfetched URL into a finding — the classify LLM only
ever sets `changeType`/`evidence`/severity-relevant fields, never `sourceUrl` (that's copied through from
the KB `ChangeEntry`, which was stamped with the URL that was actually fetched at ingest time). So this
check never rejects anything today; it exists to protect future LLM stages that might cite a source they
didn't actually fetch.

**Tier-3 findings:** `agent/validator.py` quarantines actionable (ACTION/REVIEW) findings sourced from a
tier-3 feed to the watchlist — a tier-3 finding is rejected outright unless it's already flagged
`watchlist`. No current feed in `config.yaml` emits tier-3, so this path never fires today; the wiring
that would actually promote a low-confidence signal into the watchlist (rather than just rejecting it) is
a follow-up.
