# Contract Findings + Report Integration (Change-Monitor Plan 11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn detected SP-API contract changes into persistent business-risk **Findings** on the repos that use SP-API, rendered in the weekly report — reusing the existing `Finding` / delta / report machinery.

**Architecture:** Three small units that bridge Plan 10's `contract-scan` output to the existing reporting tail: a **usage scoper** (maps each `ContractChange` to the repos whose inventory shows they use that marketplace's API), a **findings adapter** (maps scoped changes → `Finding` with deterministic severity, plus a *carry-forward* step so one-shot changes persist as ONGOING instead of aging out after two runs), and an **orchestrator + `contract-report` CLI** that ties scan-output + inventory + prior findings through `compute_delta` → `assemble_findings_doc` → `render_report`. No new report format, no LLM (that's Plan 12/blast-radius).

**Tech Stack:** Python 3.12 (project `.venv` — `source .venv/bin/activate`; system python is 3.10, do NOT use it). Tests: `python -m pytest -q`. Stdlib + existing agent modules.

## Global Constraints

- **TDD**: failing test first, watch it fail, then implement. Frequent commits.
- **Deterministic, no I/O in unit tests**: all inputs are dicts/lists; the CLI test writes small JSON to `tmp_path`. No network, no LLM.
- **Persistence is mandatory (Plan 10 final-review note #1):** `ContractChange`s are ONE-SHOT — a change fires only on the transition run. Findings MUST be carried forward from the prior findings doc into the current set so a break stays ONGOING until addressed, rather than being marked RESOLVED after two absent runs. Do NOT feed raw one-shot changes straight to `compute_delta`.
- **Reuse the shared tail** — `agent.lib.finding.Finding` / `finding_id`, `agent.delta.compute_delta`, `agent.report.assemble_findings_doc` / `render_report`. Do NOT fork the report format or the delta engine.
- **Finding id keying (Plan 10 note #3):** `finding_id(projectId, techKey, changeRef)` where `changeRef = f"{opKey}|{detail}"` — stable across runs so the delta engine matches. `projectId` distinguishes repos (two repos with the same change get distinct ids).
- **Severity map (from the spec):** BREAKING + used → ACTION · AMBIGUOUS + used → REVIEW · BREAKING + unused → watchlist (severity OK, `watchlist=True`) · ADDITIVE → OK.
- **v1 scope:** SP-API only (marketplace `sp-api` → techKey `api:amazon-sp-api`); the marketplace→techKey map is extensible. Findings do not auto-RESOLVE in v1 (carry-forward keeps them ONGOING); reverse-change resolution is a documented follow-up.

---

## File Structure

- **Create** `agent/contract_scope.py` — `scope_changes(changes, inventory)`: attach the using-repos to each change. (Task 1)
- **Create** `agent/contract_findings.py` — `changes_to_findings(scoped, repo_ids, now)` + `carry_forward(new_findings, prev_doc, now)`. (Task 2)
- **Create** `agent/contract_report.py` — `build_contract_report(changes, inventory, active, prev_doc, now)`. (Task 3)
- **Modify** `agent/cli.py` — add the `contract-report` subcommand. (Task 3)
- **Create** tests: `tests/test_contract_scope.py` (T1), `tests/test_contract_findings.py` (T2), `tests/test_contract_report.py` (T3).

Reference (read-only): `agent/lib/finding.py` (`Finding` fields + `finding_id`), `agent/delta.py` (`compute_delta(current, previous_doc, now) -> (delta, stamped)`), `agent/report.py` (`assemble_findings_doc(stamped, delta, coverage, watermarks, now)`, `render_report(doc)`), the Plan 10 change-dict shape `{marketplace, api, opKey, kind, verdict, before, after, detail}`, and the inventory `usedTechs` shape `[{tech_key, repo}]`.

---

## Task 1: Usage scoper

**Files:**
- Create: `agent/contract_scope.py`
- Test: `tests/test_contract_scope.py`

**Interfaces:**
- Consumes: the change dicts (Plan 10) + `inventory["usedTechs"]` (`[{tech_key, repo}]`).
- Produces:
  - `scope_changes(changes: list[dict], inventory: dict) -> list[dict]` — for each change, map `change["marketplace"]` to a techKey via `_MARKETPLACE_TECHKEY`, find the repos in `usedTechs` with that tech_key, and emit one scoped dict per using-repo `{**change, "techKey", "repo", "used": True}`; if no repo uses it (or the marketplace is unknown), emit a single `{**change, "techKey", "repo": "", "used": False}` row.
  - `_MARKETPLACE_TECHKEY: dict[str, str]` — `{"sp-api": "api:amazon-sp-api", "shopify": "api:shopify", "walmart": "api:walmart-marketplace", "ebay": "api:ebay"}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_contract_scope.py`:

```python
from agent.contract_scope import scope_changes


def _change(**kw):
    base = {"marketplace": "sp-api", "api": "orders/ordersV0", "opKey": "GET /orders",
            "kind": "response_field", "verdict": "BREAKING",
            "before": "payload.AmazonOrderId", "after": "",
            "detail": "response field removed: payload.AmazonOrderId"}
    base.update(kw)
    return base


def _inv(used):
    return {"usedTechs": [{"tech_key": tk, "repo": r} for tk, r in used]}


def test_scope_emits_one_row_per_using_repo():
    inv = _inv([("api:amazon-sp-api", "repoA"), ("api:amazon-sp-api", "repoB"),
                ("api:shopify", "repoC")])
    rows = scope_changes([_change()], inv)
    assert {(r["repo"], r["used"]) for r in rows} == {("repoA", True), ("repoB", True)}
    assert all(r["techKey"] == "api:amazon-sp-api" for r in rows)


def test_scope_unused_when_no_repo_uses_it():
    rows = scope_changes([_change()], _inv([("api:shopify", "repoC")]))
    assert len(rows) == 1 and rows[0]["used"] is False and rows[0]["repo"] == ""
    assert rows[0]["techKey"] == "api:amazon-sp-api"


def test_scope_unknown_marketplace_is_unused():
    rows = scope_changes([_change(marketplace="mystery")], _inv([("api:amazon-sp-api", "repoA")]))
    assert len(rows) == 1 and rows[0]["used"] is False and rows[0]["techKey"] == ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_scope.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.contract_scope'`.

- [ ] **Step 3: Implement the scoper**

Create `agent/contract_scope.py`:

```python
"""Scope each contract change to the repos whose inventory shows they use the affected
marketplace API, so a break can be turned into a per-repo Finding."""
from __future__ import annotations

# ContractChange["marketplace"] -> the inventory/patterns techKey (extensible).
_MARKETPLACE_TECHKEY = {
    "sp-api": "api:amazon-sp-api",
    "shopify": "api:shopify",
    "walmart": "api:walmart-marketplace",
    "ebay": "api:ebay",
}


def _repos_using(inventory: dict, tech_key: str) -> list:
    return sorted({u["repo"] for u in inventory.get("usedTechs", [])
                   if u.get("tech_key") == tech_key})


def scope_changes(changes: list, inventory: dict) -> list:
    out: list = []
    for c in changes:
        tech_key = _MARKETPLACE_TECHKEY.get(c.get("marketplace"), "")
        repos = _repos_using(inventory, tech_key) if tech_key else []
        if repos:
            for repo in repos:
                out.append({**c, "techKey": tech_key, "repo": repo, "used": True})
        else:
            out.append({**c, "techKey": tech_key, "repo": "", "used": False})
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_scope.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/contract_scope.py tests/test_contract_scope.py
git commit -m "feat(contract): usage scoper (map contract changes to repos that use the API)"
```

---

## Task 2: Findings adapter + carry-forward persistence

**Files:**
- Create: `agent/contract_findings.py`
- Test: `tests/test_contract_findings.py`

**Interfaces:**
- Consumes: scoped dicts (Task 1); `agent.lib.finding.Finding` / `finding_id`.
- Produces:
  - `changes_to_findings(scoped: list[dict], repo_ids: dict, now: str) -> list[Finding]` — one `Finding` per scoped row. `projectId = repo_ids.get(repo, 0)`; `id = finding_id(projectId, techKey, f"{opKey}|{detail}")`; `findingType="contract-drift"`, `category="integration"`, `tech=techKey.split(":")[-1]`; `changeType` from verdict via `_VERDICT_CHANGETYPE`; `severity`/`watchlist` via `_severity`; `evidence=detail`; `sourceUrl` built for SP-API from the api path.
  - `carry_forward(new_findings: list[Finding], prev_doc: dict, now: str) -> list[Finding]` — union `new_findings` with the prior `contract-drift` findings (from `prev_doc["findings"]` + `prev_doc["watchlist"]`), deduped by id (new supersedes prior of the same id). This makes one-shot changes persist as ONGOING.

- [ ] **Step 1: Write the failing test**

Create `tests/test_contract_findings.py`:

```python
from agent.contract_findings import changes_to_findings, carry_forward


def _scoped(verdict="BREAKING", used=True, repo="repoA", opKey="GET /orders",
            detail="response field removed: payload.AmazonOrderId", marketplace="sp-api",
            api="orders-api-model/ordersV0"):
    return {"marketplace": marketplace, "api": api, "opKey": opKey, "kind": "response_field",
            "verdict": verdict, "before": "payload.AmazonOrderId", "after": "",
            "detail": detail, "techKey": "api:amazon-sp-api", "repo": repo, "used": used}


def test_breaking_used_is_action():
    f = changes_to_findings([_scoped()], {"repoA": 7}, "2026-07-13")[0]
    assert f.severity == "ACTION" and f.watchlist is False
    assert f.findingType == "contract-drift" and f.techKey == "api:amazon-sp-api"
    assert f.projectId == 7 and f.changeType == "breaking" and "AmazonOrderId" in f.evidence
    assert f.sourceUrl.endswith("models/orders-api-model/ordersV0.json")


def test_ambiguous_used_is_review_and_additive_is_ok():
    review = changes_to_findings([_scoped(verdict="AMBIGUOUS")], {"repoA": 1}, "2026-07-13")[0]
    additive = changes_to_findings([_scoped(verdict="ADDITIVE")], {"repoA": 1}, "2026-07-13")[0]
    assert review.severity == "REVIEW" and additive.severity == "OK"


def test_breaking_unused_is_watchlist():
    f = changes_to_findings([_scoped(used=False, repo="")], {}, "2026-07-13")[0]
    assert f.watchlist is True and f.severity == "OK"


def test_same_change_two_repos_get_distinct_ids():
    rows = [_scoped(repo="repoA"), _scoped(repo="repoB")]
    fs = changes_to_findings(rows, {"repoA": 1, "repoB": 2}, "2026-07-13")
    assert fs[0].id != fs[1].id                                  # projectId distinguishes them


def test_carry_forward_persists_prior_contract_findings():
    prev_finding = changes_to_findings([_scoped()], {"repoA": 7}, "2026-07-01")[0]
    prev_doc = {"findings": [prev_finding.to_dict()], "watchlist": []}
    # This run detected nothing new (one-shot change already fired last week)
    carried = carry_forward([], prev_doc, "2026-07-13")
    assert len(carried) == 1 and carried[0].id == prev_finding.id  # persisted, not dropped


def test_carry_forward_ignores_non_contract_findings_and_dedups():
    prev_finding = changes_to_findings([_scoped()], {"repoA": 7}, "2026-07-01")[0]
    prev_doc = {"findings": [prev_finding.to_dict(),
                             {"id": "x", "findingType": "lifecycle", "severity": "ACTION",
                              "repo": "r", "techKey": "runtime:php", "tech": "php",
                              "projectId": 0, "category": "runtime", "changeType": "deprecation",
                              "sourceUrl": "", "sourceTier": 1}],
                "watchlist": []}
    fresh = changes_to_findings([_scoped(detail="response field removed: payload.OrderStatus")],
                                {"repoA": 7}, "2026-07-13")
    carried = carry_forward(fresh, prev_doc, "2026-07-13")
    ids = {f.id for f in carried}
    assert prev_finding.id in ids and fresh[0].id in ids         # both contract findings kept
    assert all(f.findingType == "contract-drift" for f in carried)  # lifecycle finding NOT carried
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_findings.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.contract_findings'`.

- [ ] **Step 3: Implement the findings adapter**

Create `agent/contract_findings.py`:

```python
"""Map scoped contract changes -> shared Finding objects, with carry-forward persistence so
one-shot contract changes stay ONGOING across weekly runs instead of aging out."""
from __future__ import annotations

from agent.lib.finding import Finding, finding_id

_VERDICT_CHANGETYPE = {"BREAKING": "breaking", "AMBIGUOUS": "behavioral", "ADDITIVE": "additive"}

_ACTIONS = {
    "ACTION": "Schedule migration — a breaking API contract change affects this repo.",
    "REVIEW": "Assess impact — an ambiguous contract change affects this repo.",
    "OK": "No action; recorded for the audit trail.",
}


def _severity(verdict: str, used: bool):
    """Returns (severity, watchlist). Unused breaks/ambiguities are recorded on the watchlist."""
    if verdict in ("BREAKING", "AMBIGUOUS"):
        sev = "ACTION" if verdict == "BREAKING" else "REVIEW"
        return (sev, False) if used else ("OK", True)
    return ("OK", False)                                        # ADDITIVE


def _source_url(marketplace: str, api: str) -> str:
    if marketplace == "sp-api":
        return f"https://github.com/amzn/selling-partner-api-models/blob/main/models/{api}.json"
    return ""


def changes_to_findings(scoped: list, repo_ids: dict, now: str) -> list:
    findings: list = []
    for s in scoped:
        verdict = s.get("verdict", "")
        severity, watch = _severity(verdict, s.get("used", False))
        change_ref = f"{s.get('opKey','')}|{s.get('detail','')}"
        pid = repo_ids.get(s.get("repo", ""), 0)
        tech_key = s.get("techKey", "")
        findings.append(Finding(
            id=finding_id(pid, tech_key, change_ref),
            projectId=pid, repo=s.get("repo", ""),
            findingType="contract-drift", category="integration",
            tech=tech_key.split(":")[-1], techKey=tech_key,
            changeType=_VERDICT_CHANGETYPE.get(verdict, "behavioral"),
            severity=severity, watchlist=watch,
            sourceUrl=_source_url(s.get("marketplace", ""), s.get("api", "")), sourceTier=1,
            evidence=s.get("detail", ""), changeEntryId=change_ref,
            firstSeen=now, lastSeen=now, recommendedAction=_ACTIONS.get(severity, ""),
        ))
    return findings


def carry_forward(new_findings: list, prev_doc: dict, now: str) -> list:
    by_id: dict = {}
    for d in (prev_doc.get("findings", []) + prev_doc.get("watchlist", [])):
        if d.get("findingType") == "contract-drift":
            by_id[d["id"]] = Finding.from_dict(d)
    for f in new_findings:
        by_id[f.id] = f                                        # new supersedes stale prior of same id
    return list(by_id.values())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_findings.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/contract_findings.py tests/test_contract_findings.py
git commit -m "feat(contract): changes->Finding adapter + carry-forward persistence (severity map)"
```

---

## Task 3: Contract-report orchestrator + CLI

**Files:**
- Create: `agent/contract_report.py`
- Modify: `agent/cli.py` (add the `contract-report` subcommand)
- Test: `tests/test_contract_report.py`

**Interfaces:**
- Consumes: `scope_changes` (T1), `changes_to_findings`/`carry_forward` (T2), `compute_delta` (delta.py), `assemble_findings_doc`/`render_report` (report.py).
- Produces:
  - `build_contract_report(changes: list, inventory: dict, active: dict, prev_doc: dict, now: str) -> dict` — returns `{"doc": <findings doc>, "report_md": <str>}`. Builds `repo_ids` from `active["active"]`; scopes; maps to findings; `carry_forward` for persistence; `compute_delta`; `assemble_findings_doc` with coverage `{"contractApisChanged": <#distinct api in changes>}`; `render_report`.
  - CLI `contract-report --changes <scan.json> --inventory <inv.json> --active <active.json> --prev <prev.json|-> --out-report <md> --out-findings <json> --now <date>`.

- [ ] **Step 1: Write the failing test (orchestrator)**

Create `tests/test_contract_report.py`:

```python
from agent.contract_report import build_contract_report


def _change(detail="response field removed: payload.AmazonOrderId", verdict="BREAKING"):
    return {"marketplace": "sp-api", "api": "orders-api-model/ordersV0", "opKey": "GET /orders",
            "kind": "response_field", "verdict": verdict, "before": "payload.AmazonOrderId",
            "after": "", "detail": detail}


_INV = {"usedTechs": [{"tech_key": "api:amazon-sp-api", "repo": "acme/orders-svc"}]}
_ACTIVE = {"active": [{"id": 42, "path_with_namespace": "acme/orders-svc"}]}


def test_breaking_change_becomes_action_on_using_repo():
    out = build_contract_report([_change()], _INV, _ACTIVE, {}, "2026-07-13")
    doc = out["doc"]
    assert doc["counts"]["action"] == 1
    f = doc["findings"][0]
    assert f["repo"] == "acme/orders-svc" and f["projectId"] == 42
    assert f["severity"] == "ACTION" and f["findingType"] == "contract-drift"
    assert "AmazonOrderId" in out["report_md"]                  # rendered in the report


def test_one_shot_change_persists_as_ongoing_next_run():
    run1 = build_contract_report([_change()], _INV, _ACTIVE, {}, "2026-07-13")
    assert run1["doc"]["delta"]["new"]                          # NEW on the transition run
    # Next run: the scan finds NOTHING (one-shot), prev = run1 doc
    run2 = build_contract_report([], _INV, _ACTIVE, run1["doc"], "2026-07-20")
    assert run2["doc"]["counts"]["action"] == 1                 # STILL flagged (persisted)
    assert run2["doc"]["delta"]["ongoing"] and not run2["doc"]["delta"]["resolved"]


def test_unused_break_is_watchlist_not_action():
    inv = {"usedTechs": []}                                     # nobody uses SP-API
    out = build_contract_report([_change()], inv, {"active": []}, {}, "2026-07-13")
    assert out["doc"]["counts"]["action"] == 0
    assert out["doc"]["counts"]["watchlist"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_report.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.contract_report'`.

- [ ] **Step 3: Implement the orchestrator**

Create `agent/contract_report.py`:

```python
"""Assemble a contract-drift findings doc + markdown report from scan output, reusing the
shared delta + report machinery. Persistence (carry_forward) keeps one-shot changes ONGOING."""
from __future__ import annotations

from agent.contract_scope import scope_changes
from agent.contract_findings import changes_to_findings, carry_forward
from agent.delta import compute_delta
from agent.report import assemble_findings_doc, render_report


def build_contract_report(changes: list, inventory: dict, active: dict, prev_doc: dict, now: str) -> dict:
    repo_ids = {r["path_with_namespace"]: r["id"] for r in active.get("active", [])}
    scoped = scope_changes(changes, inventory)
    new_findings = changes_to_findings(scoped, repo_ids, now)
    current = carry_forward(new_findings, prev_doc, now)        # persist one-shot changes
    delta, stamped = compute_delta(current, prev_doc, now)
    coverage = {"contractApisChanged": len({c.get("api", "") for c in changes})}
    watermarks = prev_doc.get("reportedWatermarks", {})
    doc = assemble_findings_doc(stamped, delta, coverage, watermarks, now)
    return {"doc": doc, "report_md": render_report(doc)}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_report.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Write the failing CLI test**

Append to `tests/test_contract_report.py`:

```python
import json
from agent import cli


def test_cli_contract_report_writes_findings(tmp_path):
    changes = tmp_path / "changes.json"
    changes.write_text(json.dumps({"marketplace": "sp-api", "runDate": "2026-07-13",
                                   "apisScanned": 1, "skipped": [], "changes": [_change()]}))
    inv = tmp_path / "inv.json"; inv.write_text(json.dumps(_INV))
    active = tmp_path / "active.json"; active.write_text(json.dumps(_ACTIVE))
    out_f = tmp_path / "findings.json"; out_r = tmp_path / "report.md"
    rc = cli.main(["contract-report", "--changes", str(changes), "--inventory", str(inv),
                   "--active", str(active), "--prev", "-", "--out-report", str(out_r),
                   "--out-findings", str(out_f), "--now", "2026-07-13"])
    assert rc == 0
    doc = json.loads(out_f.read_text())
    assert doc["counts"]["action"] == 1 and doc["findings"][0]["repo"] == "acme/orders-svc"
    assert "AmazonOrderId" in out_r.read_text()
```

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_report.py::test_cli_contract_report_writes_findings -q`
Expected: FAIL — `contract-report` is not a registered subcommand.

- [ ] **Step 6: Wire the CLI subcommand**

In `agent/cli.py`, add the import near the other imports:

```python
from agent import contract_report as contract_report_mod
```

Add the handler beside the other `_cmd_*` functions:

```python
def _cmd_contract_report(args) -> int:
    with open(args.changes, "r", encoding="utf-8") as fh:
        changes = json.load(fh).get("changes", [])
    with open(args.inventory, "r", encoding="utf-8") as fh:
        inventory = json.load(fh)
    with open(args.active, "r", encoding="utf-8") as fh:
        active = json.load(fh)
    prev_doc = {}
    if args.prev and args.prev != "-":
        try:
            with open(args.prev, "r", encoding="utf-8") as fh:
                prev_doc = json.load(fh)
        except FileNotFoundError:
            prev_doc = {}
    out = contract_report_mod.build_contract_report(changes, inventory, active, prev_doc, args.now)
    with open(args.out_findings, "w", encoding="utf-8") as fh:
        json.dump(out["doc"], fh, ensure_ascii=False, indent=2)
    with open(args.out_report, "w", encoding="utf-8") as fh:
        fh.write(out["report_md"])
    c = out["doc"]["counts"]
    print(f"Contract report {args.now}: {c['action']} ACTION / {c['review']} REVIEW / "
          f"{c['watchlist']} watch.")
    return 0
```

Register the subparser beside the other `sub.add_parser(...)` calls:

```python
    pcr = sub.add_parser("contract-report")
    for a in ("--changes", "--inventory", "--active", "--out-report", "--out-findings", "--now"):
        pcr.add_argument(a, required=True)
    pcr.add_argument("--prev", default="-")
    pcr.set_defaults(func=_cmd_contract_report)
```

(`main()` dispatches this via the generic `return args.func(args)` tail — no special-case branch needed.)

- [ ] **Step 7: Run the CLI test + full suite**

Run: `source .venv/bin/activate && python -m pytest tests/test_contract_report.py -q`
Expected: PASS (4 passed).

Run the full suite (Plan 10 ended at 246; this adds scope(3) + findings(6) + report(4) = 13):
Run: `source .venv/bin/activate && python -m pytest -q`
Expected: PASS — 259 passed.

- [ ] **Step 8: Commit**

```bash
git add agent/contract_report.py agent/cli.py tests/test_contract_report.py
git commit -m "feat(contract): contract-report orchestrator + CLI (scan -> findings -> report)"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-07-13-contract-break-detection-design.md`, component 5–7 and the "Plan 11 design notes"):
- "Usage scoper … tag each change used/unused" → Task 1 ✓ (marketplace→techKey map + `usedTechs` lookup)
- "Findings adapter → Finding (findingType contract-drift), severity BREAKING+used→ACTION / unused→watchlist / AMBIGUOUS+used→REVIEW" → Task 2 `_severity` + `changes_to_findings` ✓
- "reuse the existing Finding → delta → report pipeline" → Task 3 reuses `compute_delta` + `assemble_findings_doc` + `render_report` ✓
- Note #1 "changes are ONE-SHOT → persist via delta, don't rely on re-detection" → Task 2 `carry_forward` + Task 3 `test_one_shot_change_persists_as_ongoing_next_run` ✓
- Note #3 "Finding id = projectId|techKey|(opKey+detail)" → Task 2 `change_ref = f"{opKey}|{detail}"` via `finding_id` ✓
- Out of scope, correctly deferred: AI blast-radius narration (Plan 12); Shopify/Walmart/eBay sources (Plan 13); auto-RESOLVE via reverse-change detection (documented follow-up); unifying the contract report with the KB weekly report (run.sh can render both).

**Placeholder scan:** none — every code step is complete, runnable code with concrete assertions.

**Type consistency:** `scope_changes -> list[dict]` with keys `techKey/repo/used` consumed by `changes_to_findings`. `changes_to_findings -> list[Finding]` and `carry_forward -> list[Finding]` both feed `compute_delta(current, prev_doc, now) -> (delta, stamped)`; `assemble_findings_doc(stamped, delta, coverage, watermarks, now)` then `render_report(doc)` — signatures match `agent/delta.py` and `agent/report.py` exactly. `Finding(...)` uses only fields defined in `agent/lib/finding.py`. `repo_ids = {path_with_namespace: id}` mirrors `_cmd_classify_report`. CLI dispatch via `set_defaults(func=...)` matches the confirmed pattern.

**Known v1 simplifications (intentional):** SP-API only in the marketplace map (extensible); contract findings do not auto-RESOLVE (carry_forward keeps them ONGOING until addressed) — reverse-change resolution deferred; the contract report is a separate stream from the KB classify-report (both share the format; unification deferred).
