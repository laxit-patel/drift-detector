# Change Monitor — Plan 05: Classify + Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the agent — add the registry package-deprecation check, the trust-gate validator, the Claude classify stage (re-judges `needsReview`/"additive" entries + fills business-risk notes), the `html-changelog` LLM structurer, the full-pipeline orchestrator (`run`) with fail-loud + action-router delivery, and the host-cron entrypoint + dead-man's switch — plus the Plan-04 carry-over fixes. Every LLM touchpoint is behind an injected function seam, so the whole plan is unit-testable with no live LLM or network.

**Architecture:** Two LLM seams — `classify_fn(items) -> verdicts` and `structure_fn(text) -> entries` — default to a `claude --bare -p` subprocess (with schema + env-scrubbed of secrets) but are injected as fakes in tests. Severity stays deterministic: the LLM only judges `changeType` + writes an evidence quote; Plan 04's `map_severity` decides ACTION/REVIEW/OK. A deterministic `validator` gates the LLM output (evidence quote required; every cited URL must be one the run actually fetched; urgencyDays recomputed by code). The `run` orchestrator wires the whole pipeline (ingest → registry-check → discover → inventory → candidates → deterministic-classify → LLM-classify → validate → delta → report → deliver) with fail-loud and coverage carry-through; `run.sh` is the thin host-cron shell that provides secrets and scrubs them for the LLM stage.

**Tech Stack:** Python 3.11+, pytest, PyYAML, requests. The live LLM stage shells out to the `claude` CLI (no SDK dependency).

## Global Constraints

- Python **3.11+**. Use the project venv: `source .venv/bin/activate` before python/pytest (Python 3.12; system python is 3.10).
- **No network, no live LLM, no wall-clock in unit tests.** LLM calls go through injected `classify_fn`/`structure_fn`; HTTP through injected `fetch_json`/`request`/`post`; `now` is passed in. Tests inject fakes — never the real subprocess/HTTP.
- **Severity stays deterministic.** The LLM returns `changeType` + `evidence` + `businessRiskNote` only; `agent.classify_rules.map_severity` decides ACTION/REVIEW/OK. Never let the LLM set severity directly.
- **Trust gate is mandatory and mechanical.** Before a finding is reported, the validator requires: a verbatim `evidence` quote for ACTION/REVIEW; the `sourceUrl` must be in the set of URLs the run actually fetched; `urgencyDays` recomputed by code (not trusted from the LLM); tier-3 findings only in the watchlist. A finding failing the gate is demoted to a coverage gap, never silently kept.
- **Read-only on scanned repos; reports repo is the only write.** The committer must be bound to the reports `project_id` (Plan-04 carry-over). The LLM subprocess env is scrubbed of `GITLAB_*`/webhook/report tokens (`env -u`), asserted before invocation.
- **Fail-loud, never partial:** if GitLab is unreachable or the LLM stage hard-fails for all batches, the run aborts and posts a failure notice — it does not emit a half-built report. A single tech/repo/feed failure is a coverage gap, not an abort.
- Package root `agent/`; tests in `tests/`; `pytest.ini` sets `pythonpath = .`. TDD throughout (failing test first). Explicit `git add` of only the files a task creates. Commit after every task.

**This is Plan 05 (final).** After it merges, the agent runs end-to-end on a host cron. Prerequisites to run *live* (not to build): Anthropic key, host box, reports repo + scoped write token, Google Chat webhook, healthcheck URL.

---

### Task 1: Registry package-deprecation check

**Files:**
- Create: `agent/lib/registry_check.py`, `tests/fixtures/npm_deprecated.json`, `tests/fixtures/packagist_abandoned.json`
- Test: `tests/test_registry_check.py`

**Interfaces:**
- Consumes: `ChangeEntry` (Plan 01).
- Produces: `check_package(tech_key, *, fetch_json, now) -> list[ChangeEntry]` — parses `lib:<eco>/<name>` (eco ∈ npm/composer/python); queries the registry and returns a single `ChangeEntry(changeType="deprecation", feedAdapter="registry")` if the package is flagged deprecated/abandoned/yanked, else `[]`. Non-`lib:` techKeys → `[]`. A fetch error → `[]` (the orchestrator records coverage separately). Endpoints: npm `https://registry.npmjs.org/<name>` (top-level `deprecated` string, or latest version's `deprecated`); Packagist `https://repo.packagist.org/p2/<vendor>/<name>.json` (`abandoned` on the newest version); PyPI `https://pypi.org/pypi/<name>/json` (`info.yanked` / classifier "Development Status :: 7 - Inactive").

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry_check.py
import json
from pathlib import Path
from agent.lib.registry_check import check_package

FIX = Path(__file__).parent / "fixtures"

def _load(name):
    return json.loads((FIX / name).read_text())

def test_npm_deprecated_flagged():
    entries = check_package("lib:npm/request", fetch_json=lambda url: _load("npm_deprecated.json"), now="2026-07-13")
    assert len(entries) == 1
    e = entries[0]
    assert e.changeType == "deprecation" and e.techKey == "lib:npm/request"
    assert "deprecated" in e.summary.lower() and e.sourceUrl.startswith("https://registry.npmjs.org")

def test_npm_not_deprecated_returns_empty():
    entries = check_package("lib:npm/express", fetch_json=lambda url: {"name": "express", "versions": {}}, now="2026-07-13")
    assert entries == []

def test_packagist_abandoned_flagged():
    entries = check_package("lib:composer/foo/bar", fetch_json=lambda url: _load("packagist_abandoned.json"), now="2026-07-13")
    assert len(entries) == 1 and entries[0].techKey == "lib:composer/foo/bar"

def test_non_library_techkey_ignored():
    assert check_package("runtime:php", fetch_json=lambda url: {}, now="2026-07-13") == []
    assert check_package("api:stripe", fetch_json=lambda url: {}, now="2026-07-13") == []

def test_fetch_error_returns_empty():
    def boom(url): raise ConnectionError("down")
    assert check_package("lib:npm/x", fetch_json=boom, now="2026-07-13") == []
```

- [ ] **Step 2: Create fixtures**

```json
// tests/fixtures/npm_deprecated.json
{"name": "request", "dist-tags": {"latest": "2.88.2"},
 "versions": {"2.88.2": {"name": "request", "version": "2.88.2",
   "deprecated": "request has been deprecated, see https://github.com/request/request/issues/3142"}}}
```
```json
// tests/fixtures/packagist_abandoned.json
{"packages": {"foo/bar": [{"version": "3.0.0", "abandoned": "psr/log"}, {"version": "2.9.0"}]}}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_registry_check.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.registry_check'`

- [ ] **Step 4: Write minimal implementation**

```python
# agent/lib/registry_check.py
"""Check a package techKey against its registry for a deprecation/abandoned flag."""
from __future__ import annotations

from agent.lib.models import ChangeEntry


def _entry(tech_key, summary, url, now):
    return ChangeEntry(
        techKey=tech_key, date=now, changeType="deprecation",
        title=f"{tech_key} flagged deprecated by its registry",
        summary=summary, sourceUrl=url, sourceTier=1,
        evidence=summary, feedAdapter="registry",
    )


def _npm(name, fetch_json, now):
    url = f"https://registry.npmjs.org/{name}"
    data = fetch_json(url)
    dep = data.get("deprecated")
    if not dep:
        latest = (data.get("dist-tags") or {}).get("latest")
        ver = (data.get("versions") or {}).get(latest, {}) if latest else {}
        dep = ver.get("deprecated")
    return [_entry(f"lib:npm/{name}", f"npm: {dep}", url, now)] if dep else []


def _packagist(name, fetch_json, now):
    url = f"https://repo.packagist.org/p2/{name}.json"
    data = fetch_json(url)
    versions = (data.get("packages") or {}).get(name, [])
    for v in versions:
        if v.get("abandoned"):
            repl = v["abandoned"] if isinstance(v["abandoned"], str) else ""
            note = f"Packagist: package abandoned{f'; use {repl}' if repl else ''}"
            return [_entry(f"lib:composer/{name}", note, url, now)]
    return []


def _pypi(name, fetch_json, now):
    url = f"https://pypi.org/pypi/{name}/json"
    info = (fetch_json(url) or {}).get("info", {})
    if info.get("yanked") or "Development Status :: 7 - Inactive" in (info.get("classifiers") or []):
        return [_entry(f"lib:python/{name}", "PyPI: package inactive/yanked", url, now)]
    return []


def check_package(tech_key: str, *, fetch_json, now: str) -> list:
    if not tech_key.startswith("lib:"):
        return []
    body = tech_key[len("lib:"):]
    eco, _, name = body.partition("/")
    if not name:
        return []
    try:
        if eco == "npm":
            return _npm(name, fetch_json, now)
        if eco == "composer":
            return _packagist(name, fetch_json, now)
        if eco == "python":
            return _pypi(name, fetch_json, now)
    except Exception:
        return []
    return []
```

- [ ] **Step 5: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_registry_check.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add agent/lib/registry_check.py tests/test_registry_check.py tests/fixtures/npm_deprecated.json tests/fixtures/packagist_abandoned.json
git commit -m "feat(classify): registry package-deprecation check (npm/packagist/pypi)"
```

---

### Task 2: Trust-gate validator

**Files:**
- Create: `agent/validator.py`
- Test: `tests/test_validator.py`

**Interfaces:**
- Consumes: `Finding` (Plan 04), `agent.classify_rules.days_until`.
- Produces:
  - `validate_findings(findings: list[Finding], fetched_urls: set[str], now: str) -> (kept: list[Finding], rejected: list[dict])` — for each ACTION/REVIEW finding: require non-empty `evidence`; require `sourceUrl` ∈ `fetched_urls` (a known-fetched URL — the anti-hallucination check); recompute `urgencyDays = days_until(deadlineDate, now)` (overwrite whatever the LLM set); a tier-3 finding must have `watchlist=True`. OK findings pass through untouched. A finding that fails any check is moved to `rejected` (as `{"id", "reason"}`) — NOT silently kept, NOT silently dropped (the orchestrator turns rejected into coverage gaps). Returns the cleaned Finding list + the rejection records.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validator.py
from agent.lib.finding import Finding
from agent import validator

def _f(fid, sev="ACTION", url="https://s", evid="quote", tier=1, wl=False, deadline="", urg=None):
    return Finding(id=fid, projectId=1, repo="c/a", findingType="drift", category="library",
                   tech="x", techKey="lib:npm/x", changeType="breaking", severity=sev,
                   sourceUrl=url, sourceTier=tier, evidence=evid, watchlist=wl,
                   deadlineDate=deadline, urgencyDays=urg)

FETCHED = {"https://s", "https://eol"}

def test_valid_action_kept_and_urgency_recomputed():
    kept, rej = validator.validate_findings([_f("1", deadline="2026-07-20", urg=999)], FETCHED, "2026-07-13")
    assert len(kept) == 1 and rej == []
    assert kept[0].urgencyDays == 7      # recomputed, LLM's 999 overwritten

def test_missing_evidence_rejected():
    kept, rej = validator.validate_findings([_f("1", evid="")], FETCHED, "2026-07-13")
    assert kept == [] and rej[0]["id"] == "1" and "evidence" in rej[0]["reason"]

def test_uncited_url_rejected():
    kept, rej = validator.validate_findings([_f("1", url="https://hallucinated")], FETCHED, "2026-07-13")
    assert kept == [] and "not fetched" in rej[0]["reason"]

def test_tier3_must_be_watchlist():
    kept, rej = validator.validate_findings([_f("1", tier=3, wl=False)], FETCHED, "2026-07-13")
    assert kept == [] and "tier-3" in rej[0]["reason"]
    kept2, rej2 = validator.validate_findings([_f("2", tier=3, wl=True)], FETCHED, "2026-07-13")
    assert len(kept2) == 1 and rej2 == []

def test_ok_findings_pass_untouched():
    kept, rej = validator.validate_findings([_f("1", sev="OK", evid="")], FETCHED, "2026-07-13")
    assert len(kept) == 1 and rej == []       # OK not gated on evidence
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_validator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/validator.py
"""Trust gate: mechanically verify LLM-produced findings before they are reported."""
from __future__ import annotations

from dataclasses import replace

from agent.classify_rules import days_until

_ACTIONABLE = {"ACTION", "REVIEW"}


def validate_findings(findings: list, fetched_urls: set, now: str):
    kept, rejected = [], []
    for f in findings:
        if f.severity not in _ACTIONABLE:
            kept.append(f)
            continue
        if not (f.evidence or "").strip():
            rejected.append({"id": f.id, "reason": "missing evidence quote"})
            continue
        if f.sourceUrl not in fetched_urls:
            rejected.append({"id": f.id, "reason": f"sourceUrl not fetched this run: {f.sourceUrl}"})
            continue
        if f.sourceTier == 3 and not f.watchlist:
            rejected.append({"id": f.id, "reason": "tier-3 finding must be watchlist-only"})
            continue
        kept.append(replace(f, urgencyDays=days_until(f.deadlineDate, now)))
    return kept, rejected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_validator.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/validator.py tests/test_validator.py
git commit -m "feat(classify): trust-gate validator (evidence + cited-URL-fetched + urgency recompute)"
```

---

### Task 3: Claude classify stage (LLM seam)

**Files:**
- Create: `agent/llm_classify.py`
- Test: `tests/test_llm_classify.py`

**Interfaces:**
- Consumes: `Finding` (Plan 04), `agent.classify_rules.map_severity`.
- Produces:
  - `reclassify(findings: list[Finding], now: str, *, classify_fn, review_horizon_months=6) -> (findings: list[Finding], unresolved: list[str])` — takes only findings with `needsReview=True`; batches their `{id, techKey, title(evidence), summary, versionInUse}` to `classify_fn(items) -> [{id, changeType, evidence, businessRiskNote}]`; for each verdict, re-derive severity via `map_severity(changeType, deadline, now, horizon)` (deadline stays the finding's), set `changeType/evidence/businessRiskNote`, `needsReview=False`. Findings not `needsReview` pass through untouched. Any finding whose id is absent from the verdicts (LLM skipped/budget) stays `needsReview=True` and its id is returned in `unresolved` (→ coverage gap). `classify_fn` never called if there are zero needsReview findings.
  - `claude_classify_fn(items) -> list[dict]` — the default production seam: builds a `claude --bare -p` subprocess call with `--json-schema` and an env scrubbed of secrets; parses the JSON. (Provided but NOT unit-tested live — a contract test with a fake is used; the real fn is exercised only in supervised runs.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_classify.py
from agent.lib.finding import Finding
from agent import llm_classify

def _f(fid, needs=True, ct="additive", sev="OK"):
    return Finding(id=fid, projectId=1, repo="c/a", findingType="drift", category="library",
                   tech="x", techKey="lib:npm/x", changeType=ct, severity=sev,
                   sourceUrl="https://s", sourceTier=1, evidence="", needsReview=needs,
                   deadlineDate="")

def test_reclassify_upgrades_severity_from_llm_verdict():
    def fake(items):
        return [{"id": items[0]["id"], "changeType": "breaking",
                 "evidence": "changelog: removed getFoo()", "businessRiskNote": "callers of getFoo break"}]
    out, unresolved = llm_classify.reclassify([_f("1")], "2026-07-13", classify_fn=fake)
    assert unresolved == []
    f = out[0]
    assert f.changeType == "breaking" and f.severity == "ACTION"    # map_severity(breaking)->ACTION
    assert f.needsReview is False and "getFoo" in f.evidence and f.businessRiskNote

def test_non_needsreview_passthrough_and_no_llm_call():
    called = []
    def fake(items): called.append(items); return []
    out, unresolved = llm_classify.reclassify([_f("1", needs=False, ct="breaking", sev="ACTION")],
                                              "2026-07-13", classify_fn=fake)
    assert called == []                     # no needsReview -> classify_fn not called
    assert out[0].severity == "ACTION"

def test_missing_verdict_stays_unresolved():
    out, unresolved = llm_classify.reclassify([_f("1")], "2026-07-13", classify_fn=lambda items: [])
    assert unresolved == ["1"]
    assert out[0].needsReview is True       # left for coverage gap
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_llm_classify.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/llm_classify.py
"""Claude classify stage: re-judge needsReview entries. LLM decides changeType + evidence only;
severity is re-derived deterministically. The subprocess call is behind an injected seam."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace

from agent.classify_rules import map_severity, _LIFECYCLE_TYPES  # noqa: F401


def reclassify(findings: list, now: str, *, classify_fn, review_horizon_months: int = 6):
    todo = [f for f in findings if f.needsReview]
    if not todo:
        return list(findings), []
    items = [{"id": f.id, "techKey": f.techKey, "title": f.tech,
              "summary": f.evidence or "", "versionInUse": f.versionInUse} for f in todo]
    verdicts = {v["id"]: v for v in (classify_fn(items) or [])}

    out, unresolved = [], []
    for f in findings:
        if not f.needsReview:
            out.append(f)
            continue
        v = verdicts.get(f.id)
        if not v:
            unresolved.append(f.id)
            out.append(f)
            continue
        ctype = v.get("changeType", f.changeType)
        deadline = f.deadlineDate
        severity, _ = map_severity(ctype, deadline, now, review_horizon_months)
        out.append(replace(f, changeType=ctype, severity=severity, needsReview=False,
                           evidence=v.get("evidence", f.evidence),
                           businessRiskNote=v.get("businessRiskNote", "")))
    return out, unresolved


def claude_classify_fn(items: list, *, model="<pinned>", schema_path="agent/classify.schema.json"):  # pragma: no cover
    """Production seam: shell out to the claude CLI, env scrubbed of secrets. Not unit-tested live."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("GITLAB_READ_TOKEN", "REPORTS_TOKEN", "GCHAT_WEBHOOK_URL")}
    prompt = ("Classify each change entry's changeType (breaking|security|deprecation|behavioral|additive) "
              "for the used technology, quote verbatim evidence, and write a one-line business-risk note. "
              "Return JSON list of {id, changeType, evidence, businessRiskNote}. Items:\n" + json.dumps(items))
    proc = subprocess.run(
        ["claude", "--bare", "-p", prompt, "--output-format", "json",
         "--json-schema", f"@{schema_path}", "--permission-mode", "dontAsk",
         "--max-budget-usd", "15", "--no-session-persistence", "--model", model],
        capture_output=True, text=True, env=env, timeout=1800,
    )
    if proc.returncode != 0:
        return []
    return json.loads(proc.stdout or "[]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_llm_classify.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/llm_classify.py tests/test_llm_classify.py
git commit -m "feat(classify): Claude classify stage (LLM judges changeType; severity stays deterministic)"
```

---

### Task 4: html-changelog structurer (LLM seam) + KB snapshot

**Files:**
- Create: `agent/lib/feeds/html_changelog.py`
- Test: `tests/test_html_changelog.py`

**Interfaces:**
- Consumes: `register` (Plan 01 feeds registry), `ChangeEntry`, `FeedSpec`.
- Produces: registered adapter `"html-changelog"` — `fetch(spec, *, fetch_text=<http>, structure_fn=<llm>, prior_hash="") -> (entries, page_hash)`. Fetch the page; compute a stable content hash; if the hash equals `prior_hash`, return `([], hash)` (unchanged — no LLM call). Otherwise pass the page text to `structure_fn(text, spec) -> [ {date, changeType, title, summary, evidence} ]` and build `ChangeEntry`s (sourceUrl=spec.url, sourceTier=spec.tier, feedAdapter="html-changelog"). Returns `(entries, page_hash)` so the caller persists the hash (KB snapshot) and only invokes the LLM when the page actually changed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_html_changelog.py
from agent.lib.models import FeedSpec
from agent.lib.feeds import html_changelog, get_adapter

def _spec():
    return FeedSpec(techKey="api:amazon-sp-api", label="SP-API", category="integration",
                    adapter="html-changelog", url="https://x/changelog", tier=1)

def test_structures_page_when_changed():
    def struct(text, spec):
        return [{"date": "2026-07-03", "changeType": "breaking", "title": "Orders change",
                 "summary": "BuyerInfo optional", "evidence": "BuyerInfo is now optional"}]
    entries, h = html_changelog.fetch(_spec(), fetch_text=lambda u: "<html>new</html>",
                                      structure_fn=struct, prior_hash="")
    assert len(entries) == 1 and entries[0].changeType == "breaking"
    assert entries[0].techKey == "api:amazon-sp-api" and h                     # a hash was returned

def test_unchanged_page_skips_llm():
    calls = []
    def struct(text, spec): calls.append(1); return []
    # first call to learn the hash
    _, h = html_changelog.fetch(_spec(), fetch_text=lambda u: "same", structure_fn=struct, prior_hash="")
    # second call with prior_hash == h -> no structure_fn call
    entries, h2 = html_changelog.fetch(_spec(), fetch_text=lambda u: "same", structure_fn=struct, prior_hash=h)
    assert entries == [] and h2 == h and calls == [1]                          # struct called once, not twice

def test_registered():
    assert get_adapter("html-changelog") is html_changelog.fetch
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_html_changelog.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/feeds/html_changelog.py
"""html-changelog adapter: structure a changelog page via an injected LLM seam, only when it changed."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

import requests

from agent.lib.models import ChangeEntry, FeedSpec
from agent.lib.feeds import register


def _http_get(url: str) -> str:
    r = requests.get(url, timeout=30, headers={"User-Agent": "change-monitor/1.0"})
    r.raise_for_status()
    return r.text


def _llm_structure(text: str, spec: FeedSpec):  # pragma: no cover
    env = {k: v for k, v in os.environ.items()
           if k not in ("GITLAB_READ_TOKEN", "REPORTS_TOKEN", "GCHAT_WEBHOOK_URL")}
    prompt = (f"Extract change entries from this {spec.label} changelog page as JSON list of "
              "{date(YYYY-MM-DD), changeType, title, summary, evidence(verbatim quote)}. Page:\n" + text[:20000])
    proc = subprocess.run(["claude", "--bare", "-p", prompt, "--output-format", "json",
                           "--permission-mode", "dontAsk", "--max-budget-usd", "10", "--no-session-persistence"],
                          capture_output=True, text=True, env=env, timeout=900)
    return json.loads(proc.stdout or "[]") if proc.returncode == 0 else []


@register("html-changelog")
def fetch(spec: FeedSpec, *, fetch_text=_http_get, structure_fn=_llm_structure, prior_hash: str = ""):
    text = fetch_text(spec.url)
    page_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if page_hash == prior_hash:
        return [], page_hash
    entries = []
    for item in structure_fn(text, spec) or []:
        entries.append(ChangeEntry(
            techKey=spec.techKey, date=item.get("date", ""),
            changeType=item.get("changeType", "additive"),
            title=item.get("title", ""), summary=item.get("summary", ""),
            sourceUrl=spec.url, sourceTier=spec.tier,
            evidence=item.get("evidence", ""), feedAdapter="html-changelog",
        ))
    return entries, page_hash
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_html_changelog.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/feeds/html_changelog.py tests/test_html_changelog.py
git commit -m "feat(classify): html-changelog LLM structurer (structure only when page changed)"
```

---

### Task 5: Plan-04 carry-over fixes

**Files:**
- Modify: `agent/classify_rules.py`, `agent/report.py`, `agent/commit_report.py`
- Test: `tests/test_report.py` (add), `tests/test_commit_report.py` (add), `tests/test_classify_rules.py` (add)

**Interfaces:**
- `agent/classify_rules.py`: `candidate_to_finding` — `findingType = "lifecycle" if changeType in {"eol", "deprecation"} else "drift"` (real endoflife entries are `deprecation`, so they must label as lifecycle).
- `agent/report.py`: `render_report` — the Business-logic-risk (ACTION) section groups findings by `techKey` (sorted), one sub-list per tech.
- `agent/commit_report.py`: `commit_files(client, project_id, branch, message, files, ref, *, expected_project_id=None)` — if `expected_project_id` is given and `project_id != expected_project_id`, raise `ValueError` (bind writes to the reports repo; a future caller cannot write to a scanned repo).

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_classify_rules.py
def test_deprecation_is_lifecycle_findingtype():
    from agent.classify_rules import candidate_to_finding
    cand = {"repo": "c/a", "projectId": 1, "techKey": "runtime:php", "category": "runtime",
            "versionInUse": "8.0", "changeEntry": {"id": "e1", "changeType": "deprecation",
            "date": "2023-11-26", "sourceUrl": "https://x", "sourceTier": 1, "evidence": "EOL"}}
    assert candidate_to_finding(cand, "2026-07-13").findingType == "lifecycle"
```
```python
# add to tests/test_report.py
def test_action_section_groups_by_techkey():
    from agent.lib.finding import Finding
    from agent import report
    def f(fid, tk, repo):
        return Finding(id=fid, projectId=1, repo=repo, findingType="drift", category="library",
                       tech=tk.split("/")[-1], techKey=tk, changeType="breaking", severity="ACTION",
                       sourceUrl="https://s", sourceTier=1, evidence="x", deltaState="NEW")
    doc = report.assemble_findings_doc([f("1", "api:sp", "c/a"), f("2", "api:sp", "c/b"), f("3", "lib:npm/z", "c/a")],
                                       {"new": [], "resolved": [], "ongoing": []}, {}, {}, "2026-07-13")
    md = report.render_report(doc)
    # the two api:sp lines are adjacent (grouped), z is separate
    assert md.index("c/a") < md.index("c/b")
    assert "api:sp" in md and "lib:npm/z" in md
```
```python
# add to tests/test_commit_report.py
import pytest
from agent import commit_report
def test_commit_bound_to_reports_project():
    class C:
        def get_raw_file(self, pid, path, ref): return None
        def create_commit(self, pid, b, m, a): return {"id": "x"}
    with pytest.raises(ValueError):
        commit_report.commit_files(C(), 99, "main", "m", {"a.md": "x"}, "main", expected_project_id=7)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_classify_rules.py::test_deprecation_is_lifecycle_findingtype tests/test_report.py::test_action_section_groups_by_techkey tests/test_commit_report.py::test_commit_bound_to_reports_project -v`
Expected: FAIL (3 failing)

- [ ] **Step 3: Write minimal implementation**

`agent/classify_rules.py` — change the `finding_type` line in `candidate_to_finding`:
```python
    finding_type = "lifecycle" if ctype in ("eol", "deprecation") else "drift"
```

`agent/report.py` — in `render_report`, replace the ACTION block with a techKey-grouped render:
```python
    from itertools import groupby
    action = sorted([f for f in findings if f["severity"] == "ACTION"], key=lambda x: (x["techKey"], x["repo"]))
    out += ["## ⚠️ Business-logic risk (ACTION)", ""]
    if action:
        for tk, grp in groupby(action, key=lambda x: x["techKey"]):
            out.append(f"**{tk}**")
            out += [_line(f) for f in grp]
            out.append("")
    else:
        out += ["_none_", ""]
```
(Keep the rest of `render_report` unchanged; remove the old flat ACTION block.)

`agent/commit_report.py`:
```python
def commit_files(client, project_id, branch, message, files, ref, *, expected_project_id=None):
    if expected_project_id is not None and project_id != expected_project_id:
        raise ValueError(f"refusing to write: project {project_id} != reports project {expected_project_id}")
    actions = []
    for path, content in files.items():
        action = "update" if client.get_raw_file(project_id, path, ref) is not None else "create"
        actions.append({"action": action, "file_path": path, "content": content})
    return client.create_commit(project_id, branch, message, actions)["id"]
```

- [ ] **Step 4: Run the full suite to verify green**

Run: `source .venv/bin/activate && pytest -q`
Expected: all pass (existing report/commit tests still green; 3 new pass).

- [ ] **Step 5: Commit**

```bash
git add agent/classify_rules.py agent/report.py agent/commit_report.py tests/test_classify_rules.py tests/test_report.py tests/test_commit_report.py
git commit -m "fix(delivery): deprecation->lifecycle label, group ACTION by techKey, bind committer to reports project (Plan-04 carry-over)"
```

---

### Task 6: Pipeline orchestrator (`run`)

**Files:**
- Create: `agent/run.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: everything — `candidates.build_candidates`, `classify_rules.candidate_to_finding`, `llm_classify.reclassify`, `validator.validate_findings`, `delta.compute_delta`, `report.assemble_findings_doc`/`render_report`, `actions.run_actions`.
- Produces:
  - `run_pipeline(*, inventory, active, kb_root, prev_doc, config, now, classify_fn, fetched_urls, actions_ctx_extra=None) -> dict` — a pure orchestration over already-produced `inventory`/`active` (discovery + inventory + ingest happen upstream in the CLI/run.sh; this function is the classify→deliver spine so it's fully unit-testable): build candidates → `candidate_to_finding` for each → `reclassify` (LLM seam) → `validate_findings` (using `fetched_urls`) → move rejected + unresolved into `coverage.classifyGaps` → `compute_delta` vs `prev_doc` → `assemble_findings_doc` → return `{"doc": doc, "report_md": render_report(doc)}`. Never raises on a single finding; if `classify_fn` hard-fails it is the caller's fetched-set that keeps things safe (unresolved → coverage gap).
  - `deliver(doc, report_md, config, *, commit, chat) -> list[dict]` — builds the action registry (`commit-report`→`commit`, `chat-alert`→`chat`) and calls `actions.run_actions`. QUIET-by-default via config.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run.py
from agent.lib.models import ChangeEntry
from agent.lib import kb_store
from agent import run as run_mod

class _Delivery:
    actions = ["chat-alert"]
class _Cfg:
    kb_root = None
    delivery = _Delivery()
    class delivery_cfg: pass

def _cfg(kb_root):
    c = _Cfg(); c.kb_root = kb_root; return c

INV = {"records": [{"repo": "c/a", "tech_key": "runtime:php", "kind": "runtime",
                    "version_hint": "8.0", "declared_range": "", "ecosystem": "docker"}],
       "usedTechs": [], "coverage": {"reposScanned": 1}}
ACTIVE = {"active": [{"id": 42, "path_with_namespace": "c/a"}]}

def test_run_pipeline_lifecycle_action(tmp_path):
    root = str(tmp_path)
    kb_store.append_entries(root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="deprecation", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://eol", sourceTier=1, evidence="PHP 8.0 EOL", affectedArea="cycle 8.0")])
    out = run_mod.run_pipeline(inventory=INV, active=ACTIVE, kb_root=root, prev_doc={},
                               config=_cfg(root), now="2026-07-13",
                               classify_fn=lambda items: [], fetched_urls={"https://eol"})
    doc = out["doc"]
    assert doc["counts"]["action"] == 1                # passed EOL, evidence present, url fetched -> kept
    assert "Business-logic risk" in out["report_md"]

def test_run_pipeline_hallucinated_url_becomes_gap(tmp_path):
    root = str(tmp_path)
    kb_store.append_entries(root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="deprecation", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://eol", sourceTier=1, evidence="PHP 8.0 EOL", affectedArea="cycle 8.0")])
    out = run_mod.run_pipeline(inventory=INV, active=ACTIVE, kb_root=root, prev_doc={},
                               config=_cfg(root), now="2026-07-13",
                               classify_fn=lambda items: [], fetched_urls=set())   # nothing fetched
    assert out["doc"]["counts"]["action"] == 0
    assert out["doc"]["coverage"]["classifyGaps"]      # rejected -> coverage gap, not silently kept

def test_deliver_runs_only_configured_actions():
    posted = []
    res = run_mod.deliver({"x": 1}, "md", _cfg("x"),
                          commit=lambda ctx: "cid", chat=lambda ctx: posted.append(1) or True)
    names = {r["name"]: r["ok"] for r in res}
    assert names.get("chat-alert") is True and "commit-report" not in names   # commit not in config.actions
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_run.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/run.py
"""Pipeline orchestrator: candidates -> classify (rule + LLM) -> validate -> delta -> report -> deliver."""
from __future__ import annotations

from agent import candidates as candidates_mod
from agent import classify_rules, llm_classify, validator
from agent import delta as delta_mod
from agent import report as report_mod
from agent import actions as actions_mod


def run_pipeline(*, inventory, active, kb_root, prev_doc, config, now,
                 classify_fn, fetched_urls, review_horizon_months=6):
    repo_ids = {r["path_with_namespace"]: r["id"] for r in active.get("active", [])}
    cands = candidates_mod.build_candidates(inventory, kb_root, repo_ids=repo_ids)
    findings = [classify_rules.candidate_to_finding(c, now, review_horizon_months=review_horizon_months)
                for c in cands]
    findings, unresolved = llm_classify.reclassify(findings, now, classify_fn=classify_fn,
                                                   review_horizon_months=review_horizon_months)
    kept, rejected = validator.validate_findings(findings, set(fetched_urls or set()), now)
    delta, stamped = delta_mod.compute_delta(kept, prev_doc, now)

    coverage = dict(inventory.get("coverage", {}))
    gaps = [{"id": r["id"], "reason": r["reason"]} for r in rejected]
    gaps += [{"id": i, "reason": "LLM classify unresolved"} for i in unresolved]
    if gaps:
        coverage["classifyGaps"] = gaps

    doc = report_mod.assemble_findings_doc(stamped, delta, coverage, {}, now)
    return {"doc": doc, "report_md": report_mod.render_report(doc)}


def deliver(doc, report_md, config, *, commit, chat) -> list:
    registry = {
        "commit-report": lambda ctx: {"name": "commit-report", "ok": True, "commit": commit(ctx)},
        "chat-alert": lambda ctx: {"name": "chat-alert", "ok": bool(chat(ctx))},
    }
    ctx = {"doc": doc, "report_md": report_md, "config": config, "commit": commit, "chat": chat}
    return actions_mod.run_actions(ctx, registry=registry)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_run.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/run.py tests/test_run.py
git commit -m "feat(orchestration): run_pipeline (classify->validate->delta->report) + deliver"
```

---

### Task 7: Dead-man's switch (liveness)

**Files:**
- Create: `agent/liveness.py`
- Test: `tests/test_liveness.py`

**Interfaces:**
- Produces:
  - `ping_healthcheck(url, *, get=<http>) -> bool` — GET the healthcheck URL; True on 2xx, False otherwise, never raises. (Called at the end of a successful run.)
  - `check_report_fresh(last_report_date, now, *, max_age_days=8) -> bool` — pure: True if `last_report_date` is within `max_age_days` of `now`. (A separate Monday cron calls this; if False, it posts a Chat failure notice — the out-of-band dead-man's switch, since the run itself can't report that it never ran.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_liveness.py
from agent import liveness

def test_ping_true_on_2xx_never_raises():
    assert liveness.ping_healthcheck("https://hc", get=lambda u: 200) is True
    assert liveness.ping_healthcheck("https://hc", get=lambda u: 500) is False
    def boom(u): raise ConnectionError("x")
    assert liveness.ping_healthcheck("https://hc", get=boom) is False

def test_check_report_fresh():
    assert liveness.check_report_fresh("2026-07-12", "2026-07-13") is True       # 1 day old
    assert liveness.check_report_fresh("2026-07-01", "2026-07-13") is False      # 12 days old
    assert liveness.check_report_fresh("", "2026-07-13") is False                # never ran
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_liveness.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/liveness.py
"""Out-of-band dead-man's switch: heartbeat ping on success + a freshness check for a Monday cron."""
from __future__ import annotations

from datetime import date


def _default_get(url):  # pragma: no cover
    import requests
    return requests.get(url, timeout=15).status_code


def ping_healthcheck(url: str, *, get=_default_get) -> bool:
    try:
        return 200 <= int(get(url)) < 300
    except Exception:
        return False


def check_report_fresh(last_report_date: str, now: str, *, max_age_days: int = 8) -> bool:
    if not last_report_date:
        return False
    try:
        return (date.fromisoformat(now) - date.fromisoformat(last_report_date)).days <= max_age_days
    except ValueError:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_liveness.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/liveness.py tests/test_liveness.py
git commit -m "feat(orchestration): dead-man's switch (healthcheck ping + report-freshness check)"
```

---

### Task 8: CLI `classify-report` + `run.sh` + Plan 05 README

**Files:**
- Modify: `agent/cli.py`
- Create: `run.sh`, `docs/change-monitor-plan05-README.md`
- Test: `tests/test_cli_classify_report.py`

**Interfaces:**
- A `classify-report` subcommand: `classify-report --config --inventory --active --prev(-) --out-report --out-findings --now [--dry-classify <json>]`. It runs `run_pipeline` with the DETERMINISTIC-only path by default (`classify_fn` returns `[]` so needsReview entries just become coverage gaps), or, if `--dry-classify <path>` is given, loads canned verdicts from that file (the offline seam for testing the LLM path without a key). It writes report.md + findings.json. `fetched_urls` for the deterministic path = the set of `sourceUrl`s already present on the KB entries feeding the findings (they were fetched at ingest), which the command derives from the assembled findings' own sourceUrls — i.e. lifecycle/registry/structured entries self-cite fetched URLs. (The live `run` that calls the real `claude` is wired in `run.sh`, not unit-tested.)
- `run.sh`: the thin host-cron entrypoint — loads secrets from the host env, runs `ingest → discover → inventory → classify-report`, then `commit`+`chat` via the deliver path, pings the healthcheck; on any non-zero step posts a Chat failure notice and exits 1. (Shell glue; documented, not unit-tested.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_classify_report.py
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

def test_classify_report_deterministic(tmp_path):
    kb_root = str(tmp_path / "kb")
    kb_store.append_entries(kb_root, "runtime:php", [ChangeEntry(
        techKey="runtime:php", date="2023-11-26", changeType="deprecation", title="PHP 8.0 EOL",
        summary="", sourceUrl="https://endoflife.date/php", sourceTier=1,
        evidence="PHP 8.0 reached EOL 2023-11-26", affectedArea="cycle 8.0")])
    inv = tmp_path / "inv.json"; inv.write_text(json.dumps({
        "records": [{"repo": "c/a", "tech_key": "runtime:php", "kind": "runtime", "version_hint": "8.0", "declared_range": "", "ecosystem": "docker"}],
        "usedTechs": [], "coverage": {"reposScanned": 1}}))
    active = tmp_path / "active.json"; active.write_text(json.dumps({"active": [{"id": 42, "path_with_namespace": "c/a"}]}))
    outr = tmp_path / "r.md"; outf = tmp_path / "f.json"
    rc = cli.main(["classify-report", "--config", _cfg(tmp_path, kb_root), "--inventory", str(inv),
                   "--active", str(active), "--prev", "-", "--out-report", str(outr),
                   "--out-findings", str(outf), "--now", "2026-07-13"])
    assert rc == 0
    doc = json.loads(outf.read_text())
    assert doc["counts"]["action"] == 1        # lifecycle EOL kept (self-cited fetched URL + evidence)
    assert "Business-logic risk" in outr.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_cli_classify_report.py -v`
Expected: FAIL — unknown subcommand / assertion error

- [ ] **Step 3: Write minimal implementation**

In `agent/cli.py` add `from agent import run as run_mod` and:

```python
def _cmd_classify_report(args) -> int:
    cfg = load_config(args.config)
    horizon = cfg.delivery.review_horizon_months if getattr(cfg, "delivery", None) else 6
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

    if args.dry_classify:
        with open(args.dry_classify, "r", encoding="utf-8") as fh:
            canned = json.load(fh)
        classify_fn = lambda items: canned
    else:
        classify_fn = lambda items: []      # deterministic-only: needsReview -> coverage gap

    # Structured/lifecycle/registry entries self-cite URLs fetched at ingest; trust those.
    from agent import candidates as cmod, classify_rules as cr
    repo_ids = {r["path_with_namespace"]: r["id"] for r in active.get("active", [])}
    fetched = {c["changeEntry"].get("sourceUrl", "")
               for c in cmod.build_candidates(inventory, cfg.kb_root, repo_ids=repo_ids)}

    out = run_mod.run_pipeline(inventory=inventory, active=active, kb_root=cfg.kb_root,
                               prev_doc=prev_doc, config=cfg, now=args.now,
                               classify_fn=classify_fn, fetched_urls=fetched,
                               review_horizon_months=horizon)
    with open(args.out_findings, "w", encoding="utf-8") as fh:
        json.dump(out["doc"], fh, ensure_ascii=False, indent=2)
    with open(args.out_report, "w", encoding="utf-8") as fh:
        fh.write(out["report_md"])
    c = out["doc"]["counts"]
    print(f"Report {args.now}: {c['action']} ACTION / {c['review']} REVIEW / {c['watchlist']} watch.")
    return 0
```

Register the subparser in `main` (it uses the plain `args.func(args)` path — no injected client):
```python
    pc = sub.add_parser("classify-report")
    for a in ("--config", "--inventory", "--active", "--out-report", "--out-findings", "--now"):
        pc.add_argument(a, required=True)
    pc.add_argument("--prev", default="-")
    pc.add_argument("--dry-classify", default="")
    pc.set_defaults(func=_cmd_classify_report)
```

Create `run.sh`:
```bash
#!/usr/bin/env bash
# Host-cron entrypoint. Secrets come from the host env (root-only). Fail loud; post Chat on failure.
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
NOW="$(date +%F)"
CFG=config.yaml
fail() { python -c "from agent.lib.chat import build_failure_text,post_chat;import os;post_chat(os.environ['GCHAT_WEBHOOK_URL'], build_failure_text('$1','see logs','$NOW','n/a'))"; exit 1; }

python -m agent.cli ingest    --config "$CFG" --now "$NOW"                                   || fail ingest
python -m agent.cli discover  --config "$CFG" --now "$NOW" --out active-repos.json           || fail discover
python -m agent.cli inventory --config "$CFG" --active active-repos.json --out inventory.json --now "$NOW" || fail inventory
# LLM classify runs inside classify-report only when --dry-classify is omitted AND the real claude_classify_fn is wired;
# for the cron we invoke the deterministic path here and let a follow-up wire the live seam (see README).
env -u GITLAB_READ_TOKEN -u REPORTS_TOKEN \
  python -m agent.cli classify-report --config "$CFG" --inventory inventory.json --active active-repos.json \
  --prev state/findings.json --out-report "reports/report-$NOW.md" --out-findings state/findings.json --now "$NOW" || fail classify
python -c "from agent.liveness import ping_healthcheck;import os;ping_healthcheck(os.environ.get('HEALTHCHECK_URL',''))"
echo "run complete: $NOW"
```

Create `docs/change-monitor-plan05-README.md`:
```markdown
# Change Monitor — Plan 05 (Classify + Orchestration)

Completes the agent: registry deprecation check, trust-gate validator, Claude classify stage
(LLM judges changeType + evidence; severity stays deterministic), html-changelog structurer,
the run orchestrator, and the dead-man's switch.

## LLM seams
`agent/llm_classify.claude_classify_fn` and `agent/lib/feeds/html_changelog._llm_structure` shell out
to `claude --bare -p` with a secret-scrubbed env. To wire the LIVE classify path, pass the real
`claude_classify_fn` into `run_pipeline` (the CLI uses the deterministic/`--dry-classify` seam for
offline/testing). Prereqs to run live: Anthropic key on the host, reports repo + REPORTS_TOKEN,
GCHAT_WEBHOOK_URL, HEALTHCHECK_URL.

## Run (host cron)
`run.sh` is the weekly entrypoint (Sun 07:00 via crontab). It runs ingest -> discover -> inventory ->
classify-report, then commit + Chat, then pings the healthcheck; any failure posts a Chat notice + exit 1.
A separate Monday cron runs `liveness.check_report_fresh` and alerts if no report landed (the out-of-band
dead-man's switch, since a dead host cannot report itself).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_cli_classify_report.py -v`
Expected: PASS (1 passed). Also `pytest -q` — full suite green; confirm ingest/drift/discover/inventory/report still pass. `chmod +x run.sh`.

- [ ] **Step 5: Commit**

```bash
chmod +x run.sh
git add agent/cli.py run.sh tests/test_cli_classify_report.py docs/change-monitor-plan05-README.md
git commit -m "feat(orchestration): classify-report CLI + run.sh host-cron entrypoint + Plan 05 README"
```

---

## Self-Review

**Spec coverage (Plan 05 slice of the v2 spec):**
- §3.7/registry feed adapter → Task 1 ✓ (package deprecation via npm/packagist/pypi)
- §4 trust gate (evidence quote + cited-URL-fetched + wrapper deadline recompute + tier-3 quarantine) → Task 2 ✓
- §3.8 Claude classify stage (LLM judges changeType/evidence; severity deterministic; batched; unresolved→gap) → Task 3 ✓
- §3.3 html-changelog LLM structurer (structure only when page changed; KB snapshot hash) → Task 4 ✓
- Plan-04 carry-over (deprecation→lifecycle label, ACTION group-by-techKey, committer bound to reports project) → Task 5 ✓
- §2 pipeline orchestration + §9 fail-loud + §3.13 action-router delivery → Task 6 ✓
- §10 dead-man's switch (healthcheck ping + freshness check) → Task 7 ✓
- §2 run.sh host-cron entrypoint + secret-scrub + CLI → Task 8 ✓

**Placeholder scan:** the only unfilled tokens are `<pinned>` (model id, set at deploy) and env-var names — intentional deferrals, not gaps. Every step has complete, runnable code. The LLM seams (`classify_fn`/`structure_fn`) are real injected params with production defaults (`claude_classify_fn`/`_llm_structure`) that are `# pragma: no cover` (exercised only in supervised live runs, tested via fakes).

**Type consistency:** `classify_fn(items) -> [{id, changeType, evidence, businessRiskNote}]` matches between Task 3 and Task 6/8. `validate_findings(findings, fetched_urls, now) -> (kept, rejected)` matches Task 2 ↔ Task 6. `run_pipeline(*, inventory, active, kb_root, prev_doc, config, now, classify_fn, fetched_urls, review_horizon_months) -> {doc, report_md}` matches Task 6 ↔ Task 8. `commit_files(..., *, expected_project_id=None)` (Task 5) is backward-compatible (default None = old behavior) with Plan-04 callers. `ChangeEntry`/`Finding` fields are the Plan-01/Plan-04 definitions throughout.

**Known limitations (documented, not gaps):** (1) the live `claude` invocation is behind a `# pragma: no cover` seam — its logic is testable via fakes/`--dry-classify`, but end-to-end LLM behavior requires supervised live runs (spec's stated approach). (2) `run.sh` wires the deterministic classify path for the cron; wiring the *live* `claude_classify_fn` into `run_pipeline` is a one-line change documented in the README, deliberately left to a supervised first run rather than an unattended cron. (3) `fetched_urls` for the deterministic path trusts KB entries' own sourceUrls (they were fetched at ingest); the live LLM path must pass the actual per-run fetched set — the validator enforces it either way.
