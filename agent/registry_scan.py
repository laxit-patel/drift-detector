# agent/registry_scan.py
"""Scan the packages an inventory uses against their registries and append deprecation
entries to the KB (so they flow into candidates/report like any other Change Entry)."""
from __future__ import annotations

import requests

from agent.lib import kb_store
from agent.lib.registry_check import check_package


def _http_json(url):  # pragma: no cover
    r = requests.get(url, timeout=30, headers={"User-Agent": "change-monitor/1.0"})
    r.raise_for_status()
    return r.json()


def scan_inventory_packages(inventory: dict, kb_root: str, *, fetch_json=_http_json, now: str) -> list:
    """For each unique lib:* techKey in the inventory records, check its registry and append
    any deprecation ChangeEntry to the KB. Returns the list of techKeys checked."""
    techkeys = sorted({r["tech_key"] for r in inventory.get("records", [])
                       if r.get("tech_key", "").startswith("lib:")})
    for tk in techkeys:
        entries = check_package(tk, fetch_json=fetch_json, now=now)
        if entries:
            kb_store.append_entries(kb_root, tk, entries)
    return techkeys
