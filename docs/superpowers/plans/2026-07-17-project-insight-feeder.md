# Project Insight — Branch 1: The Deterministic Feeder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect the `getHost() . $path` URL-assembly idiom (closing the `amazonspapi` 262-endpoint miss) and add a general per-repo coverage "conscience" (residue: unattributed path-literals + PHP egress sinks → a coverage grade), so no repo looks clean when the scanner is blind.

**Architecture:** Three new opengrep rule kinds (`path-literal`, `sink`, `path-assembly`) feed a refactored endpoint builder (`scan_endpoints`) that attributes host-less path literals to a repo's *single* classified vendor (strict guard → no false endpoints) and reports everything it couldn't attribute as residue. `_rollup_coverage` turns residue into a per-repo grade, superseding the Spec B SDK-package undercount as the headline honesty signal. Deterministic, hermetic, zero-LLM-token. No AI in this branch.

**Tech Stack:** Python 3.12 (.venv, uv-managed), Opengrep/semgrep rule packs (PHP + string-literal regex rules), pyyaml. Existing modules: `agent/lib/vendor_rules.py`, `agent/lib/endpoints.py`, `agent/lib/classify_url.py`, `agent/lib/repo_scan.py`, `agent/inventory_scan.py`, `agent/lib/inventory_render.py`, `agent/lib/dashboard_render.py`.

## Global Constraints

- Python 3.12 in `.venv`. Run tests with `.venv/bin/python -m pytest -q` from the repo root. NO pip — stdlib + existing deps (pyyaml) only. NO new dependency.
- DETERMINISTIC, ZERO-LLM-TOKEN. Same inputs → byte-identical `inventory.json` + `dashboard.html` + `INVENTORY.md`. NO network in any unit test. NO AI anywhere in this branch.
- HERMETIC: never execute scanned code. Detection is opengrep matching + Python string/line analysis only. No dataflow engine, no multi-hop/cross-file resolution — the concat rule is single-hop, file-local.
- NO FALSE ENDPOINTS. A host-less path literal is attributed ONLY when the repo has **exactly one distinct classified vendor** (one `techKey` across all classified endpoints) AND the literal's file also contains a `path-assembly` match. Otherwise it stays residue — never a guessed attribution.
- ADDITIVE: `coverage.residue` and the path-attribution are new; existing coverage keys (`privateSources`, `sdkMediated`, `endpoints`, `packages`, `repos`) unchanged in shape; existing artifacts (SARIF/BOM/AUDIT.md/audit.json) untouched; `audit.py` NOT touched. `build_endpoints(...)` keeps its exact current signature and return type (a `list` of endpoint dicts) for backward compatibility.
- Residue trust: the conscience must not cry wolf. Version-bearing path-literals only (`/vN/` or `/YYYY-MM-DD/`). PHP egress sinks scoped to HTTP-unambiguous calls only (`curl_exec`, `curl_setopt(...CURLOPT_URL...)`, `new GuzzleHttp\Client`) — `file_get_contents`/`fopen` are DEFERRED (too noisy without argument analysis; noted, not built).
- The undercount condition from Spec B (`sdkMediated`) is retained as DATA but is no longer the headline; the residue grade is. Do not delete `sdkMediated`.
- TDD, frequent commits, DRY, YAGNI.

## File Structure

- `agent/lib/vendor_rules.py` — MODIFY: add `_path_literal_rule`, `_sink_rule`, `_path_assembly_rule`; wire into `build_ruleset`. (New rule kinds: `path-literal`, `sink`, `path-assembly`.)
- `agent/lib/classify_url.py` — MODIFY: add `path_literal_of(line) -> str` (extract a version-bearing `/…` string literal from a source line). Reuse existing `version_of`.
- `agent/lib/endpoints.py` — MODIFY: add `scan_endpoints(...) -> {"endpoints": [...], "residue": {...}}` (refactor of the current `build_endpoints` body + path attribution + residue); keep `build_endpoints(...)` as a thin wrapper returning `["endpoints"]`.
- `agent/lib/repo_scan.py` — MODIFY: call `scan_endpoints`, store `record["residue"]`.
- `agent/inventory_scan.py` — MODIFY: in `_rollup_coverage`, build `coverage["residue"]` (with per-repo grade) from `record["residue"]`.
- `agent/lib/inventory_render.py` — MODIFY: per-repo section shows the coverage grade + residue line (replacing the Spec B SDK-only ⚠ line).
- `agent/lib/dashboard_render.py` — MODIFY: projection carries the residue/grade; Coverage section leads with the grade + residue samples.
- `tests/fixtures/insight/` — CREATE: two synthetic PHP repos (Component 3).
- Tests: `tests/test_vendor_rules.py`, `tests/test_classify_url.py`, `tests/test_endpoints.py`, `tests/test_repo_scan.py`, `tests/test_inventory_scan.py`, `tests/test_inventory_render.py`, `tests/test_dashboard_render.py`, `tests/test_insight_fixture.py` (new).

---

### Task 1: Rule pack — `path-literal`, `sink`, `path-assembly`

**Files:**
- Modify: `agent/lib/vendor_rules.py`
- Test: `tests/test_vendor_rules.py`

**Interfaces:**
- Consumes: existing `build_ruleset(vendors, languages) -> {"rules": [...]}`, `DEFAULT_LANGUAGES`.
- Produces: three new rule dicts in the ruleset, with `metadata.kind` ∈ {`path-literal`, `sink`, `path-assembly`}. `path-literal` is a string-literal `=~` rule over `DEFAULT_LANGUAGES`; `sink` and `path-assembly` are PHP-only semgrep patterns.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_vendor_rules.py`:

```python
from agent.lib.vendor_rules import build_ruleset


def _by_kind(ruleset):
    return {r["metadata"]["kind"]: r for r in ruleset["rules"] if "kind" in r.get("metadata", {})}


def test_ruleset_has_path_literal_sink_and_assembly_rules():
    rs = build_ruleset(vendors=[])
    kinds = _by_kind(rs)
    # path-literal: string-literal regex over all languages, matches a version segment
    assert "path-literal" in kinds
    pl = kinds["path-literal"]
    assert pl["languages"] == build_ruleset(vendors=[])["rules"][0]["languages"]  # same DEFAULT_LANGUAGES
    assert "v[0-9]" in pl["pattern"] and "[0-9]{4}-[0-9]{2}-[0-9]{2}" in pl["pattern"]
    # sink: PHP-only, curl_exec + CURLOPT_URL + Guzzle client
    assert "sink" in kinds
    sk = kinds["sink"]
    assert sk["languages"] == ["php"]
    pats = " ".join(p.get("pattern", "") for p in sk["pattern-either"])
    assert "curl_exec" in pats and "CURLOPT_URL" in pats and "GuzzleHttp\\Client" in pats
    # path-assembly: PHP-only, getHost() . $path
    assert "path-assembly" in kinds
    pa = kinds["path-assembly"]
    assert pa["languages"] == ["php"]
    assert "getHost()" in pa["pattern"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vendor_rules.py::test_ruleset_has_path_literal_sink_and_assembly_rules -v`
Expected: FAIL — `KeyError: 'path-literal'` (rules not added yet).

- [ ] **Step 3: Write minimal implementation**

In `agent/lib/vendor_rules.py`, add the three rule builders after `_vendor_rule`:

```python
def _path_literal_rule(languages: list) -> dict:
    # Version-bearing resource-path literals ("/orders/2026-01-01/orders", "/catalog/v0/items").
    # String-literal (comment-safe) regex, same as the url-literal rule. Classified in Python.
    return {"id": "path-literal", "languages": list(languages), "message": "resource-path literal",
            "severity": "INFO", "metadata": {"kind": "path-literal"},
            "pattern": r'"=~/\/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})\//"'}


def _sink_rule() -> dict:
    # PHP HTTP egress sinks — unambiguous only (curl_exec, CURLOPT_URL, Guzzle client).
    # file_get_contents/fopen deferred (noisy without argument-shape analysis).
    return {"id": "php-http-sink", "languages": ["php"], "message": "HTTP egress sink",
            "severity": "INFO", "metadata": {"kind": "sink"},
            "pattern-either": [
                {"pattern": "curl_exec(...)"},
                {"pattern": "curl_setopt($CH, CURLOPT_URL, $U)"},
                {"pattern": r"new \GuzzleHttp\Client(...)"},
            ]}


def _path_assembly_rule() -> dict:
    # The concat idiom: a config host getter concatenated with a path variable/literal.
    return {"id": "path-assembly", "languages": ["php"], "message": "URL assembled from getHost() + path",
            "severity": "INFO", "metadata": {"kind": "path-assembly"},
            "pattern": "$URL = $OBJ->getHost() . $PATH"}
```

Then extend `build_ruleset`:

```python
def build_ruleset(vendors: list | None = None, languages: list = DEFAULT_LANGUAGES) -> dict:
    rules = [_url_rule(languages)]
    rules += [_vendor_rule(v, languages) for v in (vendors or [])]
    rules += [_path_literal_rule(languages), _sink_rule(), _path_assembly_rule()]
    return {"rules": rules}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_vendor_rules.py -v`
Expected: PASS (the new test + any existing tests in the file).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/vendor_rules.py tests/test_vendor_rules.py
git commit -m "feat(insight): opengrep rules for path-literals, PHP sinks, concat assembly"
```

---

### Task 2: `path_literal_of` — extract a version-bearing path literal from a line

**Files:**
- Modify: `agent/lib/classify_url.py`
- Test: `tests/test_classify_url.py`

**Interfaces:**
- Consumes: existing `version_of(url, vendor) -> str | None` (already extracts `2026-01-01` / `v0` from a bare path via `DEFAULT_VERSION_REGEX = '/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})'`).
- Produces: `path_literal_of(line: str) -> str` — the first quoted string on the line that starts with `/` and contains a version segment; `""` if none. Full URLs (`://`) are excluded (handled by the url-literal path).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_classify_url.py`:

```python
from agent.lib.classify_url import path_literal_of, version_of


def test_path_literal_of_extracts_versioned_path():
    assert path_literal_of("$resource_path = '/orders/2026-01-01/orders';") == "/orders/2026-01-01/orders"
    assert path_literal_of('$p = "/catalog/v0/items";') == "/catalog/v0/items"
    # no version segment -> not a candidate
    assert path_literal_of("$p = '/local/file/path';") == ""
    # a full URL is not a path literal (handled elsewhere)
    assert path_literal_of("$u = 'https://api.x.com/v1/foo';") == ""
    # version extraction on a bare path reuses version_of
    assert version_of("/orders/2026-01-01/orders", None) == "2026-01-01"
    assert version_of("/catalog/v0/items", None) == "v0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_classify_url.py::test_path_literal_of_extracts_versioned_path -v`
Expected: FAIL — `ImportError: cannot import name 'path_literal_of'`.

- [ ] **Step 3: Write minimal implementation**

In `agent/lib/classify_url.py`, add near `segment_at` (reuse the module's `re` import and `DEFAULT_VERSION_REGEX`):

```python
_VERSION_SEG = re.compile(r"/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})(/|$)")


def path_literal_of(line: str) -> str:
    """The first quoted string on `line` that is a version-bearing resource path
    ('/orders/2026-01-01/orders'). Excludes full URLs (those go through the url path)."""
    for m in re.finditer(r"""['"](/[^'"]*)['"]""", line):
        s = m.group(1)
        if "://" in s:
            continue
        if _VERSION_SEG.search(s):
            return s
    return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_classify_url.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/classify_url.py tests/test_classify_url.py
git commit -m "feat(insight): path_literal_of — extract versioned path literals from a line"
```

---

### Task 3: `scan_endpoints` — concat attribution + residue

**Files:**
- Modify: `agent/lib/endpoints.py`
- Modify: `agent/lib/repo_scan.py:22`
- Test: `tests/test_endpoints.py`, `tests/test_repo_scan.py`

**Interfaces:**
- Consumes: existing `build_endpoints(matches, repo_root, vendors, *, max_files=20) -> list` internals (the `add`/`groups` machinery), `classify_url.path_literal_of`, `classify_url.version_of`, `_relpath`, `_read_line`. Vendor objects have `.vendor`, `.techKey`, `.domains` (list), `.version_regex`.
- Produces:
  - `scan_endpoints(matches, repo_root, vendors, *, max_files=20) -> {"endpoints": list, "residue": {"pathLiterals": [{"sample": str, "loc": str}], "sinks": [{"kind": str, "loc": str}]}}`.
  - `build_endpoints(...)` UNCHANGED signature/return, now `return scan_endpoints(...)["endpoints"]`.
  - `repo_scan.scan_repo` stores `record["residue"] = scan_endpoints(...)["residue"]` and keeps `record["endpoints"]` as today.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_endpoints.py` (mirror the existing test style — hand-built `matches` dicts with `kind`/`path`/`line`; use the repo's `Vendor` type). Create a small tmp file so `_read_line` can read the path literal:

```python
from pathlib import Path
from agent.lib.vendors import Vendor
from agent.lib.endpoints import scan_endpoints, build_endpoints

_SP = Vendor("Amazon SP-API", "api:amazon-sp-api", ("sellingpartnerapi",), r'/(v[0-9]+|[0-9]{4}-[0-9]{2}-[0-9]{2})')
_STRIPE = Vendor("Stripe", "api:stripe", ("stripe.com",), r'/(v[0-9]+)')


def _write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_path_literal_attributed_when_single_vendor_and_assembly_present(tmp_path):
    _write(tmp_path, "Configuration.php", "$host = 'sellingpartnerapi-na.amazon.com';\n")
    _write(tmp_path, "OrdersApi.php",
           "$resource_path = '/orders/2026-01-01/orders';\n"
           "$url = $this->config->getHost() . $resource_path;\n")
    matches = [
        {"kind": "url", "path": "Configuration.php", "line": 1},              # classifies SP-API host
        {"kind": "path-literal", "path": "OrdersApi.php", "line": 1},
        {"kind": "path-assembly", "path": "OrdersApi.php", "line": 2},
    ]
    out = scan_endpoints(matches, str(tmp_path), [_SP, _STRIPE])
    eps = out["endpoints"]
    # the SP-API host endpoint + the attributed path endpoint
    orders = [e for e in eps if e.get("version") == "2026-01-01"]
    assert orders and orders[0]["techKey"] == "api:amazon-sp-api"
    assert "OrdersApi.php:1" in orders[0]["files"]
    assert out["residue"]["pathLiterals"] == []                              # it was attributed, not residue


def test_path_literal_is_residue_when_two_vendors(tmp_path):
    _write(tmp_path, "cfg.php", "$a = 'sellingpartnerapi'; $b = 'stripe.com';\n")
    _write(tmp_path, "Api.php",
           "$resource_path = '/orders/2026-01-01/orders';\n"
           "$url = $this->config->getHost() . $resource_path;\n")
    matches = [
        {"kind": "url", "path": "cfg.php", "line": 1},                        # line has BOTH hosts -> 2 vendors
        {"kind": "path-literal", "path": "Api.php", "line": 1},
        {"kind": "path-assembly", "path": "Api.php", "line": 2},
    ]
    out = scan_endpoints(matches, str(tmp_path), [_SP, _STRIPE])
    assert not any(e.get("version") == "2026-01-01" for e in out["endpoints"])   # NOT attributed (ambiguous)
    assert out["residue"]["pathLiterals"] == [{"sample": "/orders/2026-01-01/orders", "loc": "Api.php:1"}]


def test_path_literal_is_residue_when_no_assembly_in_file(tmp_path):
    _write(tmp_path, "Configuration.php", "$host = 'sellingpartnerapi';\n")
    _write(tmp_path, "Const.php", "$VERSIONED = '/orders/2026-01-01/orders';\n")   # a literal, no assembly here
    matches = [
        {"kind": "url", "path": "Configuration.php", "line": 1},
        {"kind": "path-literal", "path": "Const.php", "line": 1},
        # no path-assembly match in Const.php
    ]
    out = scan_endpoints(matches, str(tmp_path), [_SP])
    assert not any(e.get("version") == "2026-01-01" for e in out["endpoints"])
    assert out["residue"]["pathLiterals"] == [{"sample": "/orders/2026-01-01/orders", "loc": "Const.php:1"}]


def test_sinks_are_reported_as_residue(tmp_path):
    matches = [{"kind": "sink", "path": "Client.php", "line": 7}]
    out = scan_endpoints(matches, str(tmp_path), [_SP])
    assert out["residue"]["sinks"] == [{"kind": "egress", "loc": "Client.php:7"}]


def test_build_endpoints_still_returns_a_list(tmp_path):
    _write(tmp_path, "x.php", "$u = 'https://api.stripe.com/v1/charges';\n")
    matches = [{"kind": "url", "path": "x.php", "line": 1}]
    eps = build_endpoints(matches, str(tmp_path), [_STRIPE])
    assert isinstance(eps, list) and eps[0]["techKey"] == "api:stripe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_endpoints.py -k "scan_endpoints or path_literal or sinks or build_endpoints_still" -v`
Expected: FAIL — `ImportError: cannot import name 'scan_endpoints'`.

- [ ] **Step 3: Write minimal implementation**

In `agent/lib/endpoints.py`, rename the current `build_endpoints` body into `scan_endpoints`, add the path-attribution + residue logic, and make `build_endpoints` a wrapper. Replace the whole `build_endpoints` function with:

```python
def scan_endpoints(matches: list, repo_root: str, vendors: list, *, max_files: int = 20) -> dict:
    by_tk = {v.techKey: v for v in vendors}
    line_cache: dict = {}
    groups: dict = {}
    seen_known: set = set()

    def add(vendor, techKey, host, version, example, rel, lineno):
        loc = f"{rel}:{lineno}"
        if techKey and (techKey, loc) in seen_known:
            return
        if techKey:
            seen_known.add((techKey, loc))
        key = (techKey or f"unknown:{host}", host, version)
        rec = groups.get(key)
        if rec is None:
            rec = {"vendor": vendor, "domain": host, "version": version, "techKey": techKey,
                   "example": (example or host).rstrip("\"';,)"), "file_count": 0, "files": [],
                   "classified": bool(techKey)}
            groups[key] = rec
        rec["file_count"] += 1
        if len(rec["files"]) < max_files and loc not in rec["files"]:
            rec["files"].append(loc)

    for m in sorted(matches, key=lambda x: 0 if x.get("kind") == "url" else 1):
        rel = _relpath(m.get("path", ""), repo_root)
        lineno = int(m.get("line", 0) or 0)
        line = _read_line(repo_root, rel, lineno, line_cache)
        kind = m.get("kind")
        if kind == "url":
            for url in classify_url.extract_urls(line):
                host = classify_url.host_of(url)
                v = classify_url.classify_host(host, vendors)
                if v is None and classify_url.is_ignored(host):
                    continue
                add(v.vendor if v else UNKNOWN, v.techKey if v else "", host,
                    classify_url.version_of(url, v), url, rel, lineno)
        elif kind == "endpoint":
            v = by_tk.get(m.get("techKey", ""))
            d = classify_url.domain_in_line(line, v.domains) if v else ""
            if v and d:
                seg = classify_url.segment_at(line, d)
                add(v.vendor, v.techKey, d, classify_url.version_of(seg, v), seg, rel, lineno)

    # --- concat idiom: attribute host-less path literals to the repo's SINGLE classified vendor ---
    classified_tks = {r["techKey"] for r in groups.values() if r["techKey"]}
    assembly_files = {_relpath(m.get("path", ""), repo_root)
                      for m in matches if m.get("kind") == "path-assembly"}
    attributed_locs: set = set()
    if len(classified_tks) == 1 and assembly_files:
        v = by_tk.get(next(iter(classified_tks)))
        if v is not None:
            for m in matches:
                if m.get("kind") != "path-literal":
                    continue
                rel = _relpath(m.get("path", ""), repo_root)
                if rel not in assembly_files:
                    continue
                lineno = int(m.get("line", 0) or 0)
                path = classify_url.path_literal_of(_read_line(repo_root, rel, lineno, line_cache))
                if not path:
                    continue
                add(v.vendor, v.techKey, v.domains[0], classify_url.version_of(path, v), path, rel, lineno)
                attributed_locs.add(f"{rel}:{lineno}")

    # --- residue: what we could NOT attribute (the conscience) ---
    residue_paths, residue_sinks = [], []
    for m in matches:
        rel = _relpath(m.get("path", ""), repo_root)
        lineno = int(m.get("line", 0) or 0)
        loc = f"{rel}:{lineno}"
        kind = m.get("kind")
        if kind == "path-literal" and loc not in attributed_locs:
            path = classify_url.path_literal_of(_read_line(repo_root, rel, lineno, line_cache))
            if path:
                residue_paths.append({"sample": path, "loc": loc})
        elif kind == "sink":
            residue_sinks.append({"kind": "egress", "loc": loc})

    return {"endpoints": list(groups.values()),
            "residue": {"pathLiterals": residue_paths, "sinks": residue_sinks}}


def build_endpoints(matches: list, repo_root: str, vendors: list, *, max_files: int = 20) -> list:
    return scan_endpoints(matches, repo_root, vendors, max_files=max_files)["endpoints"]
```

Then wire `repo_scan.py`. Replace line 22 (`endpoints = [e for e in build_endpoints(...) if e.get("domain")]`) with:

```python
    scanned_eps = scan_endpoints(scan["matches"], repo_abs, vendors)
    endpoints = [e for e in scanned_eps["endpoints"] if e.get("domain")]
```

and after the `record["privateSources"] = ...` line add:

```python
    record["residue"] = scanned_eps["residue"]
```

Update the import at the top of `repo_scan.py`:

```python
from agent.lib.endpoints import build_endpoints, scan_endpoints
```

(`build_endpoints` may still be imported elsewhere; leave it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_endpoints.py tests/test_repo_scan.py -v`
Expected: PASS (new tests + existing `test_repo_scan.py` — `scan_repo` now also sets `record["residue"]`; the existing repo-scan assertions are unaffected because `build_endpoints`/endpoint output is unchanged).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/endpoints.py agent/lib/repo_scan.py tests/test_endpoints.py tests/test_repo_scan.py
git commit -m "feat(insight): scan_endpoints — concat-idiom attribution + residue detection"
```

---

### Task 4: Coverage rollup + per-repo grade

**Files:**
- Modify: `agent/inventory_scan.py` (`_rollup_coverage`)
- Test: `tests/test_inventory_scan.py`

**Interfaces:**
- Consumes: `record["residue"] = {"pathLiterals": [...], "sinks": [...]}` (Task 3); each repo record's `endpoints` (classified = `vendor` set and `!= "Unknown"`).
- Produces: `coverage["residue"] = {"pathLiterals": [...], "sinks": [...], "byRepo": [{"repo", "attributed", "unattributedPaths", "unresolvedSinks", "grade"}]}` where `grade` ∈ {`HIGH`,`PARTIAL`,`LOW`}. A module-level `_coverage_grade(attributed, unattributed_paths, sinks) -> str`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_inventory_scan.py`:

```python
from agent.inventory_scan import _rollup_coverage, _coverage_grade


def test_coverage_grade_thresholds():
    assert _coverage_grade(attributed=0, unattributed_paths=262, sinks=0) == "LOW"
    assert _coverage_grade(attributed=5, unattributed_paths=3, sinks=0) == "PARTIAL"
    assert _coverage_grade(attributed=0, unattributed_paths=0, sinks=2) == "PARTIAL"   # sinks only
    assert _coverage_grade(attributed=5, unattributed_paths=0, sinks=0) == "HIGH"
    assert _coverage_grade(attributed=0, unattributed_paths=0, sinks=0) == "HIGH"      # nothing to miss


def test_rollup_builds_residue_and_grade():
    repos = [
        {"path": "amazonspapi",
         "endpoints": [{"vendor": "Amazon SP-API"}],
         "residue": {"pathLiterals": [{"sample": "/orders/2026-01-01/orders", "loc": "OrdersApi.php:44"}],
                     "sinks": [{"kind": "egress", "loc": "Client.php:7"}]}},
        {"path": "clean", "endpoints": [{"vendor": "Stripe"}],
         "residue": {"pathLiterals": [], "sinks": []}},
    ]
    coverage = {"reposScanned": 2, "reposErrored": [], "manifestsUnparsed": []}
    _rollup_coverage(coverage, repos, discovered_count=2)
    res = coverage["residue"]
    assert len(res["pathLiterals"]) == 1 and len(res["sinks"]) == 1
    by = {r["repo"]: r for r in res["byRepo"]}
    assert by["amazonspapi"]["grade"] == "PARTIAL"      # has 1 attributed endpoint + residue
    assert by["amazonspapi"]["unattributedPaths"] == 1 and by["amazonspapi"]["unresolvedSinks"] == 1
    assert by["clean"]["grade"] == "HIGH"
```

Note: the first repo has 1 attributed endpoint AND residue → PARTIAL (not LOW; LOW requires zero attributed). This matches `_coverage_grade`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_inventory_scan.py -k "coverage_grade or residue_and_grade" -v`
Expected: FAIL — `ImportError: cannot import name '_coverage_grade'`.

- [ ] **Step 3: Write minimal implementation**

In `agent/inventory_scan.py`, add the grade helper at module level (near the top, after imports):

```python
def _coverage_grade(attributed: int, unattributed_paths: int, sinks: int) -> str:
    if unattributed_paths and attributed == 0:
        return "LOW"
    if unattributed_paths or (attributed == 0 and sinks):
        return "PARTIAL"
    return "HIGH"
```

In `_rollup_coverage`, after the existing `coverage["sdkMediated"] = [...]` block, add:

```python
    res_paths, res_sinks, by_repo = [], [], []
    for r in repos:
        rr = r.get("residue") or {"pathLiterals": [], "sinks": []}
        plist = [{"repo": r.get("path"), **p} for p in rr.get("pathLiterals", [])]
        slist = [{"repo": r.get("path"), **s} for s in rr.get("sinks", [])]
        res_paths += plist
        res_sinks += slist
        attributed = sum(1 for e in r.get("endpoints", [])
                         if e.get("vendor") and e["vendor"] != "Unknown")
        by_repo.append({"repo": r.get("path"), "attributed": attributed,
                        "unattributedPaths": len(plist), "unresolvedSinks": len(slist),
                        "grade": _coverage_grade(attributed, len(plist), len(slist))})
    coverage["residue"] = {"pathLiterals": res_paths, "sinks": res_sinks, "byRepo": by_repo}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_inventory_scan.py -v`
Expected: PASS (new tests + existing `sdkMediated`/`privateSources` tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add agent/inventory_scan.py tests/test_inventory_scan.py
git commit -m "feat(insight): coverage.residue + per-repo coverage grade (the conscience)"
```

---

### Task 5: Render the grade — INVENTORY.md + dashboard

**Files:**
- Modify: `agent/lib/inventory_render.py` (`_per_repo_section`)
- Modify: `agent/lib/dashboard_render.py` (`_build_projection` + Coverage section JS)
- Test: `tests/test_inventory_render.py`, `tests/test_dashboard_render.py`

**Interfaces:**
- Consumes: `coverage["residue"]["byRepo"]` (per-repo grade) from Task 4; the existing `_per_repo_section` and dashboard `_build_projection`/Coverage-section machinery from Spec B.
- Produces: per-repo INVENTORY.md grade line; dashboard projection `coverageGrades` (list of `byRepo`) + `residueSamples`; the Coverage section renders the grades. The Spec B SDK-only `⚠ … SDK package(s)` per-repo line is REPLACED by the grade line.

- [ ] **Step 1: Write the failing test (INVENTORY.md)**

In `tests/test_inventory_render.py`, adapt the Spec B per-repo test. Add:

```python
def test_per_repo_shows_coverage_grade_line():
    # a repo carrying a coverage grade + residue counts renders the grade, not the old SDK line
    repo = {"path": "amazonspapi", "sdks": ["dts/foo"], "endpoints": [],
            "coverageGrade": {"grade": "LOW", "unattributedPaths": 262, "unresolvedSinks": 3}}
    md = _render_one(repo)          # helper used by existing tests; see file
    assert "LOW" in md and "262" in md
    assert "may not be listed as endpoints" not in md   # old SDK-only ⚠ line is gone
```

NOTE for the implementer: read `tests/test_inventory_render.py` and `agent/lib/inventory_render.py` first. `_per_repo_section` currently receives the repo dict. The per-repo grade must be threaded onto each repo dict before rendering — do this in `_per_repo_section` by reading a `coverageGrade` key the caller attaches, OR (simpler, self-contained) have `inventory_render` accept the `coverage["residue"]["byRepo"]` map and look up `repo["path"]`. Choose the approach that matches how `_per_repo_section` is already called; keep it deterministic. If `_render_one` does not exist, replace the test's call with the actual render entry used by the neighbouring tests in that file and assert on the returned markdown string.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_inventory_render.py -k coverage_grade -v`
Expected: FAIL (grade line not rendered; old SDK line may still be present).

- [ ] **Step 3: Write minimal implementation (INVENTORY.md)**

In `agent/lib/inventory_render.py` `_per_repo_section`: REMOVE the Spec B SDK-undercount line (`⚠ **{len(sdks)} SDK package(s)** — SDK-mediated calls …`) and, when the repo has a coverage grade, emit:

```python
    g = repo.get("coverageGrade")
    if g and g.get("grade") and g["grade"] != "HIGH":
        out.append(f"- ⚠ **Coverage: {g['grade']}** — {g.get('unattributedPaths', 0)} endpoint-shaped "
                   f"literal(s) + {g.get('unresolvedSinks', 0)} egress sink(s) the scan couldn't attribute.")
```

Thread the grade in: wherever `_per_repo_section` is called with each repo, attach `repo["coverageGrade"]` from `coverage["residue"]["byRepo"]` keyed by `repo["path"]` (build a `{byRepo.repo: byRepo}` dict once). Keep ordering deterministic (iterate repos in their existing order).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_inventory_render.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing test (dashboard)**

In `tests/test_dashboard_render.py` (adapt the Spec B Coverage-section test):

```python
def test_dashboard_coverage_section_shows_grades():
    inv = {"repos": [], "coverage": {"residue": {
        "pathLiterals": [{"repo": "amazonspapi", "sample": "/orders/2026-01-01/orders", "loc": "OrdersApi.php:44"}],
        "sinks": [], "byRepo": [{"repo": "amazonspapi", "attributed": 0, "unattributedPaths": 262,
                                 "unresolvedSinks": 3, "grade": "LOW"}]}}}
    audit = {"actions": [], "coverage": {"notes": []}}
    html = render_dashboard(inv, audit, "2026-07-17")
    assert 'id="coverage"' in html
    data = _blob(html)
    assert any(g["repo"] == "amazonspapi" and g["grade"] == "LOW" for g in data.get("coverageGrades", []))
    assert "amazonspapi" in html and "LOW" in html


def test_dashboard_coverage_grade_xss_escaped():
    inv = {"repos": [], "coverage": {"residue": {
        "pathLiterals": [{"repo": "r", "sample": "/x/v0/</script><b>pwn", "loc": "a.php:1"}],
        "sinks": [], "byRepo": [{"repo": "r</script>", "attributed": 0, "unattributedPaths": 1,
                                 "unresolvedSinks": 0, "grade": "LOW"}]}}}
    html = render_dashboard(inv, {"actions": [], "coverage": {}}, "2026-07-17")
    assert "<script><b>pwn" not in html and "r</script>" not in html.split('id="data"')[0]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -k "coverage_section_shows_grades or coverage_grade_xss" -v`
Expected: FAIL (`coverageGrades` not in projection).

- [ ] **Step 7: Write minimal implementation (dashboard)**

In `agent/lib/dashboard_render.py` `_build_projection`, after the existing coverage reads, add:

```python
    residue = (inventory.get("coverage") or {}).get("residue") or {}
```

and add to the returned projection dict:

```python
        "coverageGrades": residue.get("byRepo", []),
        "residueSamples": residue.get("pathLiterals", []),
```

In the Coverage-section JS (the `(function(){ var cov=... })();` block added in Spec B), render the grades before/with the existing notes. All scan-derived strings via `esc`; grade repos via `esc`. Example insertion inside that IIFE, after the notes loop:

```javascript
    var grades=(DATA.coverageGrades||[]).filter(function(g){return g.grade!=="HIGH";});
    if(grades.length){
      h+='<div class="note">Coverage — repos where calls may be unattributed:</div><ul>';
      grades.forEach(function(g){ h+='<li>'+esc(g.repo)+': <b>'+esc(g.grade)+'</b> ('
        +esc(g.unattributedPaths)+' path-literals, '+esc(g.unresolvedSinks)+' sinks)</li>'; });
      h+='</ul>';
    }
```

Keep the `cov.innerHTML = h ? ("<h2>Coverage</h2>"+h) : "";` guard from the Spec B polish so an all-HIGH fleet shows no empty heading.

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py tests/test_inventory_render.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add agent/lib/inventory_render.py agent/lib/dashboard_render.py tests/test_inventory_render.py tests/test_dashboard_render.py
git commit -m "feat(insight): render coverage grade in INVENTORY.md + dashboard Coverage section"
```

---

### Task 6: Synthetic 2-repo eval fixture (end-to-end)

**Files:**
- Create: `tests/fixtures/insight/repo_a/Configuration.php`, `tests/fixtures/insight/repo_a/OrdersApi.php`, `tests/fixtures/insight/repo_a/Client.php`, `tests/fixtures/insight/repo_a/Const.php`
- Create: `tests/fixtures/insight/repo_b/Configuration.php`, `tests/fixtures/insight/repo_b/ChargesApi.php`
- Create: `tests/test_insight_fixture.py`

**Interfaces:**
- Consumes: `agent.lib.vendor_rules.build_ruleset`, `agent.lib.opengrep` (the engine runner — read `agent/lib/opengrep.py` for its function name/signature), `agent.lib.endpoints.scan_endpoints`, `agent.lib.vendors` (load the catalog).
- Produces: a committed fixture proving attribution across two vendors + residue. This test runs the REAL engine over the fixture files (hermetic, no network).

- [ ] **Step 1: Create the fixture files**

`tests/fixtures/insight/repo_a/Configuration.php`:
```php
<?php
class Configuration {
    public function getHost() { return 'https://sellingpartnerapi-na.amazon.com'; }
}
```
`tests/fixtures/insight/repo_a/OrdersApi.php`:
```php
<?php
class OrdersApi {
    public function searchOrders() {
        $resource_path = '/orders/2026-01-01/orders';
        $url = $this->config->getHost() . $resource_path;
        return $url;
    }
}
```
`tests/fixtures/insight/repo_a/Client.php` (a dynamic curl → sink residue):
```php
<?php
function send($u) {
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $u);
    return curl_exec($ch);
}
```
`tests/fixtures/insight/repo_a/Const.php` (a versioned path literal with no assembly here → path residue):
```php
<?php
$LEGACY = '/feeds/2021-06-30/documents';
```
`tests/fixtures/insight/repo_b/Configuration.php`:
```php
<?php
class Configuration {
    public function getHost() { return 'https://api.stripe.com'; }
}
```
`tests/fixtures/insight/repo_b/ChargesApi.php`:
```php
<?php
class ChargesApi {
    public function create() {
        $resource_path = '/v1/charges';
        $url = $this->config->getHost() . $resource_path;
        return $url;
    }
}
```

NOTE: `repo_a` mixes a full-URL host literal in `Configuration.php` (classifies SP-API) with the path idiom — the classified vendor is SP-API only. `repo_b` classifies Stripe only. Neither repo has two vendors, so both attribute cleanly.

- [ ] **Step 2: Write the failing test**

`tests/test_insight_fixture.py` — read `agent/lib/opengrep.py` first to get the exact runner call; the sketch (adjust the engine-run line to the real API):

```python
import os
from pathlib import Path
from agent.lib.vendor_rules import write_ruleset
from agent.lib.endpoints import scan_endpoints
from agent.lib.vendors import load_vendors     # confirm the loader name in agent/lib/vendors.py
from agent.lib import opengrep

FIX = Path(__file__).parent / "fixtures" / "insight"


def _scan(repo_dir, vendors, tmp_path):
    rules = tmp_path / "rules.yaml"
    write_ruleset(vendors, str(rules))
    matches = opengrep.run(str(repo_dir), str(rules))   # <- replace with the real runner + its return shape
    return scan_endpoints(matches, str(repo_dir), vendors)


def test_repo_a_attributes_sp_api_and_reports_residue(tmp_path):
    vendors = load_vendors()
    out = _scan(FIX / "repo_a", vendors, tmp_path)
    vers = {e.get("version") for e in out["endpoints"] if e["techKey"] == "api:amazon-sp-api"}
    assert "2026-01-01" in vers                                   # concat path attributed to SP-API
    samples = {p["sample"] for p in out["residue"]["pathLiterals"]}
    assert "/feeds/2021-06-30/documents" in samples              # Const.php literal = residue (no assembly)
    assert any("Client.php" in s["loc"] for s in out["residue"]["sinks"])   # curl_exec = sink residue


def test_repo_b_attributes_stripe_proving_idiom_not_vendor(tmp_path):
    vendors = load_vendors()
    out = _scan(FIX / "repo_b", vendors, tmp_path)
    stripe = [e for e in out["endpoints"] if e["techKey"] == "api:stripe" and e.get("version") == "v1"]
    assert stripe                                                # SAME idiom, different vendor
    assert out["residue"]["pathLiterals"] == []                 # all attributed -> clean
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_insight_fixture.py -v`
Expected: FAIL first on the import/runner name (fix to the real `opengrep` API + `load_vendors` name), then it should drive out any wiring gaps.

- [ ] **Step 4: Make it pass**

Fix the engine-runner call and vendor-loader name to the real APIs (read `agent/lib/opengrep.py` and `agent/lib/vendors.py`). Ensure `stripe.com` and `sellingpartnerapi` are in the shipped `agent/vendors.yaml` (they are — Stripe + SP-API are catalogued). Do NOT change production code to fit the test unless a real gap is found; if a gap is found, it belongs in Task 3/4 and should be fixed there with its own test.

Run: `.venv/bin/python -m pytest tests/test_insight_fixture.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/insight tests/test_insight_fixture.py
git commit -m "test(insight): synthetic 2-repo fixture — concat attribution across vendors + residue"
```

---

### Task 7: Controller verification — real amazonspapi (262/262) + eval 5/5

**This is a controller-run verification checkpoint (live). No new production code unless it reveals a gap.**

- [ ] **Step 1: Full suite green**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (baseline was 339 passed, 1 skipped on master; this branch adds tests).

- [ ] **Step 2: Scan the real private repo**

The private clone is at `~/gitlab-fleet/chetan/amazonspapi` (already present). Run:
```bash
DRIFT_GITLAB_HOSTS=git.topsdemo.in .venv/bin/python -m agent.cli inventory-scan \
  --root ~/gitlab-fleet/chetan/amazonspapi \
  --state /home/tops/.drift/reports/amazonspapi-insight/state \
  --out-json /home/tops/.drift/reports/amazonspapi-insight/inventory.json \
  --out-md /home/tops/.drift/reports/amazonspapi-insight/INVENTORY.md \
  --now 2026-07-17
```
Confirm from `inventory.json`: the repo now carries the SP-API `/…/<version>/…` endpoints attributed via the concat idiom (expect on the order of the ~262 resource-path calls, deduped by (techKey, version) group with per-call `files`), and the coverage grade is no longer clean (HIGH). Record the attributed-endpoint count and the grade in the report. (Exact "262/262" is measured against the 262 `resource_path` literals; grouping by version means fewer endpoint *records*, each with many call-sites — verify call-site coverage, not record count.)

- [ ] **Step 3: Regression net**

Run: `DRIFT_GITLAB_HOSTS=git.topsdemo.in ./bin/drift-eval run ebay --now 2026-07-17 --no-clone`
Expected: `RECALL 5/5 … [PASS]`. The additive path/residue logic must not perturb eBay recall (eBay repos use SDK/URL literals, not the getHost concat idiom, so attribution should be unchanged; residue may add a grade but must not drop recall).

- [ ] **Step 4: Record the verification**

Write a short note (in the commit or `.superpowers/sdd/` report): attributed-endpoint/call-site count on amazonspapi, the new grade, and eval 5/5. If Step 2 reveals the concat rule under-attributes on the real repo (e.g. the assembly spans the base `SellingPartnerApiRequest` trait rather than each file), record the exact shape and treat it as a follow-up idiom — do NOT loosen the single-vendor guard to compensate.

- [ ] **Step 5: Commit (verification note only)**

```bash
git add -A && git commit -m "chore(insight): verify concat attribution on real amazonspapi + eval 5/5" --allow-empty
```

---

## Self-Review

**1. Spec coverage:**
- Residue detector (path-literals + PHP sinks) → Tasks 1 (rules), 3 (detection), 4 (rollup+grade). ✓
- Coverage grade supersedes SDK undercount headline → Task 4 (grade), Task 5 (render replaces the SDK ⚠ line; `sdkMediated` data retained). ✓
- Concat idiom rule + single-vendor attribution → Tasks 1 (rule), 2 (path/version helper), 3 (attribution). ✓
- Version from path → Task 2 (reuses `version_of`; verified it already works on bare paths). ✓
- Surfacing (dashboard + INVENTORY.md, grade-led, XSS) → Task 5. ✓
- Synthetic 2-repo fixture (two vendors + sink + bare-path residue) → Task 6. ✓
- amazonspapi 262 + eval 5/5 → Task 7. ✓
- Non-goals honored: no AI, no facts store, no extra idioms, PHP-only sinks, single-hop file-local. ✓

**2. Placeholder scan:** Task 5 and Task 6 contain explicit "read the file first / adjust to the real API" notes rather than fabricated signatures for `_per_repo_section`'s call site, the dashboard Coverage IIFE, the `opengrep` runner, and the vendor loader — because those exact call shapes must be read from the code, and inventing them would be the worse failure. All new production functions (`path_literal_of`, `scan_endpoints`, `_coverage_grade`, rule builders) have complete code. Acceptable.

**3. Type consistency:** `residue = {"pathLiterals": [{"sample","loc"}], "sinks": [{"kind","loc"}]}` is produced in Task 3, stored on the record in Task 3, consumed in Task 4; `coverage["residue"]` gains `byRepo: [{"repo","attributed","unattributedPaths","unresolvedSinks","grade"}]` in Task 4, consumed by Task 5 (`coverageGrades`, `coverageGrade`). `scan_endpoints` return shape is consistent across Tasks 3/6. `_coverage_grade(attributed, unattributed_paths, sinks)` signature consistent Task 4. `build_endpoints` signature unchanged. ✓

## Execution Handoff

Deviations from spec worth surfacing to the reviewer: (a) PHP sinks are scoped to `curl_exec`/`CURLOPT_URL`/Guzzle-client only (`file_get_contents`/`fopen` deferred for residue-trust) — a deliberate narrowing of the spec's sink list; (b) the coverage grade for `amazonspapi` is PARTIAL not LOW *once the concat rule attributes its endpoints* (LOW is the pre-fix / no-attribution state) — both are correct at their respective stages.
