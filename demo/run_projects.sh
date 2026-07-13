#!/usr/bin/env bash
# Scan a local folder of git repos with the agent — no GitLab, no token.
# Usage: bash demo/run_projects.sh /path/to/dir-of-git-repos
# Only immediate subdirs that are git repos (have .git) are scanned.
set -uo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

ROOT="${1:?usage: bash demo/run_projects.sh <dir-of-git-repos>}"
OUT=demo/out; rm -rf "$OUT/kb"; mkdir -p "$OUT/kb"   # fresh KB -> pure real data each run
CFG="$OUT/projects-config.yaml"
cat > "$CFG" <<YAML
kb: { root: $OUT/kb }
source: { type: local, root: $ROOT }
scan: { activeWindowDays: 100000 }          # include repos regardless of last-commit recency
delivery: { reportsProject: demo/reports, reviewHorizonMonths: 6 }
feeds:                                        # real runtime EOL data (needs internet)
  - { techKey: runtime:php,    label: PHP,     category: runtime, adapter: endoflife, url: php,    tier: 1 }
  - { techKey: runtime:node,   label: Node.js, category: runtime, adapter: endoflife, url: nodejs, tier: 1 }
  - { techKey: runtime:python, label: Python,  category: runtime, adapter: endoflife, url: python, tier: 1 }
YAML

NOW=$(date +%F)
echo ">> ingest (real endoflife feeds)";      python -m agent.cli ingest        --config "$CFG" --now "$NOW"                                          || echo "(ingest skipped - offline?)"
echo ">> discover (local git repos)";         python -m agent.cli discover      --config "$CFG" --now "$NOW" --out "$OUT/active-repos.json"
echo ">> inventory (parse manifests on disk)";python -m agent.cli inventory     --config "$CFG" --active "$OUT/active-repos.json" --out "$OUT/inventory.json" --patterns agent/patterns.yaml --now "$NOW"
echo ">> registry-scan (npm/packagist/pypi)"; python -m agent.cli registry-scan --config "$CFG" --inventory "$OUT/inventory.json" --now "$NOW"       || echo "(registry-scan skipped - offline?)"
echo ">> classify-report";                    python -m agent.cli classify-report --config "$CFG" --inventory "$OUT/inventory.json" --active "$OUT/active-repos.json" \
  --prev - --out-report "$OUT/report.md" --out-findings "$OUT/findings.json" --now "$NOW"

echo; echo "==================== REPORT ===================="; cat "$OUT/report.md"
python - "$OUT" <<'PY'
import json, sys
out = sys.argv[1]
act = json.load(open(f"{out}/active-repos.json"))
inv = json.load(open(f"{out}/inventory.json"))
print(f"\nScanned {len(act['active'])} git repos | {len(inv['records'])} dep/runtime records | "
      f"{len(inv['usedTechs'])} integration hits")
print(f"Excluded: {len(act.get('excluded', []))} (non-git dirs / no commits)")
runtimes = sorted({f"{r['tech_key']} {r.get('version_hint') or r.get('declared_range','')}".strip()
                   for r in inv['records'] if r.get('kind') == 'runtime'})
print("\nRuntimes your repos pin (for context — old ones would flag as EOL):")
for rt in runtimes:
    print(f"  - {rt}")
print(f"\nFiles: {out}/report.md, {out}/inventory.json, {out}/findings.json")
PY
