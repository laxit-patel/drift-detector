# SP-API Contract Scan (Change-Monitor Plan 10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect real Amazon SP-API contract changes end-to-end — fetch the published API models, normalize them (they are **Swagger 2.0**, not OpenAPI 3.0), snapshot them in git state, and diff snapshot-over-snapshot into classified `ContractChange` records.

**Architecture:** Three units on top of the Plan 09 engine (`agent/lib/contract/`): a **Swagger-2.0 normalizer** (a thin sibling of `normalize_openapi` that reuses the existing `_deref`/`_flatten` — Swagger 2.0 uses the same JSON-Schema subset, only the schema map and response shape differ) behind a `normalize(doc)` dispatcher; an **SP-API SpecSource adapter** that fetches the ~63 model files from `amzn/selling-partner-api-models` (parsing with `strict=False` because the files contain literal control characters); and an **orchestrator + `contract-scan` CLI** that normalizes → loads the prior snapshot → diffs → saves the new snapshot, aggregating `ContractChange`s to a JSON. This plan produces detected CHANGES, not yet Findings — mapping `ContractChange`→`Finding`, usage-scoping to repos, and report/delta integration is Plan 11.

**Tech Stack:** Python 3.12 (project `.venv` — `source .venv/bin/activate`; system python is 3.10, do NOT use it). Tests: `python -m pytest -q`. Stdlib (`json`, `urllib`/injected HTTP). All network injected — no real HTTP in tests.

## Global Constraints

- **TDD**: failing test first, watch it fail, then implement. Frequent commits.
- **Deterministic + injected I/O**: the normalizer/dispatcher/orchestrator are pure; the SP-API adapter takes injected `fetch_tree`/`fetch_raw` callables (defaults do real GitHub HTTP, marked `# pragma: no cover`). No network/LLM/wall-clock in tests.
- **Swagger 2.0 is the reality**: SP-API models are `swagger: "2.0"` — schemas under `definitions`, a 2xx response's schema is `response["schema"]` (NOT `response["content"]["application/json"]["schema"]`), non-body params carry `type` at the top level (NOT under `schema`). `$ref`s are `#/definitions/X`. The existing `_deref` resolves by last path-segment, so passing `definitions` as the schema map makes `_flatten` work unchanged.
- **Control characters**: model files contain raw control chars; parse with `json.loads(text, strict=False)`.
- **Reuse the engine**: `normalize_swagger2` MUST reuse `_deref`/`_flatten` from `normalize_openapi.py` (do not reimplement schema flattening). Output is a `NormalizedSpec` identical in shape to the OpenAPI path.
- **v1 scope (documented):** request params = non-body params from the `parameters` array (body params skipped, matching the OpenAPI path's requestBody-deferred rule); response = first 2xx schema. No findings/scoping/report here (Plan 11).

---

## File Structure

- **Create** `agent/lib/contract/normalize.py` — `normalize_swagger2(doc)` + `normalize(doc)` dispatcher (picks 2.0 vs 3.0), reusing `_deref`/`_flatten`/`normalize_openapi`. (Task 1)
- **Create** `agent/lib/contract/spapi_source.py` — `SPAPISource` (or module fns) fetching the model file map `{api_name: doc}` via injected `fetch_tree`/`fetch_raw`. (Task 2)
- **Create** `agent/lib/contract/scan.py` — `contract_scan(specs, snapshot_root, marketplace, now, *, normalize_fn=normalize) -> list[dict]` orchestration. (Task 3)
- **Modify** `agent/cli.py` — add a `contract-scan` subcommand. (Task 3)
- **Create** tests: `tests/test_contract_normalize_swagger2.py` (T1), `tests/test_spapi_source.py` (T2), `tests/test_contract_scan.py` (T3).

Reference (read-only): `agent/lib/contract/normalize_openapi.py` (`_deref`, `_flatten`, `_METHODS`, `normalize_openapi`), `agent/lib/contract/differ.py` (`diff`), `agent/lib/contract/snapshot_store.py` (`save`/`load`), `agent/lib/contract/models.py`.

---

## Task 1: Swagger 2.0 normalizer + `normalize()` dispatcher

**Files:**
- Create: `agent/lib/contract/normalize.py`
- Test: `tests/test_contract_normalize_swagger2.py`

**Interfaces:**
- Consumes: `_deref`, `_flatten`, `_METHODS`, `normalize_openapi` (from `normalize_openapi.py`); `NormalizedSpec`, `Operation`, `Param` (models).
- Produces:
  - `normalize_swagger2(doc: dict) -> NormalizedSpec` — schema map = `doc["definitions"]`; per `paths.<path>.<method>` build `Operation(key="{METHOD} {path}", requestParams, responseFields, enums)`; request params = non-body params (`in != "body"`, `type` read at top level); response fields+enums = `_flatten` of the first 2xx `response["schema"]`.
  - `normalize(doc: dict) -> NormalizedSpec` — dispatcher: `normalize_swagger2` when `"swagger"` in doc, else `normalize_openapi`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_contract_normalize_swagger2.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_normalize_swagger2.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.contract.normalize'`.

- [ ] **Step 3: Implement the normalizer + dispatcher**

Create `agent/lib/contract/normalize.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_normalize_swagger2.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/contract/normalize.py tests/test_contract_normalize_swagger2.py
git commit -m "feat(contract): Swagger 2.0 normalizer + normalize() version dispatcher"
```

---

## Task 2: SP-API SpecSource adapter

**Files:**
- Create: `agent/lib/contract/spapi_source.py`
- Test: `tests/test_spapi_source.py`

**Interfaces:**
- Consumes: nothing from the engine (returns raw docs); `json` (parse `strict=False`).
- Produces:
  - `fetch_spapi_models(*, fetch_tree, fetch_raw) -> dict[str, dict]` — returns `{api_name: parsed_doc}`. `fetch_tree() -> list[str]` yields repo file paths; keep only `models/**/*.json`. For each kept path, `api_name` = the path with the leading `models/` stripped and the trailing `.json` removed (e.g. `models/orders-api-model/ordersV0.json` → `orders-api-model/ordersV0`). `fetch_raw(path) -> str` yields the file text, parsed via `json.loads(text, strict=False)`. A file that fails to parse is skipped (logged via the returned skip list), never crashes the batch.
  - Signature detail: returns a 2-tuple `(models: dict[str, dict], skipped: list[str])` so the caller can surface unreadable files as a coverage gap.
  - Default real-HTTP `fetch_tree`/`fetch_raw` (GitHub API against `amzn/selling-partner-api-models`) are provided but `# pragma: no cover`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_spapi_source.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_spapi_source.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.contract.spapi_source'`.

- [ ] **Step 3: Implement the adapter**

Create `agent/lib/contract/spapi_source.py`:

```python
"""Fetch the Amazon SP-API OpenAPI/Swagger model files from amzn/selling-partner-api-models.
The published models are Swagger 2.0 and contain literal control characters, so parsing uses
strict=False. HTTP is injected; a file that won't parse is skipped as a coverage gap."""
from __future__ import annotations

import json

_REPO = "amzn/selling-partner-api-models"
_API = "https://api.github.com"


def _default_fetch_tree():  # pragma: no cover - real GitHub HTTP
    import requests
    url = f"{_API}/repos/{_REPO}/git/trees/main?recursive=1"
    r = requests.get(url, timeout=30, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "change-monitor/1.0"})
    r.raise_for_status()
    return [b["path"] for b in r.json().get("tree", []) if b.get("type") == "blob"]


def _default_fetch_raw(path):  # pragma: no cover - real GitHub HTTP
    import requests
    url = f"{_API}/repos/{_REPO}/contents/{path}"
    r = requests.get(url, timeout=30, headers={"Accept": "application/vnd.github.raw",
                                               "User-Agent": "change-monitor/1.0"})
    r.raise_for_status()
    return r.text


def _api_name(path: str) -> str:
    # "models/orders-api-model/ordersV0.json" -> "orders-api-model/ordersV0"
    return path[len("models/"):].rsplit(".json", 1)[0]


def fetch_spapi_models(*, fetch_tree=_default_fetch_tree, fetch_raw=_default_fetch_raw):
    """Returns (models: dict[api_name -> parsed doc], skipped: list[path])."""
    models: dict = {}
    skipped: list = []
    for path in fetch_tree():
        if not (path.startswith("models/") and path.endswith(".json")):
            continue
        try:
            models[_api_name(path)] = json.loads(fetch_raw(path), strict=False)
        except (ValueError, OSError):
            skipped.append(path)
    return models, skipped
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_spapi_source.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/contract/spapi_source.py tests/test_spapi_source.py
git commit -m "feat(contract): SP-API SpecSource adapter (fetch models, strict=False, skip unparseable)"
```

---

## Task 3: Contract-scan orchestrator + CLI

**Files:**
- Create: `agent/lib/contract/scan.py`
- Modify: `agent/cli.py` (add the `contract-scan` subcommand)
- Test: `tests/test_contract_scan.py`

**Interfaces:**
- Consumes: `normalize` (Task 1), `snapshot_store.save`/`load` (Plan 09), `differ.diff` (Plan 09), `fetch_spapi_models` (Task 2), `NormalizedSpec`.
- Produces:
  - `contract_scan(specs: dict[str, dict], snapshot_root: str, marketplace: str, *, normalize_fn=normalize) -> list[dict]` — for each `(api, doc)`: normalize; load the prior snapshot; if a prior snapshot exists, `diff(prev, curr)` and append each change as a dict `{"marketplace", "api", "opKey", "kind", "verdict", "before", "after", "detail"}`; then save the new snapshot. First run (no prior snapshot for an api) records the baseline and yields no changes for it. Returns the aggregated change dicts across all apis.
  - CLI `contract-scan --marketplace sp-api --snapshots <dir> --out <changes.json> [--now <date>]` — fetches SP-API models via `fetch_spapi_models`, runs `contract_scan`, writes `{"marketplace", "runDate", "apisScanned", "skipped", "changes"}` JSON to `--out`, prints a one-line summary (`N changes across M apis (K breaking)`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_contract_scan.py`:

```python
from agent.lib.contract.scan import contract_scan


def _doc(with_email: bool):
    order_props = {"AmazonOrderId": {"type": "string"}}
    if with_email:
        order_props["buyerEmail"] = {"type": "string"}
    return {"swagger": "2.0",
            "paths": {"/orders/v0/orders": {"get": {"responses": {"200":
                {"schema": {"$ref": "#/definitions/Resp"}}}}}},
            "definitions": {
                "Resp": {"type": "object", "properties": {
                    "payload": {"type": "array", "items": {"$ref": "#/definitions/Order"}}}},
                "Order": {"type": "object", "properties": order_props}}}


def test_first_run_establishes_baseline_no_changes(tmp_path):
    changes = contract_scan({"orders/ordersV0": _doc(True)}, str(tmp_path), "sp-api")
    assert changes == []                                   # first snapshot -> nothing to diff
    # a snapshot now exists for the next run
    from agent.lib.contract import snapshot_store
    assert snapshot_store.load(str(tmp_path), "sp-api", "orders/ordersV0") is not None


def test_second_run_detects_buyeremail_removal(tmp_path):
    contract_scan({"orders/ordersV0": _doc(True)}, str(tmp_path), "sp-api")     # baseline
    changes = contract_scan({"orders/ordersV0": _doc(False)}, str(tmp_path), "sp-api")  # buyerEmail gone
    breaking = [c for c in changes if c["verdict"] == "BREAKING"]
    assert len(breaking) == 1
    assert breaking[0]["api"] == "orders/ordersV0"
    assert breaking[0]["marketplace"] == "sp-api"
    assert "buyerEmail" in breaking[0]["detail"]


def test_unchanged_second_run_yields_no_changes(tmp_path):
    contract_scan({"orders/ordersV0": _doc(True)}, str(tmp_path), "sp-api")
    assert contract_scan({"orders/ordersV0": _doc(True)}, str(tmp_path), "sp-api") == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_scan.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.contract.scan'`.

- [ ] **Step 3: Implement the orchestrator**

Create `agent/lib/contract/scan.py`:

```python
"""Contract-scan orchestration: normalize each spec, diff it against the prior snapshot,
save the new snapshot, and aggregate the classified changes. Deterministic; no I/O beyond
the snapshot store (the caller supplies already-fetched specs)."""
from __future__ import annotations

from agent.lib.contract import snapshot_store, differ
from agent.lib.contract.normalize import normalize


def contract_scan(specs: dict, snapshot_root: str, marketplace: str, *, normalize_fn=normalize) -> list:
    changes: list = []
    for api, doc in specs.items():
        curr = normalize_fn(doc)
        prev = snapshot_store.load(snapshot_root, marketplace, api)
        if prev is not None:
            for c in differ.diff(prev, curr):
                changes.append({"marketplace": marketplace, "api": api,
                                "opKey": c.opKey, "kind": c.kind, "verdict": c.verdict,
                                "before": c.before, "after": c.after, "detail": c.detail})
        snapshot_store.save(snapshot_root, marketplace, api, curr)
    return changes
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_scan.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Write the failing CLI test**

Append to `tests/test_contract_scan.py`:

```python
import json
import sys
from agent import cli


def test_cli_contract_scan_writes_changes(tmp_path, monkeypatch, capsys):
    # stub the SP-API fetch so no network happens
    import agent.lib.contract.scan as scan_mod
    calls = {"n": 0}

    def fake_fetch(**_kw):
        calls["n"] += 1
        with_email = calls["n"] == 1                      # run1 has buyerEmail, run2 doesn't
        return {"orders/ordersV0": _doc(with_email)}, []

    monkeypatch.setattr(scan_mod, "fetch_spapi_models", fake_fetch, raising=False)

    snaps = tmp_path / "snaps"
    out1 = tmp_path / "changes1.json"
    rc = cli.main(["contract-scan", "--marketplace", "sp-api", "--snapshots", str(snaps),
                   "--out", str(out1), "--now", "2026-07-13"])
    assert rc == 0
    doc1 = json.loads(out1.read_text())
    assert doc1["changes"] == [] and doc1["apisScanned"] == 1        # baseline

    out2 = tmp_path / "changes2.json"
    cli.main(["contract-scan", "--marketplace", "sp-api", "--snapshots", str(snaps),
              "--out", str(out2), "--now", "2026-07-20"])
    doc2 = json.loads(out2.read_text())
    assert any(c["verdict"] == "BREAKING" and "buyerEmail" in c["detail"] for c in doc2["changes"])
```

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_scan.py::test_cli_contract_scan_writes_changes -q`
Expected: FAIL — `contract-scan` is not a registered subcommand (argparse error / SystemExit).

- [ ] **Step 6: Wire the CLI subcommand**

In `agent/cli.py`, import the scan module near the other imports:

```python
from agent.lib.contract import scan as contract_scan_mod
from agent.lib.contract.spapi_source import fetch_spapi_models
```

Add a `_cmd_contract_scan` handler (place it beside the other `_cmd_*` functions):

```python
def _cmd_contract_scan(args) -> int:
    models, skipped = contract_scan_mod.fetch_spapi_models()
    changes = contract_scan_mod.contract_scan(models, args.snapshots, args.marketplace)
    doc = {"marketplace": args.marketplace, "runDate": args.now,
           "apisScanned": len(models), "skipped": skipped, "changes": changes}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    breaking = sum(1 for c in changes if c["verdict"] == "BREAKING")
    print(f"contract-scan {args.marketplace}: {len(changes)} change(s) across "
          f"{len(models)} api(s) ({breaking} breaking); {len(skipped)} skipped")
    return 0
```

Note: `_cmd_contract_scan` references `contract_scan_mod.fetch_spapi_models` so the CLI test's `monkeypatch.setattr(scan_mod, "fetch_spapi_models", ...)` intercepts it — therefore add `from agent.lib.contract.spapi_source import fetch_spapi_models` **inside** `agent/lib/contract/scan.py` (module-level) so it is patchable there. Update `scan.py` imports accordingly (add that import line to Task 3 Step 3's file).

Register the subparser where the other `sub.add_parser(...)` calls live:

```python
    pcs = sub.add_parser("contract-scan")
    pcs.add_argument("--marketplace", default="sp-api")
    pcs.add_argument("--snapshots", required=True)
    pcs.add_argument("--out", required=True)
    pcs.add_argument("--now", required=True)
    pcs.set_defaults(func=_cmd_contract_scan)
```

CONFIRMED: `agent/cli.py`'s `main()` dispatches via `set_defaults(func=...)` and a final `return args.func(args)` (with special-cases only for `deliver`/`discover`/`inventory`). So the `set_defaults(func=_cmd_contract_scan)` above plus a plain `_cmd_contract_scan(args)` signature is all that's needed — no if/elif branch to add.

Also add `fetch_spapi_models` to `agent/lib/contract/scan.py`'s module imports (so it is monkeypatchable on `scan_mod`):

```python
from agent.lib.contract.spapi_source import fetch_spapi_models
```

- [ ] **Step 7: Run the CLI test + full suite**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_scan.py -q`
Expected: PASS (4 passed).

Run the full suite (Plan 09 ended at 236; this adds normalize(3) + source(3) + scan(4) = 10):
Run: `source .venv/bin/activate && python -m pytest -q`
Expected: PASS — 246 passed.

- [ ] **Step 8: Commit**

```bash
git add agent/lib/contract/scan.py agent/cli.py tests/test_contract_scan.py
git commit -m "feat(contract): contract-scan orchestrator + CLI (snapshot + diff SP-API models)"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-07-13-contract-break-detection-design.md` and its "Plan C prerequisites" block):
- Prerequisite "confirm SP-API is OpenAPI 3.0 vs Swagger 2.0" → RESOLVED: it is Swagger 2.0; Task 1 adds `normalize_swagger2` + `normalize` dispatcher ✓
- "SP-API SpecSource adapter … fetch the OpenAPI JSON model files … at a resolved ref" → Task 2 ✓ (with the `strict=False` control-char handling the real files require)
- "Snapshot store … first run establishes baseline, emit nothing" → Task 3 `contract_scan` (prev is None → baseline, no changes) ✓, reusing Plan 09's `snapshot_store`
- "Semantic differ" reused, not reimplemented → Task 3 calls `differ.diff` ✓
- Reuses `_deref`/`_flatten` for Swagger 2.0 (schema subset is shared) → Task 1 ✓
- Out of scope for Plan 10 and correctly deferred to Plan 11: usage scoper, `ContractChange`→`Finding` mapping, severity, report/delta integration. ✓
- Documented Plan-C-prereq items still open after this plan (carry to Plan 11): `oneOf`/`anyOf` flattening; mapping to Findings must keep diff order deterministic (already sorted in Plan 09).

**Placeholder scan:** none — every code step is complete, runnable code. The one conditional instruction (CLI dispatch by `func` vs `if/elif` chain) is an explicit "match the existing pattern" directive with both branches specified, not a placeholder.

**Type consistency:** `normalize(doc) -> NormalizedSpec` and `normalize_swagger2(doc) -> NormalizedSpec` return the same type the differ consumes. `_deref`/`_flatten`/`_METHODS`/`normalize_openapi` imported from `normalize_openapi.py` with their existing signatures. `fetch_spapi_models(*, fetch_tree, fetch_raw) -> (dict, list)` — the 2-tuple is unpacked consistently in the CLI handler. `contract_scan(specs, snapshot_root, marketplace, *, normalize_fn=normalize) -> list[dict]` with the exact change-dict keys asserted in the tests. `Param(name, type, required)` / `Operation(key, requestParams, responseFields, enums)` field names match `models.py`.

**Known v1 simplifications (intentional, documented in Global Constraints):** body params skipped (both normalizers); response = first 2xx schema; param `$ref`s that point at `#/parameters/...` (shared params) are not resolved against a separate map — SP-API uses inline params, so this is low-risk and noted for Plan 11.
