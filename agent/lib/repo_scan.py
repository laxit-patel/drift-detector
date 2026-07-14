"""Scan one repo: git metadata + manifests + Opengrep endpoints -> a superset record."""
from __future__ import annotations

from agent.lib.scan_util import git_meta, _default_git
from agent.lib.manifest_scan import extract_manifest_records
from agent.lib.record_routing import partition_records
from agent.lib.opengrep import run_scan
from agent.lib.endpoints import build_endpoints
from agent.lib.superset import to_superset_repo


def scan_repo(repo_abs, repo_name, repo_id, vendors, rules_path, *,
              engine, run, git=_default_git):
    meta = git_meta(repo_abs, run=git)
    meta.update({"id": repo_id, "path": repo_name, "provenance": {"engine": "opengrep"}})

    records, unparsed = extract_manifest_records(repo_abs, repo_name)
    partitioned = partition_records(records)

    scan = run_scan(repo_abs, rules_path, engine=engine, run=run)
    endpoints = [e for e in build_endpoints(scan["matches"], repo_abs, vendors) if e.get("domain")]

    record = to_superset_repo(meta, partitioned, endpoints)
    return record, {"unparsed": unparsed, "opengrepErrors": scan["errors"]}
