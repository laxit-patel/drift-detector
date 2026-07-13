from agent.lib.contract.normalize_openapi import _flatten
from agent.lib.contract.models import Field


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
    # must terminate; the cycle point is emitted as a leaf, not infinite recursion
    assert any(f.type == "ref" for f in fields) or any(f.path == "child" for f in fields)
