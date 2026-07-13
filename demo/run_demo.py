#!/usr/bin/env python3
"""Offline demo + fine-tuning harness for the Change-Monitoring Agent.

Seeds a small Change Knowledge Base with realistic change entries, writes a sample
inventory (a fake tech stack — edit it to match yours), then runs the REAL deterministic
pipeline (candidates -> severity -> validate -> delta -> report) and prints the report.

No GitLab, no Anthropic key, no Chat needed. Run it, read the report, then tune:
  - edit SAMPLE_INVENTORY below (your real repos/deps/runtimes/integrations)
  - edit SEED_ENTRIES (what the KB "knows changed") or point config at real feeds
  - edit demo/demo-config.yaml (scan window, review horizon, vendor list)
and re-run to see how the findings change. Run twice to see week-over-week deltas.

Usage:
  source .venv/bin/activate
  python demo/run_demo.py            # first run: everything NEW
  python demo/run_demo.py --week2    # second run vs last week: ONGOING (php 8.0 upgraded -> RESOLVED)
"""
from __future__ import annotations

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from agent.lib.models import ChangeEntry            # noqa: E402
from agent.lib import kb_store                       # noqa: E402
from agent import cli                                # noqa: E402

OUT = os.path.join(HERE, "out")
KB = os.path.join(OUT, "kb")
NOW = "2026-07-13"

# --- What the KB "knows changed" (in real life this comes from `ingest` of live feeds) ---
SEED_ENTRIES = [
    # Runtimes (lifecycle EOL) — version-matched to the cycle in use via affectedArea.
    ("runtime:php", ChangeEntry(techKey="runtime:php", date="2023-11-26", changeType="deprecation",
        title="PHP 8.0 end-of-life", summary="PHP 8.0 no longer receives security fixes.",
        sourceUrl="https://endoflife.date/php", sourceTier=1, affectedArea="cycle 8.0",
        evidence="endoflife.date: PHP 8.0 EOL 2023-11-26")),
    ("runtime:php", ChangeEntry(techKey="runtime:php", date="2026-11-25", changeType="deprecation",
        title="PHP 8.1 approaching end-of-life", summary="PHP 8.1 security support ends 2026-11-25.",
        sourceUrl="https://endoflife.date/php", sourceTier=1, affectedArea="cycle 8.1",
        evidence="endoflife.date: PHP 8.1 EOL 2026-11-25")),
    ("runtime:node", ChangeEntry(techKey="runtime:node", date="2023-09-11", changeType="deprecation",
        title="Node.js 16 end-of-life", summary="Node 16 reached end-of-life.",
        sourceUrl="https://endoflife.date/nodejs", sourceTier=1, affectedArea="cycle 16",
        evidence="endoflife.date: Node 16 EOL 2023-09-11")),
    # A marketplace-integration breaking change (the whole point of the tool).
    ("api:amazon-sp-api", ChangeEntry(techKey="api:amazon-sp-api", date="2026-07-03", changeType="breaking",
        title="SP-API Orders: BuyerInfo now optional on getOrders",
        summary="getOrders may omit BuyerInfo; consumers must null-check.",
        sourceUrl="https://developer-docs.amazon.com/sp-api/changelog", sourceTier=1,
        affectedArea="Orders/getOrders", evidence="Changelog 2026-07-03: 'BuyerInfo is now optional and may be null.'")),
    # A deprecated package (registry-style).
    ("lib:npm/request", ChangeEntry(techKey="lib:npm/request", date="2024-02-11", changeType="deprecation",
        title="npm 'request' is deprecated", summary="The 'request' package is deprecated and unmaintained.",
        sourceUrl="https://registry.npmjs.org/request", sourceTier=1,
        evidence="npm: 'request has been deprecated' ")),
]

# --- A SAMPLE tech stack (EDIT THIS to your real repos). Shape matches inventory.json. ---
SAMPLE_INVENTORY = {
    "records": [
        {"repo": "clients/acme-shop", "tech_key": "runtime:php", "kind": "runtime",
         "version_hint": "8.0", "declared_range": "", "ecosystem": "docker"},
        {"repo": "clients/acme-shop", "tech_key": "lib:npm/request", "kind": "library",
         "declared_range": "^2.88", "version_hint": "", "ecosystem": "npm"},
        {"repo": "clients/biz-portal", "tech_key": "runtime:php", "kind": "runtime",
         "version_hint": "8.1", "declared_range": "", "ecosystem": "docker"},
        {"repo": "internal/tools-api", "tech_key": "runtime:node", "kind": "runtime",
         "version_hint": "16", "declared_range": "", "ecosystem": "docker"},
    ],
    "usedTechs": [
        {"repo": "clients/acme-shop", "tech_key": "api:amazon-sp-api", "evidence": "src/Amazon/Orders.php"},
    ],
    "coverage": {"reposScanned": 3, "reposErrored": [], "reposNoManifests": [], "manifestsUnparsed": []},
}

ACTIVE = {"active": [
    {"id": 101, "path_with_namespace": "clients/acme-shop"},
    {"id": 102, "path_with_namespace": "clients/biz-portal"},
    {"id": 103, "path_with_namespace": "internal/tools-api"},
]}


def _seed_kb():
    shutil.rmtree(KB, ignore_errors=True)
    by_key: dict = {}
    for tk, entry in SEED_ENTRIES:
        by_key.setdefault(tk, []).append(entry)
    for tk, entries in by_key.items():
        kb_store.append_entries(KB, tk, entries)


def main(argv):
    week2 = "--week2" in argv
    os.makedirs(OUT, exist_ok=True)
    _seed_kb()

    inv = json.loads(json.dumps(SAMPLE_INVENTORY))  # deep copy
    if week2:
        # Simulate acme-shop upgrading PHP 8.0 -> 8.2 (the passed-EOL risk should RESOLVE).
        for r in inv["records"]:
            if r["repo"] == "clients/acme-shop" and r["tech_key"] == "runtime:php":
                r["version_hint"] = "8.2"

    inv_path = os.path.join(OUT, "inventory.json")
    active_path = os.path.join(OUT, "active-repos.json")
    with open(inv_path, "w") as fh:
        json.dump(inv, fh, indent=2)
    with open(active_path, "w") as fh:
        json.dump(ACTIVE, fh, indent=2)

    findings_path = os.path.join(OUT, "findings.json")
    report_path = os.path.join(OUT, "report.md")
    prev = findings_path if week2 and os.path.exists(findings_path) else "-"

    rc = cli.main([
        "classify-report",
        "--config", os.path.join(HERE, "demo-config.yaml"),
        "--inventory", inv_path, "--active", active_path,
        "--prev", prev,
        "--out-report", report_path, "--out-findings", findings_path,
        "--now", NOW,
    ])
    print(f"\n(classify-report exit={rc})")
    print("=" * 72)
    with open(report_path) as fh:
        print(fh.read())
    print("=" * 72)
    print(f"Wrote: {report_path}  and  {findings_path}")
    print("Fine-tune: edit SAMPLE_INVENTORY / SEED_ENTRIES / demo/demo-config.yaml and re-run.")
    print("Deltas: run once (all NEW), then `python demo/run_demo.py --week2` (ONGOING + a RESOLVED).")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
