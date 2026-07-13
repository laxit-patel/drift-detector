from agent.contract_scope import scope_changes


def _change(**kw):
    base = {"marketplace": "sp-api", "api": "orders/ordersV0", "opKey": "GET /orders",
            "kind": "response_field", "verdict": "BREAKING",
            "before": "payload.AmazonOrderId", "after": "",
            "detail": "response field removed: payload.AmazonOrderId"}
    base.update(kw)
    return base


def _inv(used):
    return {"usedTechs": [{"tech_key": tk, "repo": r} for tk, r in used]}


def test_scope_emits_one_row_per_using_repo():
    inv = _inv([("api:amazon-sp-api", "repoA"), ("api:amazon-sp-api", "repoB"),
                ("api:shopify", "repoC")])
    rows = scope_changes([_change()], inv)
    assert {(r["repo"], r["used"]) for r in rows} == {("repoA", True), ("repoB", True)}
    assert all(r["techKey"] == "api:amazon-sp-api" for r in rows)


def test_scope_unused_when_no_repo_uses_it():
    rows = scope_changes([_change()], _inv([("api:shopify", "repoC")]))
    assert len(rows) == 1 and rows[0]["used"] is False and rows[0]["repo"] == ""
    assert rows[0]["techKey"] == "api:amazon-sp-api"


def test_scope_unknown_marketplace_is_unused():
    rows = scope_changes([_change(marketplace="mystery")], _inv([("api:amazon-sp-api", "repoA")]))
    assert len(rows) == 1 and rows[0]["used"] is False and rows[0]["techKey"] == ""
