from agent.lib.contract.normalize import normalize, normalize_swagger2


# Mirrors the real SP-API ordersV0.json shape: swagger 2.0, definitions,
# response.schema -> $ref, query params with top-level type, nested $ref chain, enum.
_SWAGGER2 = {
    "swagger": "2.0",
    "paths": {
        "/orders/v0/orders": {
            "get": {
                "operationId": "getOrders",
                "parameters": [
                    {"name": "MarketplaceIds", "in": "query", "required": True, "type": "array"},
                    {"name": "CreatedAfter", "in": "query", "required": False, "type": "string"},
                ],
                "responses": {"200": {"description": "ok",
                                      "schema": {"$ref": "#/definitions/GetOrdersResponse"}}},
            }
        }
    },
    "definitions": {
        "GetOrdersResponse": {"type": "object", "required": ["payload"],
            "properties": {"payload": {"$ref": "#/definitions/OrderList"}}},
        "OrderList": {"type": "object",
            "properties": {"Orders": {"type": "array", "items": {"$ref": "#/definitions/Order"}}}},
        "Order": {"type": "object", "required": ["AmazonOrderId"],
            "properties": {
                "AmazonOrderId": {"type": "string"},
                "OrderStatus": {"type": "string", "enum": ["Shipped", "Unshipped"]},
                "BuyerInfo": {"$ref": "#/definitions/BuyerInfo"}}},
        "BuyerInfo": {"type": "object", "properties": {"buyerEmail": {"type": "string"}}},
    },
}


def test_normalize_swagger2_flattens_like_openapi():
    spec = normalize_swagger2(_SWAGGER2)
    assert set(spec.operations) == {"GET /orders/v0/orders"}
    op = spec.operations["GET /orders/v0/orders"]

    params = {p.name: p for p in op.requestParams}
    assert params["MarketplaceIds"].required is True and params["MarketplaceIds"].type == "array"
    assert params["CreatedAfter"].required is False

    paths = {f.path for f in op.responseFields}
    assert "payload.Orders[].AmazonOrderId" in paths
    assert "payload.Orders[].BuyerInfo.buyerEmail" in paths       # deep $ref via definitions
    assert op.enums["payload.Orders[].OrderStatus"] == ["Shipped", "Unshipped"]


def test_normalize_swagger2_skips_body_params():
    doc = {"swagger": "2.0", "definitions": {},
           "paths": {"/x": {"post": {"parameters": [
               {"name": "body", "in": "body", "schema": {"type": "object"}},
               {"name": "qp", "in": "query", "type": "string", "required": True}],
               "responses": {"200": {"description": "ok"}}}}}}
    op = normalize_swagger2(doc).operations["POST /x"]
    names = {p.name for p in op.requestParams}
    assert names == {"qp"}                                        # body param skipped (v1)


def test_normalize_dispatches_by_version():
    # swagger 2.0 -> non-empty via definitions path; openapi 3.0 -> via components path
    s2 = normalize(_SWAGGER2)
    assert "GET /orders/v0/orders" in s2.operations
    doc3 = {"openapi": "3.0.1", "paths": {"/y": {"get": {"responses": {"200": {"content":
            {"application/json": {"schema": {"type": "object", "properties": {"a": {"type": "string"}}}}}}}}}},
            "components": {"schemas": {}}}
    s3 = normalize(doc3)
    assert "GET /y" in s3.operations and any(f.path == "a" for f in s3.operations["GET /y"].responseFields)
