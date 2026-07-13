from agent.lib.contract.models import (
    NormalizedSpec, Operation, Param, Field, ContractChange,
)


def _spec():
    return NormalizedSpec(operations={
        "GET /orders": Operation(
            key="GET /orders",
            requestParams=[Param(name="marketplaceIds", type="array", required=True)],
            responseFields=[Field(path="payload.Orders[].AmazonOrderId", type="string", nullable=False),
                            Field(path="payload.Orders[].OrderStatus", type="enum", nullable=False)],
            enums={"payload.Orders[].OrderStatus": ["Canceled", "Shipped", "Unshipped"]},
        )})


def test_normalizedspec_round_trips_through_dict():
    spec = _spec()
    restored = NormalizedSpec.from_dict(spec.to_dict())
    assert restored == spec                      # dataclass equality, structurally identical


def test_to_dict_is_json_stable():
    import json
    spec = _spec()
    # to_dict must be plain JSON-serializable (no dataclass instances left)
    dumped = json.dumps(spec.to_dict(), sort_keys=True)
    assert "AmazonOrderId" in dumped and '"Shipped"' in dumped


def test_contractchange_is_frozen_value():
    c = ContractChange(opKey="GET /orders", kind="response_field", verdict="BREAKING",
                       before="payload.Orders[].BuyerInfo.buyerEmail", after="", detail="removed")
    assert c.verdict == "BREAKING"
    try:
        c.verdict = "ADDITIVE"                    # frozen -> must raise
        assert False, "expected FrozenInstanceError"
    except Exception:
        pass
