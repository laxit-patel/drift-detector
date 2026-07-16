# Action Model & Report Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn 320 raw findings into ~50 ranked, actionable upgrades, and render a report whose first screen is the most urgent thing rather than the alphabetically-first thing.

**Architecture:** A new `agent/lib/ranking.py` holds the one shared definition of "worse" and "newer" (extracted from `facade.py`, where it already exists but is private). A new `agent/lib/actions.py` groups findings by `(repo, ref)` and ranks them. `agent/lib/audit_render.py` and `agent/lib/chat.py` become thin renderers over `actions[]`. `agent/audit.py` gains one key so EOL findings carry a structured fix like CVE findings already do.

**Tech Stack:** Python 3.12, stdlib only (`re`, `collections`). pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-16-action-model-reporting-design.md` — read it if a requirement here seems ambiguous; it is the source of truth.

## Global Constraints

- Python 3.12 in `.venv` (uv-managed). Run tests with `.venv/bin/python -m pytest -q`. **NO pip** — use `uv pip` if a dep is ever needed (none should be).
- **DETERMINISTIC, ZERO-LLM-TOKEN.** No network in any unit test. Injected seams, matching existing `agent/` style.
- **Deterministic output:** same input → byte-identical `AUDIT.md`. Runs must be diffable; tests must not be flaky. Every sort must have a total-order tie-break.
- **Backward compatibility:** `audit.json` keeps its existing `findings` key unchanged (SARIF/BOM/MCP consumers depend on it). `actions` is **additive**.
- `first_seen` is uniformly ISO `yyyy-mm-dd` (verified across all 320 real findings) — lexicographic `min` is correct.
- Every audited package is a **direct dependency** (`audit.py:88` iterates `r["sdks"]`, which are manifest declarations), so fix commands are safe to emit.
- There are **three** finding kinds: `cve`, `eol`, `sunset`. Never assume only the first two.
- TDD, frequent commits, DRY, YAGNI.

---

## File Structure

| File | Responsibility |
|---|---|
| `agent/lib/ranking.py` *(create)* | The only definition of severity order + version order. Pure, no imports from `agent`. |
| `agent/lib/actions.py` *(create)* | `build_actions(findings) -> list[dict]`. Rollup + rank. Pure. |
| `agent/lib/facade.py` *(modify)* | Delete private `_SEV_RANK`/`_semver_key`; import from `ranking`. |
| `agent/audit.py` *(modify)* | EOL findings carry structured `fixed`. |
| `agent/lib/findings_state.py` *(modify)* | Attach `audit["actions"]` after suppression is known. |
| `agent/lib/audit_render.py` *(rewrite)* | Render `actions[]` → `AUDIT.md`. |
| `agent/lib/chat.py` *(modify)* | Card reports actions. |
| `tests/test_ranking.py` *(create)* | Ranking rules incl. the EOL/SUNSET overdue-ness rule. |
| `tests/test_actions.py` *(create)* | Rollup, semver max, command mapping, sunset path. |
| `tests/test_audit_render.py` *(rewrite)* | Report structure + **the regression test**. |
| `tests/test_audit.py` *(extend)* | EOL structured `fixed`. |
| `tests/test_chat.py` *(extend)* | Card reports action counts. |

**Ordering rationale:** Task 1 has no dependencies. Task 2 is independent of Task 1. Task 3 consumes Task 1 and needs Task 2's data uniformity. Task 4 consumes Task 3.

---

## Task 1: `agent/lib/ranking.py` — the shared order

**Files:**
- Create: `agent/lib/ranking.py`
- Create: `tests/test_ranking.py`
- Modify: `agent/lib/facade.py:14` (delete `_SEV_RANK`), `:17-18` (delete `_semver_key`), `:81`, `:82`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `severity_rank(severity, status=None) -> int` — higher is worse. `0` for unknown/None.
  - `semver_key(s) -> list[int]` — sortable numeric key.

**Why this task exists:** `facade.py:14-18` already contains correct ranking logic. It is private to the MCP facade, so `audit_render.py` cannot reach it and instead does `urgent[:15]` with no sort. This task moves the logic somewhere both can import. It is the root-cause fix.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ranking.py`:

```python
"""The one shared definition of 'worse' and 'newer'. Both the MCP facade and the report
renderer rank with these, so a fix here fixes every surface at once."""
from agent.lib.ranking import severity_rank, semver_key


def test_semver_key_orders_numerically_not_lexically():
    # the real bug this exists to prevent: string sort says "1.10.0" < "1.7.4",
    # which once recommended the LOWER, still-vulnerable version.
    assert semver_key("1.10.0") > semver_key("1.7.4")
    assert max(["1.7.4", "1.10.0", "1.9.2"], key=semver_key) == "1.10.0"


def test_semver_key_handles_junk():
    assert semver_key("") == [0]
    assert semver_key(None) == [0]
    assert semver_key("v2.8.0") == [2, 8, 0]


def test_cve_severity_order():
    ranks = [severity_rank(s) for s in ("CRITICAL", "HIGH", "MODERATE", "LOW", "UNKNOWN")]
    assert ranks == sorted(ranks, reverse=True)
    assert len(set(ranks)) == 5                      # all distinct, no accidental ties


def test_severity_is_case_insensitive_and_none_safe():
    assert severity_rank("critical") == severity_rank("CRITICAL")
    assert severity_rank(None) == 0
    assert severity_rank("") == 0
    assert severity_rank("NONSENSE") == 0


def test_eol_ranked_by_overdue_ness():
    # php 7.4 died in 2022 and has no CVSS score; it must not rank below a LOW CVE.
    assert severity_rank("EOL", "DEPRECATED") == severity_rank("HIGH")
    assert severity_rank("EOL", "REVIEW") == severity_rank("MODERATE")
    assert severity_rank("EOL", "DEPRECATED") > severity_rank("LOW")


def test_sunset_ranked_by_overdue_ness():
    # the moat layer: a retired vendor API in live code. No live fixture produces these
    # yet (the catalog has no matching eBay entry), so this test is the only guard.
    assert severity_rank("SUNSET", "DEPRECATED") == severity_rank("HIGH")
    assert severity_rank("SUNSET", "REVIEW") == severity_rank("MODERATE")
    assert severity_rank("SUNSET", "DEPRECATED") > severity_rank("LOW")


def test_dated_severities_default_to_review_rank_without_status():
    # a caller that forgets `status` gets the conservative rank, never 0
    assert severity_rank("EOL") == severity_rank("MODERATE")
    assert severity_rank("SUNSET") == severity_rank("MODERATE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ranking.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.ranking'`

- [ ] **Step 3: Write the implementation**

Create `agent/lib/ranking.py`:

```python
"""The one shared definition of 'worse' (severity) and 'newer' (version).

Both the MCP facade and the report renderer import these. Keeping one copy is the point:
the ranking logic used to live privately in facade.py, so audit_render.py could not reach it
and ranked nothing at all.
"""
from __future__ import annotations

import re

_SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0, "": 0}

# Severities with no CVSS score. Ranked by overdue-ness instead: the audit already decided
# past-due vs approaching when it set `status`, so reuse that rather than re-deriving it.
_DATED_SEVERITIES = {"EOL", "SUNSET"}


def severity_rank(severity, status=None) -> int:
    """Rank a severity; higher is worse. Unknown/None -> 0.

    EOL (dead runtime/framework) and SUNSET (retired vendor API) carry no CVSS score, so they
    are ranked by overdue-ness: past its date (audit marks these DEPRECATED) ranks as HIGH;
    approaching or unconfirmed (REVIEW) ranks as MODERATE.
    """
    sev = str(severity or "").upper()
    if sev in _DATED_SEVERITIES:
        return _SEV_RANK["HIGH"] if status == "DEPRECATED" else _SEV_RANK["MODERATE"]
    return _SEV_RANK.get(sev, 0)


def semver_key(s):
    """Sortable numeric key for a version string. '1.10.0' > '1.7.4' (a string sort gets this
    backwards, which once recommended a lower, still-vulnerable version)."""
    return [int(p) for p in re.findall(r"\d+", str(s))] or [0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ranking.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Switch `facade.py` to the shared module**

In `agent/lib/facade.py`, **delete** lines 14–18 (the `_SEV_RANK` dict and the `_semver_key` function) and add the import next to the existing `agent.lib` imports:

```python
from agent.lib import osv, eol
from agent.lib.http_util import default_http
from agent.lib.ranking import severity_rank, semver_key
```

Then change the two call sites. `facade.py:81`:

```python
    worst = max((v.get("severity", "") for v in vulns), key=severity_rank, default=None)
```

`facade.py:82`:

```python
    fixes = sorted({v["fixed"] for v in vulns if v.get("fixed")}, key=semver_key)   # numeric, not string sort
```

This is behaviour-preserving: `severity_rank(s)` with the default `status=None` is identical to the old inline lambda for every non-EOL severity, and this call site only ever sees OSV CVE severities — never `EOL` or `SUNSET`, which are produced solely by `audit.py`.

- [ ] **Step 6: Verify facade is unchanged**

Run: `.venv/bin/python -m pytest tests/test_facade.py tests/test_ranking.py -q`
Expected: PASS. **`tests/test_facade.py` must pass without being edited.** If it needs a change, the extraction altered behaviour — stop and re-read Step 5.

- [ ] **Step 7: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
git add agent/lib/ranking.py tests/test_ranking.py agent/lib/facade.py
git commit -m "refactor(ranking): extract shared severity/version order from facade

The renderer could not reach facade's private _SEV_RANK/_semver_key, so it
ranked nothing. One shared module; EOL and SUNSET rank by overdue-ness."
```

---

## Task 2: EOL findings carry a structured fix

**Files:**
- Modify: `agent/audit.py:139-145`
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: nothing.
- Produces: every `kind == "eol"` finding gains `"fixed": <str|None>` — the same key CVE findings already carry (`audit.py:115`). Task 3 relies on this so it never parses English.

**Why:** measured on real data — 273 of 320 findings carry `fixed`; all 34 EOL findings carry the target **only inside prose** (`"upgrade to 8.5.8"`). `res["recommended"]` is already read on the next line to build that prose, so the value is in hand.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit.py`:

```python
def test_eol_finding_carries_structured_fixed_version():
    # the renderer must never parse "upgrade to 8.5.8" back out of prose
    def eol_check(product, floor_, now, **kw):
        return {"status": "DEPRECATED", "cycle": "7.4", "eol_date": "2022-11-28",
                "recommended": "8.5.8", "source_url": "https://endoflife.date/php"}

    doc = {"repos": [{"path": "r", "sdks": [], "runtimes": {"php": {"range": "^7.4"}}}]}
    out = audit_inventory(doc, "2026-07-14", http=lambda *a, **k: {},
                          osv_query=lambda *a, **k: [], eol_check=eol_check)
    eol_findings = [f for f in out["findings"] if f["kind"] == "eol"]
    assert len(eol_findings) == 1
    assert eol_findings[0]["fixed"] == "8.5.8"                       # structured
    assert eol_findings[0]["recommendation"] == "upgrade to 8.5.8"   # prose still there


def test_eol_finding_fixed_is_none_when_no_recommendation():
    def eol_check(product, floor_, now, **kw):
        return {"status": "DEPRECATED", "cycle": "7.4", "eol_date": "2022-11-28",
                "recommended": None, "source_url": "https://endoflife.date/php"}

    doc = {"repos": [{"path": "r", "sdks": [], "runtimes": {"php": {"range": "^7.4"}}}]}
    out = audit_inventory(doc, "2026-07-14", http=lambda *a, **k: {},
                          osv_query=lambda *a, **k: [], eol_check=eol_check)
    eol_findings = [f for f in out["findings"] if f["kind"] == "eol"]
    assert eol_findings[0]["fixed"] is None
    assert eol_findings[0]["recommendation"] == "upgrade to a supported release"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_audit.py -q -k structured_fixed`
Expected: FAIL — `KeyError: 'fixed'`

- [ ] **Step 3: Add the key**

In `agent/audit.py`, in the EOL finding dict at lines 139-145, add `"fixed"` immediately after `"version"`:

```python
                findings.append({
                    "repo": path, "kind": "eol", "ref": product, "version": spec,
                    "fixed": res.get("recommended"),
                    "status": res["status"], "severity": "EOL",
                    "detail": f"{product} {res['cycle']} end-of-life {res.get('eol_date') or ''}".strip(),
                    "date": res.get("eol_date"), "source_url": res["source_url"], "tier": 1,
                    "recommendation": (f"upgrade to {res['recommended']}" if res.get("recommended") else "upgrade to a supported release"),
                })
```

Do **not** touch the `recommendation` line — the prose stays for backward compatibility.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_audit.py -q`
Expected: PASS, no regressions in the existing audit tests.

- [ ] **Step 5: Commit**

```bash
git add agent/audit.py tests/test_audit.py
git commit -m "feat(audit): EOL findings carry a structured fixed version

All 34 EOL findings had the target only inside prose ('upgrade to 8.5.8').
res['recommended'] was already in hand. Now every finding kind is uniform
and the action model never parses English."
```

---

## Task 3: `agent/lib/actions.py` — the rollup

**Files:**
- Create: `agent/lib/actions.py`
- Create: `tests/test_actions.py`
- Modify: `agent/lib/findings_state.py` (import at top; one line after line 104)

**Interfaces:**
- Consumes: `severity_rank(severity, status=None)`, `semver_key(s)` from `agent.lib.ranking` (Task 1). `finding["fixed"]` on EOL findings (Task 2).
- Produces: `build_actions(findings: list[dict]) -> list[dict]`, ranked. Action dict keys, all always present:
  `repo, ref, eco, pkg, kind, current_version, fix_version, command, recommendation, worst, status, finding_count, critical_count, first_seen, files, fixes, sources`.
  Also: `audit["actions"]` is attached by `apply_lifecycle`. Task 4 consumes both.

**Why:** measured on the real run — 320 findings are 90 distinct `(repo, ref)` actions, 50 of them actionable. `python/torch` alone is 30 findings and 16 distinct `fixed` values that must resolve to a single max version.

- [ ] **Step 1: Write the failing test**

Create `tests/test_actions.py`:

```python
"""The rollup: findings are advisories, actions are jobs. 30 torch CVEs are one upgrade."""
from agent.lib.actions import build_actions


def _cve(repo="r", ref="npm/axios", version="0.21.1", fixed="1.16.0",
         severity="HIGH", status="DEPRECATED", first_seen="2026-07-15", **kw):
    return {"repo": repo, "ref": ref, "kind": "cve", "version": version, "fixed": fixed,
            "severity": severity, "status": status, "first_seen": first_seen,
            "detail": "d", "recommendation": f"upgrade to >= {fixed}",
            "source_url": f"https://osv.dev/{fixed}", "tier": 1, **kw}


def test_findings_collapse_to_one_action_per_repo_and_ref():
    actions = build_actions([_cve(fixed="1.1.0"), _cve(fixed="1.2.0"), _cve(fixed="1.3.0")])
    assert len(actions) == 1
    assert actions[0]["finding_count"] == 3


def test_fix_version_is_the_semver_max_not_the_string_max():
    # the real torch case: 16 distinct 'fixed' values; only the max satisfies all 30 advisories.
    fixes = ["1.5.0", "2.8.0", "1.10.0", "1.7.4", "2.0.1", "1.13.0", "2.4.1", "1.9.0",
             "2.2.0", "1.11.0", "2.6.0", "1.8.1", "2.1.0", "1.12.0", "2.7.0", "1.6.0"]
    actions = build_actions([_cve(ref="python/torch", version="1.1.0", fixed=f) for f in fixes])
    assert actions[0]["fix_version"] == "2.8.0"      # not "2.7.0" (last), not "1.9.0" (string max)


def test_same_ref_in_two_repos_is_two_actions():
    actions = build_actions([_cve(repo="a"), _cve(repo="b")])
    assert len(actions) == 2
    assert {a["repo"] for a in actions} == {"a", "b"}


def test_action_with_no_fix_is_still_emitted():
    actions = build_actions([_cve(fixed=None, recommendation="review advisory")])
    assert len(actions) == 1
    assert actions[0]["fix_version"] is None
    assert actions[0]["command"] is None
    assert actions[0]["recommendation"] == "review advisory"


def test_worst_and_status_aggregate_across_the_group():
    actions = build_actions([_cve(severity="LOW", status="REVIEW"),
                             _cve(severity="CRITICAL", status="DEPRECATED"),
                             _cve(severity="MODERATE", status="REVIEW")])
    assert actions[0]["worst"] == "CRITICAL"
    assert actions[0]["status"] == "DEPRECATED"      # DEPRECATED if ANY finding is
    assert actions[0]["critical_count"] == 1
    assert actions[0]["first_seen"] == "2026-07-15"


def test_ranking_critical_first_then_finding_count():
    small_crit = _cve(repo="z", ref="npm/a", severity="CRITICAL")
    many_high = [_cve(repo="a", ref="npm/b", severity="HIGH") for _ in range(30)]
    one_high = _cve(repo="a", ref="npm/c", severity="HIGH")
    ranked = build_actions([one_high, *many_high, small_crit])
    assert ranked[0]["ref"] == "npm/a"               # CRITICAL wins despite 1 finding, repo "z"
    assert ranked[1]["ref"] == "npm/b"               # 30 findings beat 1 at equal severity
    assert ranked[2]["ref"] == "npm/c"


def test_deprecated_outranks_review_regardless_of_severity():
    ranked = build_actions([_cve(ref="npm/a", severity="MODERATE", status="REVIEW"),
                            _cve(ref="npm/b", severity="LOW", status="DEPRECATED")])
    assert ranked[0]["ref"] == "npm/b"


def test_ties_break_stably_by_repo_then_ref():
    ranked = build_actions([_cve(repo="b", ref="npm/z"), _cve(repo="a", ref="npm/y"),
                            _cve(repo="a", ref="npm/x")])
    assert [(a["repo"], a["ref"]) for a in ranked] == [("a", "npm/x"), ("a", "npm/y"), ("b", "npm/z")]


def test_command_per_ecosystem():
    npm = build_actions([_cve(ref="npm/axios", fixed="1.16.0")])[0]
    assert npm["command"] == "npm install axios@^1.16.0"
    py = build_actions([_cve(ref="python/torch", fixed="2.8.0")])[0]
    assert py["command"] == "pip install 'torch>=2.8.0'"


def test_composer_ref_splits_on_the_first_slash_only():
    a = build_actions([_cve(ref="composer/aws/aws-sdk-php", fixed="3.371.4")])[0]
    assert a["eco"] == "composer"
    assert a["pkg"] == "aws/aws-sdk-php"
    assert a["command"] == "composer require aws/aws-sdk-php:^3.371.4"


def test_unknown_ecosystem_gets_no_command():
    a = build_actions([_cve(ref="cargo/serde", fixed="1.0.0")])[0]
    assert a["command"] is None


def test_eol_action_has_target_but_no_command():
    a = build_actions([{"repo": "r", "ref": "php", "kind": "eol", "version": "^7.4",
                        "fixed": "8.5.8", "severity": "EOL", "status": "DEPRECATED",
                        "first_seen": "2026-07-15", "detail": "php 7.4 end-of-life 2022-11-28",
                        "recommendation": "upgrade to 8.5.8",
                        "source_url": "https://endoflife.date/php", "tier": 1}])[0]
    assert a["fix_version"] == "8.5.8"
    assert a["command"] is None            # upgrading a runtime major is not a one-liner
    assert a["eco"] is None                # "php" has no "/"
    assert a["pkg"] == "php"
    assert a["worst"] == "EOL"


def test_sunset_action_preserves_files_and_emits_no_command():
    # the moat layer: ref is a bare vendor name, there is no `fixed`, and `files` is the payload.
    a = build_actions([{"repo": "r", "ref": "eBay", "kind": "sunset", "version": "v1",
                        "severity": "SUNSET", "status": "DEPRECATED", "first_seen": "2026-07-15",
                        "detail": "eBay v1 retires 2026-09-30 · used at src/Ebay/x.php:11",
                        "date": "2026-09-30", "source_url": "https://developer.ebay.com/x",
                        "tier": 1, "recommendation": "migrate to Sell API before 2026-09-30",
                        "files": ["src/Ebay/x.php:11", "src/Ebay/y.php:40"]}])[0]
    assert a["eco"] is None and a["pkg"] == "eBay"
    assert a["fix_version"] is None
    assert a["command"] is None
    assert a["recommendation"] == "migrate to Sell API before 2026-09-30"
    assert a["files"] == ["src/Ebay/x.php:11", "src/Ebay/y.php:40"]
    assert a["kind"] == "sunset"


def test_files_defaults_to_empty_for_cve_actions():
    # cve/eol findings have no `files` key at all -> must use .get, not []
    assert build_actions([_cve()])[0]["files"] == []


def test_files_union_is_order_stable_and_capped_at_six():
    def sun(files):
        return {"repo": "r", "ref": "eBay", "kind": "sunset", "version": "*",
                "severity": "SUNSET", "status": "REVIEW", "first_seen": "2026-07-15",
                "detail": "d", "recommendation": "migrate", "source_url": "u", "tier": 1,
                "files": files}
    a = build_actions([sun(["a:1", "b:2"]), sun(["b:2", "c:3", "d:4", "e:5", "f:6", "g:7", "h:8"])])[0]
    assert a["files"] == ["a:1", "b:2", "c:3", "d:4", "e:5", "f:6"]      # deduped, in order, capped


def test_sources_are_deduped_and_order_stable():
    a = build_actions([_cve(fixed="1.0.0"), _cve(fixed="1.0.0"), _cve(fixed="2.0.0")])[0]
    assert a["sources"] == ["https://osv.dev/1.0.0", "https://osv.dev/2.0.0"]


def test_empty_input_returns_empty_list():
    assert build_actions([]) == []


def test_output_is_deterministic():
    findings = [_cve(repo="b", ref="npm/z"), _cve(repo="a", ref="npm/y", severity="CRITICAL")]
    assert build_actions(findings) == build_actions(findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_actions.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.actions'`

- [ ] **Step 3: Write the implementation**

Create `agent/lib/actions.py`:

```python
"""Roll findings up into ACTIONS and rank them.

A finding is an advisory. An action is a job: "in this repo, upgrade this one thing." The
30 CVEs against torch 1.1.0 are not 30 jobs — they are one `pip install 'torch>=2.8.0'`.
Measured on a real 60-repo run: 320 findings -> 90 actions, 50 of them action-required.

Pure and deterministic: same input -> identical output, including order.
"""
from __future__ import annotations

from collections import OrderedDict

from agent.lib.ranking import severity_rank, semver_key

_MAX_FILES = 6

# Only `cve` actions get a command: an EOL means upgrading a language runtime or framework
# major, and a SUNSET means migrating to a different vendor API. Neither is a one-liner.
_COMMANDS = {
    "npm": lambda pkg, ver: f"npm install {pkg}@^{ver}",
    "composer": lambda pkg, ver: f"composer require {pkg}:^{ver}",
    "python": lambda pkg, ver: f"pip install '{pkg}>={ver}'",
}


def _split_ref(ref):
    """'composer/aws/aws-sdk-php' -> ('composer', 'aws/aws-sdk-php'). A ref with no '/' —
    every sunset finding, whose ref is a bare vendor name like 'eBay' — -> (None, ref)."""
    ref = str(ref or "")
    if "/" not in ref:
        return None, ref
    eco, pkg = ref.split("/", 1)
    return eco, pkg


def _command(kind, eco, pkg, fix_version):
    if kind != "cve" or not fix_version or eco not in _COMMANDS:
        return None
    return _COMMANDS[eco](pkg, fix_version)


def _rank_key(action):
    """Total order: action-required first, then worst severity, then blast radius, then a
    stable alphabetical tie-break so output is byte-identical across runs."""
    return (
        0 if action["status"] == "DEPRECATED" else 1,
        -severity_rank(action["worst"], action["status"]),
        -action["finding_count"],
        action["repo"],
        action["ref"],
    )


def build_actions(findings: list) -> list:
    """Group findings by (repo, ref) and rank them. Returns a list of action dicts."""
    groups: "OrderedDict[tuple, list]" = OrderedDict()
    for f in findings:
        groups.setdefault((f["repo"], f["ref"]), []).append(f)

    actions = []
    for (repo, ref), group in groups.items():
        # the worst finding drives severity AND supplies the prose fallback
        worst_f = max(group, key=lambda f: severity_rank(f.get("severity"), f.get("status")))
        status = "DEPRECATED" if any(f.get("status") == "DEPRECATED" for f in group) else "REVIEW"
        kind = worst_f.get("kind") if len({f.get("kind") for f in group}) == 1 else "cve"

        fixed = [f["fixed"] for f in group if f.get("fixed")]
        fix_version = max(fixed, key=semver_key) if fixed else None

        eco, pkg = _split_ref(ref)
        actions.append({
            "repo": repo,
            "ref": ref,
            "eco": eco,
            "pkg": pkg,
            "kind": kind,
            "current_version": worst_f.get("version"),
            "fix_version": fix_version,
            "command": _command(kind, eco, pkg, fix_version),
            "recommendation": worst_f.get("recommendation"),
            "worst": worst_f.get("severity"),
            "status": status,
            "finding_count": len(group),
            "critical_count": sum(1 for f in group if str(f.get("severity", "")).upper() == "CRITICAL"),
            "first_seen": min((f["first_seen"] for f in group if f.get("first_seen")), default=None),
            "files": list(OrderedDict.fromkeys(
                p for f in group for p in (f.get("files") or [])))[:_MAX_FILES],
            "fixes": group,
            "sources": [u for u in OrderedDict.fromkeys(
                f.get("source_url") for f in group) if u],
        })

    actions.sort(key=_rank_key)
    return actions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_actions.py -q`
Expected: PASS, 17 passed

- [ ] **Step 5: Wire `actions` into the audit document**

`actions` must be built from **non-suppressed** findings, so it belongs where suppression is already known. `agent/lib/findings_state.py:91` already computes `active`, and lines 99-104 already recompute `counts` from it. Both callers (`agent/run.py:63`, `agent/cli.py:68`) call `apply_lifecycle` right after `audit_inventory`, so this is the single DRY place.

Add the import at the top of `agent/lib/findings_state.py`, alongside the existing imports:

```python
from agent.lib.actions import build_actions
```

Then, immediately after the `audit["counts"] = {...}` block that ends at line 104, add:

```python
    audit["actions"] = build_actions(active)      # ranked jobs; `findings` stays untouched for SARIF/BOM
```

`audit["findings"]` is **not** modified — SARIF, CycloneDX and the MCP facade all read it.

- [ ] **Step 6: Write the wiring test**

Append to `tests/test_actions.py`:

```python
def test_apply_lifecycle_attaches_ranked_actions_excluding_muted(tmp_path):
    from agent.lib.findings_state import apply_lifecycle
    audit = {"generated": "2026-07-15", "coverage": {},
             "findings": [_cve(repo="a", ref="npm/x", severity="CRITICAL"),
                          _cve(repo="a", ref="npm/y", severity="LOW", status="REVIEW")]}
    apply_lifecycle(audit, str(tmp_path), "2026-07-15")
    assert [a["ref"] for a in audit["actions"]] == ["npm/x", "npm/y"]   # ranked
    assert len(audit["findings"]) == 2                                   # findings untouched
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_actions.py tests/test_audit.py -q`
Expected: PASS

- [ ] **Step 8: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 9: Commit**

```bash
git add agent/lib/actions.py tests/test_actions.py agent/lib/findings_state.py
git commit -m "feat(actions): roll findings up into ranked actions

320 findings -> 90 (repo, ref) actions, 50 actionable. fix_version is the
semver MAX across the group (torch: 16 recommendations -> 2.8.0). Commands
only for cve actions with a known eco; sunset/eol get prose. Attached in
apply_lifecycle so muted findings are excluded; `findings` is untouched."
```

---

## Task 4: Render the report and the card from actions

**Files:**
- Rewrite: `agent/lib/audit_render.py`
- Rewrite: `tests/test_audit_render.py`
- Modify: `agent/lib/chat.py:13-47`
- Modify: `tests/test_chat.py`

**Interfaces:**
- Consumes: `audit["actions"]` (Task 3), `build_actions` from `agent.lib.actions`, `severity_rank` from `agent.lib.ranking`.
- Produces: `render_audit_md(audit) -> str`; `build_chat_card(audit, now, folder=None) -> dict` (signature unchanged).

**Why:** this is the task that kills the original bug. `audit_render.py:47` currently reads `for f in urgent[:15]` with no sort, so the 10 CRITICALs sit below `…and 104 more`.

- [ ] **Step 1: Write the failing test**

Replace the contents of `tests/test_audit_render.py`:

```python
"""AUDIT.md renders ACTIONS, ranked. The first thing on the page must be the worst thing."""
from agent.lib.actions import build_actions
from agent.lib.audit_render import render_audit_md


def _cve(repo, ref, severity="HIGH", status="DEPRECATED", fixed="1.16.0", version="0.21.1"):
    return {"repo": repo, "ref": ref, "kind": "cve", "version": version, "fixed": fixed,
            "severity": severity, "status": status, "first_seen": "2026-07-15",
            "detail": "summary text", "recommendation": f"upgrade to >= {fixed}",
            "source_url": "https://osv.dev/x", "tier": 1}


def _audit(findings, **kw):
    actions = build_actions(findings)
    return {"generated": "2026-07-15", "findings": findings, "actions": actions,
            "counts": {"DEPRECATED": sum(1 for f in findings if f["status"] == "DEPRECATED"),
                       "REVIEW": sum(1 for f in findings if f["status"] == "REVIEW"),
                       "reposAffected": len({f["repo"] for f in findings})},
            "coverage": {"notes": []}, **kw}


def test_the_worst_action_is_first_not_the_alphabetically_first_repo():
    # THE REGRESSION TEST. The old renderer did `urgent[:15]` with no sort, so an
    # alphabetically-early repo buried a CRITICAL RCE under "...and 104 more".
    findings = [_cve("aaa/first-alphabetically", "npm/lodash", severity="HIGH")]
    findings += [_cve("zzz/heygen/Wav2Lip", "python/torch", severity="CRITICAL",
                      fixed="2.8.0", version="1.1.0") for _ in range(30)]
    md = render_audit_md(_audit(findings))
    first = md.index("zzz/heygen/Wav2Lip")
    second = md.index("aaa/first-alphabetically")
    assert first < second


def test_do_this_first_shows_the_command():
    md = render_audit_md(_audit([_cve("r", "python/torch", severity="CRITICAL",
                                      fixed="2.8.0", version="1.1.0")]))
    assert "## Do this first" in md
    assert "pip install 'torch>=2.8.0'" in md


def test_thirty_findings_render_as_one_action_saying_thirty():
    findings = [_cve("r", "python/torch", severity="CRITICAL", fixed="2.8.0") for _ in range(30)]
    md = render_audit_md(_audit(findings))
    assert "Fixes 30 advisories" in md
    queue_rows = [l for l in md.splitlines() if l.startswith("| 1 |")]
    assert len(queue_rows) == 1                # exactly one numbered row in the fix queue...
    assert "| 2 |" not in md                   # ...and no second one. 30 findings, 1 job.


def test_truncation_is_announced_never_silent():
    findings = [_cve(f"repo{i:02d}", "npm/x") for i in range(14)]
    md = render_audit_md(_audit(findings))
    assert "10 shown of 14" in md              # "Do this first" caps at 10 and SAYS so
    for i in range(14):
        assert f"repo{i:02d}" in md            # ...but the full queue drops nothing


def test_review_only_actions_are_not_in_the_fix_queue():
    md = render_audit_md(_audit([_cve("r", "npm/x", severity="LOW", status="REVIEW")]))
    assert "## Fix queue" not in md            # nothing action-required -> no queue section
    assert "npm/x" in md                       # ...but it still appears under "By repo"


def test_action_without_a_fix_shows_prose_not_a_broken_command():
    # OSV knows the vuln but no fixed version exists yet (13 such findings in the real run)
    unfixed = _cve("r", "npm/x", fixed=None)
    unfixed["recommendation"] = "review advisory"
    md = render_audit_md(_audit([unfixed]))
    assert "review advisory" in md
    assert "npm install" not in md          # never a command without a version to install
    assert "None" not in md                 # and never a half-formed string


def test_sunset_action_renders_its_call_sites():
    sunset = {"repo": "r", "ref": "eBay", "kind": "sunset", "version": "v1",
              "severity": "SUNSET", "status": "DEPRECATED", "first_seen": "2026-07-15",
              "detail": "eBay v1 retires 2026-09-30", "date": "2026-09-30",
              "source_url": "https://developer.ebay.com/x", "tier": 1,
              "recommendation": "migrate to Sell API before 2026-09-30",
              "files": ["src/Ebay/x.php:11"]}
    md = render_audit_md(_audit([sunset]))
    assert "eBay" in md
    assert "migrate to Sell API before 2026-09-30" in md
    assert "src/Ebay/x.php:11" in md           # the file:line payload is the point


def test_coverage_note_admits_the_transitive_gap():
    md = render_audit_md(_audit([_cve("r", "npm/x")]))
    assert "Only manifest-declared (direct) dependencies are audited" in md


def test_delta_counts_new_actions_not_new_findings():
    # 5 new advisories against one package = ONE new job to do. The delta line must say so,
    # or the weekly "what changed" number keeps overstating the work.
    findings = [_cve("r", "npm/axios") for _ in range(5)]
    md = render_audit_md(_audit(findings, delta={"new": findings, "resolved": [],
                                                 "persisting": [], "mutedCount": 0}))
    assert "🆕 1 new" in md
    assert "## 🆕 New since last scan" in md
    new_bullets = [l for l in md.splitlines() if l.startswith("- ") and "npm/axios" in l]
    assert len(new_bullets) == 1               # one bullet, not five


def test_empty_audit_renders_cleanly():
    md = render_audit_md({"generated": "2026-07-15", "findings": [], "actions": [],
                          "counts": {}, "coverage": {}})
    assert "_No open deprecation or vulnerability findings._" in md


def test_render_is_deterministic():
    a = _audit([_cve("b", "npm/z"), _cve("a", "npm/y", severity="CRITICAL")])
    assert render_audit_md(a) == render_audit_md(a)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_audit_render.py -q`
Expected: FAIL — the current renderer emits neither `## Do this first` nor commands.

- [ ] **Step 3: Write the implementation**

Replace the contents of `agent/lib/audit_render.py`:

```python
"""Render an audit into AUDIT.md — the 'what do I mend' report.

Renders ACTIONS, not raw findings. One upgrade that resolves 30 advisories is one line, and
the top of the report is the highest-ranked job. (The previous version listed findings and
took the first 15 unsorted, which hid every CRITICAL behind an alphabetically-early repo.)
"""
from __future__ import annotations

from collections import defaultdict

from agent.lib.actions import build_actions
from agent.lib.ranking import severity_rank

_BADGE = {"DEPRECATED": "🔴", "REVIEW": "🟠"}
_TOP_N = 10
_TRANSITIVE_NOTE = ("Only manifest-declared (direct) dependencies are audited. Transitive "
                    "dependencies resolved in lockfiles are not queried.")


def _esc(s) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def _target(a) -> str:
    """Where to move to: the exact version when known, else the prose recommendation."""
    if a.get("fix_version"):
        return f"`{_esc(a['current_version'])}` → **`{_esc(a['fix_version'])}`**"
    return _esc(a.get("recommendation") or "review advisory")


def _target_cell(a) -> str:
    if a.get("fix_version"):
        return f"{_esc(a['current_version'])} → {_esc(a['fix_version'])}"
    return _esc(a.get("recommendation") or "review advisory")


def _fixes_phrase(a) -> str:
    n = a["finding_count"]
    out = f"Fixes {n} advisor{'y' if n == 1 else 'ies'}"
    if a.get("critical_count"):
        out += f" ({a['critical_count']} critical)"
    return out


def _render_top(out, actions):
    urgent = [a for a in actions if a["status"] == "DEPRECATED"]
    if not urgent:
        return
    out += ["## Do this first", ""]
    for i, a in enumerate(urgent[:_TOP_N], 1):
        out.append(f"{i}. {_BADGE['DEPRECATED']} **{_esc(a['repo'])}** — "
                   f"`{_esc(a['ref'])}` {_target(a)}")
        line = f"   {_fixes_phrase(a)}."
        if a.get("first_seen"):
            line += f" Open since {_esc(a['first_seen'])}."
        out.append(line)
        if a.get("command"):
            out.append(f"   `{a['command']}`")
        if a.get("files"):
            out.append(f"   Used at: {', '.join(_esc(p) for p in a['files'])}")
        out.append("")
    if len(urgent) > _TOP_N:
        out += [f"_{_TOP_N} shown of {len(urgent)}. Full queue below._", ""]


def _render_queue(out, actions):
    urgent = [a for a in actions if a["status"] == "DEPRECATED"]
    if not urgent:
        return
    out += ["## Fix queue", "",
            "| # | Repo | Package | Now → Fix | Fixes | Worst |",
            "|---|---|---|---|---|---|"]
    for i, a in enumerate(urgent, 1):
        out.append(f"| {i} | {_esc(a['repo'])} | {_esc(a['ref'])} | {_target_cell(a)} "
                   f"| {a['finding_count']} | {_BADGE['DEPRECATED']} {_esc(a['worst'])} |")
    out.append("")


def _render_by_repo(out, actions):
    by_repo = defaultdict(list)
    for a in actions:
        by_repo[a["repo"]].append(a)
    # worst repo first; the actions within a repo are already ranked
    order = sorted(by_repo, key=lambda r: (
        -severity_rank(by_repo[r][0]["worst"], by_repo[r][0]["status"]), r))
    out += ["## By repo", ""]
    for repo in order:
        out.append(f"### {repo}")
        out.append("| Package | Now → Fix | Fixes | Worst | Advisories |")
        out.append("|---|---|---|---|---|")
        for a in by_repo[repo]:
            links = ", ".join(f"[{i}]({u})" for i, u in enumerate(a["sources"][:6], 1)) or "—"
            out.append(f"| {_esc(a['ref'])} | {_target_cell(a)} | {a['finding_count']} "
                       f"| {_BADGE.get(a['status'], '')} {_esc(a['worst'])} | {links} |")
        out.append("")


def render_audit_md(audit: dict) -> str:
    actions = audit.get("actions")
    if actions is None:                       # tolerate a raw audit that skipped apply_lifecycle
        actions = build_actions([f for f in audit.get("findings", []) if not f.get("suppressed")])
    counts = audit.get("counts", {})
    delta = audit.get("delta")
    now = audit.get("generated", "")

    urgent_n = sum(1 for a in actions if a["status"] == "DEPRECATED")
    review_n = len(actions) - urgent_n
    scanned = ((audit.get("coverage") or {}).get("repos") or {}).get("scanned")
    repos_txt = (f"{counts.get('reposAffected', 0)} of {scanned} repos" if scanned
                 else f"{counts.get('reposAffected', 0)} repos")

    out = [f"# Deprecation & Vulnerability Audit — {now}".rstrip(), ""]
    out.append(f"**🔴 {urgent_n} fixes needed · 🟠 {review_n} to review · across {repos_txt}**")

    if delta is not None:
        new_actions = build_actions(delta.get("new", []))
        out += ["", (f"_Since last scan: 🆕 {len(new_actions)} new · "
                     f"✅ {len(delta.get('resolved', []))} resolved · "
                     f"⏳ {len(delta.get('persisting', []))} still open"
                     + (f" · 🔕 {delta.get('mutedCount', 0)} muted"
                        if delta.get("mutedCount") else "") + "_")]
        if new_actions:
            out += ["", "## 🆕 New since last scan", ""]
            for a in new_actions:
                out.append(f"- {_BADGE.get(a['status'], '')} **{_esc(a['ref'])}** in "
                           f"`{_esc(a['repo'])}` — {_target_cell(a)}")
        resolved = delta.get("resolved", [])
        if resolved:
            out += ["", "## ✅ Resolved since last scan", ""]
            for r in resolved:
                out.append(f"- {_esc(r.get('ref'))} ({_esc(r.get('kind'))})")
    out.append("")

    if not actions:
        out += ["_No open deprecation or vulnerability findings._", ""]
    else:
        _render_top(out, actions)
        _render_queue(out, actions)
        _render_by_repo(out, actions)

    out += ["## Coverage & notes", ""]
    for n in (audit.get("coverage", {}) or {}).get("notes", []):
        out.append(f"- {n}")
    out.append(f"- {_TRANSITIVE_NOTE}")
    out.append("")
    return "\n".join(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_audit_render.py -q`
Expected: PASS, 11 passed

- [ ] **Step 5: Update the Chat card to report actions**

In `agent/lib/chat.py`, replace `build_chat_card` (lines 13-47). Keep the signature and the `post_chat` function exactly as they are:

```python
def build_chat_card(audit: dict, now: str, *, folder: str | None = None) -> dict:
    c = audit.get("counts", {})
    delta = audit.get("delta")
    actions = audit.get("actions")
    if actions is None:
        actions = build_actions([f for f in audit.get("findings", []) if not f.get("suppressed")])
    urgent = [a for a in actions if a["status"] == "DEPRECATED"]

    dep = Counter(a["repo"] for a in urgent)
    worst = "<br>".join(f"• <b>{repo}</b> — {n}" for repo, n in dep.most_common(5)) or "—"
    top = "<br>".join(
        f"• {a['ref']} {a['current_version']} → {a['fix_version'] or a['recommendation']}"
        f" ({a['finding_count']})" for a in urgent[:5]) or "—"

    sections = []
    if delta is not None:
        new_actions = build_actions(delta.get("new", []))
        change = (f"🆕 <b>{len(new_actions)} new</b> · ✅ {len(delta.get('resolved', []))} resolved"
                  f" · ⏳ {len(delta.get('persisting', []))} still open")
        section_new = "<br>".join(f"• {a['ref']} in {a['repo']}" for a in new_actions[:5]) or "—"
        sections.append({"header": "Since last scan", "widgets": [
            {"textParagraph": {"text": change}},
            {"textParagraph": {"text": "<b>New:</b><br>" + section_new}}]})
    sections += [
        {"header": "Worst repos", "widgets": [{"textParagraph": {"text": worst}}]},
        {"header": "Top fixes", "widgets": [{"textParagraph": {"text": top}}]},
    ]
    if folder:
        sections.append({"widgets": [{"textParagraph": {"text": f"Full report in <code>{folder}/.drift-detector/AUDIT.md</code>"}}]})

    return {"cardsV2": [{
        "cardId": "drift-audit",
        "card": {
            "header": {
                "title": f"Drift Audit — {now}",
                "subtitle": f"🔴 {len(urgent)} fixes needed · "
                            f"🟠 {len(actions) - len(urgent)} review · "
                            f"{c.get('reposAffected', 0)} repos",
            },
            "sections": sections,
        },
    }]}
```

Add the import at the top of `agent/lib/chat.py`:

```python
from agent.lib.actions import build_actions
```

- [ ] **Step 6: Write the card test**

Append to `tests/test_chat.py`:

```python
def test_card_reports_actions_not_raw_findings():
    from agent.lib.actions import build_actions
    findings = [{"repo": "r", "ref": "python/torch", "kind": "cve", "version": "1.1.0",
                 "fixed": "2.8.0", "severity": "CRITICAL", "status": "DEPRECATED",
                 "first_seen": "2026-07-15", "detail": "d",
                 "recommendation": "upgrade to >= 2.8.0",
                 "source_url": "https://osv.dev/x", "tier": 1} for _ in range(30)]
    audit = {"findings": findings, "actions": build_actions(findings),
             "counts": {"reposAffected": 1}, "coverage": {}}
    card = build_chat_card(audit, "2026-07-15")
    sub = card["cardsV2"][0]["card"]["header"]["subtitle"]
    assert "1 fixes needed" in sub          # ONE action, not 30 findings
    body = str(card)
    assert "1.1.0 → 2.8.0" in body
    assert "(30)" in body                   # ...and it says how many advisories it clears
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_chat.py tests/test_audit_render.py -q`
Expected: PASS. If a pre-existing assertion in `tests/test_chat.py` fails because the subtitle wording changed, update that assertion — the wording change is intentional and specified.

- [ ] **Step 8: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 9: Verify against the real 60-repo run (the success criteria)**

This is the check the whole plan exists to satisfy. It reads a real file outside the repo; it is a **manual verification step, not a test**.

```bash
.venv/bin/python -c "
import json
from agent.lib.actions import build_actions
from agent.lib.audit_render import render_audit_md

audit = json.load(open('/home/tops/drift-report-2026-07-15/audit.json'))
audit['actions'] = build_actions([f for f in audit['findings'] if not f.get('suppressed')])
actions = audit['actions']
urgent = [a for a in actions if a['status'] == 'DEPRECATED']
print('findings:', len(audit['findings']), '-> actions:', len(actions), '| urgent:', len(urgent))
print('top action:', urgent[0]['repo'], urgent[0]['ref'],
      urgent[0]['current_version'], '->', urgent[0]['fix_version'],
      '| fixes', urgent[0]['finding_count'])
md = render_audit_md(audit)
open('/tmp/AUDIT-new.md', 'w').write(md)
print('AUDIT.md lines:', len(md.splitlines()))
"
```

Expected:
- `findings: 320 -> actions: 90 | urgent: 50`
- `top action:` is `backup/Projects/heygen/backend/Wav2Lip python/torch 1.1.0 -> <a 2.x version> | fixes 30`
- Read `/tmp/AUDIT-new.md` and confirm "Do this first" opens with the torch action.

If the top action is anything else, the ranking is wrong — stop and fix before committing.

- [ ] **Step 10: Commit**

```bash
git add agent/lib/audit_render.py agent/lib/chat.py tests/test_audit_render.py tests/test_chat.py
git commit -m "feat(report): rank the report by urgency, render actions not findings

Kills the original bug: audit_render.py did urgent[:15] with NO sort, so an
alphabetically-early repo buried 10 CRITICALs (incl. 4x torch RCE) under
'...and 104 more'. Now: 'Do this first' = top 10 truly ranked, truncation is
announced, the fix queue drops nothing, and the card says '50 fixes needed'
instead of '119 action-required'."
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `ranking.py` with `severity_rank`/`semver_key` | 1 |
| EOL/SUNSET overdue-ness rule | 1 |
| `facade.py:81-82` swap, behaviour-preserving | 1 |
| EOL structured `fixed` | 2 |
| Action dict shape (17 keys) | 3 |
| Rollup rules, `fix_version` = semver max | 3 |
| Ranking order + stable tie-break | 3 |
| Command mapping, first-`/` split, None-safety | 3 |
| `audit.json` gains `actions`, `findings` unchanged | 3 (Step 5) |
| New `AUDIT.md` layout | 4 |
| "…10 shown of 50" no silent truncation | 4 |
| Transitive coverage note | 4 |
| Chat card reports actions | 4 (Step 5) |
| Success criteria check | 4 (Step 9) |

No gaps.

**Placeholder scan:** none — every code step carries complete code, every test step carries the actual test body, every run step carries the exact command and expected output.

**Type consistency:** `severity_rank(severity, status=None) -> int` and `semver_key(s) -> list[int]` are defined in Task 1 and used with those exact signatures in Tasks 3 and 4. `build_actions(findings) -> list[dict]` is defined in Task 3 and consumed in Task 4 with the key names listed in its Interfaces block (`repo, ref, eco, pkg, kind, current_version, fix_version, command, recommendation, worst, status, finding_count, critical_count, first_seen, files, fixes, sources`) — cross-checked against every use in `audit_render.py` and `chat.py`.

**Known deviation from the spec, deliberate:** the spec's example header reads `across 35 of 60 repos`. `counts` carries only `reposAffected`, so Task 4 reads `coverage.repos.scanned` when present and degrades to `across 35 repos` when absent, rather than inventing a number.
