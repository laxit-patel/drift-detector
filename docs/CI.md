# Drift Detector in CI (deterministic — no LLM, no tokens)

Move the guarantee off a laptop: run the scan+audit pipeline in CI, on a schedule and on PRs.
The whole job is the deterministic `run` in a container — zero LLM tokens.

## GitHub Actions (recommended)

Add `.github/workflows/drift.yml` to the repo (copy from
[`examples/drift-ci.yml`](../examples/drift-ci.yml)):

```yaml
name: Drift
on:
  schedule: [{ cron: "0 7 * * 0" }]   # weekly
  pull_request:                        # every PR
permissions:
  contents: read
  security-events: write               # to upload SARIF
jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: laxit-patel/drift-detector@v0.2.0-beta
        with:
          fail-on-deprecated: ${{ github.event_name == 'pull_request' }}
          chat-webhook: ${{ secrets.DRIFT_CHAT_WEBHOOK }}   # optional
```

What you get:
- **Security tab** — every scan uploads `findings.sarif`; CVE / EOL / vendor-sunset findings appear
  as code-scanning alerts (sunsets land on the exact `file:line`).
- **PR alerts** — GitHub code-scanning **automatically flags the NEW alerts a PR introduces** and
  annotates the diff. Add a branch-protection rule *"require code scanning results"* to **block merge**.
- **Hard gate** — `fail-on-deprecated: true` also fails the check outright on any un-muted DEPRECATED
  finding. Mute accepted existing debt (`drift-scan mute …`, committed as `.drift-detector/audit-baseline.json`)
  so the gate fires only on *new* deprecations.

Action inputs: `path` (default `.`), `fail-on-deprecated`, `upload-sarif` (default true), `chat-webhook`.
The caller workflow needs `permissions: security-events: write` for the SARIF upload (shown above) —
without it, `upload-sarif` fails with *"Resource not accessible by integration."* The gate exits **3**
on a DEPRECATED finding and **4** if the audit sources were unreachable (couldn't certify clean).

## GitLab CI (or any non-GitHub runner)

No code-scanning integration, but the deterministic gate works anywhere via the exit code:

```yaml
drift:
  image: python:3.12-bookworm
  before_script:
    - curl -LsSf https://astral.sh/uv/install.sh | sh && export PATH="$HOME/.local/bin:$PATH"
    - git clone --depth 1 https://github.com/laxit-patel/drift-detector /tmp/dd
  script:
    - /tmp/dd/bin/drift-scan run --root . --state .drift-detector --now "$(date +%F)" --fail-on-deprecated
  artifacts:
    paths: [.drift-detector/]        # AUDIT.md / bom.json / findings.sarif
```

`--fail-on-deprecated` exits 3 on any un-muted DEPRECATED finding (fails the pipeline);
the reports are kept as artifacts. Combine with a committed baseline to gate only on new drift.
