---
description: Detect third-party integration drift across one or more folders of repos — code-level API/SDK usage + what changed since the last scan — and summarize in chat.
argument-hint: <folder> [more-folders...]
---

Detect **integration drift** across the git repos found under `$ARGUMENTS` (one or more space-separated folders), and report it in chat. Discovery is **recursive** — repos nested at any depth are found, and each folder given is a separate scan root. The heavy lifting is a **deterministic scan** (Opengrep/semgrep static analysis + manifest parsing) — it costs ~no tokens; your job is only to run it and narrate / answer follow-ups. Do NOT read source files yourself to build the inventory — the scanner does that.

The bundled runner `bin/drift-scan` is **self-bootstrapping**: on first use it creates a plugin-local venv and installs the engine (needs `uv` or python≥3.11 + internet, one-time ~a minute); later runs reuse it. It works from **any** directory — you do NOT need to be in the plugin's repo.

**If no folder was given** (the user ran `/drift-detector` with nothing after it, so `$ARGUMENTS` is empty): do **not** scan. Ask them which folder(s) to scan — e.g. *"Which folder(s) should I scan? Give one or more paths, e.g. `~/work` or `~/work ~/personal`."* — and wait for their answer before running. Never scan the current directory or run with an empty root. (`/drift-detector doctor` is the one no-path exception — it runs the health check.)

**Before running, tell the user in one line** that this is a *deterministic local static-analysis scan (AST-level, via Opengrep) that costs no tokens* — so a pause is the scan working, not an expensive agent. Then run it (the `--progress` flag prints an informative per-phase log).

1. **Scan** (deterministic; only repos whose git `HEAD` changed since last time are re-analyzed, via the per-repo commit-SHA cache — so drift runs are fast). `--root` is repeatable — pass one per folder; the first folder holds the shared state/output. Locate the bundled runner, then run it:

   ```bash
   set -- $ARGUMENTS

   # find the bundled self-bootstrapping runner (portable across Claude Code versions)
   SCAN=""
   for c in "${CLAUDE_PLUGIN_ROOT:-}/bin/drift-scan" "${CLAUDE_SKILL_DIR:-}/../bin/drift-scan"; do
     [ -n "$c" ] && [ -x "$c" ] && { SCAN="$c"; break; }
   done
   [ -z "$SCAN" ] && SCAN="$(find "$HOME/.claude/plugins" -type f -name drift-scan -path '*drift-detector*' 2>/dev/null | head -1)"
   [ -z "$SCAN" ] && { echo "drift-detector: runner not found — is the plugin installed?" >&2; exit 4; }

   if [ "$1" = "doctor" ]; then "$SCAN" doctor; exit $?; fi
   if [ "$#" -eq 0 ]; then echo "No folder given. Usage: /drift-detector <folder> [more-folders]  (or: /drift-detector doctor)" >&2; exit 2; fi

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

2. **Point the user at the report — don't paste it.** The scan writes a comprehensive, drift-first Markdown report to `<first-folder>/.drift-detector/INVENTORY.md` (it leads with what changed, then the inventory, then per-repo endpoints at `file:line`). Tell the user the report is ready and give its path, and offer to open it in their Markdown preview (e.g. `code "<path>/INVENTORY.md"` in VS Code, or `xdg-open`/`open`). Do **not** dump the full report into chat.

3. **Give a short chat headline (2–4 lines), not the whole report.** Read `INVENTORY.md`/`DRIFT.md` yourself to write it:
   - If there was a prior scan and things drifted: **lead with the drift** — e.g. "⚠ svc-orders moved SP-API v0→v2; 2 repos added." Flag anything risky by name (retired APIs like Amazon **MWS**; a deprecated version; ancient Node/PHP pins). Then: "full report → `<path>/INVENTORY.md`".
   - If it's the first scan (baseline): one line — e.g. "Baseline: 12 repos · 5 APIs (SP-API×4, Shopify×2, …) · 0 errors" — then point to the report.
   Keep it tight; the report holds the detail.

4. **Follow-ups** — answer questions like *"which repos use Amazon SP-API?"*, *"who drifted onto an old runtime?"*, *"what Stripe versions are in use?"* by reading `inventory.json` (the queryable shape-map). **Do NOT re-scan for a question** — filter the JSON. Only re-scan when the user wants a fresh check or the code changed.

   `inventory.json` shape — per repo: `{path, ref, head_sha, runtimes{name:{range,techKey}}, frameworks{name:{ver}}, sdks[{eco,pkg,ver,file}], endpoints[{vendor,domain,version,techKey,file_count,files:[path:line]}]}`; rollups: `unique_apis`, `unique_api_versions[{vendor,version}]`, `unique_packages`; `coverage`. Query patterns: *"which repos use X"* → the `repos[]` whose `endpoints[].vendor`/`techKey` matches X, list `path` + `files[]` call-sites; *"who's on old version Y / old runtime"* → filter `endpoints[].version`, `sdks[].ver`, or `runtimes[]`.
