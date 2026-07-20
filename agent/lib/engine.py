"""Run the ast-grep scan engine (injected for tests) and normalize its JSON.

ast-grep is a static Rust/tree-sitter binary: ~90x faster than semgrep on a real
repo and ~165x faster to start, with no Python runtime of its own. Two of its
conventions have to be translated here, and both are easy to get silently wrong:

  • lines are 0-INDEXED (everything downstream is 1-indexed);
  • rule metadata is NOT echoed in results, so the rule file is read back to
    recover each rule's {kind, vendor, techKey}.

Rule ids are `{base}@{language}` because ast-grep rules are single-language; the
suffix is stripped so downstream code sees the base id.
"""
from __future__ import annotations

import json
import subprocess

import yaml


def _default_run(args: list) -> str:  # pragma: no cover - spawns the real engine
    proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
    return proc.stdout


def _rule_metadata(ruleset_path: str) -> dict:
    """base rule id -> {kind, vendor, techKey}, read back from the rule file.

    ast-grep accepts a `metadata:` block but drops it from results, so we recover
    it here rather than threading a second argument through the scanner.
    """
    try:
        with open(ruleset_path, encoding="utf-8") as fh:
            docs = list(yaml.safe_load_all(fh))
    except (OSError, yaml.YAMLError):
        return {}
    return {str(d["id"]).split("@")[0]: (d.get("metadata") or {})
            for d in docs if isinstance(d, dict) and d.get("id")}


def run_scan(repo_path: str, ruleset_path: str, *, engine: str = "ast-grep",
             run=_default_run) -> dict:
    out = run([engine, "scan", "-r", ruleset_path, "--json=compact", repo_path])
    try:
        data = json.loads(out) if out and out.strip() else []
    except ValueError:
        data = []
    meta_by_rule = _rule_metadata(ruleset_path)
    matches = []
    for m in data:
        base = str(m.get("ruleId", "")).split("@")[0]
        meta = meta_by_rule.get(base, {})
        matches.append({
            "checkId": base,
            "vendor": meta.get("vendor", ""), "techKey": meta.get("techKey", ""),
            "kind": meta.get("kind", ""),
            "path": m.get("file", ""),
            "line": ((m.get("range") or {}).get("start") or {}).get("line", -1) + 1,
        })
    return {"matches": matches, "scanned": [], "errors": []}
