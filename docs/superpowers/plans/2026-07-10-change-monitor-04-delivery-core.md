# Change Monitor — Plan 04: Deterministic Delivery Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic tail of the pipeline — join `inventory.json` × KB drift/lifecycle into candidate findings, map them to severity (ACTION/REVIEW/OK) by rule, compute week-over-week deltas, render a dated markdown report that leads with business-logic risk, and deliver it (commit to a reports repo + post a Google Chat summary) — all with NO LLM and NO live services in tests. This produces a real weekly report for every finding whose severity is rule-decidable (lifecycle EOL, known-dead APIs, structured-feed change entries); entries needing judgement are flagged `needsReview` for Plan 05's Claude stage.

**Architecture:** A chain of pure/deterministic modules over files: `candidates(inventory, drift) → severity map → delta vs last week → report.md + findings.json → action router (commit + chat)`. Every side effect (GitLab write, Chat POST) goes through the injected client / an injected HTTP callable, so the whole plan is unit-testable with fixtures. Reuses Plan 01's KB drift engine, Plan 02's `GitLabClient`, and Plan 03's inventory. The Finding schema defined here is the exact contract Plan 05's LLM classify stage will target.

**Tech Stack:** Python 3.11+, pytest, PyYAML. No new dependencies.

## Global Constraints

- Python **3.11+**. Use the project venv: `source .venv/bin/activate` before python/pytest (Python 3.12; system python is 3.10).
- **No network, no wall-clock, no LLM in unit tests.** `now` (ISO date) is passed in; GitLab writes go through the injected `GitLabClient`; Chat POST goes through an injected `post` callable.
- **Severity vocabulary is ACTION / REVIEW / OK** (change-agnostic), with `findingType` ∈ {drift, lifecycle} and `changeType` ∈ {breaking, security, deprecation, behavioral, additive, eol}. This matches spec §6 and the KB Change Entry `changeType`.
- **Stable finding id** = `"{projectId}|{techKey}|{changeRef}"` where `changeRef` = the KB `changeEntryId` (drift) or `"lifecycle:<status>"` (lifecycle). Never LLM-phrased text — deltas diff on this id.
- **Never silent-OK / never fabricate:** every ACTION/REVIEW finding carries a `sourceUrl` + `sourceTier` + `evidence` copied from its KB Change Entry (the entries were themselves gated at ingest). `urgencyDays`/`deadlineDate` are computed by code, never guessed. Coverage from inventory is carried through into `findings.json` unchanged.
- **Reports repo is the ONLY GitLab write target.** The committer uses a separate write token (env), scoped to that one project; the read path never gains a write token. Scanned repos stay read-only.
- Package root `agent/`; tests in `tests/`; `pytest.ini` sets `pythonpath = .`. TDD throughout (failing test first). Explicit `git add` of only the files a task creates. Commit after every task.

**This is Plan 04 of the pipeline** (05 = Claude classify stage + trust gate + run.sh + dead-man's switch + registry feed adapter). Plan 05's LLM stage will re-severity `needsReview` findings and fill `businessRiskNote`; keep those fields on the Finding so that is additive.

---

### Task 1: Finding model + findings.json container

**Files:**
- Create: `agent/lib/finding.py`
- Test: `tests/test_finding.py`

**Interfaces:**
- Produces:
  - `Finding` (frozen dataclass) fields: `id, projectId, repo, findingType, category, tech, techKey, changeType, severity, sourceUrl, sourceTier` (required) + `versionInUse="", changeEntryId="", watchlist=False, evidence="", businessRiskNote="", deadlineDate="", urgencyDays=None, deltaState="", firstSeen="", lastSeen="", needsReview=False, recommendedAction=""`. `.to_dict()` / `Finding.from_dict(d)`.
  - `finding_id(project_id, tech_key, change_ref) -> str`.
  - `empty_findings_doc(now) -> dict` — the findings.json skeleton: `{schemaVersion:1, runDate, counts:{action,review,ok,watchlist}, delta:{new:[],resolved:[],ongoing:[]}, findings:[], watchlist:[], coverage:{}, reportedWatermarks:{}}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_finding.py
from agent.lib.finding import Finding, finding_id, empty_findings_doc

def test_finding_id():
    assert finding_id(12345, "api:amazon-sp-api", "sp|2026-07-03|x") == "12345|api:amazon-sp-api|sp|2026-07-03|x"

def test_finding_roundtrip():
    f = Finding(id="1|runtime:php|lifecycle:ACTION", projectId=1, repo="c/a",
                findingType="lifecycle", category="runtime", tech="PHP", techKey="runtime:php",
                changeType="eol", severity="ACTION", sourceUrl="https://eol", sourceTier=1,
                evidence="PHP 8.0 EOL 2023-11-26", urgencyDays=-600)
    assert Finding.from_dict(f.to_dict()) == f
    assert f.needsReview is False and f.watchlist is False

def test_empty_doc_shape():
    d = empty_findings_doc("2026-07-12")
    assert d["runDate"] == "2026-07-12"
    assert d["counts"] == {"action": 0, "review": 0, "ok": 0, "watchlist": 0}
    assert d["delta"] == {"new": [], "resolved": [], "ongoing": []}
    assert d["findings"] == [] and d["watchlist"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_finding.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.finding'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/finding.py
"""The Finding model + findings.json container. The contract Plan 05's LLM stage targets."""
from __future__ import annotations

from dataclasses import dataclass, asdict


def finding_id(project_id: int, tech_key: str, change_ref: str) -> str:
    return f"{project_id}|{tech_key}|{change_ref}"


@dataclass(frozen=True)
class Finding:
    id: str
    projectId: int
    repo: str
    findingType: str          # drift | lifecycle
    category: str             # integration | framework | library | runtime
    tech: str
    techKey: str
    changeType: str           # breaking|security|deprecation|behavioral|additive|eol
    severity: str             # ACTION | REVIEW | OK
    sourceUrl: str
    sourceTier: int
    versionInUse: str = ""
    changeEntryId: str = ""
    watchlist: bool = False
    evidence: str = ""
    businessRiskNote: str = ""
    deadlineDate: str = ""
    urgencyDays: "int | None" = None
    deltaState: str = ""
    firstSeen: str = ""
    lastSeen: str = ""
    needsReview: bool = False
    recommendedAction: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        return cls(**d)


def empty_findings_doc(now: str) -> dict:
    return {
        "schemaVersion": 1,
        "runDate": now,
        "counts": {"action": 0, "review": 0, "ok": 0, "watchlist": 0},
        "delta": {"new": [], "resolved": [], "ongoing": []},
        "findings": [],
        "watchlist": [],
        "coverage": {},
        "reportedWatermarks": {},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_finding.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/finding.py tests/test_finding.py
git commit -m "feat(delivery): Finding model + findings.json container"
```

---

### Task 2: Candidate builder (join inventory × KB drift + lifecycle)

**Files:**
- Create: `agent/candidates.py`
- Test: `tests/test_candidates.py`

**Interfaces:**
- Consumes: `agent.drift.drift_for_tech` (Plan 01), `agent.lib.kb_store.load_entries` (Plan 01), `ChangeEntry` (Plan 01).
- Produces:
  - `techkeys_in_use(inventory: dict) -> dict[str, list]` — maps each techKey used in the inventory to the list of `{repo, projectId, versionInUse, category}` usages. Derived from `inventory["records"]` (library/runtime; `versionInUse` = `declared_range` or `version_hint`) and `inventory["usedTechs"]` (integrations; `versionInUse=""`, category="integration"). `projectId` comes from an inventory `repoIds` map (see note).
  - `build_candidates(inventory, kb_root, reported_watermarks) -> list[dict]` — for each used techKey, `drift_for_tech(kb_root, techKey, reported_watermarks.get(techKey))`; for every drift `ChangeEntry` × every usage of that techKey, emit a candidate `{repo, projectId, techKey, category, versionInUse, changeEntry: <dict>}`. Returns a flat list. (Lifecycle EOL entries live in the KB too — from the `endoflife` adapter — so they flow through this same drift path; no separate lifecycle branch needed.)
- **Note on projectId:** inventory records from Plan 03 carry `repo` (path) but not the numeric id. This task adds a small requirement: `build_candidates` also accepts `repo_ids: dict[str,int]` (path→id, taken from `active-repos.json`) and stamps `projectId`. If a repo isn't in the map, `projectId=0` (still deterministic; Plan 05/orchestration passes the real map).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_candidates.py
from agent.lib.models import ChangeEntry
from agent.lib import kb_store
from agent import candidates

def _seed_kb(root, techkey, entries):
    kb_store.append_entries(root, techkey, entries)

def _ce(techkey, date, ctype, title):
    return ChangeEntry(techKey=techkey, date=date, changeType=ctype, title=title,
                       summary="", sourceUrl="https://x", sourceTier=1)

INV = {
    "records": [
        {"repo": "c/a", "tech_key": "runtime:php", "kind": "runtime", "version_hint": "8.0", "declared_range": "", "ecosystem": "docker"},
        {"repo": "c/a", "tech_key": "lib:npm/stripe", "kind": "library", "declared_range": "^12", "version_hint": "", "ecosystem": "npm"},
    ],
    "usedTechs": [{"repo": "c/a", "tech_key": "api:amazon-sp-api", "evidence": "x"}],
}
REPO_IDS = {"c/a": 42}

def test_techkeys_in_use_covers_records_and_used():
    m = candidates.techkeys_in_use(INV)
    assert "runtime:php" in m and "lib:npm/stripe" in m and "api:amazon-sp-api" in m
    assert m["api:amazon-sp-api"][0]["category"] == "integration"
    assert m["runtime:php"][0]["versionInUse"] == "8.0"

def test_build_candidates_joins_drift(tmp_path):
    root = str(tmp_path)
    _seed_kb(root, "runtime:php", [_ce("runtime:php", "2025-01-01", "eol", "PHP 8.0 EOL")])
    _seed_kb(root, "lib:npm/stripe", [])   # no drift
    cands = candidates.build_candidates(INV, root, {}, repo_ids=REPO_IDS)
    php = [c for c in cands if c["techKey"] == "runtime:php"]
    assert len(php) == 1
    assert php[0]["projectId"] == 42 and php[0]["repo"] == "c/a"
    assert php[0]["changeEntry"]["changeType"] == "eol"
    assert not any(c["techKey"] == "lib:npm/stripe" for c in cands)   # no drift -> no candidate

def test_build_candidates_respects_watermark(tmp_path):
    root = str(tmp_path)
    _seed_kb(root, "runtime:php", [_ce("runtime:php", "2025-01-01", "eol", "old")])
    cands = candidates.build_candidates(INV, root, {"runtime:php": "2025-06-01"}, repo_ids=REPO_IDS)
    assert cands == []    # entry older than watermark
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_candidates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.candidates'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/candidates.py
"""Join the inventory (what each repo uses) with KB drift (what changed) into candidate findings."""
from __future__ import annotations

from agent.drift import drift_for_tech


def techkeys_in_use(inventory: dict) -> dict:
    out: dict = {}
    for r in inventory.get("records", []):
        version = r.get("declared_range") or r.get("version_hint") or ""
        out.setdefault(r["tech_key"], []).append({
            "repo": r["repo"], "versionInUse": version,
            "category": "runtime" if r.get("kind") == "runtime" else "library",
        })
    for u in inventory.get("usedTechs", []):
        out.setdefault(u["tech_key"], []).append({
            "repo": u["repo"], "versionInUse": "", "category": "integration",
        })
    return out


def build_candidates(inventory: dict, kb_root: str, reported_watermarks: dict, *, repo_ids: dict) -> list:
    used = techkeys_in_use(inventory)
    candidates: list = []
    for tech_key, usages in used.items():
        entries = drift_for_tech(kb_root, tech_key, reported_watermarks.get(tech_key))
        for ce in entries:
            for u in usages:
                candidates.append({
                    "repo": u["repo"],
                    "projectId": repo_ids.get(u["repo"], 0),
                    "techKey": tech_key,
                    "category": u["category"],
                    "versionInUse": u["versionInUse"],
                    "changeEntry": ce.to_dict(),
                })
    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_candidates.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/candidates.py tests/test_candidates.py
git commit -m "feat(delivery): candidate builder (inventory x KB drift join)"
```

---

### Task 3: Deterministic severity mapper (§6 precedence)

**Files:**
- Create: `agent/classify_rules.py`
- Test: `tests/test_classify_rules.py`

**Interfaces:**
- Consumes: `Finding`/`finding_id` (Task 1); candidate dicts (Task 2).
- Produces:
  - `days_until(date_iso, now) -> int | None` — signed day delta (`date - now`); `None` if `date_iso` empty/invalid.
  - `map_severity(change_type, deadline_date, now, review_horizon_months=6) -> (severity, needs_review)` — the §6 rule:
    - `breaking` or `security` → `("ACTION", False)`
    - `eol` or `deprecation`: if a `deadline_date` is set — passed (`days_until<0`) → `("ACTION", False)`; within horizon (`0<=days<=horizon_days`) → `("REVIEW", False)`; beyond horizon → `("OK", False)`. If no date → `("REVIEW", False)`.
    - `behavioral` → `("REVIEW", False)`
    - `additive` → `("OK", True)`  ← the LLM (Plan 05) re-judges these (a changelog entry defaulted to "additive" at ingest may actually be breaking)
    - anything else → `("REVIEW", True)`
  - `candidate_to_finding(candidate, now, *, review_horizon_months=6, category=None) -> Finding` — builds a `Finding` from a candidate: pulls `changeType`/`sourceUrl`/`sourceTier`/`evidence`/`date` from `candidate["changeEntry"]`; `deadlineDate` = the entry's `date` for eol/deprecation else ""; `urgencyDays = days_until(deadlineDate, now)`; `findingType` = "lifecycle" if changeType == "eol" else "drift"; `changeRef` = `changeEntry.id` (drift) or `f"lifecycle:{severity}"` (eol); `id = finding_id(projectId, techKey, changeRef)`; `firstSeen=lastSeen=now`; `recommendedAction` = a templated string per severity.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_classify_rules.py
from agent.classify_rules import days_until, map_severity, candidate_to_finding

def test_days_until():
    assert days_until("2026-07-20", "2026-07-10") == 10
    assert days_until("2026-07-01", "2026-07-10") == -9
    assert days_until("", "2026-07-10") is None

def test_map_severity_rules():
    assert map_severity("breaking", "", "2026-07-10") == ("ACTION", False)
    assert map_severity("security", "", "2026-07-10") == ("ACTION", False)
    assert map_severity("eol", "2020-01-01", "2026-07-10") == ("ACTION", False)      # passed
    assert map_severity("eol", "2026-09-01", "2026-07-10") == ("REVIEW", False)      # ~2 months
    assert map_severity("eol", "2030-01-01", "2026-07-10") == ("OK", False)          # far future
    assert map_severity("deprecation", "", "2026-07-10") == ("REVIEW", False)
    assert map_severity("behavioral", "", "2026-07-10") == ("REVIEW", False)
    assert map_severity("additive", "", "2026-07-10") == ("OK", True)                # needs LLM judgement

def test_candidate_to_finding_eol():
    cand = {"repo": "c/a", "projectId": 42, "techKey": "runtime:php", "category": "runtime",
            "versionInUse": "8.0", "changeEntry": {
                "id": "runtime:php|2020-01-01|php-8-0-eol", "changeType": "eol", "date": "2020-01-01",
                "sourceUrl": "https://eol", "sourceTier": 1, "evidence": "PHP 8.0 EOL"}}
    f = candidate_to_finding(cand, "2026-07-10")
    assert f.severity == "ACTION" and f.findingType == "lifecycle"
    assert f.urgencyDays < 0 and f.deadlineDate == "2020-01-01"
    assert f.id.startswith("42|runtime:php|lifecycle:")
    assert f.sourceUrl == "https://eol" and f.evidence == "PHP 8.0 EOL"

def test_candidate_to_finding_additive_needs_review():
    cand = {"repo": "c/a", "projectId": 1, "techKey": "api:shopify", "category": "integration",
            "versionInUse": "", "changeEntry": {
                "id": "shopify|2026-07-01|x", "changeType": "additive", "date": "2026-07-01",
                "sourceUrl": "https://s", "sourceTier": 1, "evidence": "some change"}}
    f = candidate_to_finding(cand, "2026-07-10")
    assert f.severity == "OK" and f.needsReview is True and f.findingType == "drift"
    assert f.changeEntryId == "shopify|2026-07-01|x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_classify_rules.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/classify_rules.py
"""Deterministic severity mapping (spec §6). Rule-decidable cases resolve here;
'additive'/ambiguous entries are marked needsReview for Plan 05's LLM stage."""
from __future__ import annotations

from datetime import date

from agent.lib.finding import Finding, finding_id

_ACTION_TYPES = {"breaking", "security"}
_LIFECYCLE_TYPES = {"eol", "deprecation"}


def days_until(date_iso: str, now: str) -> "int | None":
    if not date_iso:
        return None
    try:
        return (date.fromisoformat(date_iso) - date.fromisoformat(now)).days
    except ValueError:
        return None


def map_severity(change_type, deadline_date, now, review_horizon_months=6):
    if change_type in _ACTION_TYPES:
        return "ACTION", False
    if change_type in _LIFECYCLE_TYPES:
        d = days_until(deadline_date, now)
        if d is None:
            return "REVIEW", False
        if d < 0:
            return "ACTION", False
        if d <= review_horizon_months * 30:
            return "REVIEW", False
        return "OK", False
    if change_type == "behavioral":
        return "REVIEW", False
    if change_type == "additive":
        return "OK", True
    return "REVIEW", True


_ACTIONS = {
    "ACTION": "Schedule migration work — a breaking/sunset change affects this repo.",
    "REVIEW": "Assess impact and monitor — a deprecation/behavioral change or upcoming EOL.",
    "OK": "No action; recorded for the audit trail.",
}


def candidate_to_finding(candidate, now, *, review_horizon_months=6) -> Finding:
    ce = candidate["changeEntry"]
    ctype = ce.get("changeType", "additive")
    deadline = ce.get("date", "") if ctype in _LIFECYCLE_TYPES else ""
    severity, needs_review = map_severity(ctype, deadline, now, review_horizon_months)
    finding_type = "lifecycle" if ctype == "eol" else "drift"
    change_ref = f"lifecycle:{severity}" if ctype == "eol" else ce.get("id", "")
    return Finding(
        id=finding_id(candidate["projectId"], candidate["techKey"], change_ref),
        projectId=candidate["projectId"], repo=candidate["repo"],
        findingType=finding_type, category=candidate.get("category", "library"),
        tech=candidate["techKey"].split("/")[-1], techKey=candidate["techKey"],
        changeType=ctype, severity=severity,
        sourceUrl=ce.get("sourceUrl", ""), sourceTier=int(ce.get("sourceTier", 1)),
        versionInUse=candidate.get("versionInUse", ""),
        changeEntryId=ce.get("id", ""), evidence=ce.get("evidence", ""),
        deadlineDate=deadline, urgencyDays=days_until(deadline, now),
        firstSeen=now, lastSeen=now, needsReview=needs_review,
        recommendedAction=_ACTIONS[severity],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_classify_rules.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/classify_rules.py tests/test_classify_rules.py
git commit -m "feat(delivery): deterministic severity mapper (spec section 6 precedence)"
```

---

### Task 4: Delta engine (NEW/RESOLVED/ONGOING + flap damping)

**Files:**
- Create: `agent/delta.py`
- Test: `tests/test_delta.py`

**Interfaces:**
- Consumes: `Finding` (Task 1).
- Produces:
  - `compute_delta(current: list[Finding], previous_doc: dict, now: str) -> dict` — returns `{"new": [...ids], "resolved": [...ids], "ongoing": [...ids]}` over findings with severity ∈ {ACTION, REVIEW}. `previous_doc` is last week's findings.json (`{}` or missing → first run: everything NEW, no RESOLVED). Also stamps `deltaState` on each current Finding (returns them via a second value) and carries `firstSeen` forward from the previous doc for ONGOING findings.
  - Signature: `compute_delta(current, previous_doc, now) -> (delta: dict, stamped: list[Finding])`.
  - **Flap damping:** a finding present last week (ACTION/REVIEW) and absent this week is RESOLVED only if it was also absent-or-OK the week before — approximated here by a `resolved_pending` set persisted in the previous doc: first disappearance → recorded in `reportedWatermarks["_resolvedPending"]` (not yet reported RESOLVED, deltaState stays out of resolved); second consecutive disappearance → RESOLVED. Keep it simple: if id in previous `_resolvedPending`, report RESOLVED now; else add to pending and do NOT report.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_delta.py
from agent.lib.finding import Finding
from agent import delta

def _f(fid, sev="ACTION", first="2026-07-05"):
    return Finding(id=fid, projectId=1, repo="c/a", findingType="drift", category="library",
                   tech="x", techKey="lib:npm/x", changeType="breaking", severity=sev,
                   sourceUrl="https://x", sourceTier=1, firstSeen=first, lastSeen=first)

def _doc(ids, pending=None):
    return {"findings": [_f(i).to_dict() for i in ids],
            "reportedWatermarks": {"_resolvedPending": pending or []}}

def test_first_run_all_new():
    d, stamped = delta.compute_delta([_f("a"), _f("b")], {}, "2026-07-12")
    assert set(d["new"]) == {"a", "b"} and d["resolved"] == [] and d["ongoing"] == []
    assert all(s.deltaState == "NEW" for s in stamped)

def test_ongoing_and_new():
    prev = _doc(["a"])
    d, stamped = delta.compute_delta([_f("a"), _f("b")], prev, "2026-07-12")
    assert d["new"] == ["b"] and d["ongoing"] == ["a"]
    a = next(s for s in stamped if s.id == "a")
    assert a.deltaState == "ONGOING" and a.firstSeen == "2026-07-05"     # carried forward

def test_resolved_needs_two_consecutive_absences():
    # 'a' present last week, gone this week -> first absence -> pending, NOT resolved yet
    prev = _doc(["a"])
    d, _ = delta.compute_delta([], prev, "2026-07-12")
    assert d["resolved"] == []
    # next week 'a' still gone AND was pending -> RESOLVED
    prev2 = {"findings": [], "reportedWatermarks": {"_resolvedPending": ["a"]}}
    d2, _ = delta.compute_delta([], prev2, "2026-07-19")
    assert d2["resolved"] == ["a"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_delta.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/delta.py
"""Week-over-week delta over stable finding ids, with 2-run flap damping on RESOLVED."""
from __future__ import annotations

from dataclasses import replace

from agent.lib.finding import Finding

_ACTIONABLE = {"ACTION", "REVIEW"}


def _actionable_ids(findings_dicts):
    return {f["id"]: f for f in findings_dicts if f.get("severity") in _ACTIONABLE}


def compute_delta(current: list, previous_doc: dict, now: str):
    prev_findings = _actionable_ids(previous_doc.get("findings", []))
    prev_pending = set((previous_doc.get("reportedWatermarks") or {}).get("_resolvedPending", []))

    curr = {f.id: f for f in current if f.severity in _ACTIONABLE}
    curr_ids, prev_ids = set(curr), set(prev_findings)

    new = sorted(curr_ids - prev_ids)
    ongoing = sorted(curr_ids & prev_ids)

    disappeared = prev_ids - curr_ids
    resolved = sorted(i for i in disappeared if i in prev_pending)   # 2nd consecutive absence
    still_pending = sorted(i for i in disappeared if i not in prev_pending)  # 1st absence

    stamped = []
    for f in current:
        state = "NEW" if f.id in new else ("ONGOING" if f.id in ongoing else f.deltaState)
        first_seen = f.firstSeen
        if f.id in ongoing:
            first_seen = prev_findings[f.id].get("firstSeen", f.firstSeen)
        stamped.append(replace(f, deltaState=state, firstSeen=first_seen))

    return ({"new": new, "resolved": resolved, "ongoing": ongoing,
             "_resolvedPending": still_pending}, stamped)
```

Note: the report/orchestration writes `delta["_resolvedPending"]` into next week's `findings.json["reportedWatermarks"]["_resolvedPending"]`; the `_resolvedPending` key is popped out of the user-facing `delta` block before rendering (Task 5 handles display; the raw dict keeps it for persistence).

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_delta.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/delta.py tests/test_delta.py
git commit -m "feat(delivery): delta engine with 2-run flap damping"
```

---

### Task 5: Report writer

**Files:**
- Create: `agent/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `Finding` (Task 1).
- Produces:
  - `assemble_findings_doc(stamped: list[Finding], delta: dict, coverage: dict, watermarks: dict, now: str) -> dict` — builds the final `findings.json` dict: counts by severity + watchlist, `delta` (with `_resolvedPending` moved into `reportedWatermarks`), `findings` (non-watchlist), `watchlist` (findings with `watchlist=True`), `coverage`, `reportedWatermarks`.
  - `render_report(doc: dict) -> str` — deterministic markdown. Sections in order: (1) `# API/Integration Change Report — <runDate>`; (2) `## ⚠️ Business-logic risk (ACTION)` — ACTION findings grouped by techKey, each line `- <repo> — <tech> <versionInUse>: <evidence> (<changeType>) [source](<url>)`; (3) `## Delta` — `🆕 N new · ✅ N resolved · ⏳ N ongoing`; (4) `## Review` — REVIEW findings as a table; (5) `## Early-warning watchlist`; (6) `## Coverage` — reposScanned + any coverage gaps; (7) `## Run metadata`. Empty sections render a "_none_" line (never omitted — absence must be visible).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report.py
from agent.lib.finding import Finding
from agent import report

def _f(fid, sev, tk, repo="c/a", ct="breaking", evid="changed", wl=False):
    return Finding(id=fid, projectId=1, repo=repo, findingType="drift", category="library",
                   tech=tk.split("/")[-1], techKey=tk, changeType=ct, severity=sev,
                   sourceUrl="https://src", sourceTier=1, evidence=evid, deltaState="NEW",
                   watchlist=wl, versionInUse="12.0")

def test_assemble_counts_and_split():
    stamped = [_f("1", "ACTION", "lib:npm/a"), _f("2", "REVIEW", "lib:npm/b"),
               _f("3", "OK", "lib:npm/c"), _f("4", "REVIEW", "api:x", wl=True)]
    doc = report.assemble_findings_doc(stamped, {"new": ["1"], "resolved": [], "ongoing": [], "_resolvedPending": ["9"]},
                                       {"reposScanned": 3}, {"runtime:php": "2026-07-01"}, "2026-07-12")
    assert doc["counts"] == {"action": 1, "review": 1, "ok": 1, "watchlist": 1}
    assert len(doc["findings"]) == 3 and len(doc["watchlist"]) == 1
    assert doc["reportedWatermarks"]["_resolvedPending"] == ["9"]      # persisted for next week
    assert "_resolvedPending" not in doc["delta"]                     # stripped from display block

def test_render_leads_with_business_risk():
    doc = report.assemble_findings_doc([_f("1", "ACTION", "api:amazon-sp-api", evid="BuyerInfo now optional")],
                                       {"new": ["1"], "resolved": [], "ongoing": []}, {"reposScanned": 2}, {}, "2026-07-12")
    md = report.render_report(doc)
    assert md.index("Business-logic risk") < md.index("Delta")       # risk section leads
    assert "BuyerInfo now optional" in md and "c/a" in md
    assert "2026-07-12" in md

def test_empty_sections_show_none():
    doc = report.assemble_findings_doc([], {"new": [], "resolved": [], "ongoing": []}, {"reposScanned": 0}, {}, "2026-07-12")
    md = report.render_report(doc)
    assert "_none_" in md    # empty ACTION section is explicit, not omitted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/report.py
"""Deterministic findings.json assembly + markdown rendering (business-logic-risk lead)."""
from __future__ import annotations


def assemble_findings_doc(stamped, delta, coverage, watermarks, now):
    delta = dict(delta)
    pending = delta.pop("_resolvedPending", [])
    findings = [f for f in stamped if not f.watchlist]
    watch = [f for f in stamped if f.watchlist]
    counts = {"action": 0, "review": 0, "ok": 0, "watchlist": len(watch)}
    for f in findings:
        counts[f.severity.lower()] = counts.get(f.severity.lower(), 0) + 1
    wm = dict(watermarks or {})
    wm["_resolvedPending"] = pending
    return {
        "schemaVersion": 1, "runDate": now, "counts": counts, "delta": delta,
        "findings": [f.to_dict() for f in findings],
        "watchlist": [f.to_dict() for f in watch],
        "coverage": coverage or {}, "reportedWatermarks": wm,
    }


def _line(f):
    return (f"- {f['repo']} — {f['tech']} {f.get('versionInUse','')}: {f['evidence']} "
            f"({f['changeType']}) [source]({f['sourceUrl']})")


def render_report(doc: dict) -> str:
    findings = doc["findings"]
    action = [f for f in findings if f["severity"] == "ACTION"]
    review = [f for f in findings if f["severity"] == "REVIEW"]
    d = doc["delta"]
    out = [f"# API/Integration Change Report — {doc['runDate']}", ""]

    out += ["## ⚠️ Business-logic risk (ACTION)", ""]
    out += ([_line(f) for f in action] or ["_none_"]) + [""]

    out += ["## Delta", "",
            f"🆕 {len(d.get('new',[]))} new · ✅ {len(d.get('resolved',[]))} resolved · ⏳ {len(d.get('ongoing',[]))} ongoing", ""]

    out += ["## Review", ""]
    if review:
        out += ["| Repo | Tech | Version | Change | Source |", "|---|---|---|---|---|"]
        out += [f"| {f['repo']} | {f['tech']} | {f.get('versionInUse','')} | {f['changeType']} | [src]({f['sourceUrl']}) |" for f in review]
    else:
        out += ["_none_"]
    out += [""]

    out += ["## Early-warning watchlist", ""]
    out += ([_line(f) for f in doc["watchlist"]] or ["_none_"]) + [""]

    cov = doc.get("coverage", {})
    out += ["## Coverage", "", f"Repos scanned: {cov.get('reposScanned', 0)}"]
    for key in ("reposErrored", "reposNoManifests", "manifestsUnparsed", "presenceUnavailable"):
        items = cov.get(key) or []
        if items:
            out += [f"- {key}: {len(items)}"]
    out += [""]

    c = doc["counts"]
    out += ["## Run metadata", "",
            f"Counts: {c['action']} ACTION · {c['review']} REVIEW · {c['ok']} OK · {c['watchlist']} watchlist"]
    return "\n".join(out) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_report.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/report.py tests/test_report.py
git commit -m "feat(delivery): findings.json assembly + markdown report (business-risk lead)"
```

---

### Task 6: Google Chat client

**Files:**
- Create: `agent/lib/chat.py`
- Test: `tests/test_chat.py`

**Interfaces:**
- Produces:
  - `build_summary_text(doc: dict, report_url: str) -> str` — the plain-text Chat message: title with runDate, a counts line, an "urgent (ACTION)" bullet list capped at `max_items` (default 10), the delta line, and a `<url|Full report>` link.
  - `build_failure_text(stage: str, error: str, now: str, last_good: str) -> str`.
  - `post_chat(webhook_url, text, *, post=<http>) -> bool` — POSTs `{"text": text}`; injected `post(url, json) -> status_int`; returns True on 2xx, False otherwise (never raises).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chat.py
from agent.lib import chat

DOC = {"runDate": "2026-07-12", "counts": {"action": 2, "review": 5, "ok": 10, "watchlist": 3},
       "delta": {"new": ["a", "b"], "resolved": [], "ongoing": ["c"]},
       "findings": [{"severity": "ACTION", "repo": "c/a", "tech": "sp-api", "evidence": "BuyerInfo optional",
                     "changeType": "breaking", "versionInUse": "", "sourceUrl": "https://s"}]}

def test_summary_text_has_counts_urgent_and_link():
    t = chat.build_summary_text(DOC, "https://reports/x")
    assert "2026-07-12" in t and "2 " in t
    assert "BuyerInfo optional" in t
    assert "https://reports/x" in t

def test_failure_text():
    t = chat.build_failure_text("classify", "boom", "2026-07-12T07:00", "2026-07-05")
    assert "FAILED" in t and "classify" in t and "2026-07-05" in t

def test_post_chat_true_on_2xx():
    calls = []
    ok = chat.post_chat("https://hook", "hi", post=lambda url, json: (calls.append((url, json)) or 200))
    assert ok is True and calls[0][1] == {"text": "hi"}

def test_post_chat_false_on_error_never_raises():
    assert chat.post_chat("https://hook", "hi", post=lambda url, json: 500) is False
    def boom(url, json): raise ConnectionError("down")
    assert chat.post_chat("https://hook", "hi", post=boom) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_chat.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/chat.py
"""Google Chat webhook client (plain-text v1). All HTTP injected for testability."""
from __future__ import annotations


def _default_post(url, json):
    import requests
    return requests.post(url, json=json, timeout=30).status_code


def build_summary_text(doc: dict, report_url: str, max_items: int = 10) -> str:
    c = doc["counts"]
    d = doc["delta"]
    action = [f for f in doc.get("findings", []) if f["severity"] == "ACTION"][:max_items]
    lines = [f"*Change Monitor — {doc['runDate']}*",
             f"🔴 {c['action']} ACTION · 🟡 {c['review']} REVIEW · 👀 {c['watchlist']} watch",
             f"🆕 {len(d.get('new',[]))} new · ✅ {len(d.get('resolved',[]))} resolved · ⏳ {len(d.get('ongoing',[]))} ongoing"]
    if action:
        lines.append("")
        lines.append("*Business-logic risk:*")
        for f in action:
            ver = f" {f['versionInUse']}" if f.get("versionInUse") else ""
            lines.append(f"• {f['repo']} — {f['tech']}{ver}: {f['evidence']} ({f['changeType']})")
    lines.append("")
    lines.append(f"<{report_url}|Full report>")
    return "\n".join(lines)


def build_failure_text(stage: str, error: str, now: str, last_good: str) -> str:
    return (f"⚠️ *Change Monitor scan FAILED* — {now}\n"
            f"Reason: {stage}: {error}\nNo report was generated. Last good report: {last_good}.")


def post_chat(webhook_url: str, text: str, *, post=_default_post) -> bool:
    try:
        return 200 <= int(post(webhook_url, {"text": text})) < 300
    except Exception:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_chat.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/chat.py tests/test_chat.py
git commit -m "feat(delivery): Google Chat webhook client (plain-text)"
```

---

### Task 7: GitLab create-commit method + reports-repo committer

**Files:**
- Modify: `agent/lib/gitlab_read.py`
- Create: `agent/commit_report.py`
- Test: `tests/test_gitlab_commit.py`, `tests/test_commit_report.py`

**Interfaces:**
- On `GitLabClient` (a WRITE method — the only one; used only against the reports repo with the write token):
  - `create_commit(project_id, branch, message, actions: list[dict]) -> dict` — `POST /projects/:id/repository/commits` with body `{branch, commit_message, actions}`. Each action = `{action: "create"|"update", file_path, content}`. Requires a `post` path in the client. Since Task-2 (Plan 02) `get` is GET-only, add a private `_post(path, body) -> HttpResponse` mirroring `_do_get` (guarded, raises typed errors) and a public `create_commit`. Returns the commit dict.
  - `file_exists(project_id, path, ref) -> bool` — via `get_raw_file(...) is not None` (for choosing create vs update).
- `agent/commit_report.py`:
  - `commit_files(client, project_id, branch, message, files: dict[str,str], ref) -> str` — for each `{path: content}`, pick `create`/`update` via `file_exists`, build the `actions` array, call `create_commit`, return the commit id.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gitlab_commit.py
from agent.lib.gitlab_read import GitLabClient, HttpResponse

class FakePost:
    def __init__(self): self.calls = []
    def __call__(self, method, url, headers, params, timeout, body=None):
        self.calls.append((method, url, body))
        return HttpResponse(201, {}, '{"id":"abc123"}')

def test_create_commit_posts_actions():
    fp = FakePost()
    c = GitLabClient("https://gl.test", "wtok", request=fp)
    out = c.create_commit(9, "main", "msg", [{"action": "create", "file_path": "a.md", "content": "x"}])
    assert out["id"] == "abc123"
    method, url, body = fp.calls[0]
    assert method == "POST" and "/projects/9/repository/commits" in url
    assert body["branch"] == "main" and body["actions"][0]["file_path"] == "a.md"
```

```python
# tests/test_commit_report.py
from agent import commit_report

class FakeClient:
    def __init__(self, existing):  # set of existing paths
        self.existing = existing; self.committed = None
    def get_raw_file(self, pid, path, ref):
        return "old" if path in self.existing else None
    def create_commit(self, pid, branch, message, actions):
        self.committed = actions; return {"id": "c1"}

def test_commit_files_picks_create_vs_update():
    client = FakeClient(existing={"state/findings.json"})
    cid = commit_report.commit_files(client, 9, "main", "weekly",
              {"reports/r.md": "REPORT", "state/findings.json": "{}"}, "main")
    assert cid == "c1"
    by_path = {a["file_path"]: a["action"] for a in client.committed}
    assert by_path["reports/r.md"] == "create"          # new file
    assert by_path["state/findings.json"] == "update"    # existing file
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_gitlab_commit.py tests/test_commit_report.py -v`
Expected: FAIL — `AttributeError: 'GitLabClient' object has no attribute 'create_commit'` / `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

In `agent/lib/gitlab_read.py`, the injected `request` callable may be called with an extra `body` kwarg for POST. Add:

```python
    def _post(self, path: str, body: dict) -> HttpResponse:
        url = self._base + path
        headers = {"PRIVATE-TOKEN": self._token, "User-Agent": "change-monitor/1.0",
                   "Content-Type": "application/json"}
        try:
            resp = self._request("POST", url, headers, {}, self._timeout, body=body)
        except OSError as exc:
            raise GitLabUnreachable(str(exc)) from exc
        if resp.status == 401:
            raise GitLabAuthError(f"401 on {path}")
        if resp.status == 403:
            raise GitLabForbidden(path)
        if resp.status >= 400:
            raise GitLabError(f"{resp.status} on {path}")
        return resp

    def create_commit(self, project_id: int, branch: str, message: str, actions: list) -> dict:
        body = {"branch": branch, "commit_message": message, "actions": actions}
        return self._post(f"/projects/{project_id}/repository/commits", body).json()

    def file_exists(self, project_id: int, path: str, ref: str) -> bool:
        return self.get_raw_file(project_id, path, ref) is not None
```

Update `_default_request` to accept and forward an optional `body`:

```python
def _default_request(method, url, headers, params, timeout, body=None):  # pragma: no cover
    import requests
    resp = requests.request(method, url, headers=headers, params=params, json=body, timeout=timeout)
    return HttpResponse(status=resp.status_code, headers=dict(resp.headers), body_text=resp.text)
```

Also update `_do_get` to pass `body=None` compatibly — it calls `self._request("GET", url, headers, params or {}, self._timeout)`; since `body` defaults to `None` in `_default_request`, no change needed there, but any custom test transports for GET must tolerate the call without `body` (they do — GET path never passes it).

```python
# agent/commit_report.py
"""Commit report + state files to the reports repo (the only GitLab write path)."""
from __future__ import annotations


def commit_files(client, project_id: int, branch: str, message: str, files: dict, ref: str) -> str:
    actions = []
    for path, content in files.items():
        action = "update" if client.file_exists(project_id, path, ref) else "create"
        actions.append({"action": action, "file_path": path, "content": content})
    return client.create_commit(project_id, branch, message, actions)["id"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_gitlab_commit.py tests/test_commit_report.py -v`
Expected: PASS (2 passed). Also `pytest -q` — confirm existing GET-based client tests still pass (the `body` param is keyword-defaulted, so existing GET transports are unaffected).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/gitlab_read.py agent/commit_report.py tests/test_gitlab_commit.py tests/test_commit_report.py
git commit -m "feat(delivery): GitLab create_commit + reports-repo committer"
```

---

### Task 8: Action router + config additions

**Files:**
- Create: `agent/actions.py`
- Modify: `agent/config.py`
- Test: `tests/test_actions.py`, `tests/test_config_delivery.py`

**Interfaces:**
- `agent/config.py` gains a `DeliveryConfig(reports_project, reports_branch, report_token_env, chat_webhook_env, health_ping_env, actions: list[str], review_horizon_months, urgent_deadline_days)` parsed from a `delivery:` section; `Config.delivery: DeliveryConfig | None`. Absent → None.
- `agent/actions.py`:
  - `run_actions(ctx: dict, *, registry) -> list[dict]` — `ctx` holds `{doc, report_md, report_url, config, phase, commit, chat}`. `registry` maps action-name → callable `(ctx) -> dict`. Only actions named in `ctx["config"].delivery.actions` run (QUIET by default: an action absent from config cannot fire). Each action's exception is caught → `{"name": n, "ok": False, "error": str(exc)}`. Returns the result list.
  - Built-in actions `commit_report_action(ctx)` and `chat_alert_action(ctx)` (thin wrappers calling `ctx["commit"]`/`ctx["chat"]` injected callables — keeps this module free of GitLab/HTTP imports).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_delivery.py
import textwrap
from agent.config import load_config

def test_delivery_parsed(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        kb: { root: kb/ }
        delivery:
          reportsProject: tools/reports
          reportsBranch: main
          reportTokenEnv: REPORTS_TOKEN
          chatWebhookEnv: GCHAT_WEBHOOK_URL
          healthPingEnv: HEALTHCHECK_URL
          actions: [commit-report, chat-alert]
          reviewHorizonMonths: 6
          urgentDeadlineDays: 90
        feeds:
          - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }
    """))
    cfg = load_config(str(p))
    assert cfg.delivery.reports_project == "tools/reports"
    assert cfg.delivery.actions == ["commit-report", "chat-alert"]
    assert cfg.delivery.review_horizon_months == 6
```

```python
# tests/test_actions.py
from agent import actions

class _Cfg:
    class delivery:
        actions = ["chat-alert"]     # commit-report NOT enabled

def test_only_configured_actions_run():
    ran = []
    reg = {"chat-alert": lambda ctx: ran.append("chat") or {"name": "chat-alert", "ok": True},
           "commit-report": lambda ctx: ran.append("commit") or {"name": "commit-report", "ok": True}}
    res = actions.run_actions({"config": _Cfg}, registry=reg)
    assert ran == ["chat"]                       # commit-report absent from config -> did not fire
    assert res == [{"name": "chat-alert", "ok": True}]

def test_action_exception_is_captured():
    def boom(ctx): raise RuntimeError("x")
    class C:
        class delivery: actions = ["chat-alert"]
    res = actions.run_actions({"config": C}, registry={"chat-alert": boom})
    assert res[0]["ok"] is False and "x" in res[0]["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_actions.py tests/test_config_delivery.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError`

- [ ] **Step 3: Write minimal implementation**

In `agent/config.py` add:

```python
@dataclass
class DeliveryConfig:
    reports_project: str
    reports_branch: str = "main"
    report_token_env: str = "REPORTS_TOKEN"
    chat_webhook_env: str = "GCHAT_WEBHOOK_URL"
    health_ping_env: str = "HEALTHCHECK_URL"
    actions: list = None
    review_horizon_months: int = 6
    urgent_deadline_days: int = 90

    def __post_init__(self):
        self.actions = self.actions or []


def _delivery_from(raw: dict):
    d = raw.get("delivery")
    if not d:
        return None
    if not d.get("reportsProject"):
        raise ConfigError("delivery section: missing required field 'reportsProject'")
    return DeliveryConfig(
        reports_project=d["reportsProject"], reports_branch=d.get("reportsBranch", "main"),
        report_token_env=d.get("reportTokenEnv", "REPORTS_TOKEN"),
        chat_webhook_env=d.get("chatWebhookEnv", "GCHAT_WEBHOOK_URL"),
        health_ping_env=d.get("healthPingEnv", "HEALTHCHECK_URL"),
        actions=list(d.get("actions") or []),
        review_horizon_months=int(d.get("reviewHorizonMonths", 6)),
        urgent_deadline_days=int(d.get("urgentDeadlineDays", 90)),
    )
```

Add `delivery: "DeliveryConfig | None" = None` to `Config`, and in `load_config` set `delivery=_delivery_from(raw)`.

```python
# agent/actions.py
"""Action router: the single seam for side effects. Only config-named actions can fire (QUIET default)."""
from __future__ import annotations


def run_actions(ctx: dict, *, registry: dict) -> list:
    enabled = list(ctx["config"].delivery.actions)
    results = []
    for name in enabled:
        fn = registry.get(name)
        if fn is None:
            results.append({"name": name, "ok": False, "error": "no such action"})
            continue
        try:
            results.append(fn(ctx))
        except Exception as exc:
            results.append({"name": name, "ok": False, "error": str(exc)})
    return results


def commit_report_action(ctx: dict) -> dict:
    commit_id = ctx["commit"](ctx)     # injected callable does the GitLab commit
    return {"name": "commit-report", "ok": True, "commit": commit_id}


def chat_alert_action(ctx: dict) -> dict:
    ok = ctx["chat"](ctx)              # injected callable posts to Chat
    return {"name": "chat-alert", "ok": bool(ok)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_actions.py tests/test_config_delivery.py -v`
Expected: PASS (3 passed). Also `pytest -q` — existing config tests still green (delivery is optional).

- [ ] **Step 5: Commit**

```bash
git add agent/actions.py agent/config.py tests/test_actions.py tests/test_config_delivery.py
git commit -m "feat(delivery): action router + delivery config section"
```

---

### Task 9: CLI `report` command (deterministic pipeline tail) + README

**Files:**
- Modify: `agent/cli.py`
- Create: `docs/change-monitor-plan04-README.md`
- Test: `tests/test_cli_report.py`

**Interfaces:**
- A `report` subcommand: `report --config <c> --inventory <inventory.json> --active <active-repos.json> --prev <prev-findings.json|-> --out-report <report.md> --out-findings <findings.json> --now <YYYY-MM-DD>`. Deterministic, NO GitLab/Chat/LLM: builds candidates (from inventory + KB + prev `reportedWatermarks`), maps severity, computes delta, assembles + writes `findings.json`, renders + writes `report.md`, prints a summary. `--prev -` or a missing file → first run (`{}`). `repo_ids` are read from the `active-repos.json` `active[]` entries (`path_with_namespace`→`id`). (Commit + Chat delivery are wired in Plan 05's `run.sh`; this command stops at writing the two files, so it's fully runnable/inspectable offline.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_report.py
import json, textwrap
from agent.lib.models import ChangeEntry
from agent.lib import kb_store
from agent import cli

def _cfg(tmp_path, kb_root):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(f"""
        kb: {{ root: {kb_root} }}
        feeds:
          - {{ techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }}
    """))
    return str(p)

def test_report_cli_end_to_end(tmp_path):
    kb_root = str(tmp_path / "kb")
    # KB has a passed PHP EOL entry
    kb_store.append_entries(kb_root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="eol", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://endoflife.date/php", sourceTier=1, evidence="PHP 8.0 EOL 2023-11-26")])
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({
        "records": [{"repo": "c/a", "tech_key": "runtime:php", "kind": "runtime", "version_hint": "8.0", "declared_range": "", "ecosystem": "docker"}],
        "usedTechs": [], "coverage": {"reposScanned": 1}}))
    active = tmp_path / "active.json"
    active.write_text(json.dumps({"active": [{"id": 42, "path_with_namespace": "c/a"}]}))
    outr = tmp_path / "report.md"; outf = tmp_path / "findings.json"

    rc = cli.main(["report", "--config", _cfg(tmp_path, kb_root), "--inventory", str(inv),
                   "--active", str(active), "--prev", "-", "--out-report", str(outr),
                   "--out-findings", str(outf), "--now", "2026-07-12"])
    assert rc == 0
    findings = json.loads(outf.read_text())
    assert findings["counts"]["action"] == 1                       # passed EOL -> ACTION
    md = outr.read_text()
    assert "Business-logic risk" in md and "c/a" in md and "PHP" in md
    assert findings["findings"][0]["deltaState"] == "NEW"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_cli_report.py -v`
Expected: FAIL — `SystemExit: 2` (unknown subcommand) or assertion error

- [ ] **Step 3: Write minimal implementation**

In `agent/cli.py` add imports and the command:

```python
from agent import candidates as candidates_mod, classify_rules, delta as delta_mod, report as report_mod


def _cmd_report(args) -> int:
    cfg = load_config(args.config)
    horizon = cfg.delivery.review_horizon_months if getattr(cfg, "delivery", None) else 6
    with open(args.inventory, "r", encoding="utf-8") as fh:
        inventory = json.load(fh)
    with open(args.active, "r", encoding="utf-8") as fh:
        active = json.load(fh)
    repo_ids = {r["path_with_namespace"]: r["id"] for r in active.get("active", [])}
    if args.prev and args.prev != "-":
        try:
            with open(args.prev, "r", encoding="utf-8") as fh:
                prev_doc = json.load(fh)
        except FileNotFoundError:
            prev_doc = {}
    else:
        prev_doc = {}

    watermarks = (prev_doc.get("reportedWatermarks") or {})
    cands = candidates_mod.build_candidates(inventory, cfg.kb_root, watermarks, repo_ids=repo_ids)
    findings = [classify_rules.candidate_to_finding(c, args.now, review_horizon_months=horizon) for c in cands]
    delta, stamped = delta_mod.compute_delta(findings, prev_doc, args.now)
    # persist per-tech reported watermark = latest change-entry date surfaced this run
    new_wm = dict(watermarks)
    for c in cands:
        d = c["changeEntry"].get("date", "")
        if d:
            new_wm[c["techKey"]] = max(new_wm.get(c["techKey"], ""), d)
    doc = report_mod.assemble_findings_doc(stamped, delta, inventory.get("coverage", {}), new_wm, args.now)
    md = report_mod.render_report(doc)
    with open(args.out_findings, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    with open(args.out_report, "w", encoding="utf-8") as fh:
        fh.write(md)
    c = doc["counts"]
    print(f"Report {args.now}: {c['action']} ACTION / {c['review']} REVIEW / {c['watchlist']} watch. "
          f"Delta: {len(doc['delta']['new'])} new, {len(doc['delta']['resolved'])} resolved.")
    return 0
```

Register the subparser in `main`:

```python
    pr = sub.add_parser("report")
    for a in ("--config", "--inventory", "--active", "--out-report", "--out-findings", "--now"):
        pr.add_argument(a, required=True)
    pr.add_argument("--prev", default="-")
    pr.set_defaults(func=_cmd_report)
```

(`_cmd_report` needs no injected client, so it uses the plain `return args.func(args)` dispatch path — leave the discover/inventory client-routing branch unchanged.)

Create `docs/change-monitor-plan04-README.md`:

```markdown
# Change Monitor — Plan 04 (Deterministic Delivery Core)

Turns inventory.json + KB drift into findings.json + a markdown report — no LLM, no live services.

## Run (offline, deterministic)
```bash
source .venv/bin/activate
python -m agent.cli report --config config.yaml \
  --inventory inventory.json --active active-repos.json --prev last-findings.json \
  --out-report report.md --out-findings findings.json --now 2026-07-12
```
Severity is rule-decided (spec §6): breaking/security → ACTION; lifecycle EOL → OK/REVIEW/ACTION by
horizon; deprecation/behavioral → REVIEW; unstructured "additive" changelog entries → OK + `needsReview`
(Plan 05's Claude stage re-judges those and fills `businessRiskNote`). Delta uses 2-run flap damping.
The report LEADS with business-logic risk (ACTION). Commit-to-reports-repo + Google Chat delivery and
the LLM classify stage + run.sh + dead-man's switch land in Plan 05.

## Next (Plan 05)
Claude classify stage + trust gate (evidence quote, cited-URL-must-be-fetched), html-changelog structurer,
registry feed adapter, run.sh full pipeline + host-cron + dead-man's switch.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_cli_report.py -v`
Expected: PASS (1 passed). Also `pytest -q` — full suite green; confirm ingest/drift/discover/inventory still pass.

- [ ] **Step 5: Commit**

```bash
git add agent/cli.py tests/test_cli_report.py docs/change-monitor-plan04-README.md
git commit -m "feat(delivery): CLI report command (deterministic pipeline tail) + Plan 04 README"
```

---

## Self-Review

**Spec coverage (Plan 04 slice of the v2 spec):**
- §5.2 Finding model / findings.json → Task 1 ✓
- §3.7/§5.3 candidate build (drift × inventory join) → Task 2 ✓ (reuses Plan 01 drift)
- §6 severity precedence (ACTION/REVIEW/OK; lifecycle horizon; additive→needsReview) → Task 3 ✓
- §3.10/§7 delta engine (stable ids, NEW/RESOLVED/ONGOING, flap damping, firstSeen carry-forward, watermarks) → Task 4 ✓
- §8.1 report (business-logic-risk lead, sections, never-omit-empty) → Task 5 ✓
- §8.2 Google Chat plain-text (+ failure notice) → Task 6 ✓
- §3.12 reports-repo committer (create/update via Commits API; single write path) → Task 7 ✓
- §3.13/§9 action router (QUIET-by-default; config-gated; exception-contained) → Task 8 ✓
- Deferred (correctly, stated up front): the Claude classify stage + trust gate/validator + html-changelog structurer + run.sh + dead-man's switch + registry adapter → Plan 05. The `needsReview` flag + empty `businessRiskNote` on Finding are the additive seam for that.

**Placeholder scan:** none — every step has complete, runnable code. The injected `post`/`request`/`commit`/`chat` callables are real DI seams; production defaults (`_default_post` via requests, `create_commit` via the client) are wired.

**Type consistency:** `Finding` field names are identical across Tasks 1,3,4,5,6,9. `build_candidates(inventory, kb_root, reported_watermarks, *, repo_ids)` / `candidate_to_finding(candidate, now, *, review_horizon_months)` / `compute_delta(current, previous_doc, now) -> (delta, stamped)` / `assemble_findings_doc(stamped, delta, coverage, watermarks, now)` / `render_report(doc)` signatures match their callers in Task 9's CLI. The candidate dict shape (`repo, projectId, techKey, category, versionInUse, changeEntry`) is produced in Task 2 and consumed in Task 3. `GitLabClient.create_commit(project_id, branch, message, actions)` matches between Task 7's client and committer. The `request` callable's new optional `body` kwarg is keyword-defaulted so all Plan-02/03 GET transports remain compatible.

**Known limitations (documented, not gaps):** (1) severity for unstructured-feed entries defaults to OK+`needsReview` until Plan 05's LLM re-judges — this is intentional (a deterministic core must not guess breaking-ness). (2) `businessRiskNote` is empty until Plan 05 fills it. (3) flap damping is a 2-run approximation via `_resolvedPending`, sufficient for a weekly cadence. (4) the `report` CLI stops at writing files; commit + Chat happen in Plan 05's `run.sh` via the action router built here.
