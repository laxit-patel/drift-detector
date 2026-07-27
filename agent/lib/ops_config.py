"""Load the operational config — the ONE reviewed settings file (`drift.yml`), which lives in
the private drift-ops repo, not the public plugin.

Everything a deployment needs in one place: the fleet to scan (an array of repo/group URLs),
and how to deliver. The GitLab host is DERIVED from the fleet URLs (a single https host,
validated), so it can never drift from what is actually scanned. Secrets NEVER live here —
the token stays env-only. Pure function of the file bytes: same file → same config.

    version: 1
    fleet:
      - https://git.example.com/group/repo-a
      - https://git.example.com/group/repo-b       # all must share one https host
    delivery:
      mode: dry-run                 # dry-run | live | off
      dev_as_issues: true
      devops_project: group/ops     # where DevOps issues are filed
"""
from __future__ import annotations

import re

import yaml

_MODES = {"dry-run", "live", "off"}
_TOP = {"version", "fleet", "delivery"}
_DELIVERY = {"mode", "dev_as_issues", "devops_project"}


class ConfigError(ValueError):
    """The config is malformed — raised, never guessed-around."""


def _host_of(url: str) -> str | None:
    m = re.match(r"^https://([^/]+)/", str(url or ""))
    return m.group(1) if m else None


def load(path: str) -> dict:
    """Parse + validate drift.yml. Returns {fleet, host, delivery:{mode,dev_as_issues,
    devops_project}}. Raises ConfigError on anything malformed — an unknown key is an error,
    not ignored, so a typo can't silently disable delivery or drop a repo."""
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a YAML mapping at the top level")
    unknown = set(raw) - _TOP
    if unknown:
        raise ConfigError(f"{path}: unknown key(s) {sorted(unknown)} (allowed: {sorted(_TOP)})")

    fleet = raw.get("fleet")
    if not isinstance(fleet, list) or not fleet:
        raise ConfigError(f"{path}: `fleet` must be a non-empty list of https repo/group URLs")
    hosts = set()
    for u in fleet:
        if not str(u).startswith("https://"):
            raise ConfigError(f"{path}: fleet entry {u!r} must be an https:// URL")
        h = _host_of(u)
        if not h:
            raise ConfigError(f"{path}: cannot parse a host from {u!r}")
        hosts.add(h)
    if len(hosts) != 1:
        raise ConfigError(f"{path}: all fleet URLs must share one host, got {sorted(hosts)}")

    d = raw.get("delivery") or {}
    if not isinstance(d, dict):
        raise ConfigError(f"{path}: `delivery` must be a mapping")
    unknown_d = set(d) - _DELIVERY
    if unknown_d:
        raise ConfigError(f"{path}: unknown delivery key(s) {sorted(unknown_d)}")
    mode = d.get("mode", "dry-run")
    if mode is False:                    # YAML 1.1 parses an unquoted `off` as the bool False
        mode = "off"
    if mode not in _MODES:
        raise ConfigError(f"{path}: delivery.mode must be one of {sorted(_MODES)}, got {mode!r}")

    return {
        "fleet": [str(u) for u in fleet],
        "host": hosts.pop(),
        "delivery": {
            "mode": mode,
            "dev_as_issues": bool(d.get("dev_as_issues", False)),
            "devops_project": d.get("devops_project"),
        },
    }
