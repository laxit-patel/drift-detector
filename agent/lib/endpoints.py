"""Turn normalized engine matches into endpoint records: read the matched line from the file,
extract the API version, and aggregate per (techKey, domain, version).

Nested-domain dedup: some vendor domains are supersets of others (e.g. `maps.googleapis.com`
is a superset of `googleapis.com`), so a single URL can trigger rules for multiple techKeys at
the same (path, line). Before aggregating, we collapse each distinct location down to the match
whose vendor domain found in the line is the longest (most specific), dropping the rest, so one
occurrence is never double-attributed to both the specific and the generic vendor.
"""
from __future__ import annotations

import re
from pathlib import Path


def _read_line(repo_root: str, path: str, line: int) -> str:
    try:
        text = (Path(repo_root) / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    return lines[line - 1] if 1 <= line <= len(lines) else ""


def _domain_in(line: str, domains) -> str:
    for d in domains:
        if d in line:
            return d
    return ""


def _version(line: str, version_regex: str):
    m = re.search(version_regex, line)
    return m.group(1) if m else None


def build_endpoints(matches: list, repo_root: str, vendors: list, *, max_files: int = 20) -> list:
    by_key = {v.techKey: v for v in vendors}

    # Pass 1: resolve each endpoint match's line/domain/version, keyed by its source location.
    computed = []
    for m in matches:
        if m.get("kind") != "endpoint":
            continue
        v = by_key.get(m.get("techKey", ""))
        line = _read_line(repo_root, m.get("path", ""), int(m.get("line", 0) or 0))
        domain = _domain_in(line, v.domains) if v else ""
        version = _version(line, v.version_regex) if v else None
        loc = (m.get("path", ""), int(m.get("line", 0) or 0))
        computed.append({"loc": loc, "domain": domain, "version": version, "line": line, "match": m})

    # Most-specific-domain-wins dedup: when several matches land on the same (path, line)
    # (nested vendor domains all matching one URL), keep only the one with the longest domain.
    best_by_loc: dict = {}
    for c in computed:
        cur = best_by_loc.get(c["loc"])
        if cur is None or len(c["domain"]) > len(cur["domain"]):
            best_by_loc[c["loc"]] = c

    # Pass 2: aggregate the deduped matches into endpoint records.
    groups: dict = {}
    for c in best_by_loc.values():
        m = c["match"]
        key = (m.get("techKey", ""), c["domain"], c["version"])
        rec = groups.get(key)
        if rec is None:
            rec = {"vendor": m.get("vendor", ""), "domain": c["domain"], "version": c["version"],
                   "techKey": m.get("techKey", ""), "example": c["line"].strip(),
                   "file_count": 0, "files": []}
            groups[key] = rec
        loc_str = f"{m.get('path','')}:{m.get('line',0)}"
        rec["file_count"] += 1
        if len(rec["files"]) < max_files and loc_str not in rec["files"]:
            rec["files"].append(loc_str)
    return list(groups.values())
