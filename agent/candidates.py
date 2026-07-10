# agent/candidates.py
"""Join the inventory (what each repo uses) with the KB (what changed / lifecycle) into
candidate findings. Selects the CURRENT applicable risk surface each run (NO consuming
watermark) so the delta engine decides NEW/ONGOING/RESOLVED week-over-week. Lifecycle (eol)
entries are version-matched to the cycle in use to avoid cross-cycle noise."""
from __future__ import annotations

import re

from agent.lib import kb_store

_CYCLE = re.compile(r"cycle\s+(\S+)")


def techkeys_in_use(inventory: dict) -> dict:
    out: dict = {}
    for r in inventory.get("records", []):
        version = r.get("declared_range") or r.get("version_hint") or ""
        out.setdefault(r["tech_key"], []).append({
            "repo": r["repo"], "versionInUse": version,
            "category": "runtime" if r.get("kind") == "runtime" else "library",
        })
    for u in inventory.get("usedTechs", []):
        out.setdefault(u["tech_key"], []).append({
            "repo": u["repo"], "versionInUse": "", "category": "integration",
        })
    return out


def _cycle_of(ce: dict) -> str:
    m = _CYCLE.search(ce.get("affectedArea", "") or "")
    return m.group(1) if m else ""


def _applies(ce: dict, version_in_use: str) -> bool:
    """Lifecycle (eol) entries apply only to the cycle in use; other entries apply to the tech."""
    if ce.get("changeType") != "eol":
        return True
    cycle = _cycle_of(ce)
    if not cycle or not version_in_use:
        return True                      # can't determine -> include (never silently drop a risk)
    normalized = version_in_use.strip().lstrip("^~>=< v")
    return normalized.startswith(cycle) or cycle in version_in_use


def build_candidates(inventory: dict, kb_root: str, *, repo_ids: dict) -> list:
    used = techkeys_in_use(inventory)
    candidates: list = []
    for tech_key, usages in used.items():
        for ce in kb_store.load_entries(kb_root, tech_key):
            ced = ce.to_dict()
            for u in usages:
                if _applies(ced, u["versionInUse"]):
                    candidates.append({
                        "repo": u["repo"],
                        "projectId": repo_ids.get(u["repo"], 0),
                        "techKey": tech_key,
                        "category": u["category"],
                        "versionInUse": u["versionInUse"],
                        "changeEntry": ced,
                    })
    return candidates
