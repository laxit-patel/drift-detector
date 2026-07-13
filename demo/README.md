# Demo & Fine-Tuning Harness

Try the agent and tune it **before going live** — no GitLab, no Anthropic key, no Chat required.

## Tier 1 — Fully offline (start here)
```bash
source .venv/bin/activate
python demo/run_demo.py            # first run: everything NEW
python demo/run_demo.py --week2    # second run: ONGOING (and a risk about to RESOLVE)
python demo/run_demo.py --week2    # third run: the upgraded PHP 8.0 risk now shows ✅ RESOLVED
```
It seeds a small Change Knowledge Base with realistic change entries, writes a **sample** tech stack, then runs the **real** deterministic pipeline (candidates → §6 severity → trust-gate → delta → report) and prints `demo/out/report.md`.

### Fine-tune loop
Edit and re-run to watch the report change:
- **`SAMPLE_INVENTORY`** in `demo/run_demo.py` — replace with *your* repos/runtimes/deps/integrations (the shape matches a real `inventory.json`).
- **`SEED_ENTRIES`** — what the KB "knows changed" (in production this comes from `ingest`ing live feeds).
- **`demo/demo-config.yaml`** — `reviewHorizonMonths` (how soon an EOL becomes REVIEW), etc.

What to look for while tuning: does the right thing land in **ACTION** (breaking/passed-EOL) vs **REVIEW** (upcoming EOL/deprecation)? Is a runtime correctly **version-matched** (a repo on PHP 8.2 must NOT get PHP 8.0's EOL)? Do persistent risks stay **ONGOING** and only clear when the tech is upgraded?

## Tier 2 — Real feeds (needs internet, still no keys)
Use live deprecation data instead of the seeded KB:
```bash
python -m agent.cli ingest --config demo/demo-config.yaml --now 2026-07-13
python -m agent.cli registry-scan --config demo/demo-config.yaml --inventory demo/out/inventory.json --now 2026-07-13
python -m agent.cli classify-report --config demo/demo-config.yaml \
  --inventory demo/out/inventory.json --active demo/out/active-repos.json --prev - \
  --out-report demo/out/report.md --out-findings demo/out/findings.json --now 2026-07-13
```
Now the KB holds *real, current* Shopify/Twilio/endoflife/npm data; the inventory is still your sample. Tune the `feeds:` list and `agent/patterns.yaml` (integration presence patterns) here.

## Tier 3 — Real GitLab (needs a read-only token)
Add `gitlab:`/`scan:` sections to the config, `export GITLAB_READ_TOKEN=...`, then run `discover` + `inventory` (instead of the sample inventory) to scan your actual repos.

## Tier 4/5 — Live LLM + delivery
- LLM: pass canned verdicts now via `classify-report --dry-classify verdicts.json`; wire the real `claude_classify_fn` (needs `agent/classify.schema.json` + a pinned model id) for live judging of changelog entries.
- Delivery: `deliver` (or `run.sh`) commits to the reports repo + posts to Google Chat once `REPORTS_TOKEN` + `GCHAT_WEBHOOK_URL` are set.

Output lands in `demo/out/` (git-ignored).
