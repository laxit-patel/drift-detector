# agent/cli.py
"""CLI for Plan 01: `ingest` populates the KB from feeds; `drift` reports new entries."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse

from agent.config import load_config
from agent import kb_ingest, drift
from agent.lib.gitlab_read import GitLabClient, GitLabError, GitLabUnreachable, GitLabAuthError
from agent.lib.source import make_provider, SourceError
from agent import discover as discover_mod
from agent import inventory as inventory_mod
from agent.lib.presence import load_patterns
from agent import candidates as candidates_mod, classify_rules, delta as delta_mod, report as report_mod
from agent import run as run_mod
from agent import commit_report as commit_report_mod
from agent import registry_scan as registry_scan_mod
from agent.lib.chat import build_summary_text, post_chat
from agent.lib.contract import scan as contract_scan_mod
from agent import contract_report as contract_report_mod


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
    if client is None:
        try:
            client = make_provider(cfg)
        except SourceError as exc:
            print(f"ERROR: {exc}")
            return 2
    try:
        result = discover_mod.discover(cfg, client, args.now)
    except (GitLabUnreachable, GitLabAuthError, GitLabError) as exc:
        print(f"ERROR: {exc}")
        return 2
    discover_mod.write_active_repos(args.out, result)
    print(f"Discovered {len(result['active'])} active repos "
          f"({len(result['excluded'])} excluded). Namespaces: {result['namespacesCovered']}")
    covered = set(result["namespacesCovered"])
    expected = cfg.gitlab.expected_namespaces if cfg.gitlab else []
    for ns in expected:
        if ns not in covered:
            print(f"WARNING: expected namespace '{ns}' not present in scan — token may not see it.")
    return 0


def _cmd_inventory(args, client=None) -> int:
    cfg = load_config(args.config)
    if client is None:
        try:
            client = make_provider(cfg)
        except SourceError as exc:
            print(f"ERROR: {exc}")
            return 2
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


def _cmd_registry_scan(args) -> int:
    cfg = load_config(args.config)
    with open(args.inventory, "r", encoding="utf-8") as fh:
        inventory = json.load(fh)
    checked = registry_scan_mod.scan_inventory_packages(
        inventory, cfg.kb_root, fetch_json=registry_scan_mod._http_json, now=args.now)
    print(f"registry-scan: checked {len(checked)} techKey(s)"
          + (f": {', '.join(checked)}" if checked else ""))
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

    cands = candidates_mod.build_candidates(inventory, cfg.kb_root, repo_ids=repo_ids)
    findings = [classify_rules.candidate_to_finding(c, args.now, review_horizon_months=horizon) for c in cands]
    delta, stamped = delta_mod.compute_delta(findings, prev_doc, args.now)
    doc = report_mod.assemble_findings_doc(stamped, delta, inventory.get("coverage", {}), {}, args.now)
    md = report_mod.render_report(doc)
    with open(args.out_findings, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    with open(args.out_report, "w", encoding="utf-8") as fh:
        fh.write(md)
    c = doc["counts"]
    print(f"Report {args.now}: {c['action']} ACTION / {c['review']} REVIEW / {c['watchlist']} watch. "
          f"Delta: {len(doc['delta']['new'])} new, {len(doc['delta']['resolved'])} resolved.")
    return 0


def _cmd_classify_report(args) -> int:
    cfg = load_config(args.config)
    horizon = cfg.delivery.review_horizon_months if getattr(cfg, "delivery", None) else 6
    with open(args.inventory, "r", encoding="utf-8") as fh:
        inventory = json.load(fh)
    with open(args.active, "r", encoding="utf-8") as fh:
        active = json.load(fh)
    prev_doc = {}
    if args.prev and args.prev != "-":
        try:
            with open(args.prev, "r", encoding="utf-8") as fh:
                prev_doc = json.load(fh)
        except FileNotFoundError:
            prev_doc = {}

    if args.dry_classify:
        with open(args.dry_classify, "r", encoding="utf-8") as fh:
            canned = json.load(fh)
        classify_fn = lambda items: canned
    else:
        classify_fn = lambda items: []      # deterministic-only: needsReview -> coverage gap

    # Structured/lifecycle/registry entries self-cite URLs fetched at ingest; trust those.
    repo_ids = {r["path_with_namespace"]: r["id"] for r in active.get("active", [])}
    fetched = {c["changeEntry"].get("sourceUrl", "")
               for c in candidates_mod.build_candidates(inventory, cfg.kb_root, repo_ids=repo_ids)}

    out = run_mod.run_pipeline(inventory=inventory, active=active, kb_root=cfg.kb_root,
                               prev_doc=prev_doc, config=cfg, now=args.now,
                               classify_fn=classify_fn, fetched_urls=fetched,
                               review_horizon_months=horizon)
    with open(args.out_findings, "w", encoding="utf-8") as fh:
        json.dump(out["doc"], fh, ensure_ascii=False, indent=2)
    with open(args.out_report, "w", encoding="utf-8") as fh:
        fh.write(out["report_md"])
    c = out["doc"]["counts"]
    print(f"Report {args.now}: {c['action']} ACTION / {c['review']} REVIEW / {c['watchlist']} watch.")
    return 0


def _cmd_deliver(args, *, client=None, post=None) -> int:
    cfg = load_config(args.config)
    if getattr(cfg, "delivery", None) is None:
        print("ERROR: config has no `delivery` section; cannot deliver.")
        return 2
    d = cfg.delivery
    with open(args.findings, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    with open(args.report, "r", encoding="utf-8") as fh:
        report_md = fh.read()

    # GitLab write client (reports repo only). The reports project is addressed by URL-encoded path.
    proj_id = urllib.parse.quote(d.reports_project, safe="")
    if client is None:
        token = os.environ.get(d.report_token_env)
        if not token:
            print(f"ERROR: env var {d.report_token_env} is not set.")
            return 2
        client = GitLabClient(cfg.gitlab.base_url, token)
    webhook = os.environ.get(d.chat_webhook_env, "")

    def commit(ctx):
        files = {f"reports/report-{args.now}.md": report_md,
                 "state/findings.json": json.dumps(doc, ensure_ascii=False, indent=2)}
        return commit_report_mod.commit_files(client, proj_id, d.reports_branch,
                                              f"Change report {args.now}", files, d.reports_branch,
                                              expected_project_id=proj_id)

    def chat(ctx):
        text = build_summary_text(doc, args.report_url)
        return post_chat(webhook, text) if post is None else post_chat(webhook, text, post=post)

    results = run_mod.deliver(doc, report_md, cfg, commit=commit, chat=chat)
    for r in results:
        print(f"  {r['name']}: {'ok' if r.get('ok') else 'FAILED'}"
              + (f" ({r.get('error')})" if not r.get('ok') else ""))
    return 0 if all(r.get("ok") for r in results) else 1


def _cmd_contract_scan(args) -> int:
    models, skipped = contract_scan_mod.fetch_spapi_models()
    changes = contract_scan_mod.contract_scan(models, args.snapshots, args.marketplace)
    doc = {"marketplace": args.marketplace, "runDate": args.now,
           "apisScanned": len(models), "skipped": skipped, "changes": changes}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    breaking = sum(1 for c in changes if c["verdict"] == "BREAKING")
    print(f"contract-scan {args.marketplace}: {len(changes)} change(s) across "
          f"{len(models)} api(s) ({breaking} breaking); {len(skipped)} skipped")
    return 0


def _cmd_contract_report(args) -> int:
    with open(args.changes, "r", encoding="utf-8") as fh:
        changes = json.load(fh).get("changes", [])
    with open(args.inventory, "r", encoding="utf-8") as fh:
        inventory = json.load(fh)
    with open(args.active, "r", encoding="utf-8") as fh:
        active = json.load(fh)
    prev_doc = {}
    if args.prev and args.prev != "-":
        try:
            with open(args.prev, "r", encoding="utf-8") as fh:
                prev_doc = json.load(fh)
        except FileNotFoundError:
            prev_doc = {}
    out = contract_report_mod.build_contract_report(changes, inventory, active, prev_doc, args.now)
    with open(args.out_findings, "w", encoding="utf-8") as fh:
        json.dump(out["doc"], fh, ensure_ascii=False, indent=2)
    with open(args.out_report, "w", encoding="utf-8") as fh:
        fh.write(out["report_md"])
    c = out["doc"]["counts"]
    print(f"Contract report {args.now}: {c['action']} ACTION / {c['review']} REVIEW / "
          f"{c['watchlist']} watch.")
    return 0


def main(argv: list[str], *, client=None, post=None) -> int:
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

    prs = sub.add_parser("registry-scan")
    prs.add_argument("--config", required=True)
    prs.add_argument("--inventory", required=True)
    prs.add_argument("--now", required=True)
    prs.set_defaults(func=_cmd_registry_scan)

    pr = sub.add_parser("report")
    for a in ("--config", "--inventory", "--active", "--out-report", "--out-findings", "--now"):
        pr.add_argument(a, required=True)
    pr.add_argument("--prev", default="-")
    pr.set_defaults(func=_cmd_report)

    pc = sub.add_parser("classify-report")
    for a in ("--config", "--inventory", "--active", "--out-report", "--out-findings", "--now"):
        pc.add_argument(a, required=True)
    pc.add_argument("--prev", default="-")
    pc.add_argument("--dry-classify", default="")
    pc.set_defaults(func=_cmd_classify_report)

    pdl = sub.add_parser("deliver")
    for a in ("--config", "--findings", "--report", "--report-url", "--now"):
        pdl.add_argument(a, required=True)
    pdl.set_defaults(func=_cmd_deliver)

    pcs = sub.add_parser("contract-scan")
    pcs.add_argument("--marketplace", default="sp-api")
    pcs.add_argument("--snapshots", required=True)
    pcs.add_argument("--out", required=True)
    pcs.add_argument("--now", required=True)
    pcs.set_defaults(func=_cmd_contract_scan)

    pcr = sub.add_parser("contract-report")
    for a in ("--changes", "--inventory", "--active", "--out-report", "--out-findings", "--now"):
        pcr.add_argument(a, required=True)
    pcr.add_argument("--prev", default="-")
    pcr.set_defaults(func=_cmd_contract_report)

    args = p.parse_args(argv)
    if args.func is _cmd_deliver:
        return _cmd_deliver(args, client=client, post=post)
    if args.func in (_cmd_discover, _cmd_inventory):
        return args.func(args, client=client)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
