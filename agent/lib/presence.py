"""Integration-presence detection via GitLab blob search. Presence-level only:
'this repo uses SP-API', not which endpoint."""
from __future__ import annotations

import yaml

from agent.lib.inventory_models import UsedTech
from agent.lib.gitlab_read import GitLabError


def load_patterns(path: str) -> list:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def detect_presence(client, project_id: int, repo: str, patterns: list):
    used: list = []
    seen: set = set()
    for pat in patterns:
        tk = pat["techKey"]
        if tk in seen:
            continue
        try:
            hits = client.search_blobs(project_id, pat["query"])
        except GitLabError as exc:
            return [], f"blob search unavailable: {exc}"
        if hits:
            path = hits[0].get("path", "?")
            used.append(UsedTech(repo=repo, tech_key=tk, evidence=f"{path}: {pat['query']}"))
            seen.add(tk)
    return used, None
