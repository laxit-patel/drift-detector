import json
from agent.lib.contract.spapi_source import fetch_spapi_models


def test_fetch_filters_models_and_parses():
    tree = ["README.md", "models/orders-api-model/ordersV0.json",
            "models/feeds-api-model/feeds_2021-06-30.json", "models/notjson.txt"]
    raw = {
        "models/orders-api-model/ordersV0.json": '{"swagger":"2.0","paths":{}}',
        "models/feeds-api-model/feeds_2021-06-30.json": '{"swagger":"2.0","paths":{}}',
    }
    models, skipped = fetch_spapi_models(fetch_tree=lambda: tree,
                                         fetch_raw=lambda p: raw[p])
    assert set(models) == {"orders-api-model/ordersV0", "feeds-api-model/feeds_2021-06-30"}
    assert models["orders-api-model/ordersV0"]["swagger"] == "2.0"
    assert skipped == []


def test_fetch_parses_control_characters_strict_false():
    # real SP-API files contain literal control chars in descriptions
    tree = ["models/orders-api-model/ordersV0.json"]
    body = '{"swagger":"2.0","x":"line1\nline2\ttab","paths":{}}'   # raw newline/tab inside a string
    models, skipped = fetch_spapi_models(fetch_tree=lambda: tree,
                                         fetch_raw=lambda p: body)
    assert models["orders-api-model/ordersV0"]["x"] == "line1\nline2\ttab"
    assert skipped == []


def test_fetch_skips_unparseable_file_without_crashing():
    tree = ["models/a-api-model/a.json", "models/b-api-model/b.json"]
    raw = {"models/a-api-model/a.json": "{ not valid json ",
           "models/b-api-model/b.json": '{"swagger":"2.0","paths":{}}'}
    models, skipped = fetch_spapi_models(fetch_tree=lambda: tree,
                                         fetch_raw=lambda p: raw[p])
    assert set(models) == {"b-api-model/b"}
    assert skipped == ["models/a-api-model/a.json"]
