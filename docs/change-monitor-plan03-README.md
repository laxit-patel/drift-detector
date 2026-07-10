# Change Monitor — Plan 03 (Inventory)

Turns active-repos.json into inventory.json: manifest/runtime records + integration presence.

## Run
```bash
source .venv/bin/activate
export GITLAB_READ_TOKEN=<read_api token>
python -m agent.cli discover  --config config.yaml --now 2026-07-12 --out active-repos.json
python -m agent.cli inventory --config config.yaml --active active-repos.json --out inventory.json --now 2026-07-12
```
v1 is manifest-only (declared ranges, `parse_quality="unlocked"` for ranges); lockfile-exact
versions are a Plan-04+ enhancement. Extractors: npm/composer/python/Docker+pin-files. Integration
presence uses GitLab blob search; if search is disabled on the instance, affected repos are recorded
under `coverage.presenceUnavailable` (never silently "no integrations"). Repos with no manifests /
unparseable manifests / GitLab errors land in explicit `coverage.*` records.

## Next
- Plan 04: Claude classify (severity + used-tech match) + trust gate, delta, report, Chat, run.sh,
  dead-man's switch; plus the `registry` feed adapter fed by these `lib:*` techKeys.
