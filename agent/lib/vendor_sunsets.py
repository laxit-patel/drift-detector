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
_CACHE = None


def load_sunsets(path: str | None = None) -> list:
    with open(path or _DEFAULT, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    return [s for s in raw if isinstance(s, dict) and s.get("vendor")]


def by_vendor(sunsets: list) -> dict:
    idx: dict = defaultdict(list)
    for s in sunsets:
        idx[s["vendor"]].append(s)
    return idx


def index(path: str | None = None) -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = by_vendor(load_sunsets(path))
    return _CACHE


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
