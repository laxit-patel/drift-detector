"""Vendor catalog: the single source of truth for third-party endpoint detection."""
from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

# Captures /v3, /v24.0, /2010-10-01, /2021-06-30 — the version forms in the PM's inventory.
DEFAULT_VERSION_REGEX = r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})'


@dataclass(frozen=True)
class Vendor:
    vendor: str
    techKey: str
    domains: tuple
    version_regex: str


def vendor_slug(vendor: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", vendor.lower()).strip("-")


def load_vendors(path: str = "agent/vendors.yaml") -> list:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    out = []
    for d in raw:
        out.append(Vendor(
            vendor=d["vendor"], techKey=d["techKey"],
            domains=tuple(d.get("domains") or []),
            version_regex=d.get("versionRegex") or DEFAULT_VERSION_REGEX,
        ))
    return out
