"""Turn the broad URL-literal matches into endpoint records (discover-then-classify).

For each matched line we extract every http(s) URL, classify its host against the vendor catalog
(agent.lib.classify_url), drop boilerplate, and aggregate per (techKey|host, host, version).
Known vendors carry their `vendor`/`techKey`; un-catalogued external hosts are surfaced as
`vendor: "Unknown"` so the catalog is never the ceiling.
"""
from __future__ import annotations

from pathlib import Path

from agent.lib import classify_url

UNKNOWN = "Unknown"


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


def _relpath(path: str, repo_root: str) -> str:
    """Repo-relative form of a match path, so the persisted IR is portable/diff-stable
    (the engine returns absolute paths when scanning an absolute dir). Relative paths pass through."""
    p = Path(path)
    if not p.is_absolute():
        return path
    try:
        return str(p.resolve().relative_to(Path(repo_root).resolve()))
    except ValueError:
        return path


def build_endpoints(matches: list, repo_root: str, vendors: list, *, max_files: int = 20) -> list:
    by_tk = {v.techKey: v for v in vendors}
    line_cache: dict = {}
    groups: dict = {}
    seen_known: set = set()          # (techKey, file:line) — dedup the URL path vs the host-only path

    def add(vendor, techKey, host, version, example, rel, lineno):
        loc = f"{rel}:{lineno}"
        if techKey and (techKey, loc) in seen_known:
            return                    # this known vendor is already recorded at this exact spot
        if techKey:
            seen_known.add((techKey, loc))
        key = (techKey or f"unknown:{host}", host, version)
        rec = groups.get(key)
        if rec is None:
            rec = {"vendor": vendor, "domain": host, "version": version, "techKey": techKey,
                   "example": (example or host).rstrip("\"';,)"), "file_count": 0, "files": [],
                   "classified": bool(techKey)}
            groups[key] = rec
        rec["file_count"] += 1
        if len(rec["files"]) < max_files and loc not in rec["files"]:
            rec["files"].append(loc)

    # URL matches first, so a URL's precise host (api.sandbox.ebay.com) wins the per-(vendor,loc)
    # dedup over the per-vendor rule's coarser catalog domain (ebay.com); the vendor rule then
    # only fills host-only references that had no URL.
    for m in sorted(matches, key=lambda x: 0 if x.get("kind") == "url" else 1):
        rel = _relpath(m.get("path", ""), repo_root)
        lineno = int(m.get("line", 0) or 0)
        line = _read_line(repo_root, rel, lineno, line_cache)
        kind = m.get("kind")
        if kind == "url":                                   # discovery: classify every URL host
            for url in classify_url.extract_urls(line):
                host = classify_url.host_of(url)
                if classify_url.is_ignored(host):
                    continue
                v = classify_url.classify_host(host, vendors)
                add(v.vendor if v else UNKNOWN, v.techKey if v else "", host,
                    classify_url.version_of(url, v), url, rel, lineno)
        elif kind == "endpoint":                            # recall: host-only reference to a known vendor
            v = by_tk.get(m.get("techKey", ""))
            d = classify_url.domain_in_line(line, v.domains) if v else ""
            if v and d:
                seg = classify_url.segment_at(line, d)
                add(v.vendor, v.techKey, d, classify_url.version_of(seg, v), seg, rel, lineno)
    return list(groups.values())
