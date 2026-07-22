"""Persist the inventory IR + a per-repo cache keyed repo@head_sha (the incrementality substrate).
A cache hit (same sha) lets the scanner reuse a repo's record; a changed sha misses -> re-scan."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Per-repo cache schema. BUMP when the record shape changes so pre-upgrade caches are
# invalidated (a stale cache without new fields would silently under-report — e.g. a repo
# scanned before privateSources/versionSource existed would look "clean").
_CACHE_SCHEMA = 7      # 6->7: endpoints/files/residue now canonically sorted (determinism
                       # fix) — a v6 cache holds the OLD match-order list, so invalidate it


def _ir_path(state_dir: str) -> Path:
    return Path(state_dir) / "inventory.json"


def _repo_path(state_dir: str, path: str, head_sha: str) -> Path:
    key = hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
    return Path(state_dir) / f"repos_v{_CACHE_SCHEMA}" / f"{key}@{head_sha}.json"


def _write(p: Path, doc: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _read(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_ir(state_dir: str, doc: dict) -> None:
    _write(_ir_path(state_dir), doc)


def load_ir(state_dir: str):
    return _read(_ir_path(state_dir))


def save_repo_cache(state_dir: str, path: str, head_sha: str, record: dict) -> None:
    _write(_repo_path(state_dir, path, head_sha), record)


def load_repo_cache(state_dir: str, path: str, head_sha: str):
    return _read(_repo_path(state_dir, path, head_sha))
