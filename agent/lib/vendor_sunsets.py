"""Load the curated vendor-API-sunset catalog and classify a retirement date.

The catalog is the tool's unique layer: OSV/endoflife cover packages/runtimes, this covers
when a *vendor retires an API version* — joined against the endpoint inventory (file:line).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

_DEFAULT = str(Path(__file__).resolve().parent.parent / "vendor_sunsets.yaml")


def load_sunsets(path: str | None = None) -> list:
    with open(path or _DEFAULT, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    out = []
    for s in raw:
        # need a vendor plus a scope: a version (or "*"), a domain, or an operation
        if not (isinstance(s, dict) and s.get("vendor")
                and (s.get("version") is not None or s.get("domain") or s.get("operation"))):
            continue
        s = dict(s)
        # YAML parses an unquoted date/number as a date/int — coerce so it stays JSON-serializable
        if s.get("version") is not None:
            s["version"] = str(s["version"])
        if s.get("domain") is not None:
            s["domain"] = str(s["domain"])
        if s.get("retires") is not None:
            s["retires"] = str(s["retires"])
        out.append(s)
    return out


def by_vendor(sunsets: list) -> dict:
    idx: dict = defaultdict(list)
    for s in sunsets:
        idx[s["vendor"]].append(s)
    return idx


def status_for(retires, now: str, *, confirmed: bool) -> str:
    """A version we can't confirm the repo is on -> REVIEW. Else past-date -> DEPRECATED,
    future/undated announced retirement -> REVIEW (surface it; lead time is the point)."""
    if not confirmed:
        return "REVIEW"
    if not retires:
        return "DEPRECATED"          # already deprecated, no fixed date
    try:
        return "DEPRECATED" if date.fromisoformat(str(retires)) <= date.fromisoformat(now) else "REVIEW"
    except ValueError:
        return "REVIEW"
