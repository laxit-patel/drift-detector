from agent.contract_report import build_contract_report


def _change(detail="response field removed: payload.AmazonOrderId", verdict="BREAKING"):
    return {"marketplace": "sp-api", "api": "orders-api-model/ordersV0", "opKey": "GET /orders",
            "kind": "response_field", "verdict": verdict, "before": "payload.AmazonOrderId",
            "after": "", "detail": detail}


_INV = {"usedTechs": [{"tech_key": "api:amazon-sp-api", "repo": "acme/orders-svc"}]}
_ACTIVE = {"active": [{"id": 42, "path_with_namespace": "acme/orders-svc"}]}


def test_breaking_change_becomes_action_on_using_repo():
    out = build_contract_report([_change()], _INV, _ACTIVE, {}, "2026-07-13")
    doc = out["doc"]
    assert doc["counts"]["action"] == 1
    f = doc["findings"][0]
    assert f["repo"] == "acme/orders-svc" and f["projectId"] == 42
    assert f["severity"] == "ACTION" and f["findingType"] == "contract-drift"
    assert "AmazonOrderId" in out["report_md"]                  # rendered in the report


def test_one_shot_change_persists_as_ongoing_next_run():
    run1 = build_contract_report([_change()], _INV, _ACTIVE, {}, "2026-07-13")
    assert run1["doc"]["delta"]["new"]                          # NEW on the transition run
    # Next run: the scan finds NOTHING (one-shot), prev = run1 doc
    run2 = build_contract_report([], _INV, _ACTIVE, run1["doc"], "2026-07-20")
    assert run2["doc"]["counts"]["action"] == 1                 # STILL flagged (persisted)
    assert run2["doc"]["delta"]["ongoing"] and not run2["doc"]["delta"]["resolved"]


def test_unused_break_is_watchlist_not_action():
    inv = {"usedTechs": []}                                     # nobody uses SP-API
    out = build_contract_report([_change()], inv, {"active": []}, {}, "2026-07-13")
    assert out["doc"]["counts"]["action"] == 0
    assert out["doc"]["counts"]["watchlist"] == 1


import json
from agent import cli


def test_cli_contract_report_writes_findings(tmp_path):
    changes = tmp_path / "changes.json"
    changes.write_text(json.dumps({"marketplace": "sp-api", "runDate": "2026-07-13",
                                   "apisScanned": 1, "skipped": [], "changes": [_change()]}))
    inv = tmp_path / "inv.json"; inv.write_text(json.dumps(_INV))
    active = tmp_path / "active.json"; active.write_text(json.dumps(_ACTIVE))
    out_f = tmp_path / "findings.json"; out_r = tmp_path / "report.md"
    rc = cli.main(["contract-report", "--changes", str(changes), "--inventory", str(inv),
                   "--active", str(active), "--prev", "-", "--out-report", str(out_r),
                   "--out-findings", str(out_f), "--now", "2026-07-13"])
    assert rc == 0
    doc = json.loads(out_f.read_text())
    assert doc["counts"]["action"] == 1 and doc["findings"][0]["repo"] == "acme/orders-svc"
    assert "AmazonOrderId" in out_r.read_text()
