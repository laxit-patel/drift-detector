"""Scan a folder of clones -> the superset inventory IR (inventory.json) + INVENTORY.md."""
from __future__ import annotations

import os
from pathlib import Path

from agent.lib import ir_store, opengrep, scan_util
from agent.lib.vendors import load_vendors
from agent.lib.vendor_rules import write_ruleset
from agent.lib.repo_scan import scan_repo
from agent.lib.inv_rollups import build_rollups
from agent.lib.inventory_render import render_inventory_md
from agent.lib.inventory_diff import diff_inventories


def scan_folder(root, state_dir, now, *, engine=None, run=None, git=None) -> dict:
    run = run if run is not None else opengrep._default_run
    git = git if git is not None else scan_util._default_git
    engine = engine or scan_util.resolve_engine()      # fail-loud if absent
    os.makedirs(state_dir, exist_ok=True)
    vendors = load_vendors()
    rules_path = os.path.join(state_dir, "rules.generated.yaml")
    write_ruleset(vendors, rules_path)

    repo_dirs = sorted(d for d in Path(root).iterdir() if d.is_dir() and (d / ".git").exists())
    repos: list = []
    coverage = {"reposScanned": 0, "reposErrored": [], "manifestsUnparsed": []}
    for i, d in enumerate(repo_dirs):
        name = d.name
        abs_ = str(d.resolve())
        coverage["reposScanned"] += 1
        try:
            sha = scan_util.git_meta(abs_, run=git)["head_sha"]
            cached = ir_store.load_repo_cache(state_dir, name, sha) if sha else None
            if cached is not None:
                cached = {**cached, "id": i + 1}
                repos.append(cached)
                continue
            record, note = scan_repo(abs_, name, i + 1, vendors, rules_path,
                                     engine=engine, run=run, git=git)
            repos.append(record)
            if sha:
                ir_store.save_repo_cache(state_dir, name, sha, record)
            coverage["manifestsUnparsed"] += [{"repo": name, **u} for u in note["unparsed"]]
        except Exception as exc:            # no single repo aborts the scan
            coverage["reposErrored"].append({"repo": name, "reason": str(exc)})

    prior = ir_store.load_ir(state_dir)                # BEFORE save_ir overwrites it
    doc = {"generated": now, "scope": {"reposScanned": coverage["reposScanned"]},
           "repos": repos, "coverage": coverage}
    doc.update(build_rollups(repos))
    ir_store.save_ir(state_dir, doc)
    return {"doc": doc, "report_md": render_inventory_md(doc),
            "diff": diff_inventories(prior or {}, doc)}
