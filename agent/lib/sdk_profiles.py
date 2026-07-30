"""SDK profiles — turn a wrapper's OWN pinned version(s) into synthetic endpoints so the normal
endpoint→sunset→verify→dashboard pipeline handles them.

The `sdk-only-no-callsite` wrappers assemble their URLs from class constants / config, so there
is no URL literal to classify and no versioned path to attribute — the scanner reads the egress
sink but nothing else. Their vendor + version ARE in the source, just as a constant
(`$apiVersion = '2023-04'`). This reads those (from agent/sdk_profiles.yaml, reviewed data) and
emits a synthetic endpoint per pinned version, attributed `sdk-profile`, evidenced at the const's
file:line. Deterministic and pure: it invents nothing — the version is a literal someone opened,
the date comes from the vendor's lifecycle/sunset catalog downstream.
"""
from __future__ import annotations

import os

import yaml

from agent.lib import scope_edges

_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "sdk_profiles.yaml")


class ProfileError(ValueError):
    """A malformed profile. Loud, never silently dropped — a dropped profile is a silent gap."""


def load(path: str | None = None) -> list:
    with open(path or _DEFAULT, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    if not isinstance(raw, list):
        raise ProfileError("sdk_profiles must be a YAML list")
    for i, p in enumerate(raw):
        where = f"sdk_profile #{i} ({p.get('repo') if isinstance(p, dict) else p!r})"
        if not isinstance(p, dict):
            raise ProfileError(f"{where}: not a mapping")
        for req in ("repo", "vendor", "versions", "source"):
            if not p.get(req):
                raise ProfileError(f"{where}: missing required `{req}`")
        for v in p["versions"]:
            if not isinstance(v, dict) or not v.get("version") or not v.get("evidence"):
                raise ProfileError(f"{where}: each version needs `version` AND `evidence` "
                                   "(a file:line you opened) — a profile is a read fact, not a guess")
    return raw


def _matches(repo_record: dict, profile_repo: str) -> bool:
    """Does this scanned repo IS the profiled dependency? Match host-independently on the git
    identity's path suffix (a fleet clone's remote_url carries the real project path), with the
    clone-folder name as a fallback for a locally-scanned checkout."""
    iden = scope_edges.identity(repo_record.get("remote_url") or "")
    if iden and (iden == profile_repo or iden.endswith("/" + profile_repo)):
        return True
    path = str(repo_record.get("path") or "")
    return path == profile_repo or path.endswith(profile_repo.replace("/", "-"))


def endpoints_for(repo_record: dict, profiles: list) -> list:
    """Synthetic endpoints (one per pinned version) for a repo that matches a profile. Shaped
    exactly like a scanned endpoint so the audit's lifecycle/sunset join dates them, but marked
    `attribution: sdk-profile` and evidenced at the const line — no fabricated call-site."""
    out = []
    for p in profiles:
        if not _matches(repo_record, p["repo"]):
            continue
        for v in p["versions"]:
            out.append({
                "vendor": p["vendor"], "domain": f"sdk:{p['repo']}", "version": v["version"],
                "techKey": None, "operation": None, "apiPath": "",
                "attribution": "sdk-profile",
                "example": f"{p['repo']} pins {p['vendor']} {v['version']} ({p['source']})",
                "file_count": 1, "files": [v["evidence"]], "classified": True,
            })
    return out
