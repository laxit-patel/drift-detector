from agent.lib.contract.differ import diff
from agent.lib.contract.models import NormalizedSpec, Operation, Param, Field


def _spec(op):
    return NormalizedSpec(operations={op.key: op} if op else {})


def _op(params=None, fields=None, enums=None):
    return Operation(key="GET /orders", requestParams=params or [],
                     responseFields=fields or [], enums=enums or {})


def _verdicts(changes, kind=None):
    return {(c.kind, c.verdict) for c in changes if kind is None or c.kind == kind}


def test_operation_removed_is_breaking_added_is_additive():
    prev = NormalizedSpec(operations={"GET /orders": _op(), "GET /old": _op()})
    curr = NormalizedSpec(operations={"GET /orders": _op(), "GET /new": _op()})
    v = _verdicts(diff(prev, curr), "operation")
    assert ("operation", "BREAKING") in v and ("operation", "ADDITIVE") in v


def test_response_field_removed_is_breaking():
    prev = _spec(_op(fields=[Field("payload.BuyerInfo.buyerEmail", "string", False),
                             Field("payload.AmazonOrderId", "string", False)]))
    curr = _spec(_op(fields=[Field("payload.AmazonOrderId", "string", False)]))
    changes = diff(prev, curr)
    assert any(c.verdict == "BREAKING" and "buyerEmail" in c.detail for c in changes)


def test_response_field_added_is_additive():
    prev = _spec(_op(fields=[Field("payload.a", "string", False)]))
    curr = _spec(_op(fields=[Field("payload.a", "string", False),
                             Field("payload.b", "string", False)]))
    assert ("response_field", "ADDITIVE") in _verdicts(diff(prev, curr))


def test_response_field_type_change_is_ambiguous():
    prev = _spec(_op(fields=[Field("payload.qty", "string", False)]))
    curr = _spec(_op(fields=[Field("payload.qty", "integer", False)]))
    assert ("response_field", "AMBIGUOUS") in _verdicts(diff(prev, curr))


def test_response_field_becomes_nullable_is_ambiguous():
    prev = _spec(_op(fields=[Field("payload.x", "string", False)]))
    curr = _spec(_op(fields=[Field("payload.x", "string", True)]))
    assert ("response_field", "AMBIGUOUS") in _verdicts(diff(prev, curr))


def test_new_required_param_is_breaking_optional_is_additive():
    prev = _spec(_op(params=[Param("a", "string", True)]))
    curr = _spec(_op(params=[Param("a", "string", True),
                             Param("reqNew", "string", True),
                             Param("optNew", "string", False)]))
    v = _verdicts(diff(prev, curr), "request_param")
    assert ("request_param", "BREAKING") in v and ("request_param", "ADDITIVE") in v


def test_param_removed_and_optional_to_required_are_breaking():
    prev = _spec(_op(params=[Param("gone", "string", False), Param("a", "string", False)]))
    curr = _spec(_op(params=[Param("a", "string", True)]))
    breaking = {c.detail for c in diff(prev, curr) if c.verdict == "BREAKING"}
    assert any("removed" in d and "gone" in d for d in breaking)
    assert any("became required" in d and "a" in d for d in breaking)


def test_enum_value_removed_is_breaking_added_is_additive():
    prev = _spec(_op(enums={"payload.status": ["A", "B"]}))
    curr = _spec(_op(enums={"payload.status": ["A", "C"]}))  # B removed, C added
    v = _verdicts(diff(prev, curr), "enum")
    assert ("enum", "BREAKING") in v and ("enum", "ADDITIVE") in v


def test_identical_specs_produce_no_changes():
    s = _spec(_op(fields=[Field("payload.a", "string", False)],
                  params=[Param("m", "array", True)], enums={"payload.s": ["X"]}))
    assert diff(s, s) == []


def test_prune_orders_model_flags_buyeremail_removal_breaking():
    """The real 'Prune Orders model' change: buyerEmail removed from the Orders response."""
    common = [Field("payload.Orders[].AmazonOrderId", "string", False)]
    prev = _spec(_op(fields=common + [Field("payload.Orders[].BuyerInfo.buyerEmail", "string", False)]))
    curr = _spec(_op(fields=common))
    changes = diff(prev, curr)
    breaking = [c for c in changes if c.verdict == "BREAKING"]
    assert len(breaking) == 1
    assert breaking[0].kind == "response_field"
    assert "buyerEmail" in breaking[0].before and "buyerEmail" in breaking[0].detail
