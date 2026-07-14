"""Run the Opengrep/Semgrep engine (injected for tests) and normalize its JSON results.
Engine facts (verified 2026-07-14): --config/--json/--quiet; results carry extra.metadata;
extra.lines is login-gated so the caller reads the example line from the file instead."""
from __future__ import annotations

import json
import subprocess


def _default_run(args: list) -> str:  # pragma: no cover - spawns the real engine
    proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
    return proc.stdout


def run_scan(repo_path: str, ruleset_path: str, *, engine: str = "opengrep", run=_default_run) -> dict:
    out = run([engine, "--config", ruleset_path, "--json", "--quiet", repo_path])
    try:
        data = json.loads(out) if out and out.strip() else {}
    except ValueError:
        data = {}
    matches = []
    for r in data.get("results", []):
        meta = (r.get("extra") or {}).get("metadata") or {}
        matches.append({
            "checkId": (r.get("check_id") or "").split(".")[-1],
            "vendor": meta.get("vendor", ""), "techKey": meta.get("techKey", ""),
            "kind": meta.get("kind", ""),
            "path": r.get("path", ""), "line": (r.get("start") or {}).get("line", 0),
        })
    return {"matches": matches,
            "scanned": (data.get("paths") or {}).get("scanned", []),
            "errors": data.get("errors", [])}
