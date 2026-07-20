"""Run the scan engine (injected for tests) and normalize its JSON to one match shape.

Two dialects are supported and produce identical downstream output:
  • ast-grep (preferred) — static binary, ~90x faster on a real repo. Rules are
    per-language and carry no metadata in the output, so the rule file is read back
    to recover each rule's {kind, vendor, techKey}. Lines are 0-indexed.
  • opengrep/semgrep — `--config/--json/--quiet`; results carry extra.metadata.
Either way `extra.lines` is login-gated, so the caller reads the example line from
the file itself rather than trusting the engine's echo.
"""
from __future__ import annotations

import json
import subprocess

import yaml


def _default_run(args: list) -> str:  # pragma: no cover - spawns the real engine
    proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
    return proc.stdout


def _rule_metadata(ruleset_path: str) -> dict:
    """base rule id -> {kind, vendor, techKey}, read back from an ast-grep rule file.

    ast-grep accepts a `metadata:` block but does not echo it in results, so we
    recover it here rather than threading a second argument through the scanner.
    """
    try:
        with open(ruleset_path, encoding="utf-8") as fh:
            docs = list(yaml.safe_load_all(fh))
    except (OSError, yaml.YAMLError):
        return {}
    out = {}
    for d in docs:
        if isinstance(d, dict) and d.get("id"):
            out[str(d["id"]).split("@")[0]] = d.get("metadata") or {}
    return out


def _run_astgrep(repo_path: str, ruleset_path: str, engine: str, run) -> dict:
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
            # ast-grep reports 0-indexed lines; every downstream consumer is 1-indexed
            "line": ((m.get("range") or {}).get("start") or {}).get("line", -1) + 1,
        })
    return {"matches": matches, "scanned": [], "errors": []}


def _run_semgrep(repo_path: str, ruleset_path: str, engine: str, run) -> dict:
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


def run_scan(repo_path: str, ruleset_path: str, *, engine: str = "ast-grep",
             run=_default_run) -> dict:
    from agent.lib.scan_util import engine_family
    if engine_family(engine) == "ast-grep":
        return _run_astgrep(repo_path, ruleset_path, engine, run)
    return _run_semgrep(repo_path, ruleset_path, engine, run)
