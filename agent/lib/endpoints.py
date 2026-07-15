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
    line_cache: dict = {}
    groups: dict = {}
    for m in matches:
        if m.get("kind") != "url":
            continue
        rel = _relpath(m.get("path", ""), repo_root)
        lineno = int(m.get("line", 0) or 0)
        line = _read_line(repo_root, rel, lineno, line_cache)
        for url in classify_url.extract_urls(line):
            host = classify_url.host_of(url)
            if classify_url.is_ignored(host):
                continue
            v = classify_url.classify_host(host, vendors)
            vendor = v.vendor if v else UNKNOWN
            techKey = v.techKey if v else ""
            version = classify_url.version_of(url, v)
            key = (techKey or f"unknown:{host}", host, version)
            rec = groups.get(key)
            if rec is None:
                rec = {"vendor": vendor, "domain": host, "version": version, "techKey": techKey,
                       "example": url.rstrip("\"';,)"), "file_count": 0, "files": [],
                       "classified": bool(v)}
                groups[key] = rec
            loc_str = f"{rel}:{lineno}"
            rec["file_count"] += 1
            if len(rec["files"]) < max_files and loc_str not in rec["files"]:
                rec["files"].append(loc_str)
    return list(groups.values())
