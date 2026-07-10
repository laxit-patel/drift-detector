"""Discovery: turn the GitLab project list into the definitive active-repo scan set."""
from __future__ import annotations

import json
from datetime import date, timedelta

from agent.lib.gitlab_read import GitLabForbidden


def since_iso(now: str, window_days: int) -> str:
    d = date.fromisoformat(now) - timedelta(days=window_days)
    return d.isoformat()


def _top_namespace(path: str) -> str:
    return path.split("/", 1)[0]


def discover(config, client, now: str) -> dict:
    scan = config.scan
    since = since_iso(now, scan.active_window_days)
    allow = set(scan.allow)
    deny = set(scan.deny)
    always = set(scan.always_include)

    candidates = client.list_candidate_projects(since)
    active: list[dict] = []
    excluded: list[dict] = []
    namespaces: set[str] = set()

    for p in candidates:
        path = p["path_with_namespace"]
        namespaces.add(_top_namespace(path))
        if path in deny:
            excluded.append({"repo": path, "reason": "deny"})
            continue
        if allow and path not in allow and path not in always:
            excluded.append({"repo": path, "reason": "not_in_allow"})
            continue
        ref = scan.branch_overrides.get(path) or p.get("default_branch")
        try:
            committed = client.has_commit_since(p["id"], since, ref=ref)
        except GitLabForbidden:
            excluded.append({"repo": path, "reason": "forbidden"})
            continue
        if committed:
            reason = "active"
        elif path in always:
            reason = "always_include"
        else:
            excluded.append({"repo": path, "reason": "no_recent_commit"})
            continue
        active.append({
            "id": p["id"], "path_with_namespace": path,
            "default_branch": p.get("default_branch"), "scanned_ref": ref,
            "last_commit_date": committed, "reason": reason,
        })

    if scan.max_repos and len(active) > scan.max_repos:
        for r in active[scan.max_repos:]:
            excluded.append({"repo": r["path_with_namespace"], "reason": "max_repos_cap"})
        active = active[:scan.max_repos]

    return {
        "runDate": now,
        "scanWindowDays": scan.active_window_days,
        "namespacesCovered": sorted(namespaces),
        "active": active,
        "excluded": excluded,
    }


def write_active_repos(path: str, result: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
