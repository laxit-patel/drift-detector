"""Canonical, format-agnostic representation of an API contract, plus a diff record.
Everything downstream of the normalizer operates on these — never on raw OpenAPI/GraphQL."""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Param:
    name: str
    type: str
    required: bool


@dataclass(frozen=True)
class Field:
    path: str            # dotted, arrays marked "[]", e.g. "payload.Orders[].AmazonOrderId"
    type: str            # openapi primitive, or "object"/"array"/"enum"/"ref"/"unknown"
    nullable: bool


@dataclass
class Operation:
    key: str
    requestParams: list        # list[Param]
    responseFields: list       # list[Field]
    enums: dict                # dict[str, list[str]] — dotted field path -> sorted values


@dataclass
class NormalizedSpec:
    operations: dict           # dict[str, Operation]

    def to_dict(self) -> dict:
        return {"operations": {
            k: {"key": op.key,
                "requestParams": [asdict(p) for p in op.requestParams],
                "responseFields": [asdict(f) for f in op.responseFields],
                "enums": {name: list(vals) for name, vals in op.enums.items()}}
            for k, op in self.operations.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "NormalizedSpec":
        ops = {}
        for k, o in (d.get("operations") or {}).items():
            ops[k] = Operation(
                key=o["key"],
                requestParams=[Param(**p) for p in o.get("requestParams", [])],
                responseFields=[Field(**f) for f in o.get("responseFields", [])],
                enums={name: list(vals) for name, vals in (o.get("enums") or {}).items()},
            )
        return cls(operations=ops)


@dataclass(frozen=True)
class ContractChange:
    opKey: str
    kind: str            # "operation" | "request_param" | "response_field" | "enum"
    verdict: str         # "BREAKING" | "ADDITIVE" | "AMBIGUOUS"
    before: str          # evidence fragment (may be "")
    after: str           # evidence fragment (may be "")
    detail: str
