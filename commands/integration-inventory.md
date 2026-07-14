---
description: Scan a folder of cloned repos for third-party integration usage (APIs/SDKs, code-level) and summarize it in chat.
argument-hint: <path-to-folder-of-cloned-repos>
---

Scan the folder of cloned git repos at `$ARGUMENTS` for third-party integration usage, and report it in chat. The heavy lifting is a **deterministic Python scan** (Opengrep static analysis + manifest parsing) — it costs ~no tokens; your job is only to run it and narrate/answer follow-ups. Do NOT read files yourself to build the inventory — the scanner does that.

1. **Preflight.** From the repo root, activate the venv (`source .venv/bin/activate`) and confirm the engine is present: `opengrep --version || semgrep --version`. If neither is installed, tell the user to install Opengrep (or `uv pip install semgrep`) and STOP — never fabricate a result. The scan itself also fails loud if the engine is missing.

2. **Scan** (deterministic; only repos whose git HEAD changed since last time are re-analyzed, thanks to the per-repo commit-SHA cache):

   ```bash
   python -m agent.cli inventory-scan \
     --root "$ARGUMENTS" \
     --state "$ARGUMENTS/.integration-inventory" \
     --out-json "$ARGUMENTS/.integration-inventory/inventory.json" \
     --out-md "$ARGUMENTS/.integration-inventory/INVENTORY.md" \
     --out-diff "$ARGUMENTS/.integration-inventory/DIFF.md" \
     --now "$(date +%F)"
   ```

3. **Read** the generated `INVENTORY.md` and `DIFF.md` from `$ARGUMENTS/.integration-inventory/`.

4. **Summarize in chat**, concisely:
   - repos scanned (and any errored/coverage gaps);
   - the **top third-party APIs by repo count**, with versions where known;
   - notable **runtimes / frameworks** (call out anything ancient or end-of-life);
   - **what changed since the last scan** (from `DIFF.md`): new/removed APIs, SDK version bumps, runtime changes;
   - flag anything risky by name (e.g. Amazon **MWS** is retired; very old Node/PHP pins).

5. **Follow-ups** — answer questions like *"which repos use Amazon SP-API?"*, *"who's still on an old Node?"*, *"what versions of Stripe are in use?"* by reading `inventory.json` (the queryable inventory/IR). **Do NOT re-run the scan for a question** — the JSON is the shape-map; filter it. Only re-scan when the user asks for a fresh scan or the code changed.
