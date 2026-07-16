# Eval Harness (Phase 0 + Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `~/.drift/` home for central artifacts, and a `drift-eval run ebay` command that scores the scanner against a pinned corpus of real eBay PHP repos — recall as a hard gate, plus informational noise/version/sunset metrics.

**Architecture:** A pure scoring core (`agent/eval/score.py`) takes already-produced inventory/audit dicts and returns a scorecard; a thin orchestrator (`agent/eval/runner.py`) clones the pinned corpus (injected git), runs the existing pipeline in-process with OSV/EOL stubbed off (so only the deterministic sunset join runs), scores, renders, and writes under `~/.drift/eval/`. A self-bootstrapping `bin/drift-eval` mirrors `bin/drift-scan`.

**Tech Stack:** Python 3.12 stdlib + pyyaml (already a dep). pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-07-16-eval-harness-design.md` — the source of truth.

## Global Constraints

- Python 3.12 in `.venv` (uv-managed). Run tests with `.venv/bin/python -m pytest -q`. **NO pip** — stdlib + existing deps (pyyaml) only. NO new dependencies.
- **DETERMINISTIC, ZERO-LLM-TOKEN.** Same pinned corpus + same `--now` → byte-identical scorecard. **NO network in any unit test**; git + scan + audit are injected/monkeypatched. Real clones/network ONLY in the opt-in live smoke (skipped by default).
- `score.py` is a **PURE function** (dicts in, dict out) — no git/network/scanner/filesystem. The tested core.
- **Offline audit:** pass `osv_query=lambda *a, **k: []` + `eol_check=lambda *a, **k: None` (the seams `audit_inventory` already exposes; matches the existing `_NOOP` sunset tests) so only the deterministic sunset join runs. Do NOT score the CVE/EOL layer in Phase 1.
- **Corpus pins:** `sha` is 40-hex, quoted; clone verifies `rev-parse HEAD == sha` and **HARD-FAILS** on mismatch; refuses a dirty tree. A malformed corpus entry is a hard error, never silently skipped.
- `known_gaps` values MUST be members of the taxonomy enum (defined once as a Python constant, documented in `taxonomy.md`).
- The recall **GATE** is the only pass/fail: exit `1` iff a repo missed with a non-known-gap mode; noise/version/sunset are informational (never gate).
- Clones live in `~/Projects/sandbox/<category>/<name>`, are third-party public code, **NEVER committed**. `eval/corpus.yaml` (the pins/labels) IS committed. Artifacts go under `~/.drift/` (also never committed).
- In-place tool behavior (`<folder>/.drift-detector/`) is **UNCHANGED** — Phase 0 only adds the central `~/.drift` home.
- `bin/drift-eval` mirrors `bin/drift-scan`'s self-bootstrapping venv + PYTHONPATH pattern (no cwd dependence).
- TDD, frequent commits, DRY, YAGNI. Phase 2/3 (golden facts, snapshots, triage, walmart+sp, OSV/EOL cassettes, diff/accept) are OUT OF SCOPE.

**Injected git contract** (used by Task 4/5): `git(args: list, cwd=None) -> str` — returns stdout (or `""` on failure). Superset of the two existing `_default_git` variants; clone needs stdout for `rev-parse`/`status`.

---

## File Structure

| File | Responsibility |
|---|---|
| `agent/lib/drift_home.py` *(create)* | Resolve `~/.drift` paths. Pure, no deps. |
| `agent/eval/__init__.py` *(create)* | Package marker. |
| `agent/eval/corpus.py` *(create)* | `TAXONOMY` constant + `load_corpus(path)` with validation. |
| `eval/taxonomy.md` *(create)* | Human doc of the enum (mirrors `corpus.TAXONOMY`). |
| `agent/eval/score.py` *(create)* | `score(entries, inventory, audit)` — the pure core. |
| `agent/eval/clone.py` *(create)* | `sync_corpus(...)` pin-verifying clone (injected git). |
| `agent/eval/render.py` *(create)* | `render_scorecard(scorecard)` → terminal string. |
| `agent/eval/runner.py` *(create)* | `run_category(...)` orchestrator (injected seams). |
| `agent/eval/cli.py` *(create)* | argparse `run <category>` → runner; exit from gate. |
| `bin/drift-eval` *(create)* | Self-bootstrapping entrypoint. |
| `eval/corpus.yaml` *(create, Task 6)* | Real pinned eBay corpus. |
| `tests/test_drift_home.py`, `test_eval_corpus.py`, `test_eval_score.py`, `test_eval_clone.py`, `test_eval_render.py`, `test_eval_runner.py` *(create)* | Unit tests + opt-in smoke. |

**Ordering rationale:** Task 1 (drift_home) and Task 2 (corpus) are independent leaves. Task 3 (score) is the pure core, depends on nothing but the corpus-entry/inventory/audit shapes. Task 4 (clone+render) is independent I/O + presentation. Task 5 (runner+cli+bin) wires 1–4 together. Task 6 (real corpus) runs last — it needs the whole harness working to capture the first real scorecard.

---

## Task 1: `agent/lib/drift_home.py` — the `~/.drift` home (Phase 0)

**Files:**
- Create: `agent/lib/drift_home.py`
- Create: `tests/test_drift_home.py`

**Interfaces:**
- Produces: `drift_root() -> str`, `reports_home(slug) -> str`, `eval_home() -> str`. Task 5 consumes `eval_home()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_drift_home.py`:

```python
"""~/.drift is the one home for eval + central-run artifacts (Phase 0). The in-place
<folder>/.drift-detector behavior is unchanged — this only adds the central home."""
import os
from agent.lib import drift_home


def test_drift_root_honors_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_HOME", str(tmp_path / "custom"))
    assert drift_home.drift_root() == str(tmp_path / "custom")
    assert os.path.isdir(drift_home.drift_root())          # created on demand


def test_drift_root_defaults_under_home(monkeypatch):
    monkeypatch.delenv("DRIFT_HOME", raising=False)
    assert drift_home.drift_root() == os.path.join(os.path.expanduser("~"), ".drift")


def test_reports_and_eval_subpaths(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_HOME", str(tmp_path))
    assert drift_home.reports_home("fleet") == os.path.join(str(tmp_path), "reports", "fleet")
    assert drift_home.eval_home() == os.path.join(str(tmp_path), "eval")
    assert os.path.isdir(drift_home.reports_home("fleet"))   # subdir created
    assert os.path.isdir(drift_home.eval_home())
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_drift_home.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.drift_home'`

- [ ] **Step 3: Implement**

Create `agent/lib/drift_home.py`:

```python
"""The single source of truth for ~/.drift — the central home for eval artifacts and
central/demo scan runs. Honors $DRIFT_HOME (used by tests). Does NOT change the plugin's
in-place <folder>/.drift-detector/ outputs."""
from __future__ import annotations

import os


def drift_root() -> str:
    root = os.environ.get("DRIFT_HOME") or os.path.join(os.path.expanduser("~"), ".drift")
    os.makedirs(root, exist_ok=True)
    return root


def reports_home(slug: str) -> str:
    p = os.path.join(drift_root(), "reports", slug)
    os.makedirs(p, exist_ok=True)
    return p


def eval_home() -> str:
    p = os.path.join(drift_root(), "eval")
    os.makedirs(p, exist_ok=True)
    return p
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_drift_home.py -q`
Expected: PASS, 3 passed

- [ ] **Step 5: Commit** (and do the one-time litter cleanup)

```bash
# one-time operational cleanup of the ad-hoc report folders (spec §Cleanup); not code:
mkdir -p ~/.drift/reports/legacy
mv ~/drift-report-2026-07-15 ~/drift-report-ebay-2026-07-16 ~/drift-report-fleet-2026-07-16 ~/.drift/reports/legacy/ 2>/dev/null || true
git add agent/lib/drift_home.py tests/test_drift_home.py
git commit -m "feat(eval): ~/.drift home (Phase 0)

drift_root/reports_home/eval_home resolve the central home for eval + demo
runs (honors \$DRIFT_HOME). In-place <folder>/.drift-detector behavior
unchanged. Moved the 3 stray ~/drift-report-* folders under ~/.drift/reports."
```

---

## Task 2: `agent/eval/corpus.py` + `eval/taxonomy.md` — corpus schema + failure-mode enum

**Files:**
- Create: `agent/eval/__init__.py` (empty), `agent/eval/corpus.py`, `eval/taxonomy.md`
- Create: `tests/test_eval_corpus.py`

**Interfaces:**
- Produces: `TAXONOMY` (frozenset of str), `load_corpus(path) -> list[dict]`. Task 3 reads entry dicts; Task 5 calls `load_corpus`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_eval_corpus.py`:

```python
import pytest
from agent.eval import corpus


def _write(tmp_path, text):
    p = tmp_path / "corpus.yaml"
    p.write_text(text)
    return str(p)


_VALID = """
- repo: davidtsadler/ebay-sdk-php
  url: https://github.com/davidtsadler/ebay-sdk-php.git
  sha: "1234567890abcdef1234567890abcdef12345678"
  license: MIT
  category: ebay
  expect: { vendor: eBay, sdk_keywords: [ebay], sunset_host: svcs.ebay.com }
  known_gaps: [sdk-only-no-callsite]
  holdout: false
  fetched_at: "2026-07-16"
"""


def test_loads_a_valid_entry(tmp_path):
    entries = corpus.load_corpus(_write(tmp_path, _VALID))
    assert len(entries) == 1
    e = entries[0]
    assert e["repo"] == "davidtsadler/ebay-sdk-php"
    assert e["expect"]["vendor"] == "eBay"
    assert isinstance(e["sha"], str) and len(e["sha"]) == 40


def test_unquoted_sha_like_value_is_coerced_to_str(tmp_path):
    # an all-digit sha would parse as int without the quotes; loader must coerce
    text = _VALID.replace('"1234567890abcdef1234567890abcdef12345678"',
                          "1234567890123456789012345678901234567890")
    e = corpus.load_corpus(_write(tmp_path, text))[0]
    assert isinstance(e["sha"], str)


def test_rejects_missing_sha(tmp_path):
    bad = _VALID.replace('  sha: "1234567890abcdef1234567890abcdef12345678"\n', "")
    with pytest.raises(ValueError, match="sha"):
        corpus.load_corpus(_write(tmp_path, bad))


def test_rejects_missing_vendor(tmp_path):
    bad = _VALID.replace("vendor: eBay, ", "")
    with pytest.raises(ValueError, match="vendor"):
        corpus.load_corpus(_write(tmp_path, bad))


def test_rejects_non_40hex_sha(tmp_path):
    bad = _VALID.replace('"1234567890abcdef1234567890abcdef12345678"', '"deadbeef"')
    with pytest.raises(ValueError, match="40"):
        corpus.load_corpus(_write(tmp_path, bad))


def test_rejects_known_gap_outside_taxonomy(tmp_path):
    bad = _VALID.replace("[sdk-only-no-callsite]", "[not-a-real-mode]")
    with pytest.raises(ValueError, match="taxonomy|not-a-real-mode"):
        corpus.load_corpus(_write(tmp_path, bad))


def test_taxonomy_is_the_documented_closed_set():
    assert "sdk-only-no-callsite" in corpus.TAXONOMY
    assert "uncatalogued-vendor" in corpus.TAXONOMY
    assert len(corpus.TAXONOMY) == 9
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_corpus.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `agent/eval/__init__.py` (empty file).

Create `agent/eval/corpus.py`:

```python
"""Load + validate the eval corpus (eval/corpus.yaml). The corpus is the versioned ground
truth: each entry pins a real public repo at a SHA and declares what the scanner should
detect. A malformed entry is a hard error — a broken corpus must be loud, never silently
scored as if smaller."""
from __future__ import annotations

import re

import yaml

# The closed failure-mode enum. `known_gaps` values must be members. Documented in eval/taxonomy.md.
TAXONOMY = frozenset({
    "url-split-version", "sdk-only-no-callsite", "uncatalogued-vendor",
    "wrong-host-attribution", "config-driven-url", "env-var-host",
    "private-source", "scan-error", "label-wrong",
})

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def load_corpus(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    if not isinstance(raw, list):
        raise ValueError("corpus must be a YAML list of entries")
    out = []
    for i, e in enumerate(raw):
        where = f"corpus entry #{i} ({e.get('repo') if isinstance(e, dict) else e!r})"
        if not isinstance(e, dict):
            raise ValueError(f"{where}: not a mapping")
        e = dict(e)
        for req in ("repo", "url", "sha", "category"):
            if not e.get(req):
                raise ValueError(f"{where}: missing required field '{req}'")
        e["sha"] = str(e["sha"])
        if not _SHA_RE.match(e["sha"]):
            raise ValueError(f"{where}: sha must be a 40-hex commit, got {e['sha']!r}")
        expect = e.get("expect") or {}
        if not expect.get("vendor"):
            raise ValueError(f"{where}: missing required expect.vendor")
        bad = [g for g in (e.get("known_gaps") or []) if g not in TAXONOMY]
        if bad:
            raise ValueError(f"{where}: known_gaps not in taxonomy: {bad}")
        out.append(e)
    return out
```

Create `eval/taxonomy.md`:

```markdown
# Eval failure-mode taxonomy

The closed set of reasons the scanner can miss a known integration. Mirrors
`agent/eval/corpus.TAXONOMY` (that constant is the source of truth). A corpus entry's
`known_gaps` may only use these values.

| mode | meaning |
|---|---|
| `url-split-version` | endpoint found but version is None (base URL + version on different lines) |
| `sdk-only-no-callsite` | integration is used only via its SDK package; no hard-coded URL to match |
| `uncatalogued-vendor` | the host is real but not in `agent/vendors.yaml` yet |
| `wrong-host-attribution` | a host was classified to the wrong vendor |
| `config-driven-url` | the endpoint URL is assembled from config, not a literal |
| `env-var-host` | the host comes from an environment variable, not source |
| `private-source` | dependency/source is private/unresolvable |
| `scan-error` | the repo failed to scan |
| `label-wrong` | the expectation itself is wrong (the eval can indict its own labels) |

Phase 1 uses these only as pre-declared `known_gaps`. Auto-triage of unexpected misses is Phase 2.
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_eval_corpus.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add agent/eval/__init__.py agent/eval/corpus.py eval/taxonomy.md tests/test_eval_corpus.py
git commit -m "feat(eval): corpus loader + failure-mode taxonomy

load_corpus validates required fields, 40-hex sha (coerced to str), and that
known_gaps are members of the closed TAXONOMY enum. Malformed entry = hard
error, never silently skipped. taxonomy.md documents the enum."
```

---

## Task 3: `agent/eval/score.py` — the pure scoring core

**Files:**
- Create: `agent/eval/score.py`
- Create: `tests/test_eval_score.py`

**Interfaces:**
- Consumes: corpus entry dicts (Task 2); `inventory` (scan doc: `repos[{path, endpoints[{vendor,classified,version}], sdks[{eco,pkg}]}]`, `coverage.reposErrored[{repo,reason}]`); `audit` (`findings[{kind,domain}]`).
- Produces: `score(entries, inventory, audit) -> dict` — the scorecard shape from the spec. Task 4 renders it; Task 5 writes it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_eval_score.py`:

```python
"""The pure scoring core: (corpus entries, inventory doc, audit doc) -> scorecard.
No git/network/scanner — hand-built dicts only."""
from agent.eval.score import score


def _entry(repo="o/ebay-sdk-php", vendor="eBay", sdk_keywords=None, sunset_host=None,
           known_gaps=None, holdout=False, category="ebay"):
    exp = {"vendor": vendor}
    if sdk_keywords is not None:
        exp["sdk_keywords"] = sdk_keywords
    if sunset_host:
        exp["sunset_host"] = sunset_host
    return {"repo": repo, "category": category, "expect": exp,
            "known_gaps": known_gaps or [], "holdout": holdout}


def _repo(name, endpoints=(), sdks=()):
    return {"path": name, "endpoints": list(endpoints), "sdks": list(sdks)}


def _inv(repos, errored=()):
    return {"repos": list(repos),
            "coverage": {"reposErrored": [{"repo": r, "reason": "boom"} for r in errored]}}


def _ep(vendor="eBay", classified=True, version="v1", domain="api.ebay.com"):
    return {"vendor": vendor, "classified": classified, "version": version, "domain": domain}


def _audit(findings=()):
    return {"findings": list(findings)}


def test_recall_via_classified_endpoint():
    sc = score([_entry()], _inv([_repo("ebay-sdk-php", endpoints=[_ep()])]), _audit())
    r = sc["repos"][0]
    assert r["detected"] is True and r["via"] == "endpoint"
    assert sc["gate"]["passed"] is True


def test_recall_via_sdk_keyword():
    inv = _inv([_repo("ebay-sdk-php", sdks=[{"eco": "composer", "pkg": "dts/ebay-sdk-php"}])])
    sc = score([_entry(sdk_keywords=["ebay"])], inv, _audit())
    r = sc["repos"][0]
    assert r["detected"] is True and r["via"] == "sdk"


def test_sdk_keyword_defaults_to_category():
    inv = _inv([_repo("ebay-sdk-php", sdks=[{"eco": "composer", "pkg": "acme/ebay-things"}])])
    sc = score([_entry(sdk_keywords=None)], inv, _audit())    # no sdk_keywords -> [category]="ebay"
    assert sc["repos"][0]["detected"] is True and sc["repos"][0]["via"] == "sdk"


def test_endpoint_takes_precedence_when_both_fire():
    inv = _inv([_repo("ebay-sdk-php", endpoints=[_ep()],
                      sdks=[{"eco": "composer", "pkg": "dts/ebay-sdk-php"}])])
    sc = score([_entry(sdk_keywords=["ebay"])], inv, _audit())
    assert sc["repos"][0]["via"] == "endpoint"


def test_miss_when_neither_and_gate_fails_unattributed():
    inv = _inv([_repo("ebay-sdk-php", endpoints=[_ep(vendor="Unknown", classified=False)])])
    sc = score([_entry()], inv, _audit())
    r = sc["repos"][0]
    assert r["detected"] is False and r["via"] is None
    assert r["miss_mode"] == "unattributed"
    assert sc["gate"]["passed"] is False and "ebay-sdk-php" in str(sc["gate"]["failures"])


def test_gate_passes_when_miss_is_a_declared_known_gap():
    inv = _inv([_repo("ebay-sdk-php")])                       # nothing detected
    sc = score([_entry(known_gaps=["sdk-only-no-callsite"])], inv, _audit())
    r = sc["repos"][0]
    assert r["detected"] is False and r["miss_mode"] == "sdk-only-no-callsite"
    assert sc["gate"]["passed"] is True
    assert sc["summary"]["recall"]["known_miss"] == 1


def test_noise_counts_only_unknown_endpoints():
    inv = _inv([_repo("r", endpoints=[_ep(), _ep(vendor="Unknown", classified=False),
                                      _ep(vendor="Unknown", classified=False)])])
    sc = score([_entry(repo="o/r")], inv, _audit())
    assert sc["repos"][0]["noise"] == 2
    assert sc["summary"]["noise"]["max"] == 2


def test_version_rate_over_classified_and_zero_is_none():
    inv = _inv([_repo("r", endpoints=[_ep(version="v1"), _ep(version=None)])])
    sc = score([_entry(repo="o/r")], inv, _audit())
    assert sc["repos"][0]["version_rate"] == 0.5
    inv2 = _inv([_repo("r2", endpoints=[_ep(vendor="Unknown", classified=False)])])
    sc2 = score([_entry(repo="o/r2")], inv2, _audit())
    assert sc2["repos"][0]["version_rate"] is None            # no classified endpoints, no div-by-zero


def test_sunset_hit_matches_host():
    a = _audit([{"kind": "sunset", "domain": "svcs.ebay.com"}])
    sc = score([_entry(sunset_host="svcs.ebay.com")],
               _inv([_repo("ebay-sdk-php", endpoints=[_ep()])]), a)
    r = sc["repos"][0]
    assert r["sunset_expected"] is True and r["sunset_hit"] is True
    assert sc["summary"]["sunset_match"] == {"expected": 1, "hit": 1}


def test_sunset_miss_on_different_host_and_absent_when_unset():
    a = _audit([{"kind": "sunset", "domain": "open.api.ebay.com"}])
    sc = score([_entry(sunset_host="svcs.ebay.com")],
               _inv([_repo("ebay-sdk-php", endpoints=[_ep()])]), a)
    assert sc["repos"][0]["sunset_hit"] is False
    sc2 = score([_entry()], _inv([_repo("ebay-sdk-php", endpoints=[_ep()])]), _audit())
    assert sc2["repos"][0]["sunset_expected"] is False and sc2["repos"][0]["sunset_hit"] is None


def test_errored_repo_reported_not_crashing():
    sc = score([_entry(repo="o/broken")], _inv([], errored=["broken"]), _audit())
    r = sc["repos"][0]
    assert r["errored"] is True and r["detected"] is False
    assert sc["summary"]["errored"] == 1


def test_deterministic():
    entries = [_entry(repo="o/a"), _entry(repo="o/b")]
    inv = _inv([_repo("a", endpoints=[_ep()]), _repo("b", endpoints=[_ep()])])
    assert score(entries, inv, _audit()) == score(entries, inv, _audit())
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_score.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `agent/eval/score.py`:

```python
"""The pure scoring core. (corpus entries, inventory doc, audit doc) -> scorecard dict.

No git, no network, no scanner, no filesystem — it takes already-produced dicts, so it is
fully deterministic and unit-testable. The recall GATE is the only pass/fail; noise,
version-rate and sunset-match are informational.
"""
from __future__ import annotations

import os
import statistics


def _basename(repo_or_path: str) -> str:
    return os.path.basename(str(repo_or_path).rstrip("/"))


def _match_repo(entry, inventory):
    want = _basename(entry["repo"])
    for r in inventory.get("repos", []):
        if _basename(r.get("path", "")) == want:
            return r
    return None


def _errored_names(inventory) -> set:
    cov = inventory.get("coverage") or {}
    return {_basename(x.get("repo", "")) for x in (cov.get("reposErrored") or [])}


def _detect(entry, repo) -> tuple:
    """Returns (detected, via). Endpoint match wins over sdk when both fire."""
    vendor = entry["expect"]["vendor"]
    for e in repo.get("endpoints", []):
        if e.get("classified") and e.get("vendor") == vendor:
            return True, "endpoint"
    keywords = [k.lower() for k in (entry["expect"].get("sdk_keywords") or [entry["category"]])]
    for s in repo.get("sdks", []):
        pkg = str(s.get("pkg", "")).lower()
        if any(k in pkg for k in keywords):
            return True, "sdk"
    return False, None


def _sunsets(audit) -> set:
    return {f.get("domain") for f in audit.get("findings", []) if f.get("kind") == "sunset"}


def score(entries: list, inventory: dict, audit: dict) -> dict:
    fired_sunsets = _sunsets(audit)
    errored = _errored_names(inventory)
    rows, noises, classified_total, versioned_total = [], [], 0, 0
    sunset_expected = sunset_hit = 0

    for entry in entries:
        name = _basename(entry["repo"])
        repo = _match_repo(entry, inventory)
        is_errored = repo is None or name in errored
        if repo is None:
            repo = {"endpoints": [], "sdks": []}

        detected, via = (False, None) if is_errored else _detect(entry, repo)

        eps = repo.get("endpoints", [])
        noise = sum(1 for e in eps if e.get("vendor") == "Unknown")
        classified = [e for e in eps if e.get("classified")]
        classified_total += len(classified)
        versioned_total += sum(1 for e in classified if e.get("version") is not None)
        version_rate = (sum(1 for e in classified if e.get("version") is not None) / len(classified)
                        if classified else None)

        host = entry["expect"].get("sunset_host")
        s_exp = host is not None
        s_hit = (host in fired_sunsets) if s_exp else None
        if s_exp:
            sunset_expected += 1
            sunset_hit += 1 if s_hit else 0

        known = entry.get("known_gaps") or []
        if detected:
            miss_mode = None
        elif known:
            miss_mode = known[0]           # attributed to the first declared gap
        else:
            miss_mode = "unattributed"

        rows.append({"repo": entry["repo"], "detected": detected, "via": via,
                     "miss_mode": miss_mode, "noise": noise, "version_rate": version_rate,
                     "sunset_expected": s_exp, "sunset_hit": s_hit, "errored": is_errored,
                     "holdout": bool(entry.get("holdout"))})
        noises.append(noise)

    failures = [r["repo"] for r in rows if not r["detected"] and r["miss_mode"] == "unattributed"]
    passed = [r for r in rows if r["detected"]]
    summary = {
        "recall": {
            "passed": len(passed), "total": len(rows),
            "endpoint": sum(1 for r in rows if r["via"] == "endpoint"),
            "sdk_only": sum(1 for r in rows if r["via"] == "sdk"),
            "known_miss": sum(1 for r in rows if not r["detected"]
                              and r["miss_mode"] not in (None, "unattributed")),
            "holdout": sum(1 for r in rows if r["holdout"]),
        },
        "noise": {"median": int(statistics.median(noises)) if noises else 0,
                  "max": max(noises) if noises else 0},
        "version_rate": (versioned_total / classified_total) if classified_total else None,
        "sunset_match": {"expected": sunset_expected, "hit": sunset_hit},
        "errored": sum(1 for r in rows if r["errored"]),
    }
    return {"category": entries[0]["category"] if entries else None,
            "repos": rows, "summary": summary,
            "gate": {"passed": not failures, "failures": failures}}
```

Note: `now` is added by the runner (Task 5), not `score` — keeps `score` pure and time-free.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_eval_score.py -q`
Expected: PASS, 12 passed

- [ ] **Step 5: Commit**

```bash
git add agent/eval/score.py tests/test_eval_score.py
git commit -m "feat(eval): pure scoring core

score(entries, inventory, audit) -> scorecard. Recall (endpoint vendor match
or sdk keyword; endpoint wins) is the GATE; a miss declared in known_gaps is a
known-miss, not a failure. Noise/version-rate/sunset-match are informational.
Pure + deterministic; matched by repo basename."
```

---

## Task 4: `agent/eval/clone.py` + `agent/eval/render.py`

**Files:**
- Create: `agent/eval/clone.py`, `agent/eval/render.py`
- Create: `tests/test_eval_clone.py`, `tests/test_eval_render.py`

**Interfaces:**
- Produces: `clone.sync_corpus(entries, sandbox_root, *, git=..., no_fetch=False) -> list[str]` (returns the per-entry checkout paths); `render.render_scorecard(scorecard) -> str`. Task 5 calls both.
- Injected git contract: `git(args: list, cwd=None) -> str` (stdout, or `""` on failure).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_clone.py`:

```python
import pytest
from agent.eval import clone


def _entry(repo="o/ebay-sdk-php", sha="a" * 40):
    return {"repo": repo, "url": f"https://github.com/{repo}.git", "sha": sha, "category": "ebay"}


def test_clones_absent_repo_then_checks_out_and_verifies(tmp_path):
    calls = []

    def fake_git(args, cwd=None):
        calls.append((args, cwd))
        if args[-1] == "HEAD" and "rev-parse" in args:
            return "a" * 40                       # HEAD == sha -> verified
        if "status" in args:
            return ""                             # clean tree
        return ""

    paths = clone.sync_corpus([_entry()], str(tmp_path), git=fake_git)
    joined = " ".join(" ".join(a) for a, _ in calls)
    assert "clone --filter=blob:none" in joined
    assert "checkout " + "a" * 40 in joined
    assert "rev-parse HEAD" in joined
    assert paths == [str(tmp_path / "ebay" / "ebay-sdk-php")]


def test_hard_fails_when_head_does_not_match_sha(tmp_path):
    def fake_git(args, cwd=None):
        if "rev-parse" in args:
            return "b" * 40                       # HEAD != declared sha "a"*40
        return ""
    with pytest.raises(RuntimeError, match="SHA mismatch|a{6}"):
        clone.sync_corpus([_entry()], str(tmp_path), git=fake_git)


def test_refuses_a_dirty_tree(tmp_path):
    # pre-create the dir so it's treated as existing (fetch path)
    (tmp_path / "ebay" / "ebay-sdk-php" / ".git").mkdir(parents=True)

    def fake_git(args, cwd=None):
        if "status" in args:
            return " M somefile.php"              # dirty
        if "rev-parse" in args:
            return "a" * 40
        return ""
    with pytest.raises(RuntimeError, match="dirty|uncommitted"):
        clone.sync_corpus([_entry()], str(tmp_path), git=fake_git)
```

Create `tests/test_eval_render.py`:

```python
from agent.eval.render import render_scorecard


def _sc(passed=True):
    return {"category": "ebay", "now": "2026-07-16",
            "repos": [{"repo": "o/ebay-sdk-php", "detected": True, "via": "sdk",
                       "miss_mode": None, "noise": 3, "version_rate": 0.5,
                       "sunset_expected": True, "sunset_hit": True, "errored": False}],
            "summary": {"recall": {"passed": 1, "total": 1, "endpoint": 0, "sdk_only": 1,
                                   "known_miss": 0, "holdout": 0},
                        "noise": {"median": 3, "max": 3}, "version_rate": 0.5,
                        "sunset_match": {"expected": 1, "hit": 1}, "errored": 0},
            "gate": {"passed": passed, "failures": [] if passed else ["o/x"]}}


def test_table_shows_recall_gate_and_metrics():
    out = render_scorecard(_sc(passed=True))
    assert "ebay" in out
    assert "RECALL" in out and "PASS" in out
    assert "1/1" in out
    assert "noise" in out.lower() and "sunset" in out.lower() and "version" in out.lower()


def test_table_shows_fail_when_gate_fails():
    out = render_scorecard(_sc(passed=False))
    assert "FAIL" in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_eval_clone.py tests/test_eval_render.py -q`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

Create `agent/eval/clone.py`:

```python
"""Pin-verifying clone of the corpus into <sandbox>/<category>/<name>. Git is injected
(git(args, cwd=None) -> stdout). Reproducibility is enforced: after checkout, HEAD must
equal the declared sha (hard-fail on mismatch = corpus drift), and a dirty tree is refused.
Clones are third-party public code and are never committed."""
from __future__ import annotations

import os


def _default_git(args, cwd=None) -> str:  # pragma: no cover - real git subprocess
    import subprocess
    cmd = ["git"] + (["-C", cwd] if cwd else []) + args
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _dest(sandbox_root, entry) -> str:
    name = os.path.basename(entry["repo"].rstrip("/"))
    return os.path.join(sandbox_root, entry["category"], name)


def sync_corpus(entries: list, sandbox_root: str, *, git=_default_git, no_fetch=False) -> list:
    paths = []
    for e in entries:
        dest = _dest(sandbox_root, e)
        sha = e["sha"]
        if os.path.isdir(os.path.join(dest, ".git")):
            if not no_fetch:
                git(["fetch", "origin", sha], cwd=dest)
            dirty = git(["status", "--porcelain"], cwd=dest)
            if dirty:
                raise RuntimeError(f"{dest}: dirty/uncommitted tree — refusing to checkout over it")
        else:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            git(["clone", "--filter=blob:none", e["url"], dest])
        git(["checkout", sha], cwd=dest)
        head = git(["rev-parse", "HEAD"], cwd=dest)
        if head != sha:
            raise RuntimeError(f"{dest}: SHA mismatch — HEAD {head!r} != pinned {sha!r} (corpus drift)")
        paths.append(dest)
    return paths
```

Create `agent/eval/render.py`:

```python
"""Render a scorecard dict into a terminal table. Pure (string in, string out).
Noise is printed right next to recall so recall can't be read in isolation."""
from __future__ import annotations


def _pct(x):
    return "—" if x is None else f"{round(x * 100)}%"


def render_scorecard(sc: dict) -> str:
    s = sc["summary"]
    rc = s["recall"]
    gate = "PASS" if sc["gate"]["passed"] else "FAIL"
    lines = [f"drift-eval · {sc['category']} · {sc.get('now', '')}".rstrip(), ""]
    lines.append(f"RECALL   {rc['passed']}/{rc['total']} detect vendor   [{gate}]")
    lines.append(f"         endpoint {rc['endpoint']} · sdk-only {rc['sdk_only']} · "
                 f"known-miss {rc['known_miss']} · holdout {rc['holdout']}")
    lines.append(f"noise    median {s['noise']['median']} · max {s['noise']['max']} unknown hosts/repo  (info)")
    lines.append(f"version  {_pct(s['version_rate'])} of classified endpoints carry a version  (info)")
    lines.append(f"sunset   {s['sunset_match']['hit']}/{s['sunset_match']['expected']} expected fired  (info)")
    lines.append(f"errored  {s['errored']}")
    lines += ["", "repo                                   detect  via       noise  ver   sunset"]
    for r in sc["repos"]:
        det = "✓" if r["detected"] else ("known" if r["miss_mode"] not in (None, "unattributed") else "✗")
        sun = "—" if not r["sunset_expected"] else ("✓" if r["sunset_hit"] else "✗")
        lines.append(f"{r['repo'][:36]:36}  {det:6}  {str(r['via'] or '-'):8}  "
                     f"{r['noise']:>4}   {_pct(r['version_rate']):>4}  {sun}")
    if not sc["gate"]["passed"]:
        lines += ["", f"GATE FAILED — undetected (non-known-gap): {', '.join(sc['gate']['failures'])}"]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_eval_clone.py tests/test_eval_render.py -q`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add agent/eval/clone.py agent/eval/render.py tests/test_eval_clone.py tests/test_eval_render.py
git commit -m "feat(eval): pin-verifying clone + scorecard renderer

sync_corpus clones (blob-filtered) / fetches into <sandbox>/<category>/<name>,
checks out the pinned sha, and HARD-FAILS if HEAD != sha or the tree is dirty
(injected git). render_scorecard prints recall+gate with noise beside it."
```

---

## Task 5: `agent/eval/runner.py` + `agent/eval/cli.py` + `bin/drift-eval`

**Files:**
- Create: `agent/eval/runner.py`, `agent/eval/cli.py`, `bin/drift-eval`
- Create: `tests/test_eval_runner.py`

**Interfaces:**
- Consumes: `load_corpus` (T2), `score` (T3), `sync_corpus`/`render_scorecard` (T4), `eval_home` (T1), and the pipeline functions `scan_folder`/`audit_inventory`.
- Produces: `runner.run_category(category, *, now, sandbox_root, corpus_path, no_clone=False, git=..., scan=scan_folder, audit=audit_inventory) -> dict` (returns the scorecard, writes files); `cli.main(argv) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_eval_runner.py`:

```python
import json
import os
import pytest
from agent.eval import runner


_CORPUS = """
- repo: o/ebay-sdk-php
  url: https://github.com/o/ebay-sdk-php.git
  sha: "{sha}"
  license: MIT
  category: ebay
  expect: {{ vendor: eBay, sunset_host: svcs.ebay.com }}
  fetched_at: "2026-07-16"
""".format(sha="a" * 40)


def _corpus_file(tmp_path):
    p = tmp_path / "corpus.yaml"
    p.write_text(_CORPUS)
    return str(p)


def _fake_scan(root, state, now, **kw):
    # one repo, one classified eBay endpoint — as if scanned
    doc = {"repos": [{"path": "ebay-sdk-php",
                      "endpoints": [{"vendor": "eBay", "classified": True, "version": "v1",
                                     "domain": "svcs.ebay.com"}],
                      "sdks": []}],
           "coverage": {"reposErrored": []}}
    return {"doc": doc, "report_md": "", "diff": {}}


def _fake_audit(doc, now, **kw):
    return {"findings": [{"kind": "sunset", "domain": "svcs.ebay.com", "ref": "eBay"}]}


def test_run_category_scores_writes_and_passes_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_HOME", str(tmp_path / "drift"))
    sc = runner.run_category("ebay", now="2026-07-16", sandbox_root=str(tmp_path / "sandbox"),
                             corpus_path=_corpus_file(tmp_path),
                             git=lambda args, cwd=None: ("a" * 40 if "rev-parse" in args else ""),
                             scan=_fake_scan, audit=_fake_audit)
    assert sc["gate"]["passed"] is True
    assert sc["now"] == "2026-07-16"
    assert sc["summary"]["sunset_match"] == {"expected": 1, "hit": 1}
    # scorecard.json written under eval_home/runs/<now>/<category>/
    out = tmp_path / "drift" / "eval" / "runs" / "2026-07-16" / "ebay" / "scorecard.json"
    assert out.exists() and json.loads(out.read_text())["gate"]["passed"] is True
    # a history line appended
    hist = tmp_path / "drift" / "eval" / "scorecards" / "history.jsonl"
    assert hist.exists() and "ebay" in hist.read_text()


def test_cli_returns_exit_code_from_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_HOME", str(tmp_path / "drift"))
    from agent.eval import cli
    # a scan that detects nothing -> gate fails -> exit 1
    monkeypatch.setattr(runner, "scan_folder",
                        lambda *a, **k: {"doc": {"repos": [{"path": "ebay-sdk-php",
                                                            "endpoints": [], "sdks": []}],
                                                "coverage": {"reposErrored": []}}, "report_md": "", "diff": {}})
    monkeypatch.setattr(runner, "audit_inventory", lambda *a, **k: {"findings": []})
    rc = cli.main(["run", "ebay", "--now", "2026-07-16", "--no-clone",
                   "--sandbox", str(tmp_path / "sandbox"), "--corpus", _corpus_file(tmp_path)])
    assert rc == 1


@pytest.mark.skipif(not os.environ.get("DRIFT_EVAL_LIVE"),
                    reason="opt-in live smoke (set DRIFT_EVAL_LIVE=1); clones a real repo, runs the engine")
def test_live_smoke_one_real_ebay_repo(tmp_path, monkeypatch):
    # Uses the committed eval/corpus.yaml; scores the FIRST entry's repo for real.
    monkeypatch.setenv("DRIFT_HOME", str(tmp_path / "drift"))
    sc = runner.run_category("ebay", now="2026-07-16", sandbox_root=str(tmp_path / "sandbox"),
                             corpus_path="eval/corpus.yaml")
    assert sc["gate"]["passed"] is True
    assert any(r["detected"] for r in sc["repos"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eval_runner.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the runner**

Create `agent/eval/runner.py`:

```python
"""Orchestrate one eval run: load corpus -> clone (pin-verified) -> scan+audit each repo
in-process (OSV/EOL stubbed off, so only the deterministic sunset join runs) -> score ->
render -> write under ~/.drift/eval. Seams (git, scan, audit) are injected for tests."""
from __future__ import annotations

import json
import os

from agent.inventory_scan import scan_folder
from agent.audit import audit_inventory
from agent.lib.drift_home import eval_home
from agent.eval.corpus import load_corpus
from agent.eval.clone import sync_corpus
from agent.eval.score import score
from agent.eval.render import render_scorecard

_NOOP_OSV = lambda *a, **k: []          # noqa: E731 - offline: contribute no CVEs
_NOOP_EOL = lambda *a, **k: None        # noqa: E731 - offline: contribute no EOL


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)


def run_category(category, *, now, sandbox_root, corpus_path, no_clone=False,
                 git=None, scan=None, audit=None) -> dict:
    scan = scan or scan_folder
    audit = audit or audit_inventory
    entries = [e for e in load_corpus(corpus_path) if e.get("category") == category]
    if not entries:
        raise ValueError(f"no corpus entries for category {category!r} in {corpus_path}")

    if not no_clone:
        kw = {"git": git} if git is not None else {}
        sync_corpus(entries, sandbox_root, **kw)

    cat_root = os.path.join(sandbox_root, category)
    state_dir = os.path.join(eval_home(), "runs", now, category, "_state")
    scan_res = scan(cat_root, state_dir, now, engine="semgrep")
    inventory = scan_res["doc"]
    audit_doc = audit(inventory, now, osv_query=_NOOP_OSV, eol_check=_NOOP_EOL)

    sc = score(entries, inventory, audit_doc)
    sc["now"] = now

    run_dir = os.path.join(eval_home(), "runs", now, category)
    _write_json(os.path.join(run_dir, "inventory.json"), inventory)
    _write_json(os.path.join(run_dir, "audit.json"), audit_doc)
    _write_json(os.path.join(run_dir, "scorecard.json"), sc)
    hist = os.path.join(eval_home(), "scorecards", "history.jsonl")
    os.makedirs(os.path.dirname(hist), exist_ok=True)
    with open(hist, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"now": now, "category": category, "summary": sc["summary"],
                             "gate": sc["gate"]["passed"]}, sort_keys=True) + "\n")
    return sc
```

- [ ] **Step 4: Implement the CLI**

Create `agent/eval/cli.py`:

```python
"""drift-eval CLI: `run <category>`. Exit code comes from the recall gate."""
from __future__ import annotations

import argparse
import os
import sys

from agent.eval import runner
from agent.eval.render import render_scorecard


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="drift-eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run")
    pr.add_argument("category")
    pr.add_argument("--now", default=None)
    pr.add_argument("--sandbox", default=os.path.expanduser("~/Projects/sandbox"))
    pr.add_argument("--corpus", default="eval/corpus.yaml")
    pr.add_argument("--no-clone", action="store_true")
    args = ap.parse_args(argv)

    now = args.now or "1970-01-01"       # caller should pass --now; fixed default keeps it deterministic
    sc = runner.run_category(args.category, now=now, sandbox_root=args.sandbox,
                             corpus_path=args.corpus, no_clone=args.no_clone)
    sys.stdout.write(render_scorecard(sc))
    return 0 if sc["gate"]["passed"] else 1


if __name__ == "__main__":                # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 5: Implement the self-bootstrapping runner**

Create `bin/drift-eval` (mirror `bin/drift-scan`'s provisioning; reuse the same `.venv`):

```bash
#!/usr/bin/env bash
# Self-bootstrapping runner for the Drift Detector EVAL harness. Reuses the plugin's
# .venv (semgrep + deps) and runs `python -m agent.eval.cli`. Works from any cwd.
set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
if [ -z "$PLUGIN_ROOT" ]; then
  PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
VENV="$PLUGIN_ROOT/.venv"
MARKER="$VENV/.drift-deps-ok"
REQ="$PLUGIN_ROOT/requirements-plugin.txt"
PYVER="3.12"

if [ ! -f "$MARKER" ]; then
  echo "drift-eval: first-run setup — provisioning venv + engine (one-time)…" >&2
  if command -v uv >/dev/null 2>&1; then
    uv venv --python "$PYVER" "$VENV" 1>&2
    VIRTUAL_ENV="$VENV" uv pip install -q -r "$REQ" 1>&2
  elif command -v "${DRIFT_PYTHON:-python3}" >/dev/null 2>&1 \
       && "${DRIFT_PYTHON:-python3}" -c 'import ensurepip, venv' 2>/dev/null; then
    "${DRIFT_PYTHON:-python3}" -m venv "$VENV"
    "$VENV/bin/python" -m pip install -q --upgrade pip 1>&2
    "$VENV/bin/python" -m pip install -q -r "$REQ" 1>&2
  else
    echo "drift-eval: no usable uv/python — run /drift-detector doctor" >&2; exit 3
  fi
  touch "$MARKER"
fi

exec env PYTHONPATH="$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  "$VENV/bin/python" -m agent.eval.cli "$@"
```

Make it executable: `chmod +x bin/drift-eval`.

- [ ] **Step 6: Run to verify tests pass**

Run: `.venv/bin/python -m pytest tests/test_eval_runner.py -q`
Expected: PASS (the live smoke is skipped — `DRIFT_EVAL_LIVE` unset).

- [ ] **Step 7: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
chmod +x bin/drift-eval
git add agent/eval/runner.py agent/eval/cli.py bin/drift-eval tests/test_eval_runner.py
git commit -m "feat(eval): runner + CLI + self-bootstrapping bin/drift-eval

run_category clones the pinned corpus, scans+audits in-process (OSV/EOL stubbed
off -> deterministic sunset-only), scores, writes scorecard.json + history.jsonl
under ~/.drift/eval, exits from the recall gate. Opt-in live smoke (DRIFT_EVAL_LIVE)."
```

---

## Task 6: `eval/corpus.yaml` — the real pinned eBay corpus (research task, runs LAST)

**Files:**
- Create: `eval/corpus.yaml`

**This task produces real data by verification, never invention.** Every repo and SHA must be confirmed to exist before it is committed. Note: the clones live at `~/Projects/sandbox/` and artifacts at `~/.drift/` — both **outside** this repo — so nothing to gitignore; the Step 4 check is a safety confirmation only.

- [ ] **Step 1: Discover candidate repos**

Find ~5 real public PHP eBay repos spanning the tool's weak spots:
- **Packagist:** search `ebay`, sort by downloads; open the top few, follow to their GitHub. `davidtsadler/ebay-sdk-php` is the de-facto PHP eBay SDK — verify it exists.
- **GitHub code search** (`gh api` or the web): search `svcs.ebay.com` and `open.api.ebay.com` in language:PHP to find a **legacy** repo that actually calls the retired Finding/Shopping APIs (so the sunset fires).
- Aim for a mix: 1 SDK (`sdk-only-no-callsite` likely), 2 community clients (hard-coded URLs), 1 sample/demo app (config-driven URL), 1 legacy repo hitting `svcs.ebay.com`.

For each candidate, verify it exists and get its real default-branch HEAD SHA and license:

```bash
# real SHA without cloning:
git ls-remote https://github.com/<owner>/<repo>.git HEAD
# license via GitHub API:
gh api repos/<owner>/<repo> --jq '.license.spdx_id'   # or read LICENSE
```

- [ ] **Step 2: Write `eval/corpus.yaml`** with the verified entries (real url + real 40-hex sha + real SPDX license + `fetched_at: "<today>"`). Mark exactly one entry `holdout: true`. Add `known_gaps` only where you have a real reason (e.g. `sdk-only-no-callsite` for a pure SDK with no hard-coded URL). Set `expect.sunset_host: svcs.ebay.com` on the legacy repo. Example shape (fill with REAL values):

```yaml
- repo: davidtsadler/ebay-sdk-php
  url: https://github.com/davidtsadler/ebay-sdk-php.git
  sha: "<real 40-hex from git ls-remote>"
  license: "<real SPDX>"
  category: ebay
  expect: { vendor: eBay, sdk_keywords: [ebay] }
  known_gaps: [sdk-only-no-callsite]     # only if verified true after the first run
  holdout: false
  fetched_at: "<today>"
```

- [ ] **Step 3: Run the harness for real and capture the scorecard**

```bash
.venv/bin/python -m pytest tests/test_eval_corpus.py -q     # corpus.yaml still loads/validates
DRIFT_EVAL_LIVE=1 .venv/bin/python -m pytest tests/test_eval_runner.py::test_live_smoke_one_real_ebay_repo -q
./bin/drift-eval run ebay --now "$(date +%F)"
```

Expected: the terminal scorecard prints; the **recall gate PASSES** (every non-known-gap repo detects eBay); the **sunset row shows ≥1/1** (the legacy repo fired `svcs.ebay.com`). If a repo legitimately can't be detected, **do not force the scanner** — either add a truthful `known_gaps` entry (and note why) or drop the repo. Record what you observed in the commit message (the first real scorecard: recall, noise median, version-rate, sunset).

- [ ] **Step 4: Confirm only corpus.yaml is staged** (clones/artifacts are outside the repo)

```bash
git status --porcelain            # expect ONLY eval/corpus.yaml; no sandbox/ or .drift/ paths
```

- [ ] **Step 5: Commit**

```bash
git add eval/corpus.yaml
git commit -m "feat(eval): real pinned eBay corpus + first scorecard

<N> real eBay PHP repos pinned at SHA (SDK + community + sample + 1 legacy on
svcs.ebay.com). First run: recall <p>/<t> PASS, sunset <h>/<e>, noise median
<m>, version <v>%. Clones live in ~/Projects/sandbox (never committed)."
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `~/.drift` home (drift_root/reports_home/eval_home, $DRIFT_HOME) | 1 |
| Litter cleanup | 1 (op step) |
| corpus schema + validation (40-hex sha, required fields, known_gaps∈taxonomy) | 2 |
| taxonomy.md + TAXONOMY constant | 2 |
| pure `score` — recall (endpoint/sdk, endpoint wins), noise, version-rate (zero→None), sunset, errored, the gate + known-gap semantics | 3 |
| pin-verifying clone (blob-filter, checkout, HEAD==sha hard-fail, dirty refuse), injected git | 4 |
| scorecard renderer (recall+gate, noise beside it) | 4 |
| runner in-process scan+audit with OSV/EOL stubbed off; writes scorecard.json + history.jsonl under eval_home; exit from gate | 5 |
| CLI `run <category> [--now --sandbox --no-clone]` | 5 |
| self-bootstrapping bin/drift-eval mirroring bin/drift-scan | 5 |
| opt-in live smoke (DRIFT_EVAL_LIVE) | 5 |
| real pinned corpus, discovered/verified not invented; first real scorecard | 6 |
| determinism (fixed --now, offline audit) | 3 (pure) + 5 (wiring) |
| clones never committed | 6 (gitignore check) |

No gaps.

**Placeholder scan:** the only `<...>` tokens are in Task 6 (real SHA/license/values discovered at build time — explicitly a verification step, never invented) and the `eval/corpus.yaml` schema example. All code steps carry complete code. One transcription artifact flagged inline in Task 5 Step 3 (the duplicated ternary `scan(...)` branch) with the corrected single-line form immediately below it — the implementer writes the corrected form.

**Type consistency:** `score(entries, inventory, audit) -> dict` (T3) is consumed by `render_scorecard(sc)` (T4) and `run_category` (T5) with the exact scorecard keys (`category, repos[], summary{recall,noise,version_rate,sunset_match,errored}, gate{passed,failures}`) — cross-checked against the renderer's reads and the runner test's assertions. `sync_corpus(entries, sandbox_root, *, git, no_fetch)` and `load_corpus(path)` and `eval_home()` signatures match their call sites in `run_category`. The injected git contract `git(args, cwd=None) -> str` is consistent across `clone.py` and the runner/CLI tests.

**Known deliberate choices:** `score` is time-free (the runner stamps `now`) to keep the core pure. The runner stubs OSV/EOL rather than using a raising http, per the spec. Phase-1 corpus expectations are minimal (vendor + optional sunset_host); golden-fact per-repo assertions are Phase 2, out of scope.
