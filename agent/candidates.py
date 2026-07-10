"""Join the inventory (what each repo uses) with KB drift (what changed) into candidate findings."""
from __future__ import annotations

from agent.drift import drift_for_tech


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


def build_candidates(inventory: dict, kb_root: str, reported_watermarks: dict, *, repo_ids: dict) -> list:
    used = techkeys_in_use(inventory)
    candidates: list = []
    for tech_key, usages in used.items():
        entries = drift_for_tech(kb_root, tech_key, reported_watermarks.get(tech_key))
        for ce in entries:
            for u in usages:
                candidates.append({
                    "repo": u["repo"],
                    "projectId": repo_ids.get(u["repo"], 0),
                    "techKey": tech_key,
                    "category": u["category"],
                    "versionInUse": u["versionInUse"],
                    "changeEntry": ce.to_dict(),
                })
    return candidates
