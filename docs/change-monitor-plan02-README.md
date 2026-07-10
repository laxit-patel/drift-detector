# Change Monitor — Plan 02 (GitLab Read Client + Discovery)

Read-only GitLab access + active-repo discovery.

## Run
```bash
source .venv/bin/activate
export GITLAB_READ_TOKEN=<read_api token>
python -m agent.cli discover --config config.yaml --now 2026-07-12 --out active-repos.json
```
Add a `gitlab:` section (baseUrl, tokenEnv, expectedNamespaces) and a `scan:` section
(activeWindowDays, allow/deny/alwaysInclude, branchOverrides, maxRepos) to `config.yaml`.
"active" = a real commit in the window (verified via `commits?all=true`). GitLab-unreachable/401
aborts; a single repo's 403 becomes a coverage-gap. A missing expected namespace prints a WARNING.

## Next
- Plan 03: inventory (manifest/runtime extractors + integration-presence) → inventory.json.
- Plan 04: Claude classify + trust gate, delta, report, Chat, run.sh, dead-man's switch.
