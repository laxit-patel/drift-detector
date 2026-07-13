from agent.lib.contract.normalize_openapi import _flatten
from agent.lib.contract.models import Field
from agent.lib.contract.normalize_openapi import normalize_openapi


_MINI_OPENAPI = {
    "openapi": "3.0.1",
    "paths": {
        "/orders/v0/orders": {
            "get": {
                "operationId": "getOrders",
                "parameters": [
                    {"name": "MarketplaceIds", "in": "query", "required": True,
                     "schema": {"type": "array"}},
                    {"name": "CreatedAfter", "in": "query", "required": False,
                     "schema": {"type": "string"}},
                ],
                "responses": {"200": {"content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/GetOrdersResponse"}}}}},
            }
        }
    },
    "components": {"schemas": {
        "GetOrdersResponse": {"type": "object", "required": ["payload"],
            "properties": {"payload": {"$ref": "#/components/schemas/OrderList"}}},
        "OrderList": {"type": "object",
            "properties": {"Orders": {"type": "array",
                "items": {"$ref": "#/components/schemas/Order"}}}},
        "Order": {"type": "object", "required": ["AmazonOrderId"],
            "properties": {
                "AmazonOrderId": {"type": "string"},
                "OrderStatus": {"type": "string", "enum": ["Shipped", "Unshipped"]},
                "BuyerInfo": {"$ref": "#/components/schemas/BuyerInfo"}}},
        "BuyerInfo": {"type": "object",
            "properties": {"buyerEmail": {"type": "string"}}},
    }},
}


def test_flatten_nested_object_with_required_and_ref():
    components = {
        "Order": {"type": "object", "required": ["AmazonOrderId"],
                  "properties": {
                      "AmazonOrderId": {"type": "string"},
                      "BuyerInfo": {"$ref": "#/components/schemas/BuyerInfo"}}},
        "BuyerInfo": {"type": "object",
                      "properties": {"buyerEmail": {"type": "string"}}},
    }
    schema = {"$ref": "#/components/schemas/Order"}
    fields, enums = _flatten(schema, components)
    paths = {f.path: f for f in fields}
    assert paths["AmazonOrderId"].type == "string" and paths["AmazonOrderId"].nullable is False
    assert paths["BuyerInfo"].type == "object" and paths["BuyerInfo"].nullable is True
    assert paths["BuyerInfo.buyerEmail"].type == "string"
    assert enums == {}


def test_flatten_array_items_get_bracket_marker():
    components = {}
    schema = {"type": "object", "properties": {
        "Orders": {"type": "array", "items": {"type": "object",
                   "properties": {"id": {"type": "string"}}}}}}
    fields, _ = _flatten(schema, components)
    paths = {f.path for f in fields}
    assert "Orders" in paths and "Orders[].id" in paths


def test_flatten_collects_enums_by_path():
    components = {}
    schema = {"type": "object", "properties": {
        "OrderStatus": {"type": "string", "enum": ["Shipped", "Unshipped", "Canceled"]}}}
    fields, enums = _flatten(schema, components)
    assert {f.path: f.type for f in fields}["OrderStatus"] == "enum"
    assert enums["OrderStatus"] == ["Canceled", "Shipped", "Unshipped"]     # sorted


def test_flatten_nullable_flag_from_schema():
    components = {}
    schema = {"type": "object", "required": ["a"],
              "properties": {"a": {"type": "string"},
                             "b": {"type": "string", "nullable": True}}}
    fields, _ = _flatten(schema, components)
    by = {f.path: f for f in fields}
    assert by["a"].nullable is False and by["b"].nullable is True


def test_flatten_survives_circular_ref():
    components = {"Node": {"type": "object", "properties": {
        "child": {"$ref": "#/components/schemas/Node"}}}}
    fields, _ = _flatten({"$ref": "#/components/schemas/Node"}, components)
    child = [f for f in fields if f.path == "child"]
    assert child and child[0].type == "ref"        # object-property cycle tagged 'ref', terminates


def test_normalize_openapi_builds_operation_with_params_fields_enums():
    spec = normalize_openapi(_MINI_OPENAPI)
    assert set(spec.operations) == {"GET /orders/v0/orders"}
    op = spec.operations["GET /orders/v0/orders"]

    params = {p.name: p for p in op.requestParams}
    assert params["MarketplaceIds"].required is True and params["MarketplaceIds"].type == "array"
    assert params["CreatedAfter"].required is False

    paths = {f.path for f in op.responseFields}
    assert "payload.Orders[].AmazonOrderId" in paths
    assert "payload.Orders[].BuyerInfo.buyerEmail" in paths     # deep $ref chain flattened

    assert op.enums["payload.Orders[].OrderStatus"] == ["Shipped", "Unshipped"]


def test_normalize_openapi_ignores_paths_without_operations():
    doc = {"paths": {"/x": {"parameters": [], "description": "no methods here"}}}
    assert normalize_openapi(doc).operations == {}


def test_flatten_allof_merges_all_members():
    components = {
        "Base": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
        "Extra": {"type": "object", "properties": {"note": {"type": "string"}}},
    }
    schema = {"allOf": [{"$ref": "#/components/schemas/Base"},
                        {"$ref": "#/components/schemas/Extra"}]}
    fields, _ = _flatten(schema, components)
    paths = {f.path for f in fields}
    assert "id" in paths and "note" in paths        # both members merged, not zero fields


def test_flatten_top_level_array_response():
    components = {}
    schema = {"type": "array", "items": {"type": "object",
              "properties": {"orderId": {"type": "string"}}}}
    fields, _ = _flatten(schema, components)
    assert any(f.path == "[].orderId" for f in fields)   # array items flattened, not dropped
