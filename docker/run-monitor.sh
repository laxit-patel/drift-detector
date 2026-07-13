#!/usr/bin/env bash
# Container entrypoint. Stateless compute: every persistent artifact lives under
# $STATE_DIR (kb/, findings.json, reports/), which the CI workflow restores from
# git before this runs and commits back after. Secrets arrive via env.
#
#   Required env : GITHUB_TOKEN (or config's tokenEnv) — read access to the repos to scan
#   Optional env : GCHAT_WEBHOOK_URL, HEALTHCHECK_URL, REPORT_URL_BASE, RUN_DATE, CONFIG_FILE, STATE_DIR
set -euo pipefail

CFG="${CONFIG_FILE:-/work/config.yaml}"
STATE_DIR="${STATE_DIR:-/work/state}"          # persisted in git: kb/, findings.json, reports/
SCRATCH="${SCRATCH_DIR:-/tmp/cm-scratch}"      # derived intermediates — NOT persisted
NOW="${RUN_DATE:-$(date +%F)}"                 # RUN_DATE lets CI pin a reproducible date
REPORTS_DIR="$STATE_DIR/reports"
FINDINGS="$STATE_DIR/findings.json"
REPORT="$REPORTS_DIR/report-$NOW.md"

mkdir -p "$STATE_DIR/kb" "$REPORTS_DIR" "$SCRATCH"

fail() {   # $1 = stage. Post a failure card to Chat (best-effort) then exit non-zero.
  python -c "import os,sys;from agent.lib.chat import build_failure_text,post_chat;\
post_chat(os.environ.get('GCHAT_WEBHOOK_URL',''), build_failure_text(sys.argv[1],'see CI logs',sys.argv[2],'n/a'))" \
    "$1" "$NOW" 2>/dev/null || true
  echo "FAILED at stage: $1" >&2
  exit 1
}

echo ">> ingest";        python -m agent.cli ingest        --config "$CFG" --now "$NOW"                                                    || fail ingest
echo ">> discover";      python -m agent.cli discover      --config "$CFG" --now "$NOW" --out "$SCRATCH/active-repos.json"               || fail discover
echo ">> inventory";     python -m agent.cli inventory     --config "$CFG" --active "$SCRATCH/active-repos.json" \
                             --out "$SCRATCH/inventory.json" --patterns agent/patterns.yaml --now "$NOW"                                 || fail inventory
echo ">> registry-scan"; python -m agent.cli registry-scan --config "$CFG" --inventory "$SCRATCH/inventory.json" --now "$NOW"           || echo "registry-scan skipped (offline / rate-limited)"

# Last run's findings.json (if any) is this run's delta baseline; '-' means first run.
if [ -s "$FINDINGS" ]; then PREV_ARG="$FINDINGS"; else PREV_ARG="-"; fi
echo ">> classify-report"
python -m agent.cli classify-report --config "$CFG" \
  --inventory "$SCRATCH/inventory.json" --active "$SCRATCH/active-repos.json" \
  --prev "$PREV_ARG" --out-report "$REPORT" --out-findings "$FINDINGS" --now "$NOW"                                                       || fail classify

# Deliver: post the summary to Chat (git push of state is the CI workflow's job).
if [ -n "${GCHAT_WEBHOOK_URL:-}" ]; then
  python -c "import json,os,sys;from agent.lib.chat import build_summary_text,post_chat;\
doc=json.load(open(sys.argv[1]));\
url=os.environ.get('REPORT_URL_BASE','')+os.path.basename(sys.argv[2]);\
post_chat(os.environ.get('GCHAT_WEBHOOK_URL',''), build_summary_text(doc, url))" \
    "$FINDINGS" "$REPORT" || echo "chat post failed (non-fatal)"
else
  echo "delivery skipped: GCHAT_WEBHOOK_URL not set — report written to $REPORT only"
fi

# Dead-man's switch: ping ONLY after a fully successful run.
python -c "import os;from agent.liveness import ping_healthcheck;ping_healthcheck(os.environ.get('HEALTHCHECK_URL',''))" || true
echo "run complete: $NOW  (report: $REPORT)"
