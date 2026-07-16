"""Roll findings up into ACTIONS and rank them.

A finding is an advisory. An action is a job: "in this repo, upgrade this one thing." The
30 CVEs against torch 1.1.0 are not 30 jobs — they are one `pip install 'torch>=2.8.0'`.
Measured on a real 60-repo run: 320 findings -> 90 actions, 50 of them action-required.

Pure and deterministic: same input -> identical output, including order.
"""
from __future__ import annotations

from collections import OrderedDict

from agent.lib.ranking import severity_rank, semver_key

_MAX_FILES = 6

# Only `cve` actions get a command: an EOL means upgrading a language runtime or framework
# major, and a SUNSET means migrating to a different vendor API. Neither is a one-liner.
_COMMANDS = {
    "npm": lambda pkg, ver: f"npm install {pkg}@^{ver}",
    "composer": lambda pkg, ver: f"composer require {pkg}:^{ver}",
    "python": lambda pkg, ver: f"pip install '{pkg}>={ver}'",
}


def _split_ref(ref):
    """'composer/aws/aws-sdk-php' -> ('composer', 'aws/aws-sdk-php'). A ref with no '/' —
    every sunset finding, whose ref is a bare vendor name like 'eBay' — -> (None, ref)."""
    ref = str(ref or "")
    if "/" not in ref:
        return None, ref
    eco, pkg = ref.split("/", 1)
    return eco, pkg


def _command(kind, eco, pkg, fix_version):
    if kind != "cve" or not fix_version or eco not in _COMMANDS:
        return None
    return _COMMANDS[eco](pkg, fix_version)


def _rank_key(action):
    """Total order: action-required first, then worst severity, then blast radius, then a
    stable alphabetical tie-break so output is byte-identical across runs."""
    return (
        0 if action["status"] == "DEPRECATED" else 1,
        -severity_rank(action["worst"], action["status"]),
        -action["finding_count"],
        action["repo"],
        action["ref"],
    )


def build_actions(findings: list) -> list:
    """Group findings by (repo, ref) and rank them. Returns a list of action dicts."""
    groups: "OrderedDict[tuple, list]" = OrderedDict()
    for f in findings:
        groups.setdefault((f["repo"], f["ref"]), []).append(f)

    actions = []
    for (repo, ref), group in groups.items():
        # the worst finding drives severity AND supplies the prose fallback
        worst_f = max(group, key=lambda f: severity_rank(f.get("severity"), f.get("status")))
        status = "DEPRECATED" if any(f.get("status") == "DEPRECATED" for f in group) else "REVIEW"
        kind = worst_f.get("kind") if len({f.get("kind") for f in group}) == 1 else "cve"

        fixed = [f["fixed"] for f in group if f.get("fixed")]
        fix_version = max(fixed, key=semver_key) if fixed else None

        eco, pkg = _split_ref(ref)
        actions.append({
            "repo": repo,
            "ref": ref,
            "eco": eco,
            "pkg": pkg,
            "kind": kind,
            "current_version": worst_f.get("version"),
            "fix_version": fix_version,
            "command": _command(kind, eco, pkg, fix_version),
            "recommendation": worst_f.get("recommendation"),
            "worst": worst_f.get("severity"),
            "status": status,
            "finding_count": len(group),
            "critical_count": sum(1 for f in group if str(f.get("severity", "")).upper() == "CRITICAL"),
            "first_seen": min((f["first_seen"] for f in group if f.get("first_seen")), default=None),
            "files": list(OrderedDict.fromkeys(
                p for f in group for p in (f.get("files") or [])))[:_MAX_FILES],
            "fixes": group,
            "sources": [u for u in OrderedDict.fromkeys(
                f.get("source_url") for f in group) if u],
        })

    actions.sort(key=_rank_key)
    return actions
