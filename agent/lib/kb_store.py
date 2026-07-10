"""Append-only JSONL knowledge-base store. Idempotent by ChangeEntry.id."""
from __future__ import annotations

import json
from pathlib import Path

from agent.lib.models import ChangeEntry, techkey_to_dir


def _dir(root: str, techKey: str) -> Path:
    return Path(root) / techkey_to_dir(techKey)


def changes_path(root: str, techKey: str) -> Path:
    return _dir(root, techKey) / "changes.jsonl"


def _watermark_path(root: str, techKey: str) -> Path:
    return _dir(root, techKey) / "watermark.json"


def load_entries(root: str, techKey: str) -> list[ChangeEntry]:
    p = changes_path(root, techKey)
    if not p.exists():
        return []
    out: list[ChangeEntry] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(ChangeEntry.from_dict(json.loads(line)))
    return out


def append_entries(root: str, techKey: str, entries: list[ChangeEntry]) -> list[ChangeEntry]:
    existing_ids = {e.id for e in load_entries(root, techKey)}
    fresh = [e for e in entries if e.id not in existing_ids]
    if not fresh:
        return []
    p = changes_path(root, techKey)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for e in fresh:
            fh.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
    return fresh


def read_watermark(root: str, techKey: str) -> dict:
    p = _watermark_path(root, techKey)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def write_watermark(root: str, techKey: str, data: dict) -> None:
    p = _watermark_path(root, techKey)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
