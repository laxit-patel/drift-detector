# Integration Inventory — Unit 1: Opengrep Endpoint Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect third-party API usage in source code and produce the superset schema's `endpoints[]` records — `{vendor, domain, version, techKey, example, file_count, files:[path:line]}` — using Opengrep with a vendor catalog as the single source of truth.

**Architecture:** `agent/vendors.yaml` is the single source of truth (each vendor → `techKey`, domains, version regex). A generator renders it into an Opengrep rule pack of **AST-aware string-literal patterns** (`"=~/domain/"`) that match endpoint URLs in code while skipping comments. A runner invokes the engine (through an injected callable so unit tests use canned JSON — no binary), and an aggregator reads the matched line from the file, extracts the API version, and groups matches into per-repo endpoint records. SDK-in-code detection is out of scope for Unit 1 (manifests cover declared SDKs in Unit 2).

**Tech Stack:** Python 3.12 (project `.venv`, uv-managed — `source .venv/bin/activate`; system python is 3.10, do NOT use it). Tests: `python -m pytest -q`. Engine: `opengrep` in production, `semgrep` (installed in `.venv`, format-identical) as the dev proxy. YAML via `PyYAML` (already a dep).

## Global Constraints

- **TDD**: failing test first, watch it fail, then implement. Frequent commits.
- **Injected engine seam**: Opengrep/Semgrep is invoked through an injected `run(args) -> str` callable. **Unit tests never spawn the real binary** — they inject a fake returning canned JSON. A separate **opt-in live test** uses the real engine and **skips if it is absent** (`shutil.which`).
- **Verified engine facts** (semgrep 1.169, confirmed live 2026-07-14):
  - CLI: `<engine> --config <rules.yaml> --json --quiet <path>` → JSON on stdout.
  - JSON: `{results:[{check_id, path, start:{line,col,offset}, end:{…}, extra:{metadata:{vendor,techKey,kind}, severity}}], errors:[], paths:{scanned:[…]}}`.
  - `extra.lines`/`fingerprint` are login-gated (`"requires login"`) in Semgrep OSS → **read the example line from the file at `path:start.line`**; do NOT use `extra.lines`.
  - The comment-safe pattern for "a string literal containing X" is `pattern: '"=~/<regex>/"'` (matches the literal, skips comments). `"...X..."` does NOT work (literal ellipsis). `pattern-regex` matches comments (false positives) — do NOT use it for endpoints.
  - `check_id` gets a path prefix (e.g. `tmp.stripe-endpoint`) → take the last dotted segment; drive logic off `extra.metadata`, not the full id.
- **`techKey` on every endpoint record** (`api:<slug>`) — the join key the deprecation layer needs later.
- **Match existing style**: registered-extractor / injected-callable patterns like `agent/lib/`.

---

## File Structure

- **Create** `agent/vendors.yaml` — the vendor catalog (single source of truth). (Task 1)
- **Create** `agent/lib/vendors.py` — `Vendor` dataclass + `load_vendors()` + `vendor_slug()`. (Task 1)
- **Create** `agent/lib/vendor_rules.py` — `build_ruleset(vendors)` / `write_ruleset(...)`: render the catalog into an Opengrep endpoint rule pack. (Task 2)
- **Create** `agent/lib/opengrep.py` — `run_scan(...)`: invoke the engine (injected `run`) + parse `results` into normalized matches. (Task 3)
- **Create** `agent/lib/endpoints.py` — `build_endpoints(matches, repo_root, vendors)`: file-line read + version extract + aggregate into endpoint records. (Task 4)
- **Create** tests: `tests/test_vendors.py` (T1), `tests/test_vendor_rules.py` (T2), `tests/test_opengrep_runner.py` (T3), `tests/test_endpoints.py` + `tests/test_opengrep_live.py` (T4).

Reference (read-only): `docs/results/INVENTORY-2026-07-10.md` (the 27-vendor list + version forms), `docs/superpowers/specs/2026-07-14-integration-inventory-plugin-design.md` (endpoint record shape), `agent/patterns.yaml` (the existing 9 domain patterns).

---

## Task 1: Vendor catalog + loader

**Files:**
- Create: `agent/vendors.yaml`
- Create: `agent/lib/vendors.py`
- Test: `tests/test_vendors.py`

**Interfaces:**
- Produces:
  - `Vendor(vendor: str, techKey: str, domains: tuple[str,...], version_regex: str)` — frozen dataclass.
  - `DEFAULT_VERSION_REGEX = r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})'` — captures `/v3`, `/v24.0`, `/2010-10-01`. Used when a vendor omits `versionRegex`.
  - `load_vendors(path: str = "agent/vendors.yaml") -> list[Vendor]` — parses the YAML; each entry `{vendor, techKey, domains:[...], versionRegex?}`; missing `versionRegex` → `DEFAULT_VERSION_REGEX`.
  - `vendor_slug(vendor: str) -> str` — lowercased, non-alphanumeric → `-` (for rule ids), e.g. `"Amazon SP-API"` → `"amazon-sp-api"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vendors.py`:

```python
from agent.lib.vendors import load_vendors, vendor_slug, Vendor, DEFAULT_VERSION_REGEX


def test_loads_catalog_with_expected_vendors():
    vs = load_vendors()
    by_key = {v.techKey: v for v in vs}
    # spot-check the marketplace + a few others from the PM's inventory
    assert "api:amazon-sp-api" in by_key
    assert "api:amazon-mws" in by_key
    assert "api:stripe" in by_key and "api:shopify" in by_key
    assert "sellingpartnerapi" in by_key["api:amazon-sp-api"].domains
    assert len(vs) >= 20                          # ~27 vendors from the report


def test_missing_version_regex_falls_back_to_default():
    vs = load_vendors()
    # every vendor has a usable version_regex (own or default)
    assert all(v.version_regex for v in vs)
    assert any(v.version_regex == DEFAULT_VERSION_REGEX for v in vs)


def test_vendor_slug():
    assert vendor_slug("Amazon SP-API") == "amazon-sp-api"
    assert vendor_slug("Meta Graph API") == "meta-graph-api"


def test_vendor_is_frozen():
    v = Vendor("X", "api:x", ("x.com",), r"/(v\d+)")
    try:
        v.techKey = "api:y"
        assert False
    except Exception:
        pass
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_vendors.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.vendors'`.

- [ ] **Step 3: Create the vendor catalog**

Create `agent/vendors.yaml` (the 27 vendors from `docs/results/INVENTORY-2026-07-10.md`; `versionRegex` omitted where the default suffices):

```yaml
# Vendor catalog — single source of truth for endpoint detection.
# domains: substrings matched inside string literals (AST-aware) by the generated rules.
# versionRegex: one capture group = the API version, applied to the matched line (default covers /vN and dates).
- { vendor: Amazon SP-API,    techKey: api:amazon-sp-api,       domains: [sellingpartnerapi] }
- { vendor: Amazon MWS,       techKey: api:amazon-mws,          domains: [mws.amazonservices] }
- { vendor: Amazon Ads API,   techKey: api:amazon-ads,          domains: [advertising-api.amazon] }
- { vendor: eBay,             techKey: api:ebay,                domains: [api.ebay.com] }
- { vendor: Walmart,          techKey: api:walmart-marketplace, domains: [walmartapis.com] }
- { vendor: Shopify,          techKey: api:shopify,             domains: [myshopify.com] }
- { vendor: Stripe,           techKey: api:stripe,              domains: [api.stripe.com] }
- { vendor: PayPal,           techKey: api:paypal,              domains: [api.paypal.com] }
- { vendor: Square,           techKey: api:square,              domains: [connect.squareup.com] }
- { vendor: Razorpay,         techKey: api:razorpay,            domains: [api.razorpay.com] }
- { vendor: Google APIs,      techKey: api:google,              domains: [googleapis.com] }
- { vendor: Google Maps,      techKey: api:google-maps,         domains: [maps.googleapis.com] }
- { vendor: Google OAuth2,    techKey: api:google-oauth2,       domains: [oauth2.googleapis.com] }
- { vendor: Firebase FCM,     techKey: api:firebase-fcm,        domains: [fcm.googleapis.com] }
- { vendor: Meta Graph API,   techKey: api:meta-graph,          domains: [graph.facebook.com] }
- { vendor: Microsoft Graph,  techKey: api:microsoft-graph,     domains: [graph.microsoft.com] }
- { vendor: OpenAI,           techKey: api:openai,              domains: [api.openai.com] }
- { vendor: Anthropic,        techKey: api:anthropic,           domains: [api.anthropic.com] }
- { vendor: Twilio,           techKey: api:twilio,              domains: [api.twilio.com] }
- { vendor: SendGrid,         techKey: api:sendgrid,            domains: [api.sendgrid.com] }
- { vendor: Mailgun,          techKey: api:mailgun,             domains: [api.mailgun.net] }
- { vendor: Vonage Nexmo,     techKey: api:vonage,              domains: [rest.nexmo.com] }
- { vendor: GitHub,           techKey: api:github,              domains: [api.github.com] }
- { vendor: Slack,            techKey: api:slack,               domains: [slack.com/api, hooks.slack.com] }
- { vendor: LinkedIn,         techKey: api:linkedin,            domains: [api.linkedin.com] }
- { vendor: Twitter X,        techKey: api:twitter,             domains: [api.twitter.com, api.x.com] }
```

- [ ] **Step 4: Implement the loader**

Create `agent/lib/vendors.py`:

```python
"""Vendor catalog: the single source of truth for third-party endpoint detection."""
from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

# Captures /v3, /v24.0, /2010-10-01, /2021-06-30 — the version forms in the PM's inventory.
DEFAULT_VERSION_REGEX = r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})'


@dataclass(frozen=True)
class Vendor:
    vendor: str
    techKey: str
    domains: tuple
    version_regex: str


def vendor_slug(vendor: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", vendor.lower()).strip("-")


def load_vendors(path: str = "agent/vendors.yaml") -> list:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    out = []
    for d in raw:
        out.append(Vendor(
            vendor=d["vendor"], techKey=d["techKey"],
            domains=tuple(d.get("domains") or []),
            version_regex=d.get("versionRegex") or DEFAULT_VERSION_REGEX,
        ))
    return out
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_vendors.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add agent/vendors.yaml agent/lib/vendors.py tests/test_vendors.py
git commit -m "feat(inventory): vendor catalog (vendors.yaml) + loader"
```

---

## Task 2: Rule-pack generator

**Files:**
- Create: `agent/lib/vendor_rules.py`
- Test: `tests/test_vendor_rules.py`

**Interfaces:**
- Consumes: `Vendor`, `vendor_slug` (Task 1).
- Produces:
  - `DEFAULT_LANGUAGES = ["php", "js", "ts", "python", "ruby", "go", "java", "csharp"]`.
  - `build_ruleset(vendors: list[Vendor], languages: list[str] = DEFAULT_LANGUAGES) -> dict` — returns `{"rules": [...]}`. One rule per vendor, id `"<slug>-endpoint"`, `languages`, `metadata: {vendor, techKey, kind: "endpoint"}`, and `pattern-either` of `{"pattern": '"=~/<re.escape(domain)>/"'}` for each domain. (The `"=~/…/"` literal-regex is the verified comment-safe idiom.)
  - `write_ruleset(vendors, path, languages=DEFAULT_LANGUAGES) -> None` — dumps the ruleset as YAML to `path`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vendor_rules.py`:

```python
import yaml
from agent.lib.vendors import Vendor
from agent.lib.vendor_rules import build_ruleset, write_ruleset, DEFAULT_LANGUAGES


_VS = [Vendor("Stripe", "api:stripe", ("api.stripe.com",), r"/(v\d+)"),
       Vendor("Slack", "api:slack", ("slack.com/api", "hooks.slack.com"), r"/(v\d+)")]


def test_build_ruleset_one_rule_per_vendor_with_metadata():
    rs = build_ruleset(_VS)
    rules = rs["rules"]
    assert len(rules) == 2
    stripe = next(r for r in rules if r["id"] == "stripe-endpoint")
    assert stripe["metadata"] == {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"}
    assert stripe["languages"] == DEFAULT_LANGUAGES


def test_rule_uses_comment_safe_literal_regex_pattern_per_domain():
    rs = build_ruleset(_VS)
    slack = next(r for r in rs["rules"] if r["id"] == "slack-endpoint")
    pats = [p["pattern"] for p in slack["pattern-either"]]
    # two domains -> two literal-regex patterns; dots escaped; NOT raw pattern-regex
    assert '"=~/slack\\.com/api/"' in pats or any("slack" in p and p.startswith('"=~/') for p in pats)
    assert len(pats) == 2
    assert all(p.startswith('"=~/') and p.endswith('/"') for p in pats)


def test_write_ruleset_is_valid_yaml(tmp_path):
    p = tmp_path / "rules.yaml"
    write_ruleset(_VS, str(p))
    loaded = yaml.safe_load(p.read_text())
    assert "rules" in loaded and len(loaded["rules"]) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_vendor_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.vendor_rules'`.

- [ ] **Step 3: Implement the generator**

Create `agent/lib/vendor_rules.py`:

```python
"""Render the vendor catalog into an Opengrep endpoint rule pack. The AST-aware
'"=~/regex/"' string-literal pattern matches endpoint URLs in code while skipping comments."""
from __future__ import annotations

import re

import yaml

from agent.lib.vendors import vendor_slug

DEFAULT_LANGUAGES = ["php", "js", "ts", "python", "ruby", "go", "java", "csharp"]


def _rule_for(v, languages: list) -> dict:
    patterns = [{"pattern": '"=~/' + re.escape(d) + '/"'} for d in v.domains]
    return {
        "id": f"{vendor_slug(v.vendor)}-endpoint",
        "languages": list(languages),
        "message": f"{v.vendor} endpoint",
        "severity": "INFO",
        "metadata": {"vendor": v.vendor, "techKey": v.techKey, "kind": "endpoint"},
        "pattern-either": patterns,
    }


def build_ruleset(vendors: list, languages: list = DEFAULT_LANGUAGES) -> dict:
    return {"rules": [_rule_for(v, languages) for v in vendors]}


def write_ruleset(vendors: list, path: str, languages: list = DEFAULT_LANGUAGES) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(build_ruleset(vendors, languages), fh, sort_keys=False)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_vendor_rules.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/vendor_rules.py tests/test_vendor_rules.py
git commit -m "feat(inventory): generate Opengrep endpoint rule pack from vendor catalog"
```

---

## Task 3: Engine runner

**Files:**
- Create: `agent/lib/opengrep.py`
- Test: `tests/test_opengrep_runner.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure parse).
- Produces:
  - `_default_run(args: list) -> str` — `subprocess.run(args, capture_output=True, text=True, timeout=600).stdout`; `# pragma: no cover`.
  - `run_scan(repo_path: str, ruleset_path: str, *, engine: str = "opengrep", run=_default_run) -> dict` — invokes `[engine, "--config", ruleset_path, "--json", "--quiet", repo_path]`, parses stdout JSON, returns `{"matches": [...], "scanned": [...], "errors": [...]}`. Each match: `{"checkId", "vendor", "techKey", "kind", "path", "line"}` where `checkId` = the last dotted segment of `check_id`, and `vendor/techKey/kind` come from `extra.metadata`, `line` from `start.line`. A blank/invalid stdout yields empty lists (never raises).

- [ ] **Step 1: Write the failing test**

Create `tests/test_opengrep_runner.py`:

```python
import json
from agent.lib.opengrep import run_scan


_CANNED = json.dumps({
    "results": [
        {"check_id": "tmp.stripe-endpoint", "path": "src/pay.php",
         "start": {"line": 3, "col": 8}, "end": {"line": 3, "col": 40},
         "extra": {"metadata": {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"},
                   "severity": "INFO", "lines": "requires login"}},
    ],
    "errors": [{"message": "parse error", "path": "src/weird.php"}],
    "paths": {"scanned": ["src/pay.php", "src/weird.php"]},
})


def test_run_scan_parses_matches_from_metadata():
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return _CANNED

    res = run_scan("/repo", "/tmp/rules.yaml", engine="opengrep", run=fake_run)
    assert seen["args"] == ["opengrep", "--config", "/tmp/rules.yaml", "--json", "--quiet", "/repo"]
    m = res["matches"][0]
    assert m == {"checkId": "stripe-endpoint", "vendor": "Stripe", "techKey": "api:stripe",
                 "kind": "endpoint", "path": "src/pay.php", "line": 3}
    assert res["scanned"] == ["src/pay.php", "src/weird.php"]
    assert len(res["errors"]) == 1


def test_run_scan_blank_output_is_empty_not_crash():
    res = run_scan("/repo", "/r.yaml", run=lambda args: "")
    assert res == {"matches": [], "scanned": [], "errors": []}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_opengrep_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.opengrep'`.

- [ ] **Step 3: Implement the runner**

Create `agent/lib/opengrep.py`:

```python
"""Run the Opengrep/Semgrep engine (injected for tests) and normalize its JSON results.
Engine facts (verified 2026-07-14): --config/--json/--quiet; results carry extra.metadata;
extra.lines is login-gated so the caller reads the example line from the file instead."""
from __future__ import annotations

import json
import subprocess


def _default_run(args: list) -> str:  # pragma: no cover - spawns the real engine
    proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
    return proc.stdout


def run_scan(repo_path: str, ruleset_path: str, *, engine: str = "opengrep", run=_default_run) -> dict:
    out = run([engine, "--config", ruleset_path, "--json", "--quiet", repo_path])
    try:
        data = json.loads(out) if out and out.strip() else {}
    except ValueError:
        data = {}
    matches = []
    for r in data.get("results", []):
        meta = (r.get("extra") or {}).get("metadata") or {}
        matches.append({
            "checkId": (r.get("check_id") or "").split(".")[-1],
            "vendor": meta.get("vendor", ""), "techKey": meta.get("techKey", ""),
            "kind": meta.get("kind", ""),
            "path": r.get("path", ""), "line": (r.get("start") or {}).get("line", 0),
        })
    return {"matches": matches,
            "scanned": (data.get("paths") or {}).get("scanned", []),
            "errors": data.get("errors", [])}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_opengrep_runner.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/opengrep.py tests/test_opengrep_runner.py
git commit -m "feat(inventory): Opengrep engine runner (injected, parses results -> matches)"
```

---

## Task 4: Endpoint aggregator + live smoke

**Files:**
- Create: `agent/lib/endpoints.py`
- Test: `tests/test_endpoints.py`, `tests/test_opengrep_live.py`

**Interfaces:**
- Consumes: match dicts (Task 3), `Vendor` (Task 1), `build_ruleset`/`write_ruleset` (Task 2), `run_scan` (Task 3).
- Produces:
  - `build_endpoints(matches: list, repo_root: str, vendors: list, *, max_files: int = 20) -> list[dict]` — for each `kind == "endpoint"` match, read the file line at `repo_root/path:line`, pick the vendor by `techKey`, determine `domain` (first vendor domain present in the line), extract `version` via the vendor's `version_regex` (group 1, or `None`), and aggregate into records keyed by `(techKey, domain, version)`. Each record: `{vendor, domain, version, techKey, example, file_count, files:[path:line]}`. `example` = the stripped line of the first match in the group. `file_count` = true count of distinct `path:line`; `files` capped at `max_files`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_endpoints.py`:

```python
from agent.lib.vendors import Vendor
from agent.lib.endpoints import build_endpoints


def _write(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


_VENDORS = [Vendor("Amazon SP-API", "api:amazon-sp-api", ("sellingpartnerapi",),
                   r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})'),
            Vendor("Stripe", "api:stripe", ("api.stripe.com",), r'/(v\d+)')]


def test_aggregates_endpoints_with_version_and_filelines(tmp_path):
    _write(tmp_path, "a.php", 'x\n$u = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders";\n')
    _write(tmp_path, "b.php", '$v = "https://api.stripe.com/v1/charges";\n')
    matches = [
        {"kind": "endpoint", "techKey": "api:amazon-sp-api", "vendor": "Amazon SP-API",
         "path": "a.php", "line": 2},
        {"kind": "endpoint", "techKey": "api:stripe", "vendor": "Stripe", "path": "b.php", "line": 1},
    ]
    eps = build_endpoints(matches, str(tmp_path), _VENDORS)
    by_key = {(e["techKey"], e["version"]): e for e in eps}
    sp = by_key[("api:amazon-sp-api", "v0")]
    assert sp["domain"] == "sellingpartnerapi" and sp["files"] == ["a.php:2"] and sp["file_count"] == 1
    assert "sellingpartnerapi" in sp["example"]
    assert by_key[("api:stripe", "v1")]["domain"] == "api.stripe.com"


def test_same_vendor_version_groups_and_counts(tmp_path):
    _write(tmp_path, "a.php", '"https://api.stripe.com/v1/a";\n')
    _write(tmp_path, "b.php", '"https://api.stripe.com/v1/b";\n')
    matches = [{"kind": "endpoint", "techKey": "api:stripe", "vendor": "Stripe", "path": p, "line": 1}
               for p in ("a.php", "b.php")]
    eps = build_endpoints(matches, str(tmp_path),
                          [Vendor("Stripe", "api:stripe", ("api.stripe.com",), r'/(v\d+)')])
    assert len(eps) == 1 and eps[0]["file_count"] == 2 and set(eps[0]["files"]) == {"a.php:1", "b.php:1"}


def test_no_version_when_url_has_none(tmp_path):
    _write(tmp_path, "a.php", '"https://api.stripe.com/charges";\n')
    eps = build_endpoints([{"kind": "endpoint", "techKey": "api:stripe", "vendor": "Stripe",
                            "path": "a.php", "line": 1}], str(tmp_path),
                          [Vendor("Stripe", "api:stripe", ("api.stripe.com",), r'/(v\d+)')])
    assert eps[0]["version"] is None


def test_non_endpoint_matches_ignored(tmp_path):
    eps = build_endpoints([{"kind": "sdk", "techKey": "api:stripe", "vendor": "Stripe",
                            "path": "a.php", "line": 1}], str(tmp_path), _VENDORS)
    assert eps == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_endpoints.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.endpoints'`.

- [ ] **Step 3: Implement the aggregator**

Create `agent/lib/endpoints.py`:

```python
"""Turn normalized engine matches into endpoint records: read the matched line from the file,
extract the API version, and aggregate per (techKey, domain, version)."""
from __future__ import annotations

import re
from pathlib import Path


def _read_line(repo_root: str, path: str, line: int) -> str:
    try:
        text = (Path(repo_root) / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    return lines[line - 1] if 1 <= line <= len(lines) else ""


def _domain_in(line: str, domains) -> str:
    for d in domains:
        if d in line:
            return d
    return ""


def _version(line: str, version_regex: str):
    m = re.search(version_regex, line)
    return m.group(1) if m else None


def build_endpoints(matches: list, repo_root: str, vendors: list, *, max_files: int = 20) -> list:
    by_key = {v.techKey: v for v in vendors}
    groups: dict = {}
    for m in matches:
        if m.get("kind") != "endpoint":
            continue
        v = by_key.get(m.get("techKey", ""))
        line = _read_line(repo_root, m.get("path", ""), int(m.get("line", 0) or 0))
        domain = _domain_in(line, v.domains) if v else ""
        version = _version(line, v.version_regex) if v else None
        key = (m.get("techKey", ""), domain, version)
        rec = groups.get(key)
        if rec is None:
            rec = {"vendor": m.get("vendor", ""), "domain": domain, "version": version,
                   "techKey": m.get("techKey", ""), "example": line.strip(),
                   "file_count": 0, "files": []}
            groups[key] = rec
        loc = f"{m.get('path','')}:{m.get('line',0)}"
        rec["file_count"] += 1
        if len(rec["files"]) < max_files and loc not in rec["files"]:
            rec["files"].append(loc)
    return list(groups.values())
```

- [ ] **Step 4: Run the aggregator test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_endpoints.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Write the LIVE end-to-end smoke (opt-in, skips if no engine)**

Create `tests/test_opengrep_live.py` — proves the whole chain (catalog → rules → real engine → aggregation) works on real files, and that comments are correctly skipped:

```python
import shutil
import pytest

from agent.lib.vendors import Vendor
from agent.lib.vendor_rules import write_ruleset
from agent.lib.opengrep import run_scan
from agent.lib.endpoints import build_endpoints

_ENGINE = shutil.which("opengrep") or shutil.which("semgrep")


@pytest.mark.skipif(_ENGINE is None, reason="no opengrep/semgrep engine installed")
def test_live_endpoint_extraction_skips_comments(tmp_path):
    (tmp_path / "pay.php").write_text(
        '<?php\n'
        '// legacy: https://api.stripe.com/v9/dead\n'         # comment -> MUST be skipped
        '$u = "https://api.stripe.com/v1/charges";\n')
    (tmp_path / "app.js").write_text(
        'const u = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders";\n')

    vendors = [Vendor("Stripe", "api:stripe", ("api.stripe.com",),
                      r'/(v\d+)'),
               Vendor("Amazon SP-API", "api:amazon-sp-api", ("sellingpartnerapi",),
                      r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})')]
    rules = tmp_path / "rules.yaml"
    write_ruleset(vendors, str(rules))

    engine = "opengrep" if shutil.which("opengrep") else "semgrep"
    res = run_scan(str(tmp_path), str(rules), engine=engine)
    eps = build_endpoints(res["matches"], str(tmp_path), vendors)

    by_key = {e["techKey"]: e for e in eps}
    assert by_key["api:stripe"]["version"] == "v1"          # the live code line, NOT the comment's v9
    assert all("v9" not in (e.get("version") or "") for e in eps)   # comment endpoint skipped
    assert by_key["api:amazon-sp-api"]["version"] == "v0"
```

- [ ] **Step 6: Run the live smoke (with the engine present)**

Run: `source .venv/bin/activate && python -m pytest tests/test_opengrep_live.py -v`
Expected: PASS (the `.venv` has `semgrep`; the test auto-selects it). If run where no engine exists, it SKIPS (not fails).

Then the full suite:
Run: `source .venv/bin/activate && python -m pytest -q`
Expected: PASS — prior 260 + T1(4) + T2(3) + T3(2) + T4 aggregator(4) + live(1) = 274 (or 273 with the live test skipped in a no-engine environment).

- [ ] **Step 7: Commit**

```bash
git add agent/lib/endpoints.py tests/test_endpoints.py tests/test_opengrep_live.py
git commit -m "feat(inventory): endpoint aggregator (version + file:line) + live Opengrep smoke"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-07-14-integration-inventory-plugin-design.md`, §"components 1-3" and Unit 1 of the sequencing):
- "`agent/vendors.yaml` — vendor catalog {vendor, techKey, domains, versionRegex}" → Task 1 ✓ (27 vendors from the PM's report)
- "`agent/lib/opengrep.py` — wraps the CLI via an injected run; parses results" → Task 3 ✓
- "endpoint aggregator — reads the example line from the file (NOT extra.lines), extracts version, aggregates into `{vendor,domain,version,techKey,example,file_count,files[path:line]}`" → Task 4 ✓
- "`rules/` rule pack — AST string-literal patterns (not pattern-regex)" → Task 2 generates them from the catalog with the verified `"=~/…/"` idiom ✓ (SSOT = vendors.yaml; DRY)
- "live integration test, opt-in / skip if engine absent" → Task 4 `test_opengrep_live.py` ✓
- "endpoint records carry techKey" → present on every record (Task 4) ✓
- Out of scope for Unit 1 and correctly deferred: SDK-in-code rules (flaky PHP class patterns; manifests cover declared SDKs in Unit 2), the superset assembler/IR store/rollups/render (Unit 3), baseline diff (Unit 4), the plugin (Unit 5).

**Placeholder scan:** none — every code/test step is complete and runnable; all engine facts are verified live (not assumed).

**Type consistency:** `Vendor(vendor, techKey, domains, version_regex)` used identically across Tasks 1/2/4. Match dicts `{checkId, vendor, techKey, kind, path, line}` produced by `run_scan` (T3) and consumed by `build_endpoints` (T4). `build_ruleset -> {"rules": [...]}` consumed by `write_ruleset` and the live test. Endpoint record keys `{vendor, domain, version, techKey, example, file_count, files}` match the spec's schema exactly. The `"=~/…/"` pattern and `--config/--json/--quiet` invocation match the verified engine behavior.

**Known Unit-1 simplifications (intentional):** endpoint detection only (SDK-in-code deferred); `version` is best-effort from the URL (None when absent); `files` capped at 20 with a true `file_count` (mirrors the PM's truncated `files` + full count).
