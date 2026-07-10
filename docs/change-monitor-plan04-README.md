# Change Monitor — Plan 04 (Deterministic Delivery Core)

Turns inventory.json + KB drift into findings.json + a markdown report — no LLM, no live services.

## Run (offline, deterministic)
```bash
source .venv/bin/activate
python -m agent.cli report --config config.yaml \
  --inventory inventory.json --active active-repos.json --prev last-findings.json \
  --out-report report.md --out-findings findings.json --now 2026-07-12
```
Severity is rule-decided (spec §6): breaking/security → ACTION; lifecycle EOL → OK/REVIEW/ACTION by
horizon; deprecation/behavioral → REVIEW; unstructured "additive" changelog entries → OK + `needsReview`
(Plan 05's Claude stage re-judges those and fills `businessRiskNote`). Delta uses 2-run flap damping.
The report LEADS with business-logic risk (ACTION). Commit-to-reports-repo + Google Chat delivery and
the LLM classify stage + run.sh + dead-man's switch land in Plan 05.

## Next (Plan 05)
Claude classify stage + trust gate (evidence quote, cited-URL-must-be-fetched), html-changelog structurer,
registry feed adapter, run.sh full pipeline + host-cron + dead-man's switch.
