# agent/cli.py
"""CLI for Plan 01: `ingest` populates the KB from feeds; `drift` reports new entries."""
from __future__ import annotations

import argparse
import sys

from agent.config import load_config
from agent import kb_ingest, drift


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


def main(argv: list[str]) -> int:
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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
