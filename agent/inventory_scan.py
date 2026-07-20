"""Scan a folder of clones -> the superset inventory IR (inventory.json) + INVENTORY.md."""
from __future__ import annotations

import os

from agent.lib import engine as engine_mod, ir_store, scan_util
from agent.lib.vendors import load_vendors
from agent.lib.vendor_rules import write_ruleset
from agent.lib.repo_scan import scan_repo
from agent.lib.repo_discovery import discover_repos
from agent.lib.inv_rollups import build_rollups
from agent.lib.inventory_diff import diff_inventories


def _coverage_grade(attributed: int, unattributed_paths: int, sinks: int) -> str:
    """Grade a repo's endpoint coverage: HIGH/PARTIAL/LOW based on attribution and residue."""
    if unattributed_paths and attributed == 0:
        return "LOW"
    if unattributed_paths or (attributed == 0 and sinks):
        return "PARTIAL"
    return "HIGH"


def _rollup_coverage(coverage: dict, repos: list, *, discovered_count: int) -> None:
    """Make the scan say what it did (and didn't) see — repos, endpoint buckets, package
    resolution, and private sources it couldn't scan."""
    eps = [e for r in repos for e in r.get("endpoints", [])]
    pkgs = [s for r in repos for s in r.get("sdks", [])]
    resolved = sum(1 for s in pkgs if s.get("versionSource") == "lockfile")
    private = [{"repo": r.get("path"), "packages": (r.get("privateSources") or {}).get("packages", []),
                "repositories": (r.get("privateSources") or {}).get("repositories", [])}
               for r in repos if any((r.get("privateSources") or {}).values())]
    coverage["repos"] = {"discovered": discovered_count, "scanned": coverage["reposScanned"],
                         "errored": len(coverage["reposErrored"])}
    coverage["endpoints"] = {"known": sum(1 for e in eps if e.get("vendor") and e["vendor"] != "Unknown"),
                             "unknownExternal": sum(1 for e in eps if e.get("vendor") == "Unknown")}
    coverage["packages"] = {"total": len(pkgs), "lockfileResolved": resolved,
                            "floorOnly": len(pkgs) - resolved}
    coverage["privateSources"] = private
    coverage["sdkMediated"] = [
        {"repo": r.get("path"),
         "sdkCount": len(r.get("sdks", [])),
         "endpointCount": sum(1 for e in r.get("endpoints", []) if e.get("classified"))}
        for r in repos if len(r.get("sdks", [])) >= 1
    ]
    res_paths, res_sinks, by_repo = [], [], []
    for r in repos:
        rr = r.get("residue") or {"pathLiterals": [], "sinks": []}
        plist = [{"repo": r.get("path"), **p} for p in rr.get("pathLiterals", [])]
        slist = [{"repo": r.get("path"), **s} for s in rr.get("sinks", [])]
        res_paths += plist
        res_sinks += slist
        attributed = sum(1 for e in r.get("endpoints", [])
                         if e.get("vendor") and e["vendor"] != "Unknown")
        by_repo.append({"repo": r.get("path"), "attributed": attributed,
                        "unattributedPaths": len(plist), "unresolvedSinks": len(slist),
                        "grade": _coverage_grade(attributed, len(plist), len(slist))})
    coverage["residue"] = {"pathLiterals": res_paths, "sinks": res_sinks, "byRepo": by_repo}


def scan_folder(root, state_dir, now, *, engine=None, run=None, git=None, progress=None) -> dict:
    # `root` may be a single path or a list of roots; discovery is recursive.
    roots = [root] if isinstance(root, (str, os.PathLike)) else list(root)

    def _p(msg):                            # informative phase log (optional)
        if progress:
            progress(msg)

    run = run if run is not None else engine_mod._default_run
    git = git if git is not None else scan_util._default_git
    engine = engine or scan_util.resolve_engine()      # fail-loud if absent
    os.makedirs(state_dir, exist_ok=True)
    vendors = load_vendors()
    rules_path = os.path.join(state_dir, "rules.generated.yaml")
    write_ruleset(vendors, rules_path)

    _p("discovering git repos under " + ", ".join(str(r) for r in roots) + " …")
    discovered = discover_repos(roots)     # [(abs_path, identity)], sorted, deduped
    n = len(discovered)
    _p(f"  {n} repo(s) found")
    repos: list = []
    coverage = {"reposScanned": 0, "reposErrored": [], "manifestsUnparsed": []}
    for i, (abs_, name) in enumerate(discovered):
        coverage["reposScanned"] += 1
        tag = f"[{i + 1:>2}/{n}] {name}"
        try:
            sha = scan_util.git_meta(abs_, run=git)["head_sha"]
            cached = ir_store.load_repo_cache(state_dir, name, sha) if sha else None
            if cached is not None:
                _p(f"{tag}  cached (HEAD unchanged)")
                cached = {**cached, "id": i + 1}
                repos.append(cached)
                continue
            _p(f"{tag}  scan: git · manifests · AST endpoints")
            record, note = scan_repo(abs_, name, i + 1, vendors, rules_path,
                                     engine=engine, run=run, git=git)
            repos.append(record)
            if sha:
                ir_store.save_repo_cache(state_dir, name, sha, record)
            coverage["manifestsUnparsed"] += [{"repo": name, **u} for u in note["unparsed"]]
        except Exception as exc:            # no single repo aborts the scan
            _p(f"{tag}  ⚠ error: {exc}")
            coverage["reposErrored"].append({"repo": name, "reason": str(exc)})

    _p("aggregating inventory + drift delta …")
    _rollup_coverage(coverage, repos, discovered_count=n)
    prior = ir_store.load_ir(state_dir)                # BEFORE save_ir overwrites it
    root_count = len({os.path.realpath(r) for r in roots})   # distinct, not raw
    doc = {"generated": now,
           "scope": {"rootCount": root_count, "reposScanned": coverage["reposScanned"]},
           "repos": repos, "coverage": coverage}
    doc.update(build_rollups(repos))
    ir_store.save_ir(state_dir, doc)
    diff = diff_inventories(prior or {}, doc)
    # On the very first scan (no prior IR) everything is "added" — that's a
    # baseline, not drift, so the report omits the drift section.
    return {"doc": doc, "diff": diff}
