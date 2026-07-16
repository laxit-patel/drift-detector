# Drift Detector Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate one self-contained interactive `dashboard.html` per scan — a cockpit that serves the PM (exposure tiles) and the developer (drill-down fix queue) and shows the endpoint/sunset moat, from data already on disk.

**Architecture:** A new pure renderer `agent/lib/dashboard_render.py` builds a minimal JSON projection of the audit's ranked `actions[]` plus the inventory's endpoints, embeds it in a single HTML document with inline CSS + vanilla JS, and returns the string. The caller (`run.py`, `cli.py`) writes it. No server, no CDN, no build, no new dependency.

**Tech Stack:** Python 3.12 stdlib only (`html`, `json`); vanilla browser JS inlined as a Python string constant. pytest. Optional node-based JS smoke (node v24 present; test skips if absent).

**Spec:** `docs/superpowers/specs/2026-07-16-dashboard-design.md` — read it if a requirement here is ambiguous; it is the source of truth.

## Global Constraints

- Python 3.12 in `.venv` (uv-managed). Run tests with `.venv/bin/python -m pytest -q`. **NO pip** — stdlib only (`html`, `json`). NO new dependencies, NO CDN, NO external assets.
- **DETERMINISTIC, ZERO-LLM-TOKEN.** Same `(inventory, audit, now)` → byte-identical HTML. No network in any unit test.
- **Self-contained output:** inline CSS + inline JS + embedded JSON only. Must open and be fully interactive from `file://` with the browser offline.
- `render_dashboard` is a **pure function** (returns the HTML string; the caller writes the file). Injected-seam style matching `agent/lib/audit_render.py`.
- **Backward compatibility: additive only.** Do not change `audit["findings"]` or any existing artifact. `dashboard.html` is a new output.
- **Escaping is mandatory on BOTH surfaces:** `html.escape(s, quote=True)` for HTML text; `<`→`<` replacement in the serialized JSON blob so scan-derived strings (repo/pkg/vendor/file paths) containing `</script>`, `<`, `&`, `"` cannot inject. The client JS must not `innerHTML` un-escaped scan data.
- **Data source of truth:** `audit["actions"]` (ranked; fall back to `build_actions(non-suppressed findings)` when absent) + `audit["counts"]`/`audit["delta"]` + `inventory["repos"][].endpoints[]` (`domain/vendor/version/classified/file_count/files`). Tile counts computed in Python and embedded — the JS never re-derives them.
- **Tiles count ACTIONS, not findings.** A tile's number must equal the rows its filter produces. Critical = 3 on real data (10 advisories → 3 packages), not 10.
- **Latest-run-only.** No run archive, no history, no server, no connectors.
- TDD, frequent commits, DRY, YAGNI.

---

## File Structure

| File | Responsibility |
|---|---|
| `agent/lib/dashboard_render.py` *(create)* | `render_dashboard(inventory, audit, now) -> str`. Projection + tile counts + full HTML shell + inline CSS + embedded blob + inline JS. Pure. |
| `tests/test_dashboard_render.py` *(create)* | Projection/escaping/determinism/no-CDN (Task 1); JS presence + data-contract + optional node smoke (Task 2). |
| `agent/run.py` *(modify)* | One `_write(... "dashboard.html" ...)` after existing writes. |
| `agent/cli.py` *(modify)* | `--out-html` flag on the `audit` subparser + a write block in `_cmd_audit`. |
| `tests/test_run_pipeline.py` *(modify)* | `run` writes `dashboard.html`. |
| `tests/test_cli.py` *(modify or create)* | `audit --out-html` writes it; omitting doesn't. |

**Decomposition rationale:** Task 1 delivers the complete Python side (projection + static shell + CSS + a minimal bootstrap JS that renders the default panel) — independently testable on the data contract, escaping, determinism. Task 2 fills in the interactive JS (tile filters, search, accordion, theme) and its tests assert the handlers/hooks are present and the projection carries what they read. Task 3 wires it into the pipeline + CLI and runs the real-data success check. A reviewer could accept Task 1 (correct, safe, deterministic static dashboard) while rejecting Task 2 (interactions) — so they split.

---

## Task 1: `dashboard_render.py` — projection, shell, CSS, embedded blob

**Files:**
- Create: `agent/lib/dashboard_render.py`
- Create: `tests/test_dashboard_render.py`

**Interfaces:**
- Consumes: `build_actions(findings)` from `agent.lib.actions` (fallback when `audit` has no `actions`).
- Produces: `render_dashboard(inventory: dict, audit: dict, now: str) -> str` — a complete `<!doctype html>` document. Also an internal `_build_projection(inventory, audit) -> dict` with keys: `generated`, `counts` (tile counts), `delta`, `actions` (list of projected action dicts), `endpoints` (list of projected endpoint dicts), `coverageNotes`. Task 2 relies on the projection shape and the DOM hooks (`id="drift-data"`, `id="panel"`, `class="tile"` with `data-filter`, `class="search"`, `id="theme-toggle"`).

**Projected action dict** (only UI-read fields): `repo, ref, pkg, kind, current_version, fix_version, command, recommendation, worst, status, finding_count, critical_count, first_seen, cves` (list of `{id, title}` from `fixes`), `sources` (list of urls), `files` (path:line, for sunset actions).
**Projected endpoint dict:** `repo, domain, vendor, version, classified, file_count, files`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard_render.py`:

```python
"""The dashboard renders ACTIONS + endpoints into one self-contained HTML file.
Pure Python; string/JSON assertions only — no browser, no network."""
import json
import re

from agent.lib.dashboard_render import render_dashboard


def _cve(repo="r", ref="npm/axios", version="0.21.1", fixed="1.16.0", severity="HIGH",
         status="DEPRECATED", first_seen="2026-07-15", **kw):
    return {"repo": repo, "ref": ref, "kind": "cve", "version": version, "fixed": fixed,
            "severity": severity, "status": status, "first_seen": first_seen,
            "id": kw.get("id", "CVE-x"), "cve": kw.get("cve", "CVE-x"),
            "detail": kw.get("detail", "summary text"), "recommendation": f"upgrade to >= {fixed}",
            "source_url": kw.get("source_url", "https://osv.dev/x"), "tier": 1}


def _audit(findings):
    # audit WITHOUT a precomputed actions key -> exercises the build_actions fallback
    return {"generated": "2026-07-15", "findings": findings,
            "counts": {"DEPRECATED": sum(1 for f in findings if f["status"] == "DEPRECATED"),
                       "REVIEW": sum(1 for f in findings if f["status"] == "REVIEW"),
                       "reposAffected": len({f["repo"] for f in findings})},
            "coverage": {"notes": ["note one"]}}


def _inv(endpoints=()):
    return {"generated": "2026-07-15",
            "repos": [{"path": "svc-a", "endpoints": list(endpoints)}]}


def _blob(html):
    m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>',
                  html, re.DOTALL)
    assert m, "drift-data blob not found"
    return json.loads(m.group(1).replace("\\u003c", "<"))


def test_is_a_self_contained_html_document():
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    assert html.startswith("<!doctype html>")
    assert html.count('<script id="drift-data"') == 1


def test_blob_action_count_matches_non_suppressed_actions():
    findings = [_cve(ref="npm/a"), _cve(ref="npm/b"), _cve(ref="npm/c")]
    data = _blob(render_dashboard(_inv(), _audit(findings), "2026-07-15"))
    assert len(data["actions"]) == 3


def test_every_command_appears_in_the_output():
    html = render_dashboard(_inv(), _audit([_cve(ref="python/torch", fixed="2.10.0")]),
                            "2026-07-15")
    assert "pip install 'torch>=2.10.0'" in html


def test_tile_counts_are_action_based_not_finding_based():
    # 3 critical FINDINGS on the same package = ONE critical ACTION. The tile must read 1.
    findings = [_cve(ref="npm/mongoose", severity="CRITICAL", id=f"CVE-{i}", cve=f"CVE-{i}")
                for i in range(3)]
    data = _blob(render_dashboard(_inv(), _audit(findings), "2026-07-15"))
    assert data["counts"]["critical"] == 1
    assert data["counts"]["fixes"] == 1


def test_tile_counts_apis_and_unknown_from_endpoints():
    eps = [{"domain": "api.ebay.com", "vendor": "eBay", "version": "v1", "classified": True,
            "file_count": 1, "files": ["a.php:1"]},
           {"domain": "api.stripe.com", "vendor": "Stripe", "version": "v1", "classified": True,
            "file_count": 1, "files": ["b.php:1"]},
           {"domain": "x.internal.io", "vendor": "Unknown", "version": None, "classified": False,
            "file_count": 1, "files": ["c.php:1"]}]
    data = _blob(render_dashboard(_inv(eps), _audit([_cve()]), "2026-07-15"))
    assert data["counts"]["apis"] == 2        # eBay + Stripe
    assert data["counts"]["unknown"] == 1


def test_eol_action_tile_and_no_command():
    eol = {"repo": "r", "ref": "php", "kind": "eol", "version": "^7.4", "fixed": "8.5.8",
           "severity": "EOL", "status": "DEPRECATED", "first_seen": "2026-07-15",
           "detail": "php 7.4 end-of-life 2022-11-28", "recommendation": "upgrade to 8.5.8",
           "source_url": "https://endoflife.date/php", "tier": 1}
    data = _blob(render_dashboard(_inv(), _audit([eol]), "2026-07-15"))
    assert data["counts"]["eol"] == 1
    a = next(a for a in data["actions"] if a["kind"] == "eol")
    assert a["command"] is None and a["fix_version"] == "8.5.8"


def test_sunset_action_files_render_and_tile_counts():
    sunset = {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "version": "v1",
              "severity": "SUNSET", "status": "DEPRECATED", "first_seen": "2026-07-15",
              "detail": "eBay v1 retires 2026-09-30", "date": "2026-09-30",
              "recommendation": "migrate to Sell API before 2026-09-30",
              "source_url": "https://developer.ebay.com/x", "tier": 1,
              "files": ["src/Ebay/x.php:111", "src/Ebay/y.php:540"]}
    html = render_dashboard(_inv(), _audit([sunset]), "2026-07-15")
    data = _blob(html)
    assert data["counts"]["sunsets"] == 1
    assert "src/Ebay/x.php:111" in html           # the moat payload is in the file


def test_zero_sunsets_when_no_sunset_actions():
    data = _blob(render_dashboard(_inv(), _audit([_cve()]), "2026-07-15"))
    assert data["counts"]["sunsets"] == 0


def test_output_is_byte_identical_across_calls():
    inv, audit = _inv(), _audit([_cve(ref="b/z"), _cve(ref="a/y", severity="CRITICAL")])
    assert render_dashboard(inv, audit, "2026-07-15") == render_dashboard(inv, audit, "2026-07-15")


def test_empty_audit_renders_valid_document_with_nothing_found():
    html = render_dashboard(_inv(), _audit([]), "2026-07-15")
    assert html.startswith("<!doctype html>")
    assert _blob(html)["actions"] == []
    assert "Nothing found" in html or "nothing found" in html.lower()


def test_xss_scan_strings_are_escaped_on_both_surfaces():
    evil = 'a<script>alert(1)</script>&"x'
    findings = [_cve(repo=evil)]
    html = render_dashboard(_inv(), _audit(findings), "2026-07-15")
    # 1) the raw payload never appears literally as HTML
    assert "<script>alert(1)</script>" not in html
    # 2) the JSON blob cannot be broken out of: no literal </script> inside it
    blob_raw = re.search(r'<script id="drift-data"[^>]*>(.*?)</script>',
                         html, re.DOTALL).group(1)
    assert "</script>" not in blob_raw
    # 3) it still round-trips: the value is intact once parsed
    data = json.loads(blob_raw.replace("\\u003c", "<"))
    assert data["actions"][0]["repo"] == evil


def test_no_external_assets():
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    assert "<script src" not in html.lower()
    assert '<link rel="stylesheet"' not in html.lower()
    assert "@import" not in html.lower()
    assert '<img src="http' not in html.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.dashboard_render'`

- [ ] **Step 3: Write the implementation**

Create `agent/lib/dashboard_render.py`:

```python
"""Render a scan into a single self-contained dashboard.html — the interactive cockpit.

Renders ACTIONS (ranked upgrade jobs) + endpoints (the integration/sunset moat) into one
HTML file with inline CSS + vanilla JS + an embedded JSON projection. No server, no CDN, no
build: opens from file://. Pure and deterministic — same (inventory, audit, now) yields
byte-identical output. The caller writes the string to disk.
"""
from __future__ import annotations

import html
import json

from agent.lib.actions import build_actions

_MAX_CVES = 20            # cap the per-action CVE list embedded in the blob


def _actions_of(audit: dict) -> list:
    actions = audit.get("actions")
    if actions is None:                       # audits written before the action model carry only findings
        actions = build_actions([f for f in audit.get("findings", []) if not f.get("suppressed")])
    return actions


def _project_action(a: dict) -> dict:
    cves = []
    for f in a.get("fixes", []):
        if f.get("cve") or f.get("id"):
            cves.append({"id": f.get("cve") or f.get("id"), "title": f.get("detail") or ""})
    return {
        "repo": a.get("repo"), "ref": a.get("ref"), "pkg": a.get("pkg"),
        "kind": a.get("kind"), "current_version": a.get("current_version"),
        "fix_version": a.get("fix_version"), "command": a.get("command"),
        "recommendation": a.get("recommendation"), "worst": a.get("worst"),
        "status": a.get("status"), "finding_count": a.get("finding_count"),
        "critical_count": a.get("critical_count"), "first_seen": a.get("first_seen"),
        "cves": cves[:_MAX_CVES], "sources": a.get("sources", []), "files": a.get("files", []),
    }


def _endpoints_of(inventory: dict) -> list:
    out = []
    for r in inventory.get("repos", []):
        for e in r.get("endpoints", []):
            out.append({"repo": r.get("path"), "domain": e.get("domain"),
                        "vendor": e.get("vendor"), "version": e.get("version"),
                        "classified": bool(e.get("classified")),
                        "file_count": e.get("file_count"), "files": e.get("files", [])})
    return out


def _build_projection(inventory: dict, audit: dict) -> dict:
    actions = [_project_action(a) for a in _actions_of(audit)]
    endpoints = _endpoints_of(inventory)
    counts = {
        "critical": sum(1 for a in actions if a["worst"] == "CRITICAL"),
        "fixes": sum(1 for a in actions if a["status"] == "DEPRECATED"),
        "eol": sum(1 for a in actions if a["kind"] == "eol"),
        "sunsets": sum(1 for a in actions if a["kind"] == "sunset"),
        "apis": len({e["vendor"] for e in endpoints if e["classified"]}),
        "unknown": sum(1 for e in endpoints if not e["classified"]),
        "reposAffected": (audit.get("counts") or {}).get("reposAffected", 0),
    }
    return {
        "generated": audit.get("generated", ""),
        "counts": counts,
        "delta": audit.get("delta"),
        "actions": actions,
        "endpoints": endpoints,
        "coverageNotes": (audit.get("coverage") or {}).get("notes", []),
    }


def _e(s) -> str:
    """HTML-text escape (NOT audit_render._esc, which escapes markdown pipes)."""
    return html.escape("" if s is None else str(s), quote=True)


def _blob(projection: dict) -> str:
    """Serialize the projection and neutralize the one HTML-in-JS hazard: a scan string
    containing </script> would otherwise close the embedding <script> element. Replacing
    < with its \\u003c JSON escape is transparent to JSON.parse."""
    raw = json.dumps(projection, ensure_ascii=False, sort_keys=True)
    return raw.replace("<", "\\u003c")


def render_dashboard(inventory: dict, audit: dict, now: str) -> str:
    projection = _build_projection(inventory, audit)
    c = projection["counts"]
    d = projection.get("delta") or {}
    new_n = len(build_actions(d["new"])) if d.get("new") else 0
    resolved_n = len(d.get("resolved", []))
    delta_txt = (f" · ↓{resolved_n} resolved ↑{new_n} new this week"
                 if projection.get("delta") is not None else "")

    parts = []
    parts.append("<!doctype html>")
    parts.append('<html lang="en" data-theme="dark">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append(f"<title>Drift Detector — {_e(now)}</title>")
    parts.append("<style>" + _CSS + "</style>")
    parts.append("</head><body>")
    # exposure header
    parts.append('<header class="exposure">')
    parts.append(f'<span class="headline">🔴 {c["fixes"]} fixes needed · '
                 f'{c["reposAffected"]} repos{_e(delta_txt)}</span>')
    parts.append('<button id="theme-toggle" title="Toggle light/dark">◐</button>')
    parts.append("</header>")
    # tile groups
    parts.append('<section class="tiles">')
    parts.append(_tile_group("Security", [
        ("critical", "Critical", c["critical"]),
        ("fixes", "Fixes", c["fixes"]),
        ("eol", "EOL", c["eol"])]))
    parts.append(_tile_group("Integrations", [
        ("apis", "APIs used", c["apis"]),
        ("sunsets", "Sunsets", c["sunsets"]),
        ("unknown", "Unknown hosts", c["unknown"])]))
    parts.append("</section>")
    # search + panel
    parts.append('<input class="search" id="search" type="search" '
                 'placeholder="Filter by repo, package or vendor…">')
    parts.append('<table id="panel"><tbody></tbody></table>')
    parts.append('<p id="empty" class="empty" hidden>Nothing found.</p>')
    # data + behaviour
    parts.append('<script id="drift-data" type="application/json">'
                 + _blob(projection) + "</script>")
    parts.append("<script>" + _CLIENT_JS + "</script>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _tile_group(title: str, tiles) -> str:
    cells = "".join(
        f'<button class="tile" data-filter="{key}">'
        f'<span class="tile-n">{n}</span><span class="tile-label">{_e(label)}</span></button>'
        for key, label, n in tiles)
    return f'<div class="tile-group"><h2>{_e(title)}</h2><div class="tile-row">{cells}</div></div>'


_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#c9d1d9;--accent:#58a6ff;
--crit:#c0392b;--dep:#e67e22;--rev:#d4a017;--moat:#8e44ad}
:root[data-theme="light"]{--bg:#fff;--panel:#f4f4f8;--line:#ddd;--text:#1a1a2e;--accent:#4a4ae0}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--text)}
.exposure{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;
background:var(--panel);border-bottom:1px solid var(--line)}
.headline{font-weight:600}
#theme-toggle{background:none;border:1px solid var(--line);color:var(--text);border-radius:6px;
cursor:pointer;font-size:16px;padding:2px 8px}
.tiles{display:flex;gap:18px;flex-wrap:wrap;padding:16px 18px}
.tile-group h2{font-size:11px;text-transform:uppercase;letter-spacing:.08em;opacity:.7;margin:0 0 6px}
.tile-row{display:flex;gap:8px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;color:var(--text);
cursor:pointer;padding:10px 14px;min-width:78px;text-align:center;display:flex;flex-direction:column}
.tile[aria-pressed="true"]{outline:2px solid var(--accent)}
.tile-n{font-size:22px;font-weight:700}
.tile-label{font-size:11px;opacity:.8}
.search{width:calc(100% - 36px);margin:6px 18px;padding:8px 10px;border-radius:6px;
border:1px solid var(--line);background:var(--panel);color:var(--text)}
#panel{width:calc(100% - 36px);margin:0 18px 24px;border-collapse:collapse}
#panel tr.row{border-bottom:1px solid var(--line);cursor:pointer}
#panel td{padding:8px 6px;vertical-align:top}
.sev-CRITICAL{color:var(--crit);font-weight:700}.sev-HIGH{color:var(--dep)}
.sev-EOL,.sev-SUNSET{color:var(--moat)}
.detail{background:var(--panel);border-left:3px solid var(--accent)}
.cmd{font-family:ui-monospace,monospace;background:var(--bg);padding:6px 8px;border-radius:5px;
color:var(--accent);display:inline-block}
.copy{cursor:pointer;border:1px solid var(--line);background:none;color:var(--text);border-radius:4px;
margin-left:6px;padding:1px 6px}
.empty{padding:24px 18px;opacity:.7}
@media print{:root{--bg:#fff;--panel:#fff;--text:#000}.tile,#theme-toggle{border-color:#999}}
"""

# Minimal bootstrap: render every action as a row on load. Task 2 replaces this with the
# full interactive behaviour (filters, search, accordion, theme). Kept tiny + dependency-free
# so Task 1's output is a valid, data-complete, deterministic document on its own.
_CLIENT_JS = r"""
(function(){
  var DATA = JSON.parse(document.getElementById("drift-data").textContent);
  var body = document.querySelector("#panel tbody");
  function esc(s){var d=document.createElement("div");d.textContent=(s==null?"":String(s));return d.innerHTML;}
  function actionRow(a){
    var tr=document.createElement("tr");tr.className="row";
    var tgt=a.fix_version?(esc(a.current_version)+" → "+esc(a.fix_version)):esc(a.recommendation||"review");
    tr.innerHTML='<td>'+esc(a.repo)+'</td><td>'+esc(a.ref)+'</td><td>'+tgt+
      '</td><td>'+esc(a.finding_count)+'</td><td class="sev-'+esc(a.worst)+'">'+esc(a.worst)+'</td>';
    return tr;
  }
  DATA.actions.forEach(function(a){ body.appendChild(actionRow(a)); });
  document.getElementById("empty").hidden = DATA.actions.length>0;
})();
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q`
Expected: PASS, 12 passed

- [ ] **Step 5: Commit**

```bash
git add agent/lib/dashboard_render.py tests/test_dashboard_render.py
git commit -m "feat(dashboard): renderer — projection, shell, CSS, embedded blob

Pure render_dashboard(inventory, audit, now) -> self-contained HTML. Action-
based tile counts (critical=packages, not advisories), build_actions fallback
for pre-action-model audits, html.escape + <-escaped JSON blob so scan strings
can't inject. Minimal bootstrap JS renders the panel; interactions next."
```

---

## Task 2: the interactive client JS

**Files:**
- Modify: `agent/lib/dashboard_render.py` (replace the `_CLIENT_JS` constant)
- Modify: `tests/test_dashboard_render.py` (append the JS-behaviour tests)

**Interfaces:**
- Consumes: the `#drift-data` projection and DOM hooks from Task 1 (`#panel tbody`, `.tile[data-filter]`, `#search`, `#theme-toggle`, `#empty`).
- Produces: no new Python signatures — only the embedded JS grows. The projection shape is unchanged; if Task 2 needs a field not projected, add it to `_project_action`/`_project_endpoint` and update Task 1's tests.

**Why unit tests here are presence + data-contract, not behaviour:** the JS is a string inside a Python-generated file; pytest cannot click a tile. Tests assert (a) the required handlers/hooks are present in the emitted JS, and (b) the projection carries every field those handlers read. An **optional** node smoke actually executes the JS against the blob when node is available, and **skips** when it is not — matching the repo's opt-in live-smoke pattern.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard_render.py`:

```python
import shutil
import subprocess
import textwrap
import pytest


def test_client_js_wires_every_interaction():
    html = render_dashboard(_inv(), _audit([_cve()]), "2026-07-15")
    js = html.split('<script>')[-1]
    # hooks that genuinely live in the JS (data-filter is an HTML attribute, read as dataset.filter)
    for hook in ("addEventListener", "dataset.filter", "localStorage",
                 "aria-pressed", "theme-toggle", "search"):
        assert hook in js, hook
    # the accordion + copy affordances exist
    assert "navigator.clipboard" in js or "copy" in js.lower()


def test_projection_carries_every_field_the_ui_reads():
    sunset = {"repo": "ebayapi", "ref": "eBay", "kind": "sunset", "version": "v1",
              "severity": "SUNSET", "status": "DEPRECATED", "first_seen": "2026-07-15",
              "detail": "d", "date": "2026-09-30", "recommendation": "migrate before 2026-09-30",
              "source_url": "https://x", "tier": 1, "files": ["src/Ebay/x.php:111"]}
    data = _blob(render_dashboard(_inv(), _audit([sunset, _cve()]), "2026-07-15"))
    a = data["actions"][0]
    for k in ("repo", "ref", "kind", "current_version", "fix_version", "command",
              "recommendation", "worst", "status", "finding_count", "cves", "sources", "files"):
        assert k in a, k
    # endpoint rows carry what the endpoint view needs
    eps_inv = _inv([{"domain": "api.ebay.com", "vendor": "eBay", "version": "v1",
                     "classified": True, "file_count": 1, "files": ["a.php:1"]}])
    ep = _blob(render_dashboard(eps_inv, _audit([_cve()]), "2026-07-15"))["endpoints"][0]
    for k in ("repo", "domain", "vendor", "version", "classified", "file_count", "files"):
        assert k in ep, k


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed (optional JS smoke)")
def test_node_smoke_executes_client_js_and_renders_rows(tmp_path):
    # Actually run the embedded JS in a DOM-less shim to prove it parses the blob and
    # builds the right number of action rows. Skips cleanly when node is absent.
    html = render_dashboard(_inv(), _audit([_cve(ref="npm/a"), _cve(ref="npm/b")]), "2026-07-15")
    js = html.split("<script>")[-1].rsplit("</script>", 1)[0]
    blob = re.search(r'<script id="drift-data"[^>]*>(.*?)</script>', html, re.DOTALL).group(1)
    harness = tmp_path / "run.js"
    harness.write_text(textwrap.dedent(f"""
        // minimal DOM shim: enough for the dashboard JS to render rows and count them
        let rows = 0;
        function el(){{ return {{
            _cls:"", set className(v){{this._cls=v}}, get className(){{return this._cls}},
            set innerHTML(v){{}}, set textContent(v){{this._t=v}}, get innerHTML(){{return this._t||""}},
            appendChild(){{ if(this._id==="tbody-marker") rows++; }}, addEventListener(){{}},
            querySelector(){{ let e=el(); e._id="tbody-marker"; return e; }},
            querySelectorAll(){{ return []; }}, style:{{}}, dataset:{{}}, hidden:false
        }} }};
        const blob = {json.dumps(blob)};
        global.navigator = {{ clipboard:{{ writeText(){{}} }} }};
        global.localStorage = {{ getItem(){{return null}}, setItem(){{}} }};
        global.document = {{
            getElementById(id){{ if(id==="drift-data") return {{textContent: blob.replace(/\\\\u003c/g,"<")}};
                                 let e=el(); return e; }},
            querySelector(){{ let e=el(); e._id="tbody-marker"; return e; }},
            querySelectorAll(){{ return []; }}, createElement(){{ return el(); }},
            documentElement:{{ setAttribute(){{}}, getAttribute(){{return "dark"}} }},
            addEventListener(){{}}
        }};
        {js}
        console.log(rows);
    """))
    out = subprocess.run(["node", str(harness)], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "2"      # two actions -> two rows rendered by the real JS
```

Note: the node smoke's DOM shim is intentionally minimal — it proves the JS parses the blob and appends one row per action. It is not a full DOM; do not grow it to test styling. If the shim proves brittle to write against the final JS, keep it but relax the assertion to `returncode == 0` plus "rows rendered > 0", and record that in the task report — the presence + data-contract tests are the primary guarantee.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q -k "client_js or projection_carries or node_smoke"`
Expected: FAIL — the Task 1 bootstrap JS has no `addEventListener`/`localStorage`/filters.

- [ ] **Step 3: Replace `_CLIENT_JS` with the full interactive behaviour**

In `agent/lib/dashboard_render.py`, replace the `_CLIENT_JS` constant:

```python
_CLIENT_JS = r"""
(function(){
  var DATA = JSON.parse(document.getElementById("drift-data").textContent);
  var body = document.querySelector("#panel tbody");
  var empty = document.getElementById("empty");
  var search = document.getElementById("search");
  var state = { filter: null, mode: "actions", q: "" };

  function esc(s){ var d=document.createElement("div"); d.textContent=(s==null?"":String(s)); return d.innerHTML; }

  // ---- which rows does the current filter/mode select? ----
  function actionsFor(){
    var f = state.filter;
    return DATA.actions.filter(function(a){
      if(f==="critical") return a.worst==="CRITICAL";
      if(f==="fixes")    return a.status==="DEPRECATED";
      if(f==="eol")      return a.kind==="eol";
      if(f==="sunsets")  return a.kind==="sunset";
      return true;
    });
  }
  function endpointsFor(){
    var f = state.filter;
    return DATA.endpoints.filter(function(e){
      if(f==="unknown") return !e.classified;
      return true;   // "apis" -> all endpoints (classified ones carry the vendor)
    });
  }
  function matchesQ(text){ return !state.q || text.toLowerCase().indexOf(state.q)>-1; }

  // ---- row builders (textContent/DOM only — never innerHTML with scan data) ----
  function detailCell(html){ var tr=document.createElement("tr"); var td=document.createElement("td");
    td.colSpan=5; td.className="detail"; td.innerHTML=html; tr.appendChild(td); return tr; }

  function renderActions(list){
    list.forEach(function(a){
      if(!matchesQ((a.repo||"")+" "+(a.ref||""))) return;
      var tr=document.createElement("tr"); tr.className="row";
      var tgt = a.fix_version ? esc(a.current_version)+" → "+esc(a.fix_version)
                              : esc(a.recommendation||"review");
      tr.innerHTML='<td>'+esc(a.repo)+'</td><td>'+esc(a.ref)+'</td><td>'+tgt+
        '</td><td>'+esc(a.finding_count)+'</td><td class="sev-'+esc(a.worst)+'">'+esc(a.worst)+'</td>';
      var open=false, det=null;
      tr.addEventListener("click", function(){
        open=!open;
        if(open){ det=detailCell(actionDetail(a)); tr.after(det);
                  var b=det.querySelector(".copy"); if(b) b.addEventListener("click", function(ev){
                    ev.stopPropagation(); navigator.clipboard && navigator.clipboard.writeText(a.command); });
        } else if(det){ det.remove(); det=null; }
      });
      body.appendChild(tr);
    });
  }
  function actionDetail(a){
    var h="";
    if(a.command){ h+='<div><span class="cmd">'+esc(a.command)+'</span>'
      +'<button class="copy">copy</button></div>'; }
    else if(a.recommendation){ h+='<div>'+esc(a.recommendation)+'</div>'; }
    h+='<div>Clears '+esc(a.finding_count)+' advisor'+(a.finding_count==1?'y':'ies')
      +(a.critical_count?(' ('+esc(a.critical_count)+' critical)'):'')+'</div>';
    if(a.files && a.files.length){ h+='<div>Used at: '+a.files.map(esc).join(", ")+'</div>'; }
    if(a.cves && a.cves.length){ h+='<ul>'+a.cves.map(function(c){
      return '<li>'+esc(c.id)+' — '+esc(c.title)+'</li>'; }).join("")+'</ul>'; }
    if(a.sources && a.sources.length){ h+='<div>'+a.sources.map(function(u){
      return '<a href="'+esc(u)+'" rel="noopener">source ↗</a>'; }).join(" · ")+'</div>'; }
    return h;
  }
  function renderEndpoints(list){
    list.forEach(function(e){
      if(!matchesQ((e.repo||"")+" "+(e.domain||"")+" "+(e.vendor||""))) return;
      var tr=document.createElement("tr"); tr.className="row";
      tr.innerHTML='<td>'+esc(e.repo)+'</td><td>'+esc(e.domain)+'</td><td>'+esc(e.vendor)+
        '</td><td>'+esc(e.version||"?")+'</td><td>'+esc(e.file_count)+'</td>';
      var open=false, det=null;
      tr.addEventListener("click", function(){
        open=!open;
        if(open){ det=detailCell((e.files||[]).map(esc).join("<br>")||"—"); tr.after(det); }
        else if(det){ det.remove(); det=null; }
      });
      body.appendChild(tr);
    });
  }

  function render(){
    body.innerHTML="";
    if(state.mode==="endpoints"){ renderEndpoints(endpointsFor()); }
    else { renderActions(actionsFor()); }
    empty.hidden = body.children.length>0;
  }

  // ---- tiles ----
  Array.prototype.forEach.call(document.querySelectorAll(".tile"), function(t){
    t.setAttribute("aria-pressed","false");
    t.addEventListener("click", function(){
      var f=t.dataset.filter;
      var active = state.filter===f;
      Array.prototype.forEach.call(document.querySelectorAll(".tile"),
        function(x){ x.setAttribute("aria-pressed","false"); });
      if(active){ state.filter=null; state.mode="actions"; }
      else { state.filter=f; state.mode=(f==="apis"||f==="unknown"||f==="sunsets")?
               (f==="sunsets"?"actions":"endpoints"):"actions"; t.setAttribute("aria-pressed","true"); }
      render();
    });
  });

  // ---- search ----
  search.addEventListener("input", function(){ state.q=search.value.toLowerCase(); render(); });

  // ---- theme ----
  var root=document.documentElement;
  var saved=null; try{ saved=localStorage.getItem("drift-theme"); }catch(e){}
  if(saved){ root.setAttribute("data-theme", saved); }
  document.getElementById("theme-toggle").addEventListener("click", function(){
    var next = root.getAttribute("data-theme")==="dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try{ localStorage.setItem("drift-theme", next); }catch(e){}
  });

  render();
})();
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q`
Expected: PASS. The node smoke runs (node present) or skips. If the node shim is brittle, apply the relaxation noted in Step 1 and record it.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/dashboard_render.py tests/test_dashboard_render.py
git commit -m "feat(dashboard): interactive client JS — tiles, search, accordion, theme

Tile filters (sunsets stay in the action view; apis/unknown switch to the
endpoint/call-site view), case-insensitive search, inline-accordion row expand
with copy-command + CVE list + sources, localStorage theme toggle. Scan data
only ever reaches the DOM via textContent/escaped. Optional node smoke executes
the JS against the blob; skips when node is absent."
```

---

## Task 3: wire into the pipeline and the CLI

**Files:**
- Modify: `agent/run.py` (after line 67)
- Modify: `agent/cli.py` (`audit` subparser ~line 256; `_cmd_audit` ~line 72)
- Modify: `tests/test_run_pipeline.py`
- Create/Modify: `tests/test_cli_dashboard.py`

**Interfaces:**
- Consumes: `render_dashboard(inventory, audit, now)` from `agent.lib.dashboard_render`.
- Produces: a `dashboard.html` in the state dir on every `run`; an `--out-html` path on `audit`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_pipeline.py` (the file's helpers `_git_init`, `_empty_engine`, `_fake_eol` already exist):

```python
def test_run_pipeline_writes_dashboard_html(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^7.4"}}'})
    state = tmp_path / "state"
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.eol, "check", _fake_eol)
    run_pipeline(str(root), str(state), "2026-07-15",
                 engine="semgrep", run=_empty_engine, http=lambda *a, **k: {})
    dash = state / "dashboard.html"
    assert dash.exists()
    assert dash.read_text().startswith("<!doctype html>")
    assert '<script id="drift-data"' in dash.read_text()
```

Create `tests/test_cli_dashboard.py`:

```python
import json
from agent import cli


def _inventory(tmp_path):
    p = tmp_path / "inventory.json"
    p.write_text(json.dumps({"generated": "2026-07-15", "repos": [
        {"path": "svc", "endpoints": [], "sdks": [], "runtimes": {}}]}))
    return p


def test_audit_out_html_writes_dashboard(tmp_path, monkeypatch):
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.osv, "query_package", lambda *a, **k: [])
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **k: None)
    inv = _inventory(tmp_path)
    out_html = tmp_path / "dashboard.html"
    rc = cli.main(["audit", "--in", str(inv), "--now", "2026-07-15",
                   "--out-audit", str(tmp_path / "AUDIT.md"), "--out-html", str(out_html)])
    assert rc == 0
    assert out_html.exists() and out_html.read_text().startswith("<!doctype html>")


def test_audit_without_out_html_writes_none(tmp_path, monkeypatch):
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.osv, "query_package", lambda *a, **k: [])
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **k: None)
    inv = _inventory(tmp_path)
    cli.main(["audit", "--in", str(inv), "--now", "2026-07-15",
              "--out-audit", str(tmp_path / "AUDIT.md")])
    assert not (tmp_path / "dashboard.html").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_run_pipeline.py::test_run_pipeline_writes_dashboard_html tests/test_cli_dashboard.py -q`
Expected: FAIL — no dashboard written / `--out-html` unknown argument.

- [ ] **Step 3: Wire `run.py`**

Add the import near the other renderer imports (after line 15):

```python
from agent.lib.dashboard_render import render_dashboard
```

Add the write immediately after the `audit.json` write (after line 67):

```python
    _write(os.path.join(state_dir, "dashboard.html"), render_dashboard(doc, audit, now))
```

- [ ] **Step 4: Wire `cli.py`**

In the `audit` subparser (after the `--out-json` line ~262), add:

```python
    pa.add_argument("--out-html")
```

In `_cmd_audit`, add the import with the others (after line 54):

```python
    from agent.lib.dashboard_render import render_dashboard
```

and the write block after the existing `--out-json` block (after line 80):

```python
    if getattr(args, "out_html", None):
        with open(args.out_html, "w", encoding="utf-8") as fh:
            fh.write(render_dashboard(doc, audit, args.now))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_run_pipeline.py tests/test_cli_dashboard.py -q`
Expected: PASS.

- [ ] **Step 6: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 7: Success-criteria check against the real run** (manual verification, not a unit test)

The real `~/drift-report-2026-07-15/audit.json` predates the action model, so the renderer's `build_actions` fallback applies.

```bash
.venv/bin/python -c "
import json, re
from agent.lib.dashboard_render import render_dashboard
inv = json.load(open('/home/tops/drift-report-2026-07-15/inventory.json'))
audit = json.load(open('/home/tops/drift-report-2026-07-15/audit.json'))
html = render_dashboard(inv, audit, '2026-07-15')
open('/tmp/dashboard.html','w').write(html)
blob = json.loads(re.search(r'<script id=\"drift-data\"[^>]*>(.*?)</script>', html, re.DOTALL).group(1).replace('\\\\u003c','<'))
c = blob['counts']; acts = blob['actions']
urgent = [a for a in acts if a['status']=='DEPRECATED']
print('actions:', len(acts), '| urgent:', len(urgent))
print('tiles:', c)
print('first action:', urgent[0]['repo'].split('/')[-1], urgent[0]['ref'], urgent[0]['fix_version'])
print('bytes:', len(html))
"
```

Expected:
- `actions: 90 | urgent: 50`
- `tiles: {'critical': 3, 'fixes': 50, 'eol': 34, 'sunsets': 0, 'apis': 10, 'unknown': 68, 'reposAffected': 35}`
- `first action: Wav2Lip python/torch 2.10.0`

Open `/tmp/dashboard.html` in a browser with networking off and confirm: tiles show those numbers; clicking **Critical** narrows the panel to 3 rows; clicking a row reveals the `pip install 'torch>=2.10.0'` command; clicking **Unknown hosts** switches the panel to endpoints; the theme toggle flips dark/light and survives a reload. If any tile count differs from the line above, stop and fix before committing.

- [ ] **Step 8: Commit**

```bash
git add agent/run.py agent/cli.py tests/test_run_pipeline.py tests/test_cli_dashboard.py
git commit -m "feat(dashboard): wire into the run pipeline and the audit CLI

run writes dashboard.html alongside AUDIT.md; audit --out-html <path> writes it
on demand (omitting the flag writes nothing). Verified on the real 60-repo run:
90 actions / 50 urgent, tiles 3 crit / 50 fixes / 34 eol / 0 sunsets / 10 apis /
68 unknown, torch first, opens offline from file://."
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `render_dashboard(inventory, audit, now) -> str`, pure | 1 |
| Minimal projection (not raw audit.json) | 1 |
| Action-based tile counts (critical=3 not 10) | 1 |
| `build_actions` fallback for pre-action-model audits | 1 |
| Inline CSS both themes via `data-theme` | 1 |
| `html.escape` + `<`→`<` blob escaping, both surfaces | 1 |
| Determinism, empty-audit, no-CDN | 1 |
| Tile filters (critical/fixes/eol/sunsets/apis/unknown) | 2 |
| Sunsets stay in action view; apis/unknown → endpoint view | 2 |
| Search (repo/pkg/vendor, case-insensitive) | 2 |
| Inline-accordion expand: command+copy, CVEs, sources; sunset files | 2 |
| Theme toggle + localStorage | 2 |
| No `innerHTML` with un-escaped scan data | 2 (esc() helper) |
| `run` writes `dashboard.html` | 3 |
| `audit --out-html` writes it; omit → none | 3 |
| Success check on real data | 3 (Step 7) |

No gaps.

**Placeholder scan:** none — every code step carries complete code; every test step carries the test body; every run step carries the command and expected output.

**Type consistency:** `render_dashboard(inventory, audit, now) -> str` defined in Task 1, consumed unchanged in Task 3. The projection dict keys (`generated, counts, delta, actions, endpoints, coverageNotes`) and the per-action keys (`repo, ref, pkg, kind, current_version, fix_version, command, recommendation, worst, status, finding_count, critical_count, first_seen, cves, sources, files`) are defined in Task 1's `_project_action` and read by Task 2's JS — cross-checked field-by-field against `renderActions`/`actionDetail`/`renderEndpoints`. The DOM hooks (`#drift-data`, `#panel tbody`, `.tile[data-filter]`, `#search`, `#theme-toggle`, `#empty`) are emitted in Task 1's Python and bound in Task 2's JS — cross-checked.

**Known deviation / judgment call:** Task 2's unit tests assert JS *presence* + the *data contract*, not runtime behaviour — because pytest can't run a browser. The optional node smoke (node v24 is present) executes the JS against a minimal DOM shim to prove it renders one row per action; it skips cleanly if node is absent, per the repo's opt-in live-smoke convention. This is the right coverage for JS-in-a-string; the plan says so explicitly rather than pretending the string assertions test behaviour.
