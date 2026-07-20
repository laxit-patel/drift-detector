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


def scan_endpoints(matches: list, repo_root: str, vendors: list, *, max_files: int = 20) -> dict:
    by_tk = {v.techKey: v for v in vendors}
    line_cache: dict = {}
    groups: dict = {}
    seen_known: set = set()

    def add(vendor, techKey, host, version, example, rel, lineno, operation=None):
        loc = f"{rel}:{lineno}"
        if techKey and (techKey, loc, operation) in seen_known:
            return
        if techKey:
            seen_known.add((techKey, loc, operation))
        key = (techKey or f"unknown:{host}", host, version, operation)
        rec = groups.get(key)
        if rec is None:
            rec = {"vendor": vendor, "domain": host, "version": version, "techKey": techKey,
                   "operation": operation,
                   "example": (example or host).rstrip("\"';,)"), "file_count": 0, "files": [],
                   "classified": bool(techKey)}
            groups[key] = rec
        rec["file_count"] += 1
        if len(rec["files"]) < max_files and loc not in rec["files"]:
            rec["files"].append(loc)

    for m in sorted(matches, key=lambda x: 0 if x.get("kind") == "url" else 1):
        rel = _relpath(m.get("path", ""), repo_root)
        lineno = int(m.get("line", 0) or 0)
        line = _read_line(repo_root, rel, lineno, line_cache)
        kind = m.get("kind")
        if kind == "url":
            for url in classify_url.extract_urls(line):
                host = classify_url.host_of(url)
                v = classify_url.classify_host(host, vendors)
                if v is None and classify_url.is_ignored(host):
                    continue
                add(v.vendor if v else UNKNOWN, v.techKey if v else "", host,
                    classify_url.version_of(url, v), url, rel, lineno)
        elif kind == "endpoint":
            v = by_tk.get(m.get("techKey", ""))
            d = classify_url.domain_in_line(line, v.domains) if v else ""
            if v and d:
                seg = classify_url.segment_at(line, d)
                add(v.vendor, v.techKey, d, classify_url.version_of(seg, v), seg, rel, lineno)

    # --- operation markers: name the OPERATION for vendors that deprecate per-call ---
    # Same strict guard as the concat idiom: only when the repo has exactly one
    # classified vendor, so an operation is never attributed to the wrong API.
    classified_tks = {r["techKey"] for r in groups.values() if r["techKey"]}
    if len(classified_tks) == 1:
        v = by_tk.get(next(iter(classified_tks)))
        if v is not None:
            for m in matches:
                if m.get("kind") != "operation-marker":
                    continue
                rel = _relpath(m.get("path", ""), repo_root)
                lineno = int(m.get("line", 0) or 0)
                # the marker may sit past the literal's first line, so search the
                # whole matched text and fall back to the line for engines that omit it
                op = (classify_url.operation_of(m.get("text") or "")
                      or classify_url.operation_of(_read_line(repo_root, rel, lineno, line_cache)))
                if op:
                    add(v.vendor, v.techKey, v.domains[0], None, op, rel, lineno, operation=op)

    # --- concat idiom: attribute host-less path literals to the repo's SINGLE classified vendor ---
    classified_tks = {r["techKey"] for r in groups.values() if r["techKey"]}
    assembly_files = {_relpath(m.get("path", ""), repo_root)
                      for m in matches if m.get("kind") == "path-assembly"}
    attributed_locs: set = set()
    if len(classified_tks) == 1 and assembly_files:
        v = by_tk.get(next(iter(classified_tks)))
        if v is not None:
            for m in matches:
                if m.get("kind") != "path-literal":
                    continue
                rel = _relpath(m.get("path", ""), repo_root)
                if rel not in assembly_files:
                    continue
                lineno = int(m.get("line", 0) or 0)
                path = classify_url.path_literal_of(_read_line(repo_root, rel, lineno, line_cache))
                if not path:
                    continue
                add(v.vendor, v.techKey, v.domains[0], classify_url.version_of(path, v), path, rel, lineno)
                attributed_locs.add(f"{rel}:{lineno}")

    # --- residue: what we could NOT attribute (the conscience) ---
    residue_paths, residue_sinks = [], []
    for m in matches:
        rel = _relpath(m.get("path", ""), repo_root)
        lineno = int(m.get("line", 0) or 0)
        loc = f"{rel}:{lineno}"
        kind = m.get("kind")
        if kind == "path-literal" and loc not in attributed_locs:
            path = classify_url.path_literal_of(_read_line(repo_root, rel, lineno, line_cache))
            if path:
                residue_paths.append({"sample": path, "loc": loc})
        elif kind == "sink":
            residue_sinks.append({"kind": "egress", "loc": loc})

    return {"endpoints": list(groups.values()),
            "residue": {"pathLiterals": residue_paths, "sinks": residue_sinks}}


def build_endpoints(matches: list, repo_root: str, vendors: list, *, max_files: int = 20) -> list:
    return scan_endpoints(matches, repo_root, vendors, max_files=max_files)["endpoints"]
