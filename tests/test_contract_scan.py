from agent.lib.contract.scan import contract_scan


def _doc(with_email: bool):
    order_props = {"AmazonOrderId": {"type": "string"}}
    if with_email:
        order_props["buyerEmail"] = {"type": "string"}
    return {"swagger": "2.0",
            "paths": {"/orders/v0/orders": {"get": {"responses": {"200":
                {"schema": {"$ref": "#/definitions/Resp"}}}}}},
            "definitions": {
                "Resp": {"type": "object", "properties": {
                    "payload": {"type": "array", "items": {"$ref": "#/definitions/Order"}}}},
                "Order": {"type": "object", "properties": order_props}}}


def test_first_run_establishes_baseline_no_changes(tmp_path):
    changes = contract_scan({"orders/ordersV0": _doc(True)}, str(tmp_path), "sp-api")
    assert changes == []                                   # first snapshot -> nothing to diff
    # a snapshot now exists for the next run
    from agent.lib.contract import snapshot_store
    assert snapshot_store.load(str(tmp_path), "sp-api", "orders/ordersV0") is not None


def test_second_run_detects_buyeremail_removal(tmp_path):
    contract_scan({"orders/ordersV0": _doc(True)}, str(tmp_path), "sp-api")     # baseline
    changes = contract_scan({"orders/ordersV0": _doc(False)}, str(tmp_path), "sp-api")  # buyerEmail gone
    breaking = [c for c in changes if c["verdict"] == "BREAKING"]
    assert len(breaking) == 1
    assert breaking[0]["api"] == "orders/ordersV0"
    assert breaking[0]["marketplace"] == "sp-api"
    assert "buyerEmail" in breaking[0]["detail"]


def test_unchanged_second_run_yields_no_changes(tmp_path):
    contract_scan({"orders/ordersV0": _doc(True)}, str(tmp_path), "sp-api")
    assert contract_scan({"orders/ordersV0": _doc(True)}, str(tmp_path), "sp-api") == []


import json
from agent import cli


def test_cli_contract_scan_writes_changes(tmp_path, monkeypatch, capsys):
    # stub the SP-API fetch so no network happens
    import agent.lib.contract.scan as scan_mod
    calls = {"n": 0}

    def fake_fetch(**_kw):
        calls["n"] += 1
        with_email = calls["n"] == 1                      # run1 has buyerEmail, run2 doesn't
        return {"orders/ordersV0": _doc(with_email)}, []

    monkeypatch.setattr(scan_mod, "fetch_spapi_models", fake_fetch, raising=False)

    snaps = tmp_path / "snaps"
    out1 = tmp_path / "changes1.json"
    rc = cli.main(["contract-scan", "--marketplace", "sp-api", "--snapshots", str(snaps),
                   "--out", str(out1), "--now", "2026-07-13"])
    assert rc == 0
    doc1 = json.loads(out1.read_text())
    assert doc1["changes"] == [] and doc1["apisScanned"] == 1        # baseline

    out2 = tmp_path / "changes2.json"
    cli.main(["contract-scan", "--marketplace", "sp-api", "--snapshots", str(snaps),
              "--out", str(out2), "--now", "2026-07-20"])
    doc2 = json.loads(out2.read_text())
    assert any(c["verdict"] == "BREAKING" and "buyerEmail" in c["detail"] for c in doc2["changes"])
