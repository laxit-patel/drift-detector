"""Scope each contract change to the repos whose inventory shows they use the affected
marketplace API, so a break can be turned into a per-repo Finding."""
from __future__ import annotations

# ContractChange["marketplace"] -> the inventory/patterns techKey (extensible).
_MARKETPLACE_TECHKEY = {
    "sp-api": "api:amazon-sp-api",
    "shopify": "api:shopify",
    "walmart": "api:walmart-marketplace",
    "ebay": "api:ebay",
}


def _repos_using(inventory: dict, tech_key: str) -> list:
    return sorted({u["repo"] for u in inventory.get("usedTechs", [])
                   if u.get("tech_key") == tech_key})


def scope_changes(changes: list, inventory: dict) -> list:
    out: list = []
    for c in changes:
        tech_key = _MARKETPLACE_TECHKEY.get(c.get("marketplace"), "")
        repos = _repos_using(inventory, tech_key) if tech_key else []
        if repos:
            for repo in repos:
                out.append({**c, "techKey": tech_key, "repo": repo, "used": True})
        else:
            out.append({**c, "techKey": tech_key, "repo": "", "used": False})
    return out
