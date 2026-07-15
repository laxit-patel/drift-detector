"""Scan one repo: git metadata + manifests + Opengrep endpoints -> a superset record."""
from __future__ import annotations

from agent.lib.scan_util import git_meta, _default_git
from agent.lib.manifest_scan import extract_manifest_records
from agent.lib.record_routing import partition_records
from agent.lib.opengrep import run_scan
from agent.lib.endpoints import build_endpoints
from agent.lib.superset import to_superset_repo
from agent.lib import lockfile, private_sources


def scan_repo(repo_abs, repo_name, repo_id, vendors, rules_path, *,
              engine, run, git=_default_git):
    meta = git_meta(repo_abs, run=git)
    meta.update({"id": repo_id, "path": repo_name, "provenance": {"engine": "opengrep"}})

    records, unparsed = extract_manifest_records(repo_abs, repo_name)
    partitioned = partition_records(records)

    scan = run_scan(repo_abs, rules_path, engine=engine, run=run)
    endpoints = [e for e in build_endpoints(scan["matches"], repo_abs, vendors) if e.get("domain")]

    record = to_superset_repo(meta, partitioned, endpoints)
    _annotate_resolved(record, repo_abs)
    record["privateSources"] = private_sources.detect(repo_abs)   # what we can't see (say so)
    return record, {"unparsed": unparsed, "opengrepErrors": scan["errors"]}


def _annotate_resolved(record, repo_abs):
    """Attach lockfile-resolved exact versions to sdks[] (falls back to the manifest range)."""
    resolved = lockfile.resolve_versions(repo_abs)
    for s in record.get("sdks", []):
        exact = resolved.get((s["eco"], lockfile.norm(s["eco"], s["pkg"])))
        if exact:
            s["resolved"] = exact
            s["versionSource"] = "lockfile"
        else:
            s["versionSource"] = "manifest"
