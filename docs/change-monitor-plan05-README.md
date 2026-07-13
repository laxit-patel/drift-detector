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
classify-report, then commit + Chat, then pings the healthcheck; any failure posts a Chat notice + exit 1.
A separate Monday cron runs `liveness.check_report_fresh` and alerts if no report landed (the out-of-band
dead-man's switch, since a dead host cannot report itself).
