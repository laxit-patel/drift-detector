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
  // Attribute-context escaper: esc() is only safe between tags (text nodes). Any value
  // interpolated inside an HTML attribute (e.g. class="...") must also have quotes escaped,
  // or a scan string like `HIGH" onmouseover="alert(1)` breaks out of the attribute.
  function escA(s){ return esc(s).replace(/"/g,"&quot;").replace(/'/g,"&#39;"); }
  function actionRow(a){
    var tr=document.createElement("tr");tr.className="row";
    var tgt=a.fix_version?(esc(a.current_version)+" → "+esc(a.fix_version)):esc(a.recommendation||"review");
    tr.innerHTML='<td>'+esc(a.repo)+'</td><td>'+esc(a.ref)+'</td><td>'+tgt+
      '</td><td>'+esc(a.finding_count)+'</td><td class="sev-'+escA(a.worst)+'">'+esc(a.worst)+'</td>';
    return tr;
  }
  DATA.actions.forEach(function(a){ body.appendChild(actionRow(a)); });
  document.getElementById("empty").hidden = DATA.actions.length>0;
})();
"""
