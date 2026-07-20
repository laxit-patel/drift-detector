"""Render a scan into a single self-contained dashboard.html — the interactive cockpit.

Renders ACTIONS (ranked upgrade jobs) + endpoints (the integration/sunset moat) into one
HTML file with inline CSS + vanilla JS + an embedded JSON projection. No server, no CDN, no
build: opens from file://. Pure and deterministic — same (inventory, audit, now) yields
byte-identical output. The caller writes the string to disk.
"""
from __future__ import annotations

import html
import json
import os
import re

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


def _gitlab_hosts() -> set:
    return {h.strip() for h in os.environ.get("DRIFT_GITLAB_HOSTS", "").split(",") if h.strip()}


def _permalink(remote_url, head_sha, loc) -> str | None:
    """Build a GitHub/GitLab blob permalink pinned to head_sha, or None (plain text).
    A self-hosted GitLab host isn't guessable from the URL — it's allow-listed via
    $DRIFT_GITLAB_HOSTS. Unknown host -> None (never a guessed/broken link)."""
    if not remote_url or not head_sha or not loc:
        return None
    path, _, line = str(loc).rpartition(":")
    if not path or not line.isdigit():        # no "path:line" split -> whole loc is the path
        path, line = str(loc), ""
    m = re.match(r"^https://([\w.-]+)/(.+)$", remote_url)
    if not m:
        return None
    host, owner_repo = m.group(1), m.group(2)
    anchor = f"#L{line}" if line else ""
    if host == "github.com":
        return f"https://github.com/{owner_repo}/blob/{head_sha}/{path}{anchor}"
    if host == "gitlab.com" or "gitlab" in host or host in _gitlab_hosts():
        return f"https://{host}/{owner_repo}/-/blob/{head_sha}/{path}{anchor}"
    return None


def _build_projection(inventory: dict, audit: dict) -> dict:
    repo_meta = {r.get("path"): {"remote_url": r.get("remote_url"), "head_sha": r.get("head_sha")}
                 for r in inventory.get("repos", [])}
    actions = [_project_action(a) for a in _actions_of(audit)]
    for a in actions:
        rm = repo_meta.get(a["repo"], {})
        a["files"] = [{"loc": loc, "href": _permalink(rm.get("remote_url"), rm.get("head_sha"), loc)}
                      for loc in a["files"]]
    endpoints = _endpoints_of(inventory)
    cov = inventory.get("coverage") or {}
    residue = cov.get("residue") or {}
    private = []
    for p in cov.get("privateSources", []):
        for pkg in p.get("packages", []):
            private.append({"repo": p.get("repo"), "source": pkg.get("pkg"),
                            "kind": "package", "via": pkg.get("via", "")})
        for url in p.get("repositories", []):
            private.append({"repo": p.get("repo"), "source": url, "kind": "repo", "via": ""})
    counts = {
        "critical": sum(1 for a in actions if a["worst"] == "CRITICAL"),
        "fixes": sum(1 for a in actions if a["status"] == "DEPRECATED"),
        "eol": sum(1 for a in actions if a["kind"] == "eol"),
        "sunsets": sum(1 for a in actions if a["kind"] == "sunset"),
        "apis": len({e["vendor"] for e in endpoints if e["classified"]}),
        "unknown": sum(1 for e in endpoints if not e["classified"]),
        "reposAffected": (audit.get("counts") or {}).get("reposAffected", 0),
        "private": len(private),
    }
    return {
        "generated": audit.get("generated", ""),
        "counts": counts,
        "delta": audit.get("delta"),
        "actions": actions,
        "endpoints": endpoints,
        "private": private,
        "sdkMediated": cov.get("sdkMediated", []),
        "coverageNotes": (audit.get("coverage") or {}).get("notes", []),
        "coverageGrades": residue.get("byRepo", []),
        "residueSamples": residue.get("pathLiterals", []),
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


def render_dashboard(inventory: dict, audit: dict, now: str, *, diff: dict | None = None) -> str:
    projection = _build_projection(inventory, audit)
    if diff is not None:                 # the inventory drift DRIFT.md used to carry
        projection["inventoryDrift"] = diff
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
        ("unknown", "Unknown hosts", c["unknown"]),
        ("private", "Private / unreachable", c["private"])]))
    parts.append("</section>")
    # search + panel
    parts.append('<input class="search" id="search" type="search" '
                 'placeholder="Filter by repo, package or vendor…">')
    parts.append('<table id="panel"><tbody></tbody></table>')
    parts.append('<p id="empty" class="empty" hidden>Nothing found.</p>')
    parts.append('<section id="coverage" class="coverage"></section>')
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
.callsite{padding:2px 0;font-family:ui-monospace,monospace;font-size:12px}
.copy-loc{cursor:pointer;border:1px solid var(--line);background:none;color:var(--text);border-radius:4px;margin-left:6px;font-size:11px}
.empty{padding:24px 18px;opacity:.7}
.coverage{margin:16px 18px;color:var(--muted,#8a8f98);font-size:12px}
.coverage h2{font-size:13px;margin:0 0 6px}
.coverage .note{padding:2px 0}
.intro{color:var(--muted,#8a8f98);font-style:italic;padding:6px 0}
@media print{:root{--bg:#fff;--panel:#fff;--text:#000}.tile,#theme-toggle{border-color:#999}}
"""

# Full interactive behaviour: clickable tile filters, search, inline-accordion row
# drill-down, and a theme toggle. All data is already embedded in the #drift-data JSON
# blob; this reads it and renders client-side. No server, no CDN.
_CLIENT_JS = r"""
(function(){
  var DATA = JSON.parse(document.getElementById("drift-data").textContent);
  var body = document.querySelector("#panel tbody");
  var empty = document.getElementById("empty");
  var search = document.getElementById("search");
  var state = { filter: null, mode: "actions", q: "" };

  function esc(s){ var d=document.createElement("div"); d.textContent=(s==null?"":String(s)); return d.innerHTML; }
  // Attribute-context escaper: esc() is only safe between tags (text nodes). Any value
  // interpolated inside an HTML attribute (e.g. class="...", href="...") must also have
  // quotes escaped, or a scan string like `HIGH" onmouseover="alert(1)` breaks out of the
  // attribute. Use escA for every attribute-context interpolation built from scan data.
  function escA(s){ return esc(s).replace(/"/g,"&quot;").replace(/'/g,"&#39;"); }
  // Scheme allow-list for URLs rendered as a clickable href. escA only escapes HTML
  // metacharacters; it does NOT validate the scheme, so a scan-controlled source_url of
  // `javascript:...` would otherwise render as a clickable link that executes on click.
  // Only http/https URLs become links; anything else falls back to escaped plain text.
  function safeUrl(u){ u = String(u==null?"":u); return /^https?:\/\//i.test(u) ? u : null; }

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
      if(f==="apis")    return e.classified;
      return true;
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
        '</td><td>'+esc(a.finding_count)+'</td><td class="sev-'+escA(a.worst)+'">'+esc(a.worst)+'</td>';
      var open=false, det=null;
      tr.addEventListener("click", function(){
        open=!open;
        if(open){ det=detailCell(actionDetail(a)); tr.after(det);
                  var b=det.querySelector(".copy"); if(b) b.addEventListener("click", function(ev){
                    ev.stopPropagation(); navigator.clipboard && navigator.clipboard.writeText(a.command); });
                  det.querySelectorAll(".copy-loc").forEach(function(b){
                    b.addEventListener("click", function(ev){ ev.stopPropagation();
                      if(navigator.clipboard) navigator.clipboard.writeText(b.getAttribute("data-loc")); });
                  });
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
    if(a.files && a.files.length){
      h+='<div class="usedat"><b>Used at:</b>';
      a.files.forEach(function(f){
        if(f.href){
          var u=safeUrl(f.href);
          h+='<div class="callsite">'+(u? '<a href="'+escA(u)+'" rel="noopener">'+esc(f.loc)+'</a>'
                                        : esc(f.loc))+'</div>';
        } else {
          h+='<div class="callsite">'+esc(f.loc)
            +' <button class="copy-loc" data-loc="'+escA(f.loc)+'">copy</button></div>';
        }
      });
      h+='</div>';
    }
    if(a.cves && a.cves.length){ h+='<ul>'+a.cves.map(function(c){
      return '<li>'+esc(c.id)+' — '+esc(c.title)+'</li>'; }).join("")+'</ul>'; }
    if(a.sources && a.sources.length){ h+='<div>'+a.sources.map(function(u){
      var s = safeUrl(u);
      return s ? '<a href="'+escA(s)+'" rel="noopener">source ↗</a>' : esc(u); }).join(" · ")+'</div>'; }
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

  function privateFor(){
    return (DATA.private||[]).filter(function(p){ return matchesQ((p.repo||"")+" "+(p.source||"")); });
  }
  function renderPrivate(list){
    if(list.length){
      var intro=document.createElement("tr"), itd=document.createElement("td");
      itd.colSpan=5; itd.className="intro";
      itd.textContent="Sub-dependencies the scan couldn't crawl — private or unreachable.";
      intro.appendChild(itd); body.appendChild(intro);
    }
    list.forEach(function(p){
      var tr=document.createElement("tr"); tr.className="row";
      var src=esc(p.source);
      if(p.kind==="repo"){ var u=safeUrl(p.source); if(u){ src='<a href="'+escA(u)+'" rel="noopener">'+esc(p.source)+'</a>'; } }
      tr.innerHTML='<td>'+esc(p.repo)+'</td><td>'+src+'</td><td>'+esc(p.kind)+
        '</td><td>'+esc(p.via||"")+'</td><td></td>';
      body.appendChild(tr);
    });
  }

  function render(){
    body.innerHTML="";
    if(state.mode==="endpoints"){ renderEndpoints(endpointsFor()); }
    else if(state.mode==="private"){ renderPrivate(privateFor()); }
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
      else { state.filter=f;
             state.mode = (f==="apis"||f==="unknown") ? "endpoints"
                        : (f==="private") ? "private"
                        : "actions";
             t.setAttribute("aria-pressed","true"); }
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

  (function(){
    var cov=document.getElementById("coverage"); if(!cov) return;
    var h="";
    (DATA.coverageNotes||[]).forEach(function(n){ h+='<div class="note">'+esc(n)+'</div>'; });
    var grades=(DATA.coverageGrades||[]).filter(function(g){return g.grade!=="HIGH";});
    if(grades.length){
      h+='<div class="note">Coverage — repos where calls may be unattributed:</div><ul>';
      grades.forEach(function(g){ h+='<li>'+esc(g.repo)+': <b>'+esc(g.grade)+'</b> ('
        +esc(g.unattributedPaths)+' path-literals, '+esc(g.unresolvedSinks)+' sinks)</li>'; });
      h+='</ul>';
    }
    var sm=DATA.sdkMediated||[];
    if(sm.length){
      h+='<div class="note">'+esc(sm.length)+' repo(s) use SDK client(s) — calls routed through an '
        +'SDK have no URL literal and aren’t listed as endpoints, so the endpoint count may '
        +'undercount:</div><ul>';
      sm.forEach(function(m){ h+='<li>'+esc(m.repo)+' ('+esc(m.sdkCount)+' SDKs, '
        +esc(m.endpointCount)+' endpoints)</li>'; });
      h+='</ul>';
    }
    cov.innerHTML = h ? ("<h2>Coverage</h2>"+h) : "";
  })();

  render();
})();
"""
