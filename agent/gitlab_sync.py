"""Materialize a GitLab fleet into a local folder (clone/pull), then it's scanned like any folder.

Secret-safe: the token is injected into the clone URL transiently and then STRIPPED from the
repo's stored `.git/config` (remote set-url back to the plain URL), so it never persists on disk.
Best-effort per repo — one clone failure doesn't abort the sync.
"""
from __future__ import annotations

import os
import subprocess
from datetime import date

from agent.lib import gitlab


def _default_git(args, cwd=None) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=600, check=True)


def _auth_url(url: str, token: str) -> str:
    return url.replace("https://", f"https://oauth2:{token}@", 1)


def _clone_or_pull(url: str, token: str, dest: str, git) -> None:
    auth = _auth_url(url, token)
    if os.path.isdir(os.path.join(dest, ".git")):
        git(["-C", dest, "remote", "set-url", "origin", auth])
        try:
            git(["-C", dest, "fetch", "--depth", "1", "origin"])
            git(["-C", dest, "reset", "--hard", "origin/HEAD"])
        finally:
            git(["-C", dest, "remote", "set-url", "origin", url])   # strip token, even on failure
    else:
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        git(["clone", "--depth", "1", auth, dest])
        git(["-C", dest, "remote", "set-url", "origin", url])       # strip token from .git/config


def _recent(last_activity: str, now: str, days: int) -> bool:
    try:
        la = date.fromisoformat((last_activity or "")[:10])
        return (date.fromisoformat(now) - la).days <= days
    except ValueError:
        return True                     # unknown activity -> keep (never silently drop)


def sync(base_url: str, token: str, dest: str, *, group=None, active_days=None, now=None,
         git=_default_git, get=gitlab._default_get) -> dict:
    projects = gitlab.list_projects(base_url, token, group=group, get=get)
    if active_days and now:
        projects = [p for p in projects if _recent(p.get("last_activity_at"), now, active_days)]
    synced, failed = [], []
    for p in projects:
        d = os.path.join(dest, p["path"])
        try:
            _clone_or_pull(p["url"], token, d, git)
            synced.append(p["path"])
        except Exception as exc:
            failed.append({"repo": p["path"], "reason": str(exc)})
    return {"dest": dest, "total": len(projects), "synced": synced, "failed": failed}
