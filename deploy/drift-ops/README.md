# drift-ops — the Drift Detector persistence repo

This is the scaffold for the GitLab repo that **runs** Drift Detector on a schedule and
**stores** its output. In the TOPS setup that repo is `git.topsdemo.in/root/drift-detector`.

It does three jobs at once:

- **config/** — what to scan (`fleet.yaml`).
- **catalog/** — the writable overlay the scanner learns into (see `catalog/README.md`).
- **state/** — the report + finding history, committed back by CI every run (history = git log).
- **scanner/** — the bundled `agent/` package (the deterministic, **zero-AI** scanner).

The pipeline is **container-free**: it runs on the stock public `python:3.12-slim` image and
fetches the pinned scan engine at run time, so it needs **no container registry** (your GitLab
doesn't have one). No AI runs in CI.

## One-time setup

1. **Copy these files into the drift-ops repo**, then **bundle the scanner** into `scanner/`:
   ```bash
   git clone https://git.topsdemo.in/root/drift-detector.git
   cd drift-detector
   cp -r <this-plugin>/deploy/drift-ops/. .
   cp -r <this-plugin>/agent scanner/agent          # the scanner (bundled, ~1.4M)
   cp <this-plugin>/requirements-plugin.txt scanner/
   git add . && git commit -m "drift-ops scaffold + scanner" && git push
   ```
   *Updating the scanner later* (e.g. when issue delivery lands): re-copy `agent/` into
   `scanner/agent/` and push. The engine version is pinned in `.gitlab-ci.yml`.

2. **Add the CI variable** (Settings → CI/CD → Variables — **masked**):
   - `GITLAB_TOKEN` — a token that can **clone every scanned repo and file issues** (Reporter
     + `api` scope) **and write to this repo** (to commit state). A Maintainer's PAT on this
     repo with Reporter on the fleet covers all of it.

3. **Edit `config/fleet.yaml`** to list your repos (the pilot ships with `amazonspapi` +
   `ebayapi`).

4. **Add a schedule** (Settings → CI/CD → Schedules): e.g. `0 7 * * 0` (Sundays 07:00).

5. **Seed it:** run the pipeline once manually (Build → Pipelines → Run pipeline). The first
   run writes `state/` and commits it; every later run shows new/resolved since last.

## What each run does

`scan` (on `python:3.12-slim`) installs git + PyYAML, fetches the **pinned, sha256-verified**
ast-grep engine, then runs the bundled scanner over the fleet — producing
`state/drift.{json,md}` + `dashboard.html` + `chart.html` — and `verify`s them. A red pipeline
means the scan *couldn't run* (nothing scanned, or a source unreachable), never merely
"findings exist". `persist` commits `state/` + `catalog/` back with a one-line summary, tagged
`[skip ci]` so it can't trigger itself.

*Runner requirements:* egress to Docker Hub (the python image), PyPI (PyYAML), and GitHub
releases (the engine), plus your GitLab (clone the fleet + push state). x86-64 runner.

## If you later add a container registry

The plugin ships a `Dockerfile` that bakes everything into one image. If your GitLab gains a
container registry (or you use GHCR), build+push it and set `image:` in `.gitlab-ci.yml` to
the digest-pinned image, then drop the `before_script` engine-fetch and the `scanner/` bundle.
See the plugin's `docs/CONTAINER.md`.

## Not here yet

**Issue delivery** (the two streams → GitLab issues) is the next step: a `deliver` stage +
`config/delivery.yaml`. Until then the reports are the deliverable — browse `state/drift.md`
in the GitLab UI or download the pipeline artifacts.
