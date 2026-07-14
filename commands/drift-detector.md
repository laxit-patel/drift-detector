---
description: Detect third-party integration drift across one or more folders of repos — code-level API/SDK usage + what changed since the last scan — and summarize in chat.
argument-hint: <folder> [more-folders...]
---

Detect **integration drift** across the git repos found under `$ARGUMENTS` (one or more space-separated folders), and report it in chat. Discovery is **recursive** — repos nested at any depth are found, and each folder given is a separate scan root. The heavy lifting is a **deterministic scan** (Opengrep/semgrep static analysis + manifest parsing) — it costs ~no tokens; your job is only to run it and narrate / answer follow-ups. Do NOT read source files yourself to build the inventory — the scanner does that.

The bundled runner `bin/drift-scan` is **self-bootstrapping**: on first use it creates a plugin-local venv and installs the engine (needs `uv` or python≥3.11 + internet, one-time ~a minute); later runs reuse it. It works from **any** directory — you do NOT need to be in the plugin's repo.

**Before running, tell the user in one line** that this is a *deterministic local static-analysis scan (AST-level, via Opengrep) that costs no tokens* — so a pause is the scan working, not an expensive agent. Then run it (the `--progress` flag prints an informative per-phase log).

If `$ARGUMENTS` is exactly `doctor`, run `"$SCAN" doctor` (see runner discovery below) and relay its output — it checks prerequisites (uv/python/venv/engine) and prints exact install steps. Use this when a scan failed to provision.

1. **Scan** (deterministic; only repos whose git `HEAD` changed since last time are re-analyzed, via the per-repo commit-SHA cache — so drift runs are fast). `--root` is repeatable — pass one per folder; the first folder holds the shared state/output. Locate the bundled runner, then run it:

   ```bash
   set -- $ARGUMENTS

   # find the bundled self-bootstrapping runner (portable across Claude Code versions)
   SCAN=""
   for c in "${CLAUDE_PLUGIN_ROOT:-}/bin/drift-scan" \
            "${CLAUDE_SKILL_DIR:-}/../bin/drift-scan" \
            "${CLAUDE_SKILL_DIR:-}/bin/drift-scan"; do
     [ -n "$c" ] && [ -x "$c" ] && { SCAN="$c"; break; }
   done
   [ -z "$SCAN" ] && SCAN="$(find "$HOME/.claude/plugins" -type f -name drift-scan -path '*drift-detector*' 2>/dev/null | head -1)"
   [ -z "$SCAN" ] && { echo "drift-detector: runner not found — is the plugin installed?" >&2; exit 4; }

   if [ "$1" = "doctor" ]; then "$SCAN" doctor; exit $?; fi

   STATE_HOME="$1"                       # first folder holds shared state + reports
   ROOT_ARGS=(); for r in "$@"; do ROOT_ARGS+=(--root "$r"); done
   "$SCAN" --progress "${ROOT_ARGS[@]}" \
     --state "$STATE_HOME/.drift-detector" \
     --out-json "$STATE_HOME/.drift-detector/inventory.json" \
     --out-md "$STATE_HOME/.drift-detector/INVENTORY.md" \
     --out-diff "$STATE_HOME/.drift-detector/DRIFT.md" \
     --now "$(date +%F)"
   ```

   The per-phase log (`⚙ discovering…`, `⚙ [n/N] repo scan…`) and the final `✓ … · Xs` line stream to stderr — surface a short version to the user so they see it worked. If it prints a first-run setup line, that's the one-time venv/engine install — let it finish. If it exits saying `uv`/python is missing (or points to `doctor`), run `"$SCAN" doctor`, relay the fix, and STOP (never fabricate a result).

2. **Read** `DRIFT.md` and `INVENTORY.md` from `<first-folder>/.drift-detector/`.

3. **Report — lead with drift.**
   - If `DRIFT.md` shows changes (there was a prior scan): **lead with what drifted** — new/removed third-party APIs, API version bumps (e.g. SP-API v0→v2), SDK version changes, runtime changes — grouped by repo, most notable first. Flag anything risky by name (retired APIs like Amazon **MWS**; a jump onto/off a deprecated version; ancient Node/PHP pins).
   - If it's the first scan (baseline, no prior): say so, then give the **current inventory** — repos scanned, top third-party APIs by repo count (with versions where known), notable runtimes/frameworks, and any coverage gaps.

4. **Follow-ups** — answer questions like *"which repos use Amazon SP-API?"*, *"who drifted onto an old runtime?"*, *"what Stripe versions are in use?"* by reading `inventory.json` (the queryable shape-map). **Do NOT re-scan for a question** — filter the JSON. Only re-scan when the user wants a fresh check or the code changed.
