"""Persist NormalizedSpec snapshots as stable JSON under the git-backed state tree.
First run for an (marketplace, api) returns None so the caller establishes a baseline."""
from __future__ import annotations

import json
from pathlib import Path

from agent.lib.contract.models import NormalizedSpec


def _path(root: str, marketplace: str, api: str) -> Path:
    safe_api = api.replace("/", "_")
    return Path(root) / "spec-snapshots" / marketplace / f"{safe_api}.json"


def save(root: str, marketplace: str, api: str, spec: NormalizedSpec) -> None:
    p = _path(root, marketplace, api)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
                 encoding="utf-8")


def load(root: str, marketplace: str, api: str) -> "NormalizedSpec | None":
    p = _path(root, marketplace, api)
    if not p.exists():
        return None
    return NormalizedSpec.from_dict(json.loads(p.read_text(encoding="utf-8")))
