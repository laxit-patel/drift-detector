"""CLI for the Drift Detector.

Single command, `inventory-scan`, that builds the code-level third-party
integration inventory (the IR / inventory.json), the human report (INVENTORY.md),
and the drift diff vs the previous scan (DRIFT.md). Driven by the bundled
`bin/drift-scan` runner.
"""
from __future__ import annotations

import argparse
import json
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
    from agent.lib.cyclonedx import build_bom
    from agent.lib.sarif import build_sarif

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

    with open(args.out_audit, "w", encoding="utf-8") as fh:
        fh.write(render_audit_md(audit))
    if getattr(args, "out_bom", None):
        with open(args.out_bom, "w", encoding="utf-8") as fh:
            json.dump(build_bom(doc, audit["findings"], args.now), fh, ensure_ascii=False, indent=2)
    if getattr(args, "out_sarif", None):
        with open(args.out_sarif, "w", encoding="utf-8") as fh:
            json.dump(build_sarif(doc, audit["findings"]), fh, ensure_ascii=False, indent=2)
    if getattr(args, "out_json", None):
        with open(args.out_json, "w", encoding="utf-8") as fh:
            json.dump(audit, fh, ensure_ascii=False, indent=2, sort_keys=True)
    c = audit["counts"]
    print(f"✓ audit: 🔴 {c.get('DEPRECATED', 0)} action-required · 🟠 {c.get('REVIEW', 0)} review · "
          f"across {c.get('reposAffected', 0)} repos")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="drift-detector")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("audit")
    pa.add_argument("--in", dest="in_json", required=True)
    pa.add_argument("--now", required=True)
    pa.add_argument("--out-audit", required=True)
    pa.add_argument("--out-bom")
    pa.add_argument("--out-sarif")
    pa.add_argument("--out-json")
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
