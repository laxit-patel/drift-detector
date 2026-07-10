# agent/cli.py
"""CLI for Plan 01: `ingest` populates the KB from feeds; `drift` reports new entries."""
from __future__ import annotations

import argparse
import json
import os
import sys

from agent.config import load_config
from agent import kb_ingest, drift
from agent.lib.gitlab_read import GitLabClient, GitLabError, GitLabUnreachable, GitLabAuthError
from agent import discover as discover_mod
from agent import inventory as inventory_mod
from agent.lib.presence import load_patterns
from agent import candidates as candidates_mod, classify_rules, delta as delta_mod, report as report_mod


def _cmd_ingest(args) -> int:
    cfg = load_config(args.config)
    results = kb_ingest.ingest_all(cfg.feeds, cfg.kb_root, args.now)
    errored = 0
    for r in results:
        if r.status == "ok":
            print(f"  {r.techKey}: {len(r.new_entries)} new ({r.adapter})")
        else:
            errored += 1
            print(f"  {r.techKey}: ERROR — {r.error}")
    print(f"Ingest complete: {len(results)} feeds, {errored} errored.")
    return 1 if errored else 0


def _cmd_drift(args) -> int:
    cfg = load_config(args.config)
    tks = [f.techKey for f in cfg.feeds]
    wms = {tk: args.since for tk in tks}
    groups = drift.compute_drift(cfg.kb_root, tks, wms)
    if not groups:
        print("No drift since watermark.")
        return 0
    for g in groups:
        print(f"\n{g['techKey']}:")
        for e in g["entries"]:
            print(f"  [{e.date}] {e.title}  <{e.sourceUrl}>")
    return 0


def _cmd_discover(args, client=None) -> int:
    cfg = load_config(args.config)
    if cfg.gitlab is None:
        print("ERROR: config has no `gitlab` section; cannot discover.")
        return 2
    if client is None:
        token = os.environ.get(cfg.gitlab.token_env)
        if not token:
            print(f"ERROR: env var {cfg.gitlab.token_env} is not set.")
            return 2
        client = GitLabClient(cfg.gitlab.base_url, token)
    try:
        result = discover_mod.discover(cfg, client, args.now)
    except (GitLabUnreachable, GitLabAuthError, GitLabError) as exc:
        print(f"ERROR: {exc}")
        return 2
    discover_mod.write_active_repos(args.out, result)
    print(f"Discovered {len(result['active'])} active repos "
          f"({len(result['excluded'])} excluded). Namespaces: {result['namespacesCovered']}")
    covered = set(result["namespacesCovered"])
    for ns in cfg.gitlab.expected_namespaces:
        if ns not in covered:
            print(f"WARNING: expected namespace '{ns}' not present in scan — token may not see it.")
    return 0


def _cmd_inventory(args, client=None) -> int:
    cfg = load_config(args.config)
    if cfg.gitlab is None:
        print("ERROR: config has no `gitlab` section; cannot build inventory.")
        return 2
    if client is None:
        token = os.environ.get(cfg.gitlab.token_env)
        if not token:
            print(f"ERROR: env var {cfg.gitlab.token_env} is not set.")
            return 2
        client = GitLabClient(cfg.gitlab.base_url, token)
    with open(args.active, "r", encoding="utf-8") as fh:
        active = json.load(fh)
    patterns = load_patterns(args.patterns)
    inv = inventory_mod.build_inventory(client, active, patterns, args.now)
    inventory_mod.write_inventory(args.out, inv)
    cov = inv["coverage"]
    print(f"Inventory: {len(inv['records'])} dep/runtime records, {len(inv['usedTechs'])} integrations "
          f"across {cov['reposScanned']} repos.")
    for repo in {r['repo'] for r in inv['records']} | {u['repo'] for u in inv['usedTechs']}:
        print(f"  {repo}")
    return 0


def _cmd_report(args) -> int:
    cfg = load_config(args.config)
    horizon = cfg.delivery.review_horizon_months if getattr(cfg, "delivery", None) else 6
    with open(args.inventory, "r", encoding="utf-8") as fh:
        inventory = json.load(fh)
    with open(args.active, "r", encoding="utf-8") as fh:
        active = json.load(fh)
    repo_ids = {r["path_with_namespace"]: r["id"] for r in active.get("active", [])}
    if args.prev and args.prev != "-":
        try:
            with open(args.prev, "r", encoding="utf-8") as fh:
                prev_doc = json.load(fh)
        except FileNotFoundError:
            prev_doc = {}
    else:
        prev_doc = {}

    watermarks = (prev_doc.get("reportedWatermarks") or {})
    cands = candidates_mod.build_candidates(inventory, cfg.kb_root, watermarks, repo_ids=repo_ids)
    findings = [classify_rules.candidate_to_finding(c, args.now, review_horizon_months=horizon) for c in cands]
    delta, stamped = delta_mod.compute_delta(findings, prev_doc, args.now)
    # persist per-tech reported watermark = latest change-entry date surfaced this run
    new_wm = dict(watermarks)
    for c in cands:
        d = c["changeEntry"].get("date", "")
        if d:
            new_wm[c["techKey"]] = max(new_wm.get(c["techKey"], ""), d)
    doc = report_mod.assemble_findings_doc(stamped, delta, inventory.get("coverage", {}), new_wm, args.now)
    md = report_mod.render_report(doc)
    with open(args.out_findings, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    with open(args.out_report, "w", encoding="utf-8") as fh:
        fh.write(md)
    c = doc["counts"]
    print(f"Report {args.now}: {c['action']} ACTION / {c['review']} REVIEW / {c['watchlist']} watch. "
          f"Delta: {len(doc['delta']['new'])} new, {len(doc['delta']['resolved'])} resolved.")
    return 0


def main(argv: list[str], *, client=None) -> int:
    p = argparse.ArgumentParser(prog="change-monitor")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest")
    pi.add_argument("--config", required=True)
    pi.add_argument("--now", required=True)
    pi.set_defaults(func=_cmd_ingest)

    pd = sub.add_parser("drift")
    pd.add_argument("--config", required=True)
    pd.add_argument("--since", default="")
    pd.set_defaults(func=_cmd_drift)

    pv = sub.add_parser("discover")
    pv.add_argument("--config", required=True)
    pv.add_argument("--now", required=True)
    pv.add_argument("--out", required=True)
    pv.set_defaults(func=_cmd_discover)

    pn = sub.add_parser("inventory")
    pn.add_argument("--config", required=True)
    pn.add_argument("--active", required=True)
    pn.add_argument("--out", required=True)
    pn.add_argument("--patterns", default="agent/patterns.yaml")
    pn.add_argument("--now", default="")
    pn.set_defaults(func=_cmd_inventory)

    pr = sub.add_parser("report")
    for a in ("--config", "--inventory", "--active", "--out-report", "--out-findings", "--now"):
        pr.add_argument(a, required=True)
    pr.add_argument("--prev", default="-")
    pr.set_defaults(func=_cmd_report)

    args = p.parse_args(argv)
    if args.func in (_cmd_discover, _cmd_inventory):
        return args.func(args, client=client)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
