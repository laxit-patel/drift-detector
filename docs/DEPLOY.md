# Deploying the Change Monitor (Docker + GitHub Actions, no server)

The monitor runs as an **ephemeral container on a schedule** — there is no
always-on server to maintain. GitHub Actions spins up a runner weekly, pulls the
image from GHCR, runs it, commits the new state back to a git branch, and exits.
State lives in git; the compute is throwaway.

```
  build-image.yml   code changes on master ──► build ──► ghcr.io/<you>/<repo>:latest
  monitor.yml       weekly cron / "Run now" ──► pull image ──► run ──► commit state ──► exit
                                                   ▲                        │
                                                   └── monitor-state branch ┘  (kb + findings + reports)
```

## What runs, and where the state is

| Piece | Where | Notes |
|---|---|---|
| Compute | Ephemeral Actions runner | ~2 min/week, then destroyed. Not your machine. |
| Image | GHCR (`ghcr.io/<you>/<repo>`) | Rebuilt only when `agent/**`, `Dockerfile`, etc. change. |
| State | `monitor-state` branch | `kb/` (change history), `findings.json` (delta baseline), `reports/report-*.md` (archive). |
| Schedule | `.github/workflows/monitor.yml` cron | Edit the `cron:` line to change cadence. |

The `monitor-state` branch is created automatically on the first run. Browse it
to read every past report; each week's `findings.json` is the baseline the next
run diffs against for NEW / RESOLVED / ONGOING.

## Hand-off: run it in *your own* GitHub (3 steps)

Anyone can adopt this without touching code. Settings live in three tiers —
**secrets** (env, never committed), **config** (a file in your fork), **code**
(the shared image). To stand up your own copy:

1. **Copy the repo** — click **Use this template** → *Create a new repository*
   (or fork it) into your account. `build-image.yml` builds the image into
   *your* `ghcr.io/<you>/<repo>` on the first push.
2. **Add one secret** — your repo → **Settings → Secrets and variables →
   Actions → New repository secret** → **`GH_SCAN_TOKEN`** = a GitHub PAT with
   read access to the repos you want scanned. (Optional: `GCHAT_WEBHOOK_URL`,
   `HEALTHCHECK_URL`, `ANTHROPIC_API_KEY`.) **The token lives only here — never
   in a file.**
3. **Run it** — Actions → **monitor** → **Run workflow**. That's it: the owner
   defaults to *your* account automatically, so it scans your own repos with no
   config editing. The run creates the `monitor-state` branch; the weekly cron
   takes over after.

To customize *what* it watches (feeds, scan window, a different owner), edit
[`deploy/config.yaml`](../deploy/config.yaml) in your fork — it's **mounted at
run time, not baked into the image**, so a config edit takes effect on the next
run with **no rebuild**. The `owner:` placeholder is overridden in CI by the
`MONITOR_OWNER` env (set to your fork's account); set it explicitly in the file
only if the token belongs to a *different* account (e.g. scanning an org).

## One-time setup (reference)

### 1. Secrets  (repo → Settings → Secrets and variables → Actions)

| Secret | Required | Purpose |
|---|---|---|
| `GH_SCAN_TOKEN` | **yes** | PAT with **read** access to the repos you scan. The built-in `GITHUB_TOKEN` only sees *this* repo, so a PAT is required to list your repos via `/user/repos`. Fine-grained token: *Contents: Read-only* across the repos; or a classic token with `repo` (read). |
| `GCHAT_WEBHOOK_URL` | no | Google Chat space incoming-webhook URL. Omit → report is written to the branch but not posted to Chat. |
| `HEALTHCHECK_URL` | no | Dead-man's-switch ping URL (e.g. healthchecks.io). Pinged only on a **fully successful** run — see "Why the dead-man's switch" below. |
| `ANTHROPIC_API_KEY` | no | Only needed once the live Claude classify stage is wired (marketplace contract-drift). Deterministic runs (EOL / deprecation / version drift) don't need it. |

`secrets.GITHUB_TOKEN` (built-in, no setup) is used to pull the image and push
the state branch — don't confuse it with `GH_SCAN_TOKEN`.

### 2. Point it at your repos
The owner defaults to your fork's account (via `MONITOR_OWNER`), so the common
case needs no edit. To change *what* is watched, edit
[`deploy/config.yaml`](../deploy/config.yaml) — `scan.activeWindowDays`, the
`feeds` list, or an explicit `source.owner` — and commit. The file is mounted at
run time, so the change applies on the next run **without an image rebuild**.

### 3. First run
Actions tab → **monitor** → **Run workflow** (the manual button). This also
creates the `monitor-state` branch. After it's green, the weekly cron takes over.

## Triggering it

- **Automatic:** every Sunday 07:00 UTC (the `cron` in `monitor.yml`).
- **Manual ("run now"):** Actions → monitor → *Run workflow*. Optionally set a
  `run_date` to reproduce a specific date. Manual and scheduled use the identical
  path — the cron is just the clock pressing the same button.

## Run it locally (dev / demo, identical to CI)

```bash
docker build -t change-monitor .
mkdir -p _state
docker run --rm \
  -e RUN_DATE="$(date -u +%F)" \
  -e MONITOR_OWNER="your-github-username" \
  -e GITHUB_TOKEN="$(gh auth token)" \
  -e GCHAT_WEBHOOK_URL="$GCHAT_WEBHOOK_URL" \
  -v "$PWD/_state:/work/state" \
  change-monitor
# report lands in _state/reports/, baseline in _state/findings.json
```

## Why the dead-man's switch (don't skip it)

A GitHub/GitLab **scheduled pipeline can stop silently** — schedule disabled,
quota hit, repo archived — and you'd get *no alert*, because the thing that
sends alerts is the job that didn't run. `HEALTHCHECK_URL` closes that blind
spot: the run pings an **external** service on success; if that service doesn't
hear a weekly ping, *it* alerts you. CI + external ping = safe. CI alone = blind.

## Known limits (beta)

- **Deterministic slice only** until the live Claude classify stage is wired
  (needs `ANTHROPIC_API_KEY` + pinned model + `agent/classify.schema.json`). You
  get runtime EOL, deprecated/abandoned packages, and version drift today;
  marketplace contract-drift (SP-API / Shopify / Stripe changelog semantics) is
  the wiring follow-up.
- **Owner = a user**, not an org you don't own (`/user/repos?affiliation=owner`).
- **GitHub code search** (integration presence) is rate-limited/index-dependent,
  so presence detection under-counts vs a local clone.

## Moving to GitLab CI later

The image is portable. A `.gitlab-ci.yml` with a `schedule` that does
`docker pull` → `docker run` (state via a committed branch, same as here) is a
drop-in swap — nothing in the container changes. Keep the external dead-man's
switch either way.
