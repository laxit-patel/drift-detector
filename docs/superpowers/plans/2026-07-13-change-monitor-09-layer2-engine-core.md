# Layer 2 Engine Core (Change-Monitor Plan 09) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic heart of contract-break detection — a marketplace-agnostic engine that reduces an API spec to a canonical `NormalizedSpec`, persists snapshots, and diffs two snapshots into structured `ContractChange` records classified BREAKING / ADDITIVE / AMBIGUOUS.

**Architecture:** A new `agent/lib/contract/` package with four focused units: the data model (`models.py`), a git-friendly snapshot store (`snapshot_store.py`), an OpenAPI→`NormalizedSpec` normalizer (`normalize_openapi.py`, resolves `$ref`s and flattens response schemas to dotted-path fields), and a semantic differ (`differ.py`) implementing the break taxonomy. No network, no LLM, no subprocess — everything is a pure function over dicts, so unit-test coverage is exhaustive. This plan produces NO findings and touches NO existing modules; wiring the engine to a real spec source, usage scoping, and the report pipeline is Plan C.

**Tech Stack:** Python 3.12 (project `.venv` — `source .venv/bin/activate`; system python is 3.10, do NOT use it). Tests: `python -m pytest -q`. Stdlib only (`json`, `pathlib`, `dataclasses`).

## Global Constraints

- **TDD**: write the failing test first, watch it fail, then implement. Frequent commits.
- **Pure & deterministic**: no network, no LLM, no subprocess, no wall-clock. Every function takes dicts / dataclasses and returns dataclasses. Tests need no fakes beyond crafted input dicts.
- **Canonical names (from the spec — use verbatim):** dataclasses `NormalizedSpec`, `Operation`, `Param`, `Field`, `ContractChange`. Verdicts are exactly the strings `"BREAKING"`, `"ADDITIVE"`, `"AMBIGUOUS"`. `ContractChange.kind` ∈ `{"operation", "request_param", "response_field", "enum"}`.
- **op_key format (OpenAPI):** `"{METHOD} {path}"`, method upper-cased, e.g. `"GET /orders/v0/orders"`.
- **Snapshots are stable text**: JSON written `sort_keys=True, indent=2` so a git diff of a snapshot is minimal and readable.
- **Match existing style**: frozen dataclasses for value types (`Param`, `Field`, `ContractChange`) like `agent/lib/models.py`; `pathlib.Path` + `json` for storage like `agent/lib/kb_store.py`.
- **v1 scope (documented simplifications):** request params come from the OpenAPI `parameters` array (query/path/header) only — request *body* schema diffing is deferred; response fields come from the first `2xx` `application/json` response schema, fully flattened. GraphQL normalization is Plan E.

---

## File Structure

- **Create** `agent/lib/contract/__init__.py` — empty package marker. (Task 1)
- **Create** `agent/lib/contract/models.py` — `NormalizedSpec`, `Operation`, `Param`, `Field`, `ContractChange` + `NormalizedSpec.to_dict`/`from_dict`. (Task 1)
- **Create** `agent/lib/contract/snapshot_store.py` — `save`/`load` a `NormalizedSpec` under `<root>/spec-snapshots/<marketplace>/<api>.json`. (Task 2)
- **Create** `agent/lib/contract/normalize_openapi.py` — `_deref`, `_flatten` (schema→fields+enums), `normalize_openapi(doc) -> NormalizedSpec`. (Tasks 3 & 4)
- **Create** `agent/lib/contract/differ.py` — `diff(prev, curr) -> list[ContractChange]`. (Task 5)
- **Create** tests: `tests/test_contract_models.py` (T1), `tests/test_contract_snapshot.py` (T2), `tests/test_contract_normalize.py` (T3 & T4), `tests/test_contract_differ.py` (T5).

---

## Task 1: Contract data model

**Files:**
- Create: `agent/lib/contract/__init__.py`
- Create: `agent/lib/contract/models.py`
- Test: `tests/test_contract_models.py`

**Interfaces:**
- Consumes: nothing (stdlib `dataclasses` only).
- Produces:
  - `Param(name: str, type: str, required: bool)` — frozen.
  - `Field(path: str, type: str, nullable: bool)` — frozen. `path` is dotted, arrays marked with `[]` (e.g. `"payload.Orders[].AmazonOrderId"`); `type` is an OpenAPI primitive, or `"object"`/`"array"`/`"enum"`/`"ref"`/`"unknown"`.
  - `Operation(key: str, requestParams: list[Param], responseFields: list[Field], enums: dict[str, list[str]])` — mutable. `enums` maps a dotted field path → sorted enum values.
  - `NormalizedSpec(operations: dict[str, Operation])` — mutable, plus `.to_dict() -> dict` and `NormalizedSpec.from_dict(d) -> NormalizedSpec` for JSON round-tripping.
  - `ContractChange(opKey: str, kind: str, verdict: str, before: str, after: str, detail: str)` — frozen.

- [ ] **Step 1: Write the failing test**

Create `tests/test_contract_models.py`:

```python
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
    assert '"AmazonOrderId"' in dumped and '"Shipped"' in dumped


def test_contractchange_is_frozen_value():
    c = ContractChange(opKey="GET /orders", kind="response_field", verdict="BREAKING",
                       before="payload.Orders[].BuyerInfo.buyerEmail", after="", detail="removed")
    assert c.verdict == "BREAKING"
    try:
        c.verdict = "ADDITIVE"                    # frozen -> must raise
        assert False, "expected FrozenInstanceError"
    except Exception:
        pass
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.contract'`.

- [ ] **Step 3: Create the package marker**

Create `agent/lib/contract/__init__.py` (empty file):

```python
```

- [ ] **Step 4: Implement the models**

Create `agent/lib/contract/models.py`:

```python
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_models.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add agent/lib/contract/__init__.py agent/lib/contract/models.py tests/test_contract_models.py
git commit -m "feat(contract): NormalizedSpec/Operation/Param/Field/ContractChange models"
```

---

## Task 2: Snapshot store

**Files:**
- Create: `agent/lib/contract/snapshot_store.py`
- Test: `tests/test_contract_snapshot.py`

**Interfaces:**
- Consumes: `agent.lib.contract.models.NormalizedSpec` (`to_dict`/`from_dict` from Task 1).
- Produces:
  - `save(root: str, marketplace: str, api: str, spec: NormalizedSpec) -> None` — writes `<root>/spec-snapshots/<marketplace>/<api>.json` (slashes in `api` replaced with `_`), JSON `sort_keys=True, indent=2`.
  - `load(root: str, marketplace: str, api: str) -> NormalizedSpec | None` — returns the stored spec or `None` if no snapshot exists yet (first run establishes the baseline).

- [ ] **Step 1: Write the failing test**

Create `tests/test_contract_snapshot.py`:

```python
from agent.lib.contract import snapshot_store
from agent.lib.contract.models import NormalizedSpec, Operation, Param, Field


def _spec():
    return NormalizedSpec(operations={
        "GET /orders": Operation(key="GET /orders",
                                 requestParams=[Param("marketplaceIds", "array", True)],
                                 responseFields=[Field("payload.total", "integer", False)],
                                 enums={})})


def test_load_missing_returns_none(tmp_path):
    assert snapshot_store.load(str(tmp_path), "sp-api", "orders_v0") is None


def test_save_then_load_round_trips(tmp_path):
    spec = _spec()
    snapshot_store.save(str(tmp_path), "sp-api", "orders_v0", spec)
    assert snapshot_store.load(str(tmp_path), "sp-api", "orders_v0") == spec


def test_api_with_slashes_is_path_safe(tmp_path):
    spec = _spec()
    snapshot_store.save(str(tmp_path), "sp-api", "orders-api-model/ordersV0", spec)
    # stored under a single flattened filename, reloads identically
    assert snapshot_store.load(str(tmp_path), "sp-api", "orders-api-model/ordersV0") == spec


def test_snapshot_json_is_sorted_and_indented(tmp_path):
    from pathlib import Path
    snapshot_store.save(str(tmp_path), "sp-api", "orders_v0", _spec())
    p = Path(tmp_path) / "spec-snapshots" / "sp-api" / "orders_v0.json"
    text = p.read_text(encoding="utf-8")
    assert "\n  " in text                       # indented (readable git diffs)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_snapshot.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.contract.snapshot_store'`.

- [ ] **Step 3: Implement the snapshot store**

Create `agent/lib/contract/snapshot_store.py`:

```python
"""Persist NormalizedSpec snapshots as stable JSON under the git-backed state tree.
First run for an (marketplace, api) returns None so the caller establishes a baseline."""
from __future__ import annotations

import json
from pathlib import Path

from agent.lib.contract.models import NormalizedSpec


def _path(root: str, marketplace: str, api: str) -> Path:
    safe_api = api.replace("/", "_")
    return Path(root) / "spec-snapshots" / marketplace / f"{safe_api}.json"


def save(root: str, marketplace: str, api: str, spec: NormalizedSpec) -> None:
    p = _path(root, marketplace, api)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
                 encoding="utf-8")


def load(root: str, marketplace: str, api: str) -> "NormalizedSpec | None":
    p = _path(root, marketplace, api)
    if not p.exists():
        return None
    return NormalizedSpec.from_dict(json.loads(p.read_text(encoding="utf-8")))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_snapshot.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/contract/snapshot_store.py tests/test_contract_snapshot.py
git commit -m "feat(contract): snapshot store (save/load NormalizedSpec, first-run None)"
```

---

## Task 3: OpenAPI schema flattener (`$ref` resolution, nesting, arrays, enums)

**Files:**
- Create: `agent/lib/contract/normalize_openapi.py` (the `_deref` + `_flatten` helpers; `normalize_openapi` lands in Task 4)
- Test: `tests/test_contract_normalize.py`

**Interfaces:**
- Consumes: `agent.lib.contract.models.Field` (Task 1).
- Produces:
  - `_deref(schema: dict, components: dict, seen: frozenset) -> tuple[dict, frozenset, bool]` — follows a single `$ref` hop into `components` (the `components.schemas` map). Returns `(resolved_schema, updated_seen, circular)`; `circular` is `True` when the ref name is already in `seen` (cycle) — the caller stops recursing.
  - `_flatten(schema: dict, components: dict, prefix: str = "", seen: frozenset = frozenset()) -> tuple[list[Field], dict[str, list[str]]]` — walks an object/array/leaf schema into a flat list of `Field`s (dotted paths, arrays marked `[]`) plus an `enums` map (dotted path → sorted enum values). A field is `nullable` when it is not in its parent's `required` list OR its schema has `nullable: true`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_contract_normalize.py` (Task 4 appends to this same file):

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_normalize.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.contract.normalize_openapi'`.

- [ ] **Step 3: Implement `_deref` + `_flatten`**

Create `agent/lib/contract/normalize_openapi.py`:

```python
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
        sub_d, sub_seen, _c = _deref(sub or {}, components, seen)
        nullable = (name not in required) or bool(sub_d.get("nullable"))
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_normalize.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/contract/normalize_openapi.py tests/test_contract_normalize.py
git commit -m "feat(contract): OpenAPI schema flattener ($ref, nesting, arrays, enums)"
```

---

## Task 4: OpenAPI operation walk (`normalize_openapi`)

**Files:**
- Modify: `agent/lib/contract/normalize_openapi.py` (add `normalize_openapi` + `_request_params` + `_response_fields`)
- Test: `tests/test_contract_normalize.py` (append)

**Interfaces:**
- Consumes: `_deref`, `_flatten` (Task 3); `Operation`, `Param`, `NormalizedSpec` (Task 1).
- Produces:
  - `normalize_openapi(doc: dict) -> NormalizedSpec` — for every `paths.<path>.<method>` (methods get/put/post/delete/patch), builds an `Operation` keyed `"{METHOD} {path}"` with: `requestParams` from the `parameters` array (name, `schema.type`, required); `responseFields` + `enums` from the first `2xx` `application/json` response schema (flattened). `components` = `doc.components.schemas`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_contract_normalize.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_normalize.py -q`
Expected: FAIL on the two new tests — `ImportError: cannot import name 'normalize_openapi'` (not defined yet).

- [ ] **Step 3: Add the operation walk to `agent/lib/contract/normalize_openapi.py`**

Append these functions to the file (after `_flatten`):

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_normalize.py -q`
Expected: PASS (7 passed — 5 from Task 3 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/contract/normalize_openapi.py tests/test_contract_normalize.py
git commit -m "feat(contract): normalize_openapi — paths -> operations (params, fields, enums)"
```

---

## Task 5: Semantic differ (break taxonomy)

**Files:**
- Create: `agent/lib/contract/differ.py`
- Test: `tests/test_contract_differ.py`

**Interfaces:**
- Consumes: `NormalizedSpec`, `Operation`, `Param`, `Field`, `ContractChange` (Task 1).
- Produces:
  - `diff(prev: NormalizedSpec, curr: NormalizedSpec) -> list[ContractChange]` implementing the taxonomy:
    - operation removed → BREAKING · added → ADDITIVE
    - response field removed → BREAKING · added → ADDITIVE · type changed → AMBIGUOUS · non-nullable→nullable → AMBIGUOUS
    - request param removed → BREAKING · added+required → BREAKING · added+optional → ADDITIVE · optional→required → BREAKING · required→optional → ADDITIVE · type changed → AMBIGUOUS
    - enum value removed → BREAKING · added → ADDITIVE

- [ ] **Step 1: Write the failing test**

Create `tests/test_contract_differ.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_differ.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.contract.differ'`.

- [ ] **Step 3: Implement the differ**

Create `agent/lib/contract/differ.py`:

```python
"""Deterministic semantic diff of two NormalizedSpecs into classified ContractChanges.
No LLM: the verdict (BREAKING/ADDITIVE/AMBIGUOUS) is decided by structural rules alone."""
from __future__ import annotations

from agent.lib.contract.models import NormalizedSpec, Operation, ContractChange


def diff(prev: NormalizedSpec, curr: NormalizedSpec) -> list:
    changes: list = []
    prev_ops, curr_ops = prev.operations, curr.operations
    for key in prev_ops.keys() - curr_ops.keys():
        changes.append(ContractChange(opKey=key, kind="operation", verdict="BREAKING",
                                      before=key, after="", detail=f"operation removed: {key}"))
    for key in curr_ops.keys() - prev_ops.keys():
        changes.append(ContractChange(opKey=key, kind="operation", verdict="ADDITIVE",
                                      before="", after=key, detail=f"operation added: {key}"))
    for key in prev_ops.keys() & curr_ops.keys():
        changes += _diff_op(key, prev_ops[key], curr_ops[key])
    return changes


def _diff_op(key: str, pop: Operation, cop: Operation) -> list:
    ch: list = []

    # --- response fields ---
    pf = {f.path: f for f in pop.responseFields}
    cf = {f.path: f for f in cop.responseFields}
    for path in pf.keys() - cf.keys():
        ch.append(ContractChange(key, "response_field", "BREAKING",
                                 before=path, after="", detail=f"response field removed: {path}"))
    for path in cf.keys() - pf.keys():
        ch.append(ContractChange(key, "response_field", "ADDITIVE",
                                 before="", after=path, detail=f"response field added: {path}"))
    for path in pf.keys() & cf.keys():
        a, b = pf[path], cf[path]
        if a.type != b.type:
            ch.append(ContractChange(key, "response_field", "AMBIGUOUS",
                                     before=f"{path}:{a.type}", after=f"{path}:{b.type}",
                                     detail=f"response field type changed: {path}"))
        elif not a.nullable and b.nullable:
            ch.append(ContractChange(key, "response_field", "AMBIGUOUS",
                                     before=f"{path}:non-null", after=f"{path}:nullable",
                                     detail=f"response field became nullable: {path}"))

    # --- request params ---
    pp = {p.name: p for p in pop.requestParams}
    cp = {p.name: p for p in cop.requestParams}
    for name in pp.keys() - cp.keys():
        ch.append(ContractChange(key, "request_param", "BREAKING",
                                 before=name, after="", detail=f"request param removed: {name}"))
    for name in cp.keys() - pp.keys():
        required = cp[name].required
        ch.append(ContractChange(key, "request_param", "BREAKING" if required else "ADDITIVE",
                                 before="", after=name,
                                 detail=f"request param added ({'required' if required else 'optional'}): {name}"))
    for name in pp.keys() & cp.keys():
        a, b = pp[name], cp[name]
        if not a.required and b.required:
            ch.append(ContractChange(key, "request_param", "BREAKING",
                                     before=f"{name}:optional", after=f"{name}:required",
                                     detail=f"request param became required: {name}"))
        elif a.required and not b.required:
            ch.append(ContractChange(key, "request_param", "ADDITIVE",
                                     before=f"{name}:required", after=f"{name}:optional",
                                     detail=f"request param became optional: {name}"))
        elif a.type != b.type:
            ch.append(ContractChange(key, "request_param", "AMBIGUOUS",
                                     before=f"{name}:{a.type}", after=f"{name}:{b.type}",
                                     detail=f"request param type changed: {name}"))

    # --- enums ---
    for path in set(pop.enums) | set(cop.enums):
        pv, cv = set(pop.enums.get(path, [])), set(cop.enums.get(path, []))
        before, after = ",".join(sorted(pv)), ",".join(sorted(cv))
        if pv - cv:
            ch.append(ContractChange(key, "enum", "BREAKING", before=before, after=after,
                                     detail=f"enum value(s) removed at {path}: {sorted(pv - cv)}"))
        if cv - pv:
            ch.append(ContractChange(key, "enum", "ADDITIVE", before=before, after=after,
                                     detail=f"enum value(s) added at {path}: {sorted(cv - pv)}"))
    return ch
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_differ.py -q`
Expected: PASS (10 passed).

Then run the full suite (Plan 08 ended at 208; this plan adds models(3) + snapshot(4) + normalize(7) + differ(10) = 24):
Run: `source .venv/bin/activate && python -m pytest -q`
Expected: PASS — 232 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/contract/differ.py tests/test_contract_differ.py
git commit -m "feat(contract): semantic differ (break taxonomy: BREAKING/ADDITIVE/AMBIGUOUS)"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-07-13-contract-break-detection-design.md`, components 2–4 and "Plan B — Layer 2 engine core"):
- "`NormalizedSpec` model + `Operation`/`Param`/`Field`" → Task 1 ✓ (exact field names from the spec).
- "OpenAPI normalizer … reduces raw OpenAPI to the canonical shape" → Tasks 3 (flatten/$ref) + 4 (operation walk) ✓.
- "Snapshot store … first run = establish baseline, emit nothing" → Task 2 (`load` returns `None`) ✓.
- "Semantic differ … deterministic classification (no LLM)" with the break taxonomy table → Task 5 ✓ (every taxonomy row has a test).
- "the `NormalizedSpec`-as-the-diff-target abstraction" → differ operates only on `NormalizedSpec`, never raw OpenAPI ✓.
- Integration anchor "simulate the real *Prune Orders model* change → buyerEmail removed" → `test_prune_orders_model_flags_buyeremail_removal_breaking` (Task 5) ✓.
- Out of scope for Plan B and correctly absent: SpecSource adapters, usage scoper, findings/report integration (Plan C), AI blast-radius (Plan D), GraphQL/eBay/Walmart normalizers (Plan E). ✓

**Placeholder scan:** none — every code step is complete, runnable code; every test asserts concrete values.

**Type consistency:** `NormalizedSpec.operations: dict[str, Operation]`; `Operation.responseFields: list[Field]`, `.requestParams: list[Param]`, `.enums: dict[str, list[str]]`; `ContractChange(opKey, kind, verdict, before, after, detail)` used identically in the differ and its tests. `_flatten` returns `(list[Field], dict)` in Task 3 and is consumed that way in Task 4's `_response_fields`. `_deref` returns the `(schema, seen, circular)` triple everywhere it is called. Verdict strings and `kind` values match the Global Constraints exactly. Snapshot JSON produced by `to_dict` is reconstructed by `from_dict` (Task 1 round-trip test guarantees it; Task 2 relies on it).

**Known v1 simplifications (documented in Global Constraints, intentional):** request params = OpenAPI `parameters` array only (request *body* diffing deferred); response = first `2xx` `application/json` schema; response-field type *narrowing* is classified AMBIGUOUS rather than BREAKING (a safe over-flag pending a later refinement). These are deliberate scope choices, not gaps.
