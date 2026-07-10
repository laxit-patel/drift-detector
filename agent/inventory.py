"""Inventory orchestration: per active repo, parse manifests + detect integrations,
aggregate into inventory.json with explicit coverage records."""
from __future__ import annotations

import json

from agent.lib.extractors import extractor_for
# Import extractors so they self-register:
from agent.lib.extractors import npm, composer, python, runtime_pins  # noqa: F401
from agent.lib.presence import detect_presence
from agent.lib.gitlab_read import GitLabError, GitLabForbidden


def inventory_repo(client, repo_entry: dict, patterns: list) -> dict:
    repo = repo_entry["path_with_namespace"]
    pid = repo_entry["id"]
    ref = repo_entry.get("scanned_ref") or repo_entry.get("default_branch")
    notes = {"unparsed": [], "noManifest": False, "presenceNote": None, "repoError": None}
    try:
        paths = client.get_tree(pid, ref)
    except (GitLabForbidden, GitLabError) as exc:
        notes["repoError"] = str(exc)
        return {"records": [], "usedTechs": [], "notes": notes}

    records: list = []
    matched_any = False
    for path in paths:
        fn = extractor_for(path)
        if not fn:
            continue
        matched_any = True
        content = client.get_raw_file(pid, path, ref)
        if content is None:
            continue
        try:
            records.extend(fn(repo, path, content))
        except ValueError as exc:
            notes["unparsed"].append({"path": path, "reason": str(exc)})

    used, presence_note = detect_presence(client, pid, repo, patterns)
    notes["presenceNote"] = presence_note
    notes["noManifest"] = (not matched_any) and (not used)
    return {"records": records, "usedTechs": used, "notes": notes}


def build_inventory(client, active_repos: dict, patterns: list, now: str) -> dict:
    all_records: list = []
    all_used: list = []
    cov = {"reposScanned": 0, "reposNoManifests": [], "manifestsUnparsed": [],
           "reposErrored": [], "presenceUnavailable": []}
    for entry in active_repos.get("active", []):
        repo = entry["path_with_namespace"]
        cov["reposScanned"] += 1
        res = inventory_repo(client, entry, patterns)
        all_records.extend(r.to_dict() for r in res["records"])
        all_used.extend(u.to_dict() for u in res["usedTechs"])
        n = res["notes"]
        if n["repoError"]:
            cov["reposErrored"].append({"repo": repo, "reason": n["repoError"]})
        if n["noManifest"]:
            cov["reposNoManifests"].append({"repo": repo, "reason": "no manifests detected"})
        for u in n["unparsed"]:
            cov["manifestsUnparsed"].append({"repo": repo, "path": u["path"], "reason": u["reason"]})
        if n["presenceNote"]:
            cov["presenceUnavailable"].append({"repo": repo, "reason": n["presenceNote"]})
    return {"runDate": now, "records": all_records, "usedTechs": all_used, "coverage": cov}


def write_inventory(path: str, inv: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(inv, fh, ensure_ascii=False, indent=2)
