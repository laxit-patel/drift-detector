"""Turn normalized engine matches into endpoint records: read the matched line from the file,
extract the API version, and aggregate per (techKey, domain, version).

Nesting-only dedup: some vendor domains are supersets of others (e.g. `maps.googleapis.com`
is a superset of `googleapis.com`), so a single URL can trigger rules for multiple techKeys at
the same (path, line). When that happens we drop the generic match and keep only the most
specific one. But two matches on the same line are NOT always the same URL -- a minified or
concatenated source line can legitimately contain two unrelated vendor URLs (e.g. a Stripe URL
and an Amazon SP-API URL on one line). Since this tool must never silently miss a genuine
endpoint, we only drop a match when its resolved domain is a proper substring of another
match's resolved domain at the same (path, line); unrelated domains on the same line are both
kept.
"""
from __future__ import annotations

import re
from pathlib import Path


def _read_line(repo_root: str, path: str, line: int, cache: dict) -> str:
    lines = cache.get(path)
    if lines is None:
        try:
            text = (Path(repo_root) / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        lines = text.splitlines()
        cache[path] = lines
    return lines[line - 1] if 1 <= line <= len(lines) else ""


def _domain_in(line: str, domains) -> str:
    for d in domains:
        if d in line:
            return d
    return ""


def _version(line: str, version_regex: str):
    m = re.search(version_regex, line)
    return m.group(1) if m else None


def _segment(line: str, domain: str) -> str:
    """The URL substring anchored at this vendor's domain (domain -> next quote/space),
    so a second vendor URL on the same line can't contaminate version/example."""
    idx = line.find(domain)
    if idx < 0:
        return line
    import re as _re
    return _re.split(r'["\'\s]', line[idx:], 1)[0]


def build_endpoints(matches: list, repo_root: str, vendors: list, *, max_files: int = 20) -> list:
    by_key = {v.techKey: v for v in vendors}

    # Pass 1: resolve each endpoint match's line/domain/version, keyed by its source location.
    computed = []
    line_cache: dict = {}
    for m in matches:
        if m.get("kind") != "endpoint":
            continue
        v = by_key.get(m.get("techKey", ""))
        line = _read_line(repo_root, m.get("path", ""), int(m.get("line", 0) or 0), line_cache)
        domain = _domain_in(line, v.domains) if v else ""
        # Anchor version/example to THIS vendor's own URL segment so a second vendor URL on the
        # same line (realistic in minified/bundled JS) can't contaminate the version we report.
        seg = _segment(line, domain) if domain else line
        version = _version(seg, v.version_regex) if v else None
        loc = (m.get("path", ""), int(m.get("line", 0) or 0))
        computed.append({"loc": loc, "domain": domain, "version": version, "seg": seg, "match": m})

    # Nesting-only dedup: group matches by (path, line), then within each group drop a match
    # only when its resolved domain is a proper substring (strictly shorter, and `in`) of some
    # other match's resolved domain in the same group. Two unrelated domains on the same line
    # (neither a substring of the other) are both kept. An empty "" domain (unknown vendor) is
    # a substring of any non-empty domain, so it's dropped when a real domain is present at the
    # same spot; if every domain in a group is "", they all survive (len(d) < len(d) is False).
    by_loc: dict = {}
    for c in computed:
        by_loc.setdefault(c["loc"], []).append(c)

    kept = []
    for group in by_loc.values():
        domains = [g["domain"] for g in group]
        for g in group:
            d = g["domain"]
            is_nested = any(len(d) < len(other) and d in other for other in domains)
            if not is_nested:
                kept.append(g)

    # Pass 2: aggregate the deduped matches into endpoint records.
    groups: dict = {}
    for c in kept:
        m = c["match"]
        key = (m.get("techKey", ""), c["domain"], c["version"])
        rec = groups.get(key)
        if rec is None:
            rec = {"vendor": m.get("vendor", ""), "domain": c["domain"], "version": c["version"],
                   "techKey": m.get("techKey", ""), "example": c["seg"].strip(),
                   "file_count": 0, "files": []}
            groups[key] = rec
        loc_str = f"{m.get('path','')}:{m.get('line',0)}"
        rec["file_count"] += 1
        if len(rec["files"]) < max_files and loc_str not in rec["files"]:
            rec["files"].append(loc_str)
    return list(groups.values())
