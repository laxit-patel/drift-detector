#!/usr/bin/env bash
# Host-cron entrypoint. Secrets come from the host env (root-only). Fail loud; post Chat on failure.
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
NOW="$(date +%F)"
CFG=config.yaml
fail() { python -c "from agent.lib.chat import build_failure_text,post_chat;import os;post_chat(os.environ['GCHAT_WEBHOOK_URL'], build_failure_text('$1','see logs','$NOW','n/a'))"; exit 1; }

python -m agent.cli ingest    --config "$CFG" --now "$NOW"                                   || fail ingest
python -m agent.cli discover  --config "$CFG" --now "$NOW" --out active-repos.json           || fail discover
python -m agent.cli inventory --config "$CFG" --active active-repos.json --out inventory.json --now "$NOW" || fail inventory
# LLM classify runs inside classify-report only when --dry-classify is omitted AND the real claude_classify_fn is wired;
# for the cron we invoke the deterministic path here and let a follow-up wire the live seam (see README).
env -u GITLAB_READ_TOKEN -u REPORTS_TOKEN \
  python -m agent.cli classify-report --config "$CFG" --inventory inventory.json --active active-repos.json \
  --prev state/findings.json --out-report "reports/report-$NOW.md" --out-findings state/findings.json --now "$NOW" || fail classify
python -c "from agent.liveness import ping_healthcheck;import os;ping_healthcheck(os.environ.get('HEALTHCHECK_URL',''))"
echo "run complete: $NOW"
