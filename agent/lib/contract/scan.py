"""Contract-scan orchestration: normalize each spec, diff it against the prior snapshot,
save the new snapshot, and aggregate the classified changes. Deterministic; no I/O beyond
the snapshot store (the caller supplies already-fetched specs)."""
from __future__ import annotations

from agent.lib.contract import snapshot_store, differ
from agent.lib.contract.normalize import normalize
from agent.lib.contract.spapi_source import fetch_spapi_models


def contract_scan(specs: dict, snapshot_root: str, marketplace: str, *, normalize_fn=normalize) -> list:
    changes: list = []
    for api, doc in specs.items():
        curr = normalize_fn(doc)
        prev = snapshot_store.load(snapshot_root, marketplace, api)
        if prev is not None:
            for c in differ.diff(prev, curr):
                changes.append({"marketplace": marketplace, "api": api,
                                "opKey": c.opKey, "kind": c.kind, "verdict": c.verdict,
                                "before": c.before, "after": c.after, "detail": c.detail})
        snapshot_store.save(snapshot_root, marketplace, api, curr)
    return changes
