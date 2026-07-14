---
description: Detect third-party integration drift across a folder of repos — code-level API/SDK usage + what changed since the last scan — and summarize in chat.
argument-hint: <path-to-folder-of-cloned-repos>
---

Detect **integration drift** across the folder of cloned git repos at `$ARGUMENTS`, and report it in chat. The heavy lifting is a **deterministic Python scan** (Opengrep static analysis + manifest parsing) — it costs ~no tokens; your job is only to run it and narrate / answer follow-ups. Do NOT read source files yourself to build the inventory — the scanner does that.

1. **Preflight.** From the repo root, activate the venv (`source .venv/bin/activate`) and confirm the engine: `opengrep --version || semgrep --version`. If neither is installed, tell the user to install Opengrep (or `uv pip install semgrep`) and STOP — never fabricate a result. The scan also fails loud if the engine is missing.

2. **Scan** (deterministic; only repos whose git `HEAD` changed since last time are re-analyzed, via the per-repo commit-SHA cache — so drift runs are fast):

   ```bash
   python -m agent.cli inventory-scan \
     --root "$ARGUMENTS" \
     --state "$ARGUMENTS/.drift-detector" \
     --out-json "$ARGUMENTS/.drift-detector/inventory.json" \
     --out-md "$ARGUMENTS/.drift-detector/INVENTORY.md" \
     --out-diff "$ARGUMENTS/.drift-detector/DRIFT.md" \
     --now "$(date +%F)"
   ```

3. **Read** `DRIFT.md` and `INVENTORY.md` from `$ARGUMENTS/.drift-detector/`.

4. **Report — lead with drift.**
   - If `DRIFT.md` shows changes (there was a prior scan): **lead with what drifted** — new/removed third-party APIs, API version bumps (e.g. SP-API v0→v2), SDK version changes, runtime changes — grouped by repo, most notable first. Flag anything risky by name (retired APIs like Amazon **MWS**; a jump onto/off a deprecated version; ancient Node/PHP pins).
   - If it's the first scan (baseline, no prior): say so, then give the **current inventory** — repos scanned, top third-party APIs by repo count (with versions where known), notable runtimes/frameworks, and any coverage gaps.

5. **Follow-ups** — answer questions like *"which repos use Amazon SP-API?"*, *"who drifted onto an old runtime?"*, *"what Stripe versions are in use?"* by reading `inventory.json` (the queryable shape-map). **Do NOT re-scan for a question** — filter the JSON. Only re-scan when the user wants a fresh check or the code changed.
