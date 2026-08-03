# Probabilistic (AI) Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, AI-powered probabilistic scan that runs after the deterministic scan, cross-checks all repos, and renders a *separate* unverified report — with any lead promotable through the existing absorb gate.

**Architecture:** A pure, deterministic core (`compare` + `render`) consumes an `ai_results.json` produced by an AI driver, and a certified `drift.json`, to emit `probabilistic.html`. The one non-deterministic part (the AI reading repos) is isolated behind the `ai_results.json` contract and lives only in the plugin promptfile. The certified pipeline and the `verify` contract are untouched.

**Tech Stack:** Python 3.12 (stdlib + PyYAML only), pytest. No network in unit tests. The plugin flow is a markdown promptfile driving Claude in-session.

## Global Constraints

- Python 3.12 in `.venv` (uv-managed). Run tests with `.venv/bin/python -m pytest -q`. NO pip — stdlib + PyYAML only. NO new dependency.
- DETERMINISTIC, ZERO-LLM-TOKEN in the pure core: same `ai_results.json` + `drift.json` → byte-identical `probabilistic.html`. No network in any unit test.
- ADDITIVE ONLY: the deterministic scan, `dashboard.html`, `drift.json`, `drift.md`, and `drift-scan verify` are UNTOUCHED. `probabilistic.html` is a new, separate artifact OUTSIDE the verify contract.
- TRUST BOUNDARY: every probabilistic surface is labelled "AI · unverified"; it is never merged into `dashboard.html` or governed by `verify`.
- Vendor matching is coverage-level: normalize a vendor to its first token, lowercased (`re.split(r"[ (/]", v)[0].strip().lower()`), matched per-repo. This mirrors the AI-vs-tool experiment's `norm`.
- "Cannot see ≠ clean": a repo the AI failed to read is reported as `reposReadByAI < reposScanned` and named as "not cross-checked" — never silently dropped.
- Self-contained HTML: inline CSS/JS, no CDN, opens `file://`. All scan-derived strings HTML-escaped.
- TDD, frequent commits, DRY, YAGNI.

**Data contracts (exact shapes):**

`ai_results.json` (produced by the AI driver, consumed by the core):
```json
{"meta": {"reposRead": 33, "tokens": 782188},
 "repos": [{"repo": "ebayapi",
            "integrations": [{"vendor": "eBay", "host": "", "version": "v1",
                              "endpoint": "GetOrders", "file": "src/X.php", "line": "9",
                              "retired": "unknown", "note": ""}],
            "summary": "one line"}]}
```

`drift.json["endpoints"]` (the certified per-repo integrations, ALREADY produced by `drift-scan run`) — each element:
```json
{"repo": "ebayapi", "vendor": "eBay", "version": "v1", "classified": true,
 "domain": "...", "files": ["src/X.php:9"], "file_count": 4}
```

`compare(...)` output (`comparison`):
```json
{"tallies": {"agree": 3, "aiOnly": 2, "toolOnly": 1, "reposReadByAI": 33, "reposScanned": 33},
 "notCrossChecked": ["repoX"],
 "byRepo": [{"repo": "ebayapi",
             "agree": ["eBay"], "toolOnly": ["amazon sp-api"],
             "aiOnly": [{"vendor": "Kogan", "endpoint": "...", "file": "...", "line": "...",
                         "retired": "unknown", "note": ""}]}]}
```

---

### Task 1: `probabilistic.compare` — the pure three-way diff

**Files:**
- Create: `agent/lib/probabilistic.py`
- Test: `tests/test_probabilistic.py`

**Interfaces:**
- Consumes: `ai_results` (dict, the `ai_results.json` shape above); `certified_endpoints` (list, `drift.json["endpoints"]`).
- Produces: `compare(ai_results: dict, certified_endpoints: list) -> dict` returning the `comparison` shape above. `norm(vendor: str) -> str` helper.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_probabilistic.py
from agent.lib.probabilistic import compare, norm


def _ai(repos):
    return {"meta": {"reposRead": len(repos), "tokens": 1000}, "repos": repos}


def test_norm_reduces_vendor_to_first_token_lowercased():
    assert norm("Amazon SP-API") == "amazon"
    assert norm("eBay") == "ebay"
    assert norm("THE ICONIC (SellerCenter)") == "the"


def test_compare_classifies_agree_aionly_toolonly_per_repo():
    certified = [
        {"repo": "r1", "vendor": "eBay", "classified": True, "files": ["a.php:1"]},
        {"repo": "r1", "vendor": "Amazon SP-API", "classified": True, "files": ["b.php:2"]},
    ]
    ai = _ai([{"repo": "r1", "summary": "s", "integrations": [
        {"vendor": "eBay", "endpoint": "GetX", "file": "a.php", "line": "1", "retired": "no"},
        {"vendor": "Kogan", "endpoint": "list", "file": "k.php", "line": "9", "retired": "unknown"},
    ]}])
    out = compare(ai, certified)
    assert out["tallies"] == {"agree": 1, "aiOnly": 1, "toolOnly": 1,
                              "reposReadByAI": 1, "reposScanned": 1}
    repo = out["byRepo"][0]
    assert repo["repo"] == "r1"
    assert repo["agree"] == ["ebay"]
    assert repo["toolOnly"] == ["amazon"]
    assert [x["vendor"] for x in repo["aiOnly"]] == ["Kogan"]      # leads keep the full record


def test_repo_the_ai_did_not_read_is_named_not_cross_checked():
    certified = [{"repo": "r1", "vendor": "eBay", "classified": True, "files": ["a.php:1"]},
                 {"repo": "r2", "vendor": "Shopify", "classified": True, "files": ["c.php:3"]}]
    ai = _ai([{"repo": "r1", "summary": "s", "integrations": [
        {"vendor": "eBay", "endpoint": "x", "file": "a.php", "line": "1", "retired": "no"}]}])
    out = compare(ai, certified)
    assert out["tallies"]["reposScanned"] == 2 and out["tallies"]["reposReadByAI"] == 1
    assert out["notCrossChecked"] == ["r2"]


def test_unclassified_certified_endpoints_are_ignored():
    certified = [{"repo": "r1", "vendor": "Unknown", "classified": False, "files": ["a.php:1"]}]
    ai = _ai([{"repo": "r1", "summary": "s", "integrations": []}])
    out = compare(ai, certified)
    assert out["tallies"]["toolOnly"] == 0


def test_compare_is_deterministic():
    certified = [{"repo": "r1", "vendor": "eBay", "classified": True, "files": ["a.php:1"]}]
    ai = _ai([{"repo": "r1", "summary": "s", "integrations": [
        {"vendor": "Kogan", "endpoint": "x", "file": "k.php", "line": "9", "retired": "unknown"},
        {"vendor": "MyDeal", "endpoint": "y", "file": "m.php", "line": "3", "retired": "unknown"}]}])
    assert compare(ai, certified) == compare(ai, certified)
    # aiOnly leads are sorted by vendor for stable output
    assert [x["vendor"] for x in compare(ai, certified)["byRepo"][0]["aiOnly"]] == ["Kogan", "MyDeal"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_probabilistic.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.lib.probabilistic'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/probabilistic.py
"""The PROBABILISTIC overlay: compare an AI cross-check (ai_results) against the certified
endpoints (drift.json["endpoints"]) into a three-way diff. Pure + deterministic — the AI's
non-determinism is upstream, captured in ai_results.json. This module invents nothing and
certifies nothing; its output is explicitly UNVERIFIED and rendered as a separate artifact."""
from __future__ import annotations

import re

_FIRST = re.compile(r"[ (/]")


def norm(vendor: str) -> str:
    """A vendor's coverage key: first token, lowercased. 'Amazon SP-API' -> 'amazon'. This is
    coarse ON PURPOSE — the AI names vendors in prose, the tool in records; matching the head
    token compares COVERAGE (did each see this vendor at all), not exact endpoint strings."""
    return _FIRST.split(str(vendor or "").strip())[0].strip().lower()


def compare(ai_results: dict, certified_endpoints: list) -> dict:
    # certified vendors per repo (classified only)
    tool_by_repo: dict = {}
    for e in certified_endpoints:
        if not e.get("classified"):
            continue
        v = norm(e.get("vendor"))
        if v and v != "unknown":
            tool_by_repo.setdefault(e.get("repo"), set()).add(v)

    ai_by_repo = {r.get("repo"): r for r in ai_results.get("repos", [])}
    scanned = set(tool_by_repo) | set(ai_by_repo)
    agree = aionly = toolonly = 0
    by_repo = []
    for repo in sorted(scanned):
        tool_v = tool_by_repo.get(repo, set())
        ai_r = ai_by_repo.get(repo)
        ai_ints = (ai_r or {}).get("integrations", [])
        ai_v = {norm(i.get("vendor")) for i in ai_ints if norm(i.get("vendor"))}
        a = sorted(tool_v & ai_v)
        t = sorted(tool_v - ai_v)
        # aiOnly LEADS keep their full record (the actionable part); dedupe+sort by vendor
        leads_seen, leads = set(), []
        for i in sorted(ai_ints, key=lambda x: (norm(x.get("vendor")), str(x.get("file")))):
            nv = norm(i.get("vendor"))
            if nv and nv not in tool_v and nv not in leads_seen:
                leads_seen.add(nv)
                leads.append({"vendor": i.get("vendor"), "endpoint": i.get("endpoint", ""),
                              "file": i.get("file", ""), "line": str(i.get("line", "")),
                              "retired": i.get("retired", "unknown"), "note": i.get("note", "")})
        agree += len(a); toolonly += len(t); aionly += len(leads)
        by_repo.append({"repo": repo, "agree": a, "toolOnly": t, "aiOnly": leads})

    not_checked = sorted(set(tool_by_repo) - set(ai_by_repo))
    return {"tallies": {"agree": agree, "aiOnly": aionly, "toolOnly": toolonly,
                        "reposReadByAI": len(ai_by_repo), "reposScanned": len(scanned)},
            "notCrossChecked": not_checked,
            "byRepo": by_repo}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_probabilistic.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/probabilistic.py tests/test_probabilistic.py
git commit -m "feat(probabilistic): compare() — pure three-way AI-vs-certified diff"
```

---

### Task 2: `render_probabilistic` — the separate, labelled artifact

**Files:**
- Create: `agent/lib/probabilistic_render.py`
- Test: `tests/test_probabilistic_render.py`

**Interfaces:**
- Consumes: `comparison` (Task 1 output); `meta` (dict: `{"reposRead", "tokens", "now"}`).
- Produces: `render_probabilistic(comparison: dict, meta: dict) -> str` (a self-contained HTML string). `_esc(s) -> str` helper.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_probabilistic_render.py
from agent.lib.probabilistic_render import render_probabilistic

_CMP = {"tallies": {"agree": 3, "aiOnly": 2, "toolOnly": 1, "reposReadByAI": 20, "reposScanned": 20},
        "notCrossChecked": [],
        "byRepo": [{"repo": "myerapi", "agree": ["ebay"], "toolOnly": [],
                    "aiOnly": [{"vendor": "Marketplacer", "endpoint": "api/v2/adverts",
                                "file": "src/Myer/Get.php", "line": "9", "retired": "unknown",
                                "note": "n"}]}]}
_META = {"reposRead": 20, "tokens": 782188, "now": "2026-07-31"}


def test_render_is_labelled_unverified_and_self_contained():
    html = render_probabilistic(_CMP, _META)
    assert "AI · unverified" in html
    assert "<script src" not in html and "cdn" not in html.lower()      # no CDN
    assert "782,188" in html or "782188" in html                        # token cost shown


def test_render_shows_tallies_and_the_leads():
    html = render_probabilistic(_CMP, _META)
    assert "Marketplacer" in html and "src/Myer/Get.php" in html        # the lead + its loc
    assert ">2<" in html or "aiOnly" in html                            # aiOnly tally surfaced


def test_render_links_back_to_the_certified_report():
    html = render_probabilistic(_CMP, _META)
    assert "dashboard.html" in html                                     # cross-link to certified


def test_render_names_not_cross_checked_repos():
    cmp2 = {**_CMP, "notCrossChecked": ["brokenRepo"],
            "tallies": {**_CMP["tallies"], "reposReadByAI": 19}}
    html = render_probabilistic(cmp2, _META)
    assert "brokenRepo" in html and "not cross-checked" in html.lower()


def test_render_escapes_scan_strings():
    evil = {"tallies": {"agree": 0, "aiOnly": 1, "toolOnly": 0, "reposReadByAI": 1, "reposScanned": 1},
            "notCrossChecked": [],
            "byRepo": [{"repo": "r", "agree": [], "toolOnly": [],
                        "aiOnly": [{"vendor": "<script>alert(1)</script>", "endpoint": "e",
                                    "file": "f", "line": "1", "retired": "no", "note": ""}]}]}
    html = render_probabilistic(evil, _META)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_is_deterministic():
    assert render_probabilistic(_CMP, _META) == render_probabilistic(_CMP, _META)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_probabilistic_render.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.lib.probabilistic_render'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/probabilistic_render.py
"""Render the probabilistic comparison as a SELF-CONTAINED, explicitly-UNVERIFIED artifact.
Separate from dashboard.html BY DESIGN: it is outside the `verify` contract, so it must SAY
it is unverified everywhere and never be mistaken for the certified report."""
from __future__ import annotations

import html


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def render_probabilistic(comparison: dict, meta: dict) -> str:
    t = comparison.get("tallies", {})
    tokens = int(meta.get("tokens", 0) or 0)
    rows = []
    for r in comparison.get("byRepo", []):
        leads = r.get("aiOnly", [])
        if not leads and not r.get("agree") and not r.get("toolOnly"):
            continue
        lead_html = "".join(
            f'<li><b>{_esc(l.get("vendor"))}</b> <code>{_esc(l.get("endpoint"))}</code> '
            f'<span class="loc">{_esc(l.get("file"))}:{_esc(l.get("line"))}</span>'
            f'{" <span class=ret>retired?</span>" if l.get("retired")=="yes" else ""}</li>'
            for l in leads) or "<li class=none>— no AI-only leads</li>"
        rows.append(
            f'<div class="repo"><div class="rname">{_esc(r.get("repo"))}</div>'
            f'<div class="mini">agree {len(r.get("agree",[]))} · '
            f'AI-only {len(leads)} · tool-only {len(r.get("toolOnly",[]))}</div>'
            f'<ul class="leads">{lead_html}</ul></div>')
    ncc = comparison.get("notCrossChecked", [])
    ncc_html = (f'<div class="ncc"><b>Not cross-checked</b> ({len(ncc)}): '
                f'{_esc(", ".join(ncc))} — the AI could not read these; absence of a lead here '
                f'is not evidence of anything.</div>') if ncc else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Probabilistic cross-check · AI · unverified</title>
<style>
:root{{color-scheme:dark light}}
body{{margin:0;font:14px/1.5 ui-sans-serif,system-ui,sans-serif;background:#0f1114;color:#e8ebf1}}
.wrap{{max-width:1000px;margin:0 auto;padding:32px 20px 64px}}
.badge{{display:inline-block;background:#4b8bff22;color:#4b8bff;font:11px ui-monospace,monospace;
letter-spacing:.08em;text-transform:uppercase;padding:4px 10px;border-radius:20px}}
h1{{font-size:26px;margin:10px 0 4px}}
.sub{{color:#98a1b1;margin:0 0 20px}}
.warn{{background:#e3b34118;border-left:3px solid #e3b341;border-radius:0 8px 8px 0;
padding:12px 15px;margin:16px 0;color:#cdd3de;font-size:13px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:14px 0}}
.tile{{background:#16191e;border:1px solid #2a2f38;border-radius:10px;padding:12px}}
.tile .n{{font-size:24px;font-weight:700}}.tile .l{{font:10px ui-monospace,monospace;color:#6a7180;text-transform:uppercase}}
.repo{{background:#16191e;border:1px solid #2a2f38;border-radius:10px;padding:12px 14px;margin:8px 0}}
.rname{{font:600 14px ui-monospace,monospace}}.mini{{color:#98a1b1;font-size:12px;margin:2px 0 6px}}
ul.leads{{margin:4px 0 0;padding-left:18px}}ul.leads li{{color:#cdd3de;font-size:13px}}
.loc{{font:11px ui-monospace,monospace;color:#6a7180}}.ret{{color:#e0533d;font-weight:600}}
.none{{color:#6a7180}}.ncc{{color:#cdd3de;font-size:13px;margin:14px 0}}
a{{color:#4b8bff}}
</style></head><body><div class="wrap">
<span class="badge">AI · unverified</span>
<h1>Probabilistic cross-check</h1>
<p class="sub">A second opinion from AI over {_esc(t.get('reposScanned'))} repos, {_esc(t.get('reposReadByAI'))} read · {tokens:,} tokens · {_esc(meta.get('now'))}</p>
<div class="warn"><b>These are leads, not findings.</b> Nothing here is verified, sourced, or
certified. The certified report is the deterministic scan → <a href="dashboard.html">dashboard.html</a>.
A lead becomes a finding only by passing the absorb gate.</div>
<div class="tiles">
<div class="tile"><div class="n">{_esc(t.get('agree'))}</div><div class="l">Agree (tool + AI)</div></div>
<div class="tile"><div class="n" style="color:#4b8bff">{_esc(t.get('aiOnly'))}</div><div class="l">AI-only (leads)</div></div>
<div class="tile"><div class="n" style="color:#e0533d">{_esc(t.get('toolOnly'))}</div><div class="l">Tool-only (certified)</div></div>
</div>
{ncc_html}
<h2 style="font-size:14px;color:#98a1b1;margin:22px 0 8px">Per repo</h2>
{''.join(rows)}
</div></body></html>"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_probabilistic_render.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/probabilistic_render.py tests/test_probabilistic_render.py
git commit -m "feat(probabilistic): render_probabilistic() — separate unverified artifact"
```

---

### Task 3: The `probabilistic` CLI subcommand — wire compare + render

**Files:**
- Modify: `agent/cli.py` (add `_cmd_probabilistic` near `_cmd_probe` ~line 316; add the subparser near the `probe` parser ~line 960)
- Modify: `bin/drift-scan:112` (add `probabilistic` to the subcommand case)
- Test: `tests/test_cli_probabilistic.py`

**Interfaces:**
- Consumes: `compare` (Task 1), `render_probabilistic` (Task 2). Reads `<state>/drift.json` and an `--ai-results` JSON file.
- Produces: writes `<state>/probabilistic.html`; validates `ai_results` shape, rejecting malformed input with a clear error (exit 2).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_probabilistic.py
import json
from agent import cli


def _state(tmp_path):
    drift = {"endpoints": [{"repo": "r1", "vendor": "eBay", "classified": True, "files": ["a.php:1"]}]}
    (tmp_path / "drift.json").write_text(json.dumps(drift))
    ai = {"meta": {"reposRead": 1, "tokens": 5}, "repos": [{"repo": "r1", "summary": "s",
          "integrations": [{"vendor": "Kogan", "endpoint": "x", "file": "k.php", "line": "9",
                            "retired": "unknown"}]}]}
    (tmp_path / "ai.json").write_text(json.dumps(ai))
    return str(tmp_path / "drift.json"), str(tmp_path / "ai.json")


def test_probabilistic_writes_labelled_html(tmp_path):
    _state(tmp_path)
    rc = cli.main(["probabilistic", "--state", str(tmp_path),
                   "--ai-results", str(tmp_path / "ai.json"), "--now", "2026-07-31"])
    assert rc == 0
    html = (tmp_path / "probabilistic.html").read_text()
    assert "AI · unverified" in html and "Kogan" in html


def test_probabilistic_rejects_malformed_ai_results(tmp_path):
    _state(tmp_path)
    (tmp_path / "bad.json").write_text('{"not": "the shape"}')
    rc = cli.main(["probabilistic", "--state", str(tmp_path),
                   "--ai-results", str(tmp_path / "bad.json"), "--now", "2026-07-31"])
    assert rc == 2                                          # missing "repos" -> refused
    assert not (tmp_path / "probabilistic.html").exists()


def test_probabilistic_needs_a_prior_scan(tmp_path):
    ai = tmp_path / "ai.json"; ai.write_text('{"meta":{},"repos":[]}')
    rc = cli.main(["probabilistic", "--state", str(tmp_path),
                   "--ai-results", str(ai), "--now", "2026-07-31"])
    assert rc == 2                                          # no drift.json -> refused
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_probabilistic.py -q`
Expected: FAIL (argparse: invalid choice: 'probabilistic')

- [ ] **Step 3: Write minimal implementation**

Add to `agent/cli.py` (near `_cmd_probe`):

```python
def _cmd_probabilistic(args) -> int:
    """Render the probabilistic (AI) cross-check as a SEPARATE, unverified artifact. Reads the
    certified <state>/drift.json + an --ai-results JSON (produced by the AI driver). Pure +
    deterministic: no network, no tokens. Refuses malformed ai_results (never fabricates)."""
    from agent.lib.probabilistic import compare
    from agent.lib.probabilistic_render import render_probabilistic
    drift_path = os.path.join(args.state, "drift.json")
    try:
        with open(drift_path, encoding="utf-8") as fh:
            drift = json.load(fh)
    except OSError:
        print(f"probabilistic: no drift.json in {args.state} — run a deterministic scan first",
              file=sys.stderr)
        return 2
    try:
        with open(args.ai_results, encoding="utf-8") as fh:
            ai = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"probabilistic: cannot read --ai-results ({exc})", file=sys.stderr)
        return 2
    if not isinstance(ai, dict) or not isinstance(ai.get("repos"), list):
        print("probabilistic: --ai-results malformed — expected {meta, repos:[...]}",
              file=sys.stderr)
        return 2
    cmp = compare(ai, drift.get("endpoints", []))
    meta = {"reposRead": (ai.get("meta") or {}).get("reposRead", cmp["tallies"]["reposReadByAI"]),
            "tokens": (ai.get("meta") or {}).get("tokens", 0), "now": args.now}
    out = os.path.join(args.state, "probabilistic.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_probabilistic(cmp, meta))
    tl = cmp["tallies"]
    print(f"✓ probabilistic (AI · unverified): {tl['aiOnly']} AI-only lead(s), "
          f"{tl['agree']} agree, {tl['toolOnly']} tool-only · {out}")
    return 0
```

Add the subparser (near the `probe` parser):

```python
    ppc = sub.add_parser("probabilistic")   # AI cross-check -> separate UNVERIFIED artifact
    ppc.add_argument("--state", required=True)
    ppc.add_argument("--ai-results", required=True, help="ai_results.json from the AI driver")
    ppc.add_argument("--now", required=True)
    ppc.set_defaults(func=_cmd_probabilistic)
```

Modify `bin/drift-scan:112` — add `probabilistic` to the case list:

```bash
  audit|run|deliver|notify|sbom|sarif|brief|precedents|config-preflight|schedule|unschedule|mute|preflight|recommend|absorb|verify|catalog-refresh|catalog-check|plan|probe|freshness|probabilistic) SUB="$1"; shift ;;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_probabilistic.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/cli.py bin/drift-scan tests/test_cli_probabilistic.py
git commit -m "feat(cli): drift-scan probabilistic — render the AI cross-check artifact"
```

---

### Task 4: The plugin flow — offer the cross-check, drive the AI, render, offer promote

**Files:**
- Modify: `commands/drift-detector.md` (add a "## Probabilistic cross-check (opt-in)" section after "## Deliver the report")
- Test: `tests/test_plugin.py` (extend — assert the new section + subcommand are referenced)

**Interfaces:**
- Consumes: the `drift-scan probabilistic` subcommand (Task 3); the deterministic scan (`drift-scan run`); the existing `commands/drift-absorb.md` for promotion.
- Produces: no code interface — a promptfile section that Claude follows in-session.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_plugin.py
def test_drift_detector_offers_probabilistic_cross_check():
    md = open("commands/drift-detector.md", encoding="utf-8").read()
    assert "probabilistic" in md.lower()                       # the opt-in step exists
    assert "AI · unverified" in md                             # the trust label is carried
    assert "drift-scan probabilistic" in md or "$SCAN probabilistic" in md  # wires the subcommand
    assert "drift-absorb" in md                                # promotion path referenced
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_plugin.py -q -k probabilistic`
Expected: FAIL (the section not yet added)

- [ ] **Step 3: Write minimal implementation**

Append to `commands/drift-detector.md` (after the "## Deliver the report" section):

````markdown
## Probabilistic cross-check (opt-in)

After the deterministic report is delivered, OFFER — do not auto-run — a probabilistic pass:

> "Deterministic scan complete: N repos, M certified findings. I can run an **AI · unverified**
> cross-check over all N repos — a second opinion that may surface integrations the rules
> missed. It costs ~K tokens and its output is **leads, not findings** (kept in a separate
> report). Run it?"

Only on an explicit yes:

1. For EACH scanned repo, dispatch one agent that reads the repo for third-party API
   integrations and returns STRICT JSON (vendor, host, version, endpoint, file, line,
   retired, note) — the schema in `docs/superpowers/specs/2026-07-31-probabilistic-scan-design.md`.
   A repo an agent cannot read is reported, never dropped.
2. Assemble the results into `<state>/ai_results.json` (`{meta:{reposRead,tokens}, repos:[...]}`).
3. Render the separate artifact — NEVER touch `dashboard.html`:
   `"$SCAN" probabilistic --state <state> --ai-results <state>/ai_results.json --now $(date +%F)`
   This writes `<state>/probabilistic.html` (labelled **AI · unverified**, outside `verify`).
4. Show the tally (agree / AI-only / tool-only) and point to `probabilistic.html`.
5. For any AI-only lead worth keeping, OFFER to promote it via `/drift-absorb` — the absorb gate
   verifies it (sourced date, no false attribution, residue shrinks) before it can ever become a
   certified finding. Never present a lead as certified; never merge one without the gate.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_plugin.py -q -k probabilistic`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add commands/drift-detector.md tests/test_plugin.py
git commit -m "feat(plugin): offer opt-in AI probabilistic cross-check after the deterministic scan"
```

---

### Task 5: Full-suite + end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Full suite green**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all prior tests + the ~14 new ones), no network.

- [ ] **Step 2: Deterministic path unchanged (verify still governs only certified surfaces)**

Run: `./bin/drift-scan run --root ~/gitlab-fleet/rushikesh/ebayapi --state /tmp/pb --now 2026-07-31 && ./bin/drift-scan verify --state /tmp/pb`
Expected: `verify` green; `/tmp/pb/probabilistic.html` does NOT exist (the AI pass is opt-in, not part of `run`).

- [ ] **Step 3: End-to-end probabilistic render from a fixture**

```bash
cat > /tmp/pb/ai.json <<'JSON'
{"meta":{"reposRead":1,"tokens":1234},"repos":[{"repo":"ebayapi","summary":"eBay + a new one",
 "integrations":[{"vendor":"eBay","endpoint":"GetOrders","file":"src/config/ebay.php","line":"8","retired":"no"},
                 {"vendor":"Kogan","endpoint":"list","file":"src/K.php","line":"3","retired":"unknown"}]}]}
JSON
./bin/drift-scan probabilistic --state /tmp/pb --ai-results /tmp/pb/ai.json --now 2026-07-31
grep -q "AI · unverified" /tmp/pb/probabilistic.html && grep -q "Kogan" /tmp/pb/probabilistic.html && echo OK
```
Expected: prints the tally + `OK` (the Kogan AI-only lead rendered, labelled unverified; eBay is `agree`).

- [ ] **Step 4: Commit (if any verification fixups were needed)**

```bash
git add -A && git commit -m "test(probabilistic): full-suite + end-to-end verification green"
```

---

## Notes for the implementer

- The AI driver (Task 4, step 1) is the ONLY non-deterministic piece and lives in the promptfile — there is no Python unit test for "the AI read correctly"; the pure core (Tasks 1–3) is what's proven.
- Do NOT add `probabilistic.html` to `drift-scan verify`, to `run_pipeline`'s outputs, or to the SBOM/SARIF bundle. It is deliberately outside all of them.
- The SDK/CI headless path is explicitly OUT OF SCOPE for this plan (banked in the spec's non-goals).
```
