"""OpenAPI (3.0) -> NormalizedSpec. Resolves local $refs and flattens response schemas
into dotted-path Field records so the differ can compare two specs structurally."""
from __future__ import annotations

from agent.lib.contract.models import NormalizedSpec, Operation, Param, Field

_METHODS = ("get", "put", "post", "delete", "patch")


def _deref(schema: dict, components: dict, seen: frozenset):
    """Follow one $ref hop. Returns (schema, seen, circular)."""
    ref = (schema or {}).get("$ref")
    if not ref:
        return schema or {}, seen, False
    name = ref.split("/")[-1]
    if name in seen:
        return {}, seen, True
    return components.get(name, {}), seen | {name}, False


def _flatten(schema: dict, components: dict, prefix: str = "", seen: frozenset = frozenset()):
    """Walk an object/array/leaf schema. Returns (list[Field], enums: dict[path -> values])."""
    schema, seen, circular = _deref(schema or {}, components, seen)
    if circular:
        return [Field(path=prefix or "?", type="ref", nullable=True)], {}
    fields: list = []
    enums: dict = {}
    props = schema.get("properties")
    if not props:
        return fields, enums
    required = set(schema.get("required", []))
    for name, sub in props.items():
        path = f"{prefix}.{name}" if prefix else name
        sub_d, sub_seen, circular = _deref(sub or {}, components, seen)
        nullable = (name not in required) or bool(sub_d.get("nullable"))
        if circular:                                  # circular ref via an object property
            fields.append(Field(path=path, type="ref", nullable=True))
            continue
        if "enum" in sub_d:
            enums[path] = sorted(str(v) for v in sub_d["enum"])
            fields.append(Field(path=path, type="enum", nullable=nullable))
        elif sub_d.get("properties") or sub_d.get("type") == "object":
            fields.append(Field(path=path, type="object", nullable=nullable))
            f2, e2 = _flatten(sub, components, path, seen)
            fields += f2
            enums.update(e2)
        elif sub_d.get("type") == "array":
            fields.append(Field(path=path, type="array", nullable=nullable))
            f2, e2 = _flatten(sub_d.get("items") or {}, components, path + "[]", sub_seen)
            fields += f2
            enums.update(e2)
        else:
            fields.append(Field(path=path, type=sub_d.get("type") or "unknown", nullable=nullable))
    return fields, enums


def _request_params(op: dict, components: dict) -> list:
    out: list = []
    for p in op.get("parameters") or []:
        p, _s, _c = _deref(p or {}, components, frozenset())
        name = p.get("name")
        if not name:
            continue
        schema = p.get("schema") or {}
        out.append(Param(name=name, type=schema.get("type") or "unknown",
                         required=bool(p.get("required"))))
    return out


def _response_fields(op: dict, components: dict):
    for code, resp in (op.get("responses") or {}).items():
        if not str(code).startswith("2"):
            continue
        content = (resp or {}).get("content") or {}
        schema = (content.get("application/json") or {}).get("schema")
        if schema:
            return _flatten(schema, components)
    return [], {}


def normalize_openapi(doc: dict) -> NormalizedSpec:
    components = ((doc.get("components") or {}).get("schemas") or {})
    operations: dict = {}
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method in _METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            key = f"{method.upper()} {path}"
            fields, enums = _response_fields(op, components)
            operations[key] = Operation(key=key,
                                        requestParams=_request_params(op, components),
                                        responseFields=fields, enums=enums)
    return NormalizedSpec(operations=operations)
