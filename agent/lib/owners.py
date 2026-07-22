"""Route a finding or an action to the team that fixes it — the two delivery streams.

Decided with DevOps at the launch meeting:
  - **DevOps** owns the platform: package vulnerabilities (a manifest/lockfile bump) and
    **runtime** end-of-life (a base-image / language upgrade).
  - **Developers** own the application: vendor API sunsets (integration code) and
    **framework** end-of-life — a Laravel 8→11 or Django LTS jump is app-code migration,
    not an infra bump, so it lands on the team that owns the code.

A PURE function of the record's own fields (`kind`, and for an eol its `refKind`), so
verify can recompute it and fail if the stored `owner` ever disagrees with drift.json —
the same "one payload, verified projections" guarantee every other derived field gets.
"""
from __future__ import annotations

DEVOPS = "devops"
DEVELOPER = "developer"
OWNERS = (DEVOPS, DEVELOPER)


def owner(record: dict) -> str:
    """'devops' | 'developer' for a finding or an action. Total and deterministic."""
    kind = record.get("kind")
    if kind == "cve":
        return DEVOPS
    if kind == "eol":
        # runtimes (php, node, python) are DevOps; frameworks (laravel, django) are the
        # developers' app-code migration. refKind is stamped on every eol record; a
        # missing one defaults to the developer (app) queue rather than silently routing
        # a runtime to DevOps.
        return DEVOPS if record.get("refKind") == "runtime" else DEVELOPER
    # sunset (and any future integration kind) is developer work
    return DEVELOPER
