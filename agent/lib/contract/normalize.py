"""Format dispatcher + Swagger-2.0 normalizer. SP-API publishes Swagger 2.0, which uses the
same JSON-Schema subset as OpenAPI 3.0 for schemas — so we reuse _deref/_flatten and only
adapt the schema-map location (definitions), the response shape (response.schema), and the
non-body param shape (top-level type)."""
from __future__ import annotations

from agent.lib.contract.models import NormalizedSpec, Operation, Param
from agent.lib.contract.normalize_openapi import _deref, _flatten, _METHODS, normalize_openapi


def _request_params_v2(op: dict, defs: dict) -> list:
    out: list = []
    for p in op.get("parameters") or []:
        p, _s, _c = _deref(p or {}, defs, frozenset())
        if p.get("in") == "body":
            continue                                   # body schema diffing deferred (v1)
        name = p.get("name")
        if not name:
            continue
        out.append(Param(name=name, type=p.get("type") or "unknown",
                         required=bool(p.get("required"))))
    return out


def _response_fields_v2(op: dict, defs: dict):
    for code, resp in (op.get("responses") or {}).items():
        if not str(code).startswith("2"):
            continue
        schema = (resp or {}).get("schema")
        if schema:
            return _flatten(schema, defs)
    return [], {}


def normalize_swagger2(doc: dict) -> NormalizedSpec:
    defs = doc.get("definitions") or {}
    operations: dict = {}
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method in _METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            key = f"{method.upper()} {path}"
            fields, enums = _response_fields_v2(op, defs)
            operations[key] = Operation(key=key,
                                        requestParams=_request_params_v2(op, defs),
                                        responseFields=fields, enums=enums)
    return NormalizedSpec(operations=operations)


def normalize(doc: dict) -> NormalizedSpec:
    """Pick the normalizer by spec version. Swagger 2.0 -> normalize_swagger2; else OpenAPI 3.x."""
    if "swagger" in doc:
        return normalize_swagger2(doc)
    return normalize_openapi(doc)
