<!-- docs/change-monitor-plan01-README.md -->
# Change Monitor — Plan 01 (KB Foundation)

Deterministic Change Knowledge Base: ingest changelog feeds → append-only JSONL → drift.

## Run
```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m agent.cli ingest --config config.yaml --now 2026-07-12
python -m agent.cli drift  --config config.yaml --since 2026-07-05
```
Ingest is idempotent (dedupe by entry id) and append-only. Feeds that fail are
reported as errors (exit 1) but never crash the run. No GitLab or LLM needed here.

## What's next
- Plan 02: GitLab discovery + inventory + `github-releases`/`registry`/`html-changelog` adapters.
- Plan 03: Claude classify stage + trust gate, delta, report, Chat, `run.sh`, dead-man's switch.
