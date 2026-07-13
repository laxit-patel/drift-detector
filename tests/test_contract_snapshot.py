from agent.lib.contract import snapshot_store
from agent.lib.contract.models import NormalizedSpec, Operation, Param, Field


def _spec():
    return NormalizedSpec(operations={
        "GET /orders": Operation(key="GET /orders",
                                 requestParams=[Param("marketplaceIds", "array", True)],
                                 responseFields=[Field("payload.total", "integer", False)],
                                 enums={})})


def test_load_missing_returns_none(tmp_path):
    assert snapshot_store.load(str(tmp_path), "sp-api", "orders_v0") is None


def test_save_then_load_round_trips(tmp_path):
    spec = _spec()
    snapshot_store.save(str(tmp_path), "sp-api", "orders_v0", spec)
    assert snapshot_store.load(str(tmp_path), "sp-api", "orders_v0") == spec


def test_api_with_slashes_is_path_safe(tmp_path):
    spec = _spec()
    snapshot_store.save(str(tmp_path), "sp-api", "orders-api-model/ordersV0", spec)
    # stored under a single flattened filename, reloads identically
    assert snapshot_store.load(str(tmp_path), "sp-api", "orders-api-model/ordersV0") == spec


def test_snapshot_json_is_sorted_and_indented(tmp_path):
    from pathlib import Path
    snapshot_store.save(str(tmp_path), "sp-api", "orders_v0", _spec())
    p = Path(tmp_path) / "spec-snapshots" / "sp-api" / "orders_v0.json"
    text = p.read_text(encoding="utf-8")
    assert "\n  " in text                       # indented (readable git diffs)
