"""CLI for the Drift Detector.

Single command, `inventory-scan`, that builds the code-level third-party
integration inventory (the IR / inventory.json), the human report (INVENTORY.md),
and the drift diff vs the previous scan (DRIFT.md). Driven by the bundled
`bin/drift-scan` runner.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from agent import inventory_scan as inventory_scan_mod
from agent.lib.inventory_diff import render_diff_md


def _cmd_inventory_scan(args) -> int:
    progress = None
    if getattr(args, "progress", False):
        print("drift-detector · deterministic static-analysis (local · 0 LLM tokens)",
              file=sys.stderr, flush=True)

        def progress(msg):
            print(f"⚙ {msg}", file=sys.stderr, flush=True)

    t0 = time.perf_counter()
    try:
        out = inventory_scan_mod.scan_folder(args.root, args.state, args.now, progress=progress)
    except RuntimeError as exc:
        print(f"inventory-scan failed: {exc}", file=sys.stderr)
        return 2
    dt = time.perf_counter() - t0
    with open(args.out_json, "w", encoding="utf-8") as fh:
        json.dump(out["doc"], fh, ensure_ascii=False, indent=2, sort_keys=True)
    with open(args.out_md, "w", encoding="utf-8") as fh:
        fh.write(out["report_md"])
    if getattr(args, "out_diff", None):
        with open(args.out_diff, "w", encoding="utf-8") as fh:
            fh.write(render_diff_md(out["diff"]))
    d = out["doc"]
    print(f"✓ {len(d['repos'])} repos · {len(d.get('unique_apis', []))} APIs · "
          f"{len(d.get('unique_packages', []))} packages · "
          f"{len(d['coverage']['reposErrored'])} errors · {dt:.1f}s")
    return 0


def _cmd_audit(args) -> int:
    from agent.audit import audit_inventory
    from agent.lib.audit_render import render_audit_md
    from agent.lib.dashboard_render import render_dashboard

    with open(args.in_json, encoding="utf-8") as fh:
        doc = json.load(fh)
    http = None
    if getattr(args, "offline", False):
        def http(*a, **k):
            raise ConnectionError("offline")
    if getattr(args, "progress", False):
        print("drift-detector audit · OSV.dev + endoflife.date (deterministic · 0 LLM tokens)",
              file=sys.stderr, flush=True)

    audit = audit_inventory(doc, args.now, http=http) if http else audit_inventory(doc, args.now)
    from agent.lib.findings_state import apply_lifecycle
    apply_lifecycle(audit, os.path.dirname(os.path.abspath(args.in_json)), args.now)

    with open(args.out_audit, "w", encoding="utf-8") as fh:
        fh.write(render_audit_md(audit))
    if getattr(args, "out_json", None):
        with open(args.out_json, "w", encoding="utf-8") as fh:
            json.dump(audit, fh, ensure_ascii=False, indent=2, sort_keys=True)
    if getattr(args, "out_html", None):
        with open(args.out_html, "w", encoding="utf-8") as fh:
            fh.write(render_dashboard(doc, audit, args.now))
    c = audit["counts"]
    print(f"✓ audit: 🔴 {c.get('DEPRECATED', 0)} action-required · 🟠 {c.get('REVIEW', 0)} review · "
          f"across {c.get('reposAffected', 0)} repos")
    return 0


def _cmd_run(args) -> int:
    from agent.run import run_pipeline
    progress = None
    if getattr(args, "progress", False):
        print("drift-detector · scan → audit → deliver (deterministic · 0 LLM tokens)",
              file=sys.stderr, flush=True)

        def progress(msg):
            print(f"⚙ {msg}", file=sys.stderr, flush=True)
    try:
        out = run_pipeline(args.root, args.state, args.now,
                           pull=getattr(args, "pull", False), progress=progress)
    except RuntimeError as exc:
        print(f"run failed: {exc}", file=sys.stderr)
        return 2
    c = out["auditCounts"]
    print(f"✓ scan+audit: 🔴 {c.get('DEPRECATED', 0)} action-required · 🟠 {c.get('REVIEW', 0)} review")
    if getattr(args, "fail_on_deprecated", False):
        cov = out.get("coverage", {})
        if cov.get("osvErrors") or cov.get("eolErrors"):
            print("✗ gate: audit sources (OSV/endoflife) were unreachable — cannot certify clean "
                  "(exit 4). Re-run with network access.", file=sys.stderr)
            return 4                       # 'couldn't check' is NOT 'clean'
        if c.get("DEPRECATED", 0) > 0:
            print(f"✗ gate: {c['DEPRECATED']} DEPRECATED finding(s) (excluding muted) — failing (exit 3)",
                  file=sys.stderr)
            return 3
    return 0


def _cmd_schedule(args) -> int:
    from pathlib import Path
    from agent.lib import schedule as sched
    plugin_root = str(Path(__file__).resolve().parent.parent)
    try:
        line = sched.install_cron(args.root, args.state, args.at, plugin_root=plugin_root,
                                  pull=getattr(args, "pull", False))
    except Exception as exc:      # missing/failed crontab -> actionable message, not a traceback
        print(f"schedule failed: {exc}\n  Is 'crontab' installed and the cron service running?",
              file=sys.stderr)
        return 2
    print("installed cron:\n  " + line)
    return 0


def _cmd_unschedule(args) -> int:
    from agent.lib import schedule as sched
    try:
        removed = sched.remove_cron(args.state)
    except Exception as exc:
        print(f"unschedule failed: {exc}", file=sys.stderr)
        return 2
    print("removed schedule" if removed else "no schedule found")
    return 0


def _cmd_preflight(args) -> int:
    from agent.lib.repo_discovery import discover_repos
    from agent.lib import private_sources
    repos = discover_repos([args.root])
    print(f"scan-readiness · {args.root}")
    print(f"  repos discovered: {len(repos)}")
    flagged, n_pkg, n_src = [], 0, 0
    for abs_path, name in repos:
        ps = private_sources.detect(abs_path)
        if ps["packages"] or ps["repositories"]:
            flagged.append((name, ps))
            n_pkg += len(ps["packages"])
            n_src += len(ps["repositories"])
    if flagged:
        print(f"  ⚠ {len(flagged)} repo(s) declare private package sources needing access "
              f"({n_pkg} git/file deps · {n_src} private composer repos):")
        for name, ps in flagged[:20]:
            bits = [p["pkg"] for p in ps["packages"]] + ps["repositories"]
            print(f"    - {name}: {', '.join(bits[:6])}" + (" …" if len(bits) > 6 else ""))
        print("  → these need source access; clone them locally and add them as a --root to scan them.")
    else:
        print("  ✓ no private package sources detected — full source coverage.")
    return 0


def _cmd_mute(args) -> int:
    from agent.lib.findings_state import add_to_baseline, remove_from_baseline
    if args.remove:
        remove_from_baseline(args.state, args.fingerprint)
        print(f"unmuted {args.fingerprint}")
    else:
        add_to_baseline(args.state, args.fingerprint)
        print(f"muted {args.fingerprint} (excluded from action counts until unmuted)")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="drift-detector")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run")           # scan -> audit -> deliver, deterministic (cron entrypoint)
    pr.add_argument("--root", action="append", required=True)
    pr.add_argument("--state", required=True)
    pr.add_argument("--now", required=True)
    pr.add_argument("--pull", action="store_true")
    pr.add_argument("--progress", action="store_true")
    pr.add_argument("--fail-on-deprecated", action="store_true",
                    help="exit 3 if any un-muted DEPRECATED finding (CI gate)")
    pr.set_defaults(func=_cmd_run)

    psc = sub.add_parser("schedule")
    psc.add_argument("--root", required=True)
    psc.add_argument("--state", required=True)
    psc.add_argument("--at", default="0 7 * * 0")
    psc.add_argument("--pull", action="store_true")
    psc.set_defaults(func=_cmd_schedule)

    pu = sub.add_parser("unschedule")
    pu.add_argument("--state", required=True)
    pu.set_defaults(func=_cmd_unschedule)

    pmu = sub.add_parser("mute")
    pmu.add_argument("--state", required=True)
    pmu.add_argument("--fingerprint", required=True)
    pmu.add_argument("--remove", action="store_true")
    pmu.set_defaults(func=_cmd_mute)

    ppf = sub.add_parser("preflight")
    ppf.add_argument("--root", required=True)
    ppf.set_defaults(func=_cmd_preflight)

    pa = sub.add_parser("audit")
    pa.add_argument("--in", dest="in_json", required=True)
    pa.add_argument("--now", required=True)
    pa.add_argument("--out-audit", required=True)
    pa.add_argument("--out-json")
    pa.add_argument("--out-html")
    pa.add_argument("--offline", action="store_true")
    pa.add_argument("--progress", action="store_true")
    pa.set_defaults(func=_cmd_audit)

    pis = sub.add_parser("inventory-scan")
    pis.add_argument("--root", action="append", required=True,
                     help="folder to scan for git repos (recursive); repeat for multiple roots")
    for a in ("--state", "--out-json", "--out-md", "--now"):
        pis.add_argument(a, required=True)
    pis.add_argument("--out-diff", required=False)
    pis.add_argument("--progress", action="store_true",
                     help="emit an informative per-phase log to stderr")
    pis.set_defaults(func=_cmd_inventory_scan)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
