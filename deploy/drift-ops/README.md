# drift-ops — the Drift Detector persistence repo

This is the scaffold for the GitLab repo that **runs** Drift Detector on a schedule and
**stores** its output. In the TOPS setup that repo is `git.topsdemo.in/root/drift-detector`.

It does three jobs at once:

- **config/** — what to scan (`fleet.yaml`).
- **catalog/** — the writable overlay the scanner learns into (see `catalog/README.md`).
- **state/** — the report + finding history, committed back by CI every run (history = git log).

The scan is a pinned, **zero-AI** container. No Python, no engine setup, no AI runs in CI.

## Layout

```
drift-ops/
├── .gitlab-ci.yml        # scheduled: scan → verify → commit state back
├── .gitignore            # keep clones + cache out of git
├── config/fleet.yaml     # the repos to scan
├── catalog/              # the learned overlay (empty until a Learn session absorbs something)
└── state/                # reports + history (written by CI)
```

## One-time setup

1. **Copy these files** into the drift-ops repo (its default branch):
   ```bash
   git clone https://git.topsdemo.in/root/drift-detector.git
   cd drift-detector
   cp -r <this-plugin>/deploy/drift-ops/. .
   git add . && git commit -m "drift-ops scaffold" && git push
   ```

2. **Publish the scan image and pin its digest.** Tag a release of the plugin repo (`git tag
   v0.13.0 && git push --tags`) — the `container` GitHub Action builds and pushes
   `ghcr.io/laxit-patel/drift-detector-scan`. Make that GHCR package **public** (so the
   GitLab runner needs no pull secret). Then replace `REPLACE_WITH_PUBLISHED_IMAGE_DIGEST` in
   `.gitlab-ci.yml` with the published digest (GHCR shows it, or `docker buildx imagetools
   inspect ghcr.io/laxit-patel/drift-detector-scan:v0.13.0`).
   *Self-hosted alternative:* build the image in this repo's CI and push it to this project's
   own container registry, then point `image:` there.

3. **Add the CI variable** (Settings → CI/CD → Variables — **masked**, and **protected** if
   the schedule runs on a protected branch):
   - `GITLAB_TOKEN` — a token that can **clone every scanned repo and file issues** (Reporter
     + `api` scope) **and write to this repo** (to commit state). A Maintainer's PAT on this
     repo with Reporter on the fleet covers all of it.

4. **Edit `config/fleet.yaml`** to list your repos (the TOPS pilot ships with `amazonspapi`
   and `ebayapi`).

5. **Add a schedule** (Settings → CI/CD → Schedules): e.g. `0 7 * * 0` (Sundays 07:00).

6. **Seed it:** run the pipeline once manually (CI/CD → Pipelines → Run pipeline). The first
   run writes `state/` and commits it; every later run shows up as new/resolved since last.

## What each run does

`scan` pulls the pinned image, clones the fleet, produces `state/drift.{json,md}` +
`dashboard.html` + `chart.html`, and `verify`s them (a red pipeline means the scan *couldn't
run* — nothing scanned or a source was unreachable — never merely "findings exist").
`persist` commits `state/` + `catalog/` back with a one-line summary, tagged `[skip ci]` so it
can't trigger itself.

## Not here yet

**Issue delivery** (the two streams → GitLab issues) is the next step. It will add a
`deliver` stage and a `config/delivery.yaml` (where DevOps-stream issues land; developer-stream
issues go to each scanned repo). Until then, the reports are the deliverable — browse
`state/drift.md` in the GitLab UI or download the pipeline artifacts.
