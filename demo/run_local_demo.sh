#!/usr/bin/env bash
# Offline demo against a LOCAL folder of git repos — no GitLab, no token.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
R=demo/out/repos
rm -rf "$R"; mkdir -p "$R"
for name in acme-shop biz-portal; do
  mkdir -p "$R/$name"; ( cd "$R/$name" && git init -q && git config user.email d@d && git config user.name d )
done
printf 'FROM php:8.0-alpine\n' > "$R/acme-shop/Dockerfile"
printf '{"dependencies":{"stripe":"12.0.0","request":"^2.88"}}\n' > "$R/acme-shop/package.json"
printf 'use "sellingpartnerapi" client for amazon\n' > "$R/acme-shop/src.php"
printf 'FROM node:16-alpine\n' > "$R/biz-portal/Dockerfile"
( cd "$R/acme-shop" && git add -A && git commit -qm init )
( cd "$R/biz-portal" && git add -A && git commit -qm init )

CFG=demo/demo-config-local.yaml; NOW=$(date +%F); mkdir -p demo/out
python -m agent.cli ingest        --config "$CFG" --now "$NOW" || echo "(ingest needs internet; skipping is fine offline)"
python -m agent.cli discover      --config "$CFG" --now "$NOW" --out demo/out/active-repos.json
python -m agent.cli inventory     --config "$CFG" --active demo/out/active-repos.json --out demo/out/inventory.json --patterns agent/patterns.yaml --now "$NOW"
python -m agent.cli registry-scan --config "$CFG" --inventory demo/out/inventory.json --now "$NOW" || echo "(registry-scan needs internet; skipping)"
python -m agent.cli classify-report --config "$CFG" --inventory demo/out/inventory.json --active demo/out/active-repos.json \
  --prev - --out-report demo/out/report.md --out-findings demo/out/findings.json --now "$NOW"
echo "==== report ===="; cat demo/out/report.md
