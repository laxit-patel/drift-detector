"""Git metadata + engine resolution for the inventory scanner. Git is injected for tests."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys


def _default_git(args: list) -> str:  # pragma: no cover - real git subprocess
    proc = subprocess.run(["git"] + args, capture_output=True, text=True, timeout=30)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def normalize_remote(raw) -> str | None:
    """Normalize a git remote to a clean `https://host/owner/repo`, or None.

    STRIPS any embedded credentials (`https://user:token@host/…`) — the credential-leak guard:
    a token must never reach the shared dashboard. Returns None for anything it can't parse to a
    clean scheme://host/path (fail safe → no link rather than a risky one).
    """
    s = str(raw or "").strip()
    if not s:
        return None
    if "://" not in s:                                   # scp-style ssh: git@host:owner/repo(.git)
        m = re.match(r"^[\w.+-]+@([\w.-]+):(.+)$", s)
        if not m:
            return None
        host, path = m.group(1), m.group(2)
    else:                                                # scheme://[userinfo@]host[:port]/path
        m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([\w.-]+)(?::\d+)?/(.+)$", s, re.I)
        if not m:
            return None
        host, path = m.group(1), m.group(2)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not host or not path or "@" in host or "@" in path:
        return None
    return f"https://{host}/{path}"


def git_meta(repo_abs: str, *, run=_default_git) -> dict:
    def g(*a):
        return run(["-C", repo_abs, *a]) or ""
    return {
        "head_sha": g("rev-parse", "HEAD"),
        "remote_url": normalize_remote(g("remote", "get-url", "origin")),
        "ref": g("rev-parse", "--abbrev-ref", "HEAD"),
        "last_activity_at": g("log", "-1", "--format=%cI"),
        "ref_is_default": True,          # best-effort locally (v1 simplification)
    }


def resolve_engine(engine: str = "ast-grep") -> str:
    """Locate a scan engine. ast-grep is preferred (static binary, ~90x faster than
    semgrep on a real repo and ~165x faster to start); opengrep/semgrep still work."""
    for name in (engine, "ast-grep", "opengrep", "semgrep"):
        p = shutil.which(name)
        if p:
            return p
        cand = os.path.join(os.path.dirname(sys.executable), name)
        if os.path.exists(cand):
            return cand
    raise RuntimeError("No scan engine found — install ast-grep (preferred) or "
                       "opengrep/semgrep to scan code endpoints.")


def engine_family(engine: str) -> str:
    """Which CLI/rule dialect an engine binary speaks: 'ast-grep' or 'semgrep'.
    The two take different rule formats and emit different JSON."""
    base = os.path.basename(engine or "").lower()
    return "ast-grep" if ("ast-grep" in base or base == "sg") else "semgrep"
