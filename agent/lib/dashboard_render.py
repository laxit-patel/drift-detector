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
        "repo": a.get("repo"), "ref": a.get("ref"), "unit": a.get("unit"),
        "date": a.get("date"), "pkg": a.get("pkg"),
        "kind": a.get("kind"), "refKind": a.get("refKind"), "owner": a.get("owner"),
        "current_version": a.get("current_version"),
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


def _repo_label(remote_url, fallback: str) -> str:
    """`https://host/group/repo(.git)` -> `group/repo`, else the fallback (the repo path).
    A display label only — never an identity (that stays the repo path / fingerprint)."""
    m = re.match(r"^https?://[^/]+/(.+?)(?:\.git)?/?$", str(remote_url or ""))
    return m.group(1) if m else fallback


def _permalink(remote_url, head_sha, loc, gitlab_hosts=frozenset()) -> str | None:
    """Build a GitHub/GitLab blob permalink pinned to head_sha, or None (plain text).
    A self-hosted GitLab host isn't guessable from the URL — it's allow-listed. The list comes
    from the drift.yml fleet (its shared host, threaded in as `gitlab_hosts`), plus
    $DRIFT_GITLAB_HOSTS as a fallback/override. Unknown host -> None (never a guessed link)."""
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
    if host == "gitlab.com" or "gitlab" in host or host in (set(gitlab_hosts) | _gitlab_hosts()):
        return f"https://{host}/{owner_repo}/-/blob/{head_sha}/{path}{anchor}"
    return None


def _build_projection(inventory: dict, audit: dict, gitlab_hosts=frozenset()) -> dict:
    repo_meta = {r.get("path"): {"remote_url": r.get("remote_url"), "head_sha": r.get("head_sha")}
                 for r in inventory.get("repos", [])}
    actions = [_project_action(a) for a in _actions_of(audit)]
    for a in actions:
        rm = repo_meta.get(a["repo"], {})
        # display by the clean project path (chetan/amazonspapi), not the internal clone slug
        # (chetan-amazonspapi-f5043548). `repo` stays the stable identity for fingerprints.
        a["repoLabel"] = _repo_label(rm.get("remote_url"), a["repo"])
        a["files"] = [{"loc": loc,
                       "href": _permalink(rm.get("remote_url"), rm.get("head_sha"), loc, gitlab_hosts)}
                      for loc in a["files"]]
    endpoints = _endpoints_of(inventory)
    cov = inventory.get("coverage") or {}
    residue = cov.get("residue") or {}
    private, covered_deps = [], []
    for p in cov.get("privateSources", []):
        for pkg in p.get("packages", []):
            private.append({"repo": p.get("repo"), "source": pkg.get("pkg"),
                            "kind": "package", "via": pkg.get("via", "")})
        for url in p.get("repositories", []):
            private.append({"repo": p.get("repo"), "source": url, "kind": "repo", "via": ""})
        # deps that ARE scanned as their own fleet repo — the dependency edge, NOT a blind
        # spot; surfaced separately so they never inflate the "couldn't crawl" tile/list.
        for url in p.get("covered", []):
            covered_deps.append({"repo": p.get("repo"), "source": url})
    counts = {
        "critical": sum(1 for a in actions if a["worst"] == "CRITICAL"),
        "fixes": sum(1 for a in actions if a["status"] == "DEPRECATED"),
        "eol": sum(1 for a in actions if a["kind"] == "eol"),
        "sunsets": sum(1 for a in actions if a["kind"] == "sunset"),
        # PM ask: a vendor API that is ALREADY retired (past its removal date) is a
        # different, more urgent thing than a CVE "fix" or an upcoming deadline — an
        # integration that is broken NOW, not one to plan around. Its own count.
        # A sunset is DEPRECATED only when its date is in the PAST (status_for gives future
        # dates REVIEW), so `DEPRECATED and date` is exactly "retired, date known" — and it
        # recomputes from the action alone, so verify needs no `now`. A deprecated-no-date
        # sunset is deliberately excluded: no announced deadline means not yet past-due.
        "pastDue": sum(1 for a in actions
                       if a["kind"] == "sunset" and a["status"] == "DEPRECATED"
                       and a.get("date")),
        "apis": len({e["vendor"] for e in endpoints if e["classified"]}),
        "unknown": sum(1 for e in endpoints if not e["classified"]),
        "reposAffected": (audit.get("counts") or {}).get("reposAffected", 0),
        # "1 repos" read as "it only scanned one". Both numbers, or neither.
        "reposScanned": (inventory.get("scope") or {}).get("reposScanned", 0),
        "private": len(private),
        # sources you ASKED to scan that could not be read (URL 404/no-access, a typo, a
        # plain folder with no code). "cannot see" is NOT "clean" — this count exists so the
        # report can never render green over a repo it silently failed to open.
        "unscannable": len(cov.get("rootsUnscannable", [])),
        # vendors we CALL but whose retirement list nobody has checked. Counted as
        # unaudited+stale, because both mean "0 findings here is not evidence of clean".
        "unaudited": sum(1 for r in (audit.get("coverage") or {}).get("catalog", [])
                         if r.get("verdict") != "CURRENT"),
        # the two delivery streams, tallied from the actions' owner field. devops =
        # packages + runtimes; developer = API sunsets + frameworks. verify checks these
        # sum back to the fixes/review totals so the two queues can't silently miscount.
        "byOwner": {
            o: {"fixes": sum(1 for a in actions
                             if a.get("owner") == o and a["status"] == "DEPRECATED"),
                "review": sum(1 for a in actions
                              if a.get("owner") == o and a["status"] == "REVIEW")}
            for o in ("devops", "developer")},
    }
    return {
        # the payload IS drift.json; it names its own contract so any consumer — the
        # Markdown renderer, an agent, an external validator — can check the version
        # it is reading against docs/schema/
        "schemaVersion": "drift/v1",
        "generated": audit.get("generated", ""),
        "counts": counts,
        "delta": audit.get("delta"),
        "actions": actions,
        "endpoints": endpoints,
        "private": private,
        "coveredDeps": covered_deps,
        "sdkMediated": cov.get("sdkMediated", []),
        "catalog": (audit.get("coverage") or {}).get("catalog", []),
        "coverageNotes": (audit.get("coverage") or {}).get("notes", []),
        "coverageGrades": [dict(g, repoLabel=_repo_label(
            repo_meta.get(g.get("repo"), {}).get("remote_url"), g.get("repo")))
            for g in residue.get("byRepo", [])],
        "shapes": cov.get("shapes", []),
        "residueSamples": residue.get("pathLiterals", []),
        # the roots the scanner could not open, carried verbatim from inventory coverage so
        # every projection (drift.md, the dashboard) can surface them and verify can enforce
        # that they are surfaced. Each: {root, reason}.
        "rootsUnscannable": cov.get("rootsUnscannable", []),
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


def build_payload(inventory: dict, audit: dict, *, diff: dict | None = None,
                  gitlab_hosts=frozenset()) -> dict:
    """The dashboard's DATA — everything the page displays, before any HTML exists.

    This is the contract. `drift.json` is this dict and the page embeds this same
    dict, so what a test asserts on is what a reader sees. Rendered HTML cannot be
    verified by anything that does not have eyes: two bugs shipped this week — a tile
    reading `Sunsets 1` over twelve findings, then twelve rows all labelled "eBay" —
    both passed their unit tests because the tests ran a layer below the artifact.
    """
    projection = _build_projection(inventory, audit, gitlab_hosts)
    if diff is not None:                 # the inventory drift DRIFT.md used to carry
        projection["inventoryDrift"] = diff
    return projection


def _empty_bundle() -> dict:
    return {"sbom": {"bomFormat": "CycloneDX", "components": [], "vulnerabilities": []},
            "spdx": {"spdxVersion": "SPDX-2.3", "packages": []},
            "sarif": {"version": "2.1.0",
                      "runs": [{"tool": {"driver": {"rules": []}}, "results": []}]}}


def build_bundle(inventory: dict, audit: dict, now: str) -> dict:
    """The standard-format side-payloads the dashboard embeds, built from the SAME
    inventory/audit so the embedded copies are byte-for-byte what `drift-scan sbom`/`sarif`
    would write. run.py and render_dashboard both go through here."""
    from agent.lib import sbom as _sbom, spdx as _spdx, sarif as _sarif
    return {"sbom": _sbom.build_sbom(inventory, audit, now),
            "spdx": _spdx.build_spdx(inventory, now),
            "sarif": _sarif.build_sarif(audit)}


def render_dashboard(inventory: dict, audit: dict, now: str, *, diff: dict | None = None,
                     gitlab_hosts=frozenset()) -> str:
    """The cockpit: the drift report + the SBOM (CycloneDX/SPDX) + SARIF, one self-contained file."""
    payload = build_payload(inventory, audit, diff=diff, gitlab_hosts=gitlab_hosts)
    return render_payload(payload, now, bundle=build_bundle(inventory, audit, now))


def _blob_script(el_id: str, obj) -> str:
    """An embedded JSON blob, `<`-escaped so a scan string containing </script> can't close
    the element (the same hardening as _blob)."""
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c")
    return f'<script id="{el_id}" type="application/json">{raw}</script>'


def render_payload(projection: dict, now: str, *, bundle: dict | None = None) -> str:
    bundle = bundle or _empty_bundle()
    c = projection["counts"]
    d = projection.get("delta") or {}
    new_n = len(build_actions(d["new"])) if d.get("new") else 0
    resolved_n = len(d.get("resolved", []))
    delta_txt = (f" · ↓{resolved_n} resolved ↑{new_n} new this week"
                 if projection.get("delta") is not None else "")

    bo = c.get("byOwner") or {}
    _own = lambda o: (bo.get(o) or {}).get("fixes", 0) + (bo.get(o) or {}).get("review", 0)

    p = []
    p.append("<!doctype html>")
    p.append('<html lang="en">')
    p.append('<head><meta charset="utf-8">')
    p.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    p.append(f"<title>Drift Detector — DevSecOps Cockpit · {_e(now)}</title>")
    p.append("<style>" + _CSS + "</style></head><body>")

    # ---- pinned top: brand · headline · tiles · top tabs ----
    p.append('<div class="sticky">')
    p.append('<div class="brand"><span class="mark" aria-hidden="true"></span>'
             '<h1>Drift Detector</h1><span class="sub">DevSecOps Cockpit</span>'
             f'<span class="meta">{c["reposScanned"]} repos · {_e(now)}</span>'
             '<span class="spacer"></span>'
             '<span class="caps" title="Supply-chain coverage in one pass">'
             '<span class="cap hot">SBOM</span><span class="cap hot">SCA</span>'
             '<span class="cap hot">VEX</span><span class="cap hot">SARIF</span>'
             '<span class="cap">CVE · EOL · sunsets</span></span>'
             '<select id="repo-filter" class="repopick" aria-label="Scope the report to one repo" '
             'title="Scope the whole report — Summary, SBOM and SARIF — to one repo">'
             '<option value="">All repos</option></select>'
             '<button class="themebtn" id="theme">◐ Theme: auto</button></div>')
    p.append(f'<p class="headline"><span class="dot">●</span> '
             f'<span class="big">{c["fixes"]} fixes needed</span> · '
             f'{c["reposAffected"]} of {c["reposScanned"]} repos affected{_e(delta_txt)}</p>')
    p.append('<div class="tilegroups">')
    p.append(_tile_group("Ownership", [
        ("devops", "DevOps", _own("devops"), ""),
        ("developer", "Developer", _own("developer"), "")]))
    p.append(_tile_group("Security", [
        ("critical", "Critical", c["critical"], "crit"),
        ("fixes", "Fixes", c["fixes"], ""),
        ("eol", "EOL", c["eol"], "")]))
    p.append(_tile_group("Integrations", [
        ("apis", "APIs", c["apis"], ""),
        ("sunsets", "Sunsets", c["sunsets"], ""),
        ("pastdue", "Past-due", c["pastDue"], "warn"),
        ("unknown", "Unknown", c["unknown"], ""),
        ("private", "Private", c["private"], ""),
        ("unaudited", "Unaudited", c["unaudited"], "")]))
    p.append("</div>")
    # top tabs (the global repo scope now lives in the header — #repo-filter, top-right)
    p.append('<div class="tabbar tabgroup" data-panels="main" role="tablist">'
             '<button class="tab active" data-tab="p-summary" role="tab">Summary</button>'
             '<button class="tab" data-tab="p-sbom" role="tab">SBOM</button>'
             '<button class="tab" data-tab="p-sarif" role="tab">SARIF</button></div>')
    p.append("</div>")   # /sticky

    p.append('<div id="main">')

    # ---- Summary (the existing data engine renders here) ----
    p.append('<section id="p-summary" class="panel active">'
             '<div class="subbar tabgroup" data-panels="sub-summary">'
             '<button class="tab active" data-tab="s-sum-prev">Preview</button>'
             '<button class="tab" data-tab="s-sum-json">JSON · drift.json</button></div>'
             '<div class="panels" id="sub-summary">')
    p.append('<div id="s-sum-prev" class="panel active">'
             '<div class="toolbar"><input class="search" id="search" type="search" '
             'placeholder="Filter by repo, package or vendor…"></div>'
             '<table id="panel"><tbody></tbody></table>'
             '<p id="empty" class="empty" hidden>Nothing found.</p></div>')
    p.append('<div id="s-sum-json" class="panel"><p class="jsonhint">View / copy — the '
             'canonical <code>drift.json</code> every surface projects from (read-only; the '
             'verified source of truth).</p><pre id="json-drift"></pre></div>')
    p.append("</div></section>")

    # ---- SBOM ----
    p.append('<section id="p-sbom" class="panel">'
             '<div class="subbar tabgroup" data-panels="sub-sbom">'
             '<button class="tab active" data-tab="s-sbom-prev">Preview</button>'
             '<button class="tab" data-tab="s-sbom-cdx">CycloneDX</button>'
             '<button class="tab" data-tab="s-sbom-spdx">SPDX</button></div>'
             '<div class="panels" id="sub-sbom">')
    p.append('<div id="s-sbom-prev" class="panel active"><h3 id="sbom-h"></h3>'
             '<table id="sbom-table"><thead><tr><th>Type</th><th>Component</th><th>Version</th>'
             '<th>Used in</th><th>Vulns</th></tr></thead><tbody></tbody></table></div>')
    p.append('<div id="s-sbom-cdx" class="panel">'
             '<p class="jsonhint">CycloneDX 1.5 (<code>sbom.json</code>) → Dependency-Track, '
             'GitHub · <a class="viewbtn" href="https://apps.rancher.io/sbom-viewer" '
             'target="_blank" rel="noopener">Open in Rancher SBOM viewer ↗</a></p>'
             '<pre id="json-cdx"></pre></div>')
    p.append('<div id="s-sbom-spdx" class="panel">'
             '<p class="jsonhint">SPDX 2.3 (<code>sbom.spdx.json</code>) '
             '· <a class="viewbtn" href="https://apps.rancher.io/sbom-viewer" '
             'target="_blank" rel="noopener">Open in Rancher SBOM viewer ↗</a></p>'
             '<pre id="json-spdx"></pre></div>')
    p.append("</div></section>")

    # ---- SARIF ----
    p.append('<section id="p-sarif" class="panel">'
             '<div class="subbar tabgroup" data-panels="sub-sarif">'
             '<button class="tab active" data-tab="s-sarif-prev">Preview</button>'
             '<button class="tab" data-tab="s-sarif-json">JSON · sarif.json</button></div>'
             '<div class="panels" id="sub-sarif">')
    p.append('<div id="s-sarif-prev" class="panel active"><h3 id="sarif-h"></h3>'
             '<div id="sarif-groups"></div></div>')
    p.append('<div id="s-sarif-json" class="panel">'
             '<p class="jsonhint">SARIF 2.1.0 (<code>drift.sarif.json</code>) — file:line '
             'results → GitHub code scanning, VS Code · <a class="viewbtn" '
             'href="https://microsoft.github.io/sarif-web-component/" target="_blank" '
             'rel="noopener">Open in SARIF web viewer ↗</a></p>'
             '<pre id="json-sarif"></pre></div>')
    p.append("</div></section>")

    p.append("</div>")   # /main

    # ---- page footer: scan META, out of the data plane (coverage caveats, what changed,
    # methodology) — the honest "how complete was this scan" context, not the findings ----
    p.append('<footer class="pagefoot">'
             '<section id="coverage" class="coverage"></section>'
             '<section id="drift" class="coverage"></section>'
             '<section id="methodology" class="coverage"></section></footer>')

    # native <dialog> detail (opened from a Summary row)
    p.append('<dialog id="detail"><div class="dh"><span id="dlg-sev"></span>'
             '<b id="dlg-title"></b><button class="x" data-close>×</button></div>'
             '<div class="db" id="dlg-body"></div></dialog>')

    # data blobs + behaviour
    p.append('<script id="drift-data" type="application/json">' + _blob(projection) + "</script>")
    p.append(_blob_script("sbom-data", bundle["sbom"]))
    p.append(_blob_script("spdx-data", bundle["spdx"]))
    p.append(_blob_script("sarif-data", bundle["sarif"]))
    p.append("<script>" + _CLIENT_JS + "</script>")
    p.append("</body></html>")
    return "\n".join(p)


def _tile_group(title: str, tiles) -> str:
    cells = "".join(
        f'<button class="tile" data-filter="{key}"'
        + (f' data-sev="{sev}"' if sev else "") + '>'
        + (f'<span class="n" data-hot>{n}</span>' if sev == "crit"
           else f'<span class="n">{n}</span>')
        + f'<span class="t">{_e(label)}</span></button>'
        for key, label, n, sev in tiles)
    return (f'<div class="tg"><span class="lbl">{_e(title)}</span>'
            f'<div class="tiles">{cells}</div></div>')


_CSS = """
:root{
  /* dark is the DEFAULT — light-dark() resolves to the dark value unless the theme toggle
     sets color-scheme:light (or auto → light dark, following the OS). No first-paint flash. */
  color-scheme:dark;
  --accent:#e0533d; --accent-2:#3d7de0;
  --bg:light-dark(#f5f5f2,#0f1114); --panel:light-dark(#fff,#16191e);
  --panel-2:light-dark(#efefEA,#1b1f26); --line:light-dark(#e4e4de,#2a2f38);
  --ink:light-dark(#191b1f,#e8ebf1); --muted:light-dark(#6a7180,#98a1b1);
  --crit:#e0533d; --high:#e08a3d; --med:#cdb63a; --low:#5f9e6a; --info:#3d7de0; --sun:#b06ee0;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace; --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; --r:12px;
}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.5;
  -webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums;padding:0 20px 60px;
  max-width:1240px;margin:0 auto;container-type:inline-size}
code,.mono{font-family:var(--mono);font-size:.86em}
a{color:var(--accent-2);text-decoration:none} a:hover{text-decoration:underline}

.sticky{position:sticky;top:0;z-index:20;background:color-mix(in oklab,var(--bg) 88%,transparent);
  backdrop-filter:blur(8px);padding-top:12px}
.brand{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.brand .mark{width:26px;height:26px;border-radius:8px;
  background:radial-gradient(120% 120% at 30% 20%,color-mix(in oklab,var(--accent) 70%,#fff),var(--accent) 55%,color-mix(in oklab,var(--accent) 60%,#000));
  box-shadow:0 0 0 1px color-mix(in oklab,var(--accent) 40%,transparent),0 4px 14px color-mix(in oklab,var(--accent) 35%,transparent)}
.brand h1{font-size:16px;font-weight:650;letter-spacing:-.01em}
.brand .sub{font-size:10.5px;font-weight:650;letter-spacing:.04em;text-transform:uppercase;color:var(--accent);
  border:1px solid color-mix(in oklab,var(--accent) 45%,var(--line));border-radius:20px;padding:2px 9px}
.brand .meta{color:var(--muted);font-size:12.5px} .spacer{flex:1}
.caps{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-right:8px}
.cap{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:2px 7px;background:var(--panel)}
.cap.hot{color:var(--accent);border-color:color-mix(in oklab,var(--accent) 40%,var(--line))}
@container (max-width:720px){.caps{display:none}}
.themebtn{appearance:none;background:var(--panel);border:1px solid var(--line);color:var(--muted);
  border-radius:20px;padding:5px 12px;font:inherit;font-size:12px;cursor:pointer}
.themebtn:hover{color:var(--ink);border-color:var(--accent-2)}
.headline{font-size:15px;text-wrap:balance;margin:10px 0} .headline .big{font-weight:680} .dot{color:var(--crit)}
/* the three groups spread edge-to-edge across the full width instead of clustering left */
.tilegroups{display:flex;justify-content:space-between;gap:10px 22px;flex-wrap:wrap;padding-bottom:11px;border-bottom:1px solid var(--line)}
.tg{display:flex;flex-direction:column;gap:6px}
.tg .lbl{font-size:10px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
.tiles{display:flex;gap:6px;flex-wrap:wrap}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:6px 11px;min-width:66px;
  display:flex;flex-direction:column;gap:0;cursor:pointer;color:var(--ink);transition:border-color .15s,transform .1s}
.tile:hover{border-color:color-mix(in oklab,var(--accent-2) 60%,var(--line));transform:translateY(-1px)}
.tile .n{font-size:18px;font-weight:670;line-height:1.15} .tile .t{font-size:10.5px;color:var(--muted)}
.tile[data-sev=crit] .n{color:var(--crit)} .tile[data-sev=warn] .n{color:var(--high)}
.tile[aria-pressed=true]{outline:2px solid var(--accent-2);outline-offset:-1px}
.tile:has(.n[data-hot]){background:color-mix(in oklab,var(--crit) 8%,var(--panel));border-color:color-mix(in oklab,var(--crit) 30%,var(--line))}
@container (max-width:760px){.tilegroups{justify-content:flex-start}}
@container (max-width:640px){.tilegroups{gap:12px}.tile{min-width:60px;padding:6px 9px}}

.tabbar{display:flex;gap:2px;margin-top:14px;border-bottom:1px solid var(--line)}
.tab{appearance:none;background:none;border:0;color:var(--muted);font:inherit;font-weight:550;padding:10px 16px;cursor:pointer;position:relative}
.tab:hover{color:var(--ink)} .tab.active{color:var(--ink)}
.tab.active::after{content:"";position:absolute;left:10px;right:10px;bottom:-1px;height:2px;border-radius:2px;background:var(--accent)}
.subbar{display:flex;gap:2px;background:var(--panel);border:1px solid var(--line);border-bottom:0;border-radius:var(--r) var(--r) 0 0;padding:8px 8px 0}
.subbar .tab{padding:6px 13px;font-size:12.5px} .subbar .tab.active::after{background:var(--accent-2)}
.panels{background:var(--panel);border:1px solid var(--line);border-top:0;border-radius:0 0 var(--r) var(--r);padding:18px}
.panel{display:none;animation:fade .18s ease} .panel.active{display:block}
@keyframes fade{from{opacity:0;transform:translateY(2px)}to{opacity:1}}

h3{font-size:13.5px;font-weight:620;margin-bottom:12px}
/* the global repo scope, top-right in the header chip row (next to Theme) */
.repopick{appearance:none;background:var(--panel);border:1px solid var(--line);color:var(--ink);
  border-radius:20px;padding:5px 26px 5px 12px;font:inherit;font-size:12px;cursor:pointer;max-width:200px;
  background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);
  background-position:right 12px center,right 7px center;background-size:5px 5px,5px 5px;background-repeat:no-repeat}
.repopick:hover{color:var(--ink);border-color:var(--accent-2)}
.repopick:focus{outline:2px solid var(--accent-2);outline-offset:1px}
.repopick[data-scoped]{border-color:color-mix(in oklab,var(--accent) 55%,var(--line));color:var(--accent)}
.toolbar{display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
.search{flex:1;min-width:200px;background:var(--panel-2);border:1px solid var(--line);color:var(--ink);border-radius:9px;padding:7px 12px;font:inherit;accent-color:var(--accent)}
.search::placeholder{color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:13px}
thead th{position:sticky;top:0;background:var(--panel);text-align:left;color:var(--muted);font-weight:550;font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:8px 12px;border-bottom:1px solid var(--line)}
td{padding:9px 12px;border-bottom:1px solid color-mix(in oklab,var(--line) 60%,transparent);vertical-align:top}
#panel tr.row{cursor:pointer;transition:background .12s} #panel tr.row:hover{background:color-mix(in oklab,var(--accent-2) 6%,transparent)}
#sbom-table tbody tr:has(.pill.crit){box-shadow:inset 3px 0 0 var(--crit)}
#sbom-table tbody tr:has(.pill.high){box-shadow:inset 3px 0 0 var(--high)}
.big tbody tr{content-visibility:auto;contain-intrinsic-size:0 42px}
.sev-CRITICAL{color:var(--crit);font-weight:700} .sev-HIGH{color:var(--high)}
.sev-EOL,.sev-SUNSET{color:var(--sun)}
.detail{background:var(--panel-2);border-left:3px solid var(--accent-2)} .detail td{padding:10px 14px}
.cmd{font-family:var(--mono);background:var(--bg);padding:6px 8px;border-radius:5px;color:var(--accent-2);display:inline-block}
.copy,.copy-loc{cursor:pointer;border:1px solid var(--line);background:none;color:var(--muted);border-radius:5px;margin-left:6px;padding:1px 7px;font-size:11px}
.copy:hover,.copy-loc:hover{color:var(--ink)}
.callsite{padding:2px 0;font-family:var(--mono);font-size:12px}
.empty{padding:24px 6px;color:var(--muted)}
.pagefoot{margin-top:26px;padding-top:8px;border-top:1px solid var(--line)}
.pagefoot .coverage:first-child{margin-top:10px}
.coverage{margin-top:18px;color:var(--muted);font-size:12.5px} .coverage h2{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;color:var(--muted)}
.coverage .note{padding:3px 0} .coverage ul{margin:4px 0 10px 18px} .intro{color:var(--muted);font-style:italic;padding:6px 0}

.pill{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap}
.pill::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.pill.crit{color:var(--crit);background:color-mix(in oklab,var(--crit) 15%,transparent)}
.pill.high{color:var(--high);background:color-mix(in oklab,var(--high) 15%,transparent)}
.pill.med{color:var(--med);background:color-mix(in oklab,var(--med) 15%,transparent)}
.pill.low{color:var(--low);background:color-mix(in oklab,var(--low) 15%,transparent)}
.pill.sun{color:var(--sun);background:color-mix(in oklab,var(--sun) 15%,transparent)}
.pill.eol{color:var(--info);background:color-mix(in oklab,var(--info) 15%,transparent)}
details.grp{border:1px solid var(--line);border-radius:10px;margin-bottom:8px;overflow:clip}
details.grp>summary{cursor:pointer;padding:10px 14px;font-weight:600;list-style:none;display:flex;align-items:center;gap:10px;background:var(--panel-2)}
details.grp>summary::-webkit-details-marker{display:none}
details.grp>summary::before{content:"▸";color:var(--muted);transition:transform .15s}
details.grp[open]>summary::before{transform:rotate(90deg)}
.count{margin-left:auto;color:var(--muted);font-size:12px;background:var(--bg);border:1px solid var(--line);border-radius:20px;padding:1px 9px}
.jsonhint{color:var(--muted);font-size:12px;margin-bottom:8px}
.viewbtn{display:inline-block;border:1px solid color-mix(in oklab,var(--accent-2) 45%,var(--line));color:var(--accent-2);border-radius:20px;padding:2px 10px;font-size:11.5px;text-decoration:none}
.viewbtn:hover{background:color-mix(in oklab,var(--accent-2) 12%,transparent);text-decoration:none}
.jsonwrap{position:relative}
pre{background:light-dark(#f7f7f4,#0c0e12);border:1px solid var(--line);border-radius:10px;padding:14px;overflow:auto;font-family:var(--mono);font-size:12px;line-height:1.6;color:light-dark(#333,#c8d0dc);max-height:460px}
.copybtn{position:absolute;top:8px;right:8px;background:var(--panel-2);border:1px solid var(--line);color:var(--muted);font:inherit;font-size:11.5px;padding:4px 11px;border-radius:7px;cursor:pointer}
.copybtn:hover{color:var(--ink);border-color:var(--accent-2)}
dialog{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:14px;padding:0;max-width:520px;width:92vw}
dialog::backdrop{background:color-mix(in oklab,#000 55%,transparent);backdrop-filter:blur(2px)}
dialog .dh{padding:16px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px}
dialog .db{padding:16px 18px} dialog .x{margin-left:auto;background:none;border:0;color:var(--muted);font-size:18px;cursor:pointer}
.kv{display:grid;grid-template-columns:96px 1fr;gap:5px 12px;font-size:13px} .kv b{color:var(--muted);font-weight:500}
@media print{.themebtn,.tab{display:none}}
"""

# Full interactive behaviour: clickable tile filters, search, inline-accordion row
# drill-down, and a theme toggle. All data is already embedded in the #drift-data JSON
# blob; this reads it and renders client-side. No server, no CDN.
_CLIENT_JS = r"""
(function(){
  var DATA = JSON.parse(document.getElementById("drift-data").textContent);
  function blob(id){ var el=document.getElementById(id); try{ return el?JSON.parse(el.textContent):{}; }catch(e){ return {}; } }
  var SBOM = blob("sbom-data"), SPDX = blob("spdx-data"), SARIF = blob("sarif-data");
  var body = document.querySelector("#panel tbody");
  var empty = document.getElementById("empty");
  var search = document.getElementById("search");
  var state = { filter: null, mode: "actions", q: "", repo: "" };
  // the global repo scope (the #repo-filter select). "" = all repos. Applies to Summary,
  // SBOM and SARIF; the repo KEY is the inventory path (a.repo / drift:repo / the SARIF uri
  // prefix), while the dropdown shows the clean repoLabel.
  function matchesRepo(repo){ return !state.repo || repo === state.repo; }

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
      if(f==="devops")   return a.owner==="devops";      // the two delivery streams
      if(f==="developer")return a.owner==="developer";
      if(f==="sunsets")  return a.kind==="sunset";
      // "Past-due" = a sunset already retired (DEPRECATED with a passed date) — an
      // integration broken NOW, distinct from an upcoming deadline or a CVE fix.
      if(f==="pastdue")  return a.kind==="sunset" && a.status==="DEPRECATED" && a.date;
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
      // the retiring operation is part of the identity, so it must be searchable too —
      // a PM filtering for "GetCategoryFeatures" has to land on its row
      var label = a.ref + (a.unit ? " " + a.unit : "");
      if(!matchesRepo(a.repo)) return;                    // global repo scope
      if(!matchesQ((a.repoLabel||a.repo||"")+" "+label)) return;
      var tr=document.createElement("tr"); tr.className="row";
      var tgt = a.fix_version ? esc(a.current_version)+" → "+esc(a.fix_version)
                              : esc(a.recommendation||"review");
      tr.innerHTML='<td>'+esc(a.repoLabel||a.repo)+'</td><td>'+esc(label)+'</td><td>'+tgt+
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
        var link = esc(f.loc);
        if(f.href){                                 // a live permalink -> open the code in a NEW tab
          var u=safeUrl(f.href);
          if(u) link='<a href="'+escA(u)+'" target="_blank" rel="noopener">'+esc(f.loc)+'</a>';
        }
        // the copy button stays ALONGSIDE the link — a link jumps to the code, copy grabs
        // the path:line for a ticket/commit message
        h+='<div class="callsite">'+link
          +' <button class="copy-loc" data-loc="'+escA(f.loc)+'">copy</button></div>';
      });
      h+='</div>';
    }
    if(a.cves && a.cves.length){ h+='<ul>'+a.cves.map(function(c){
      return '<li>'+esc(c.id)+' — '+esc(c.title)+'</li>'; }).join("")+'</ul>'; }
    if(a.sources && a.sources.length){ h+='<div>'+a.sources.map(function(u){
      var s = safeUrl(u);
      return s ? '<a href="'+escA(s)+'" target="_blank" rel="noopener">source ↗</a>' : esc(u); }).join(" · ")+'</div>'; }
    return h;
  }
  function renderEndpoints(list){
    list.forEach(function(e){
      if(!matchesRepo(e.repo)) return;                    // global repo scope (APIs/Unknown tiles)
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
    return (DATA.private||[]).filter(function(p){
      return matchesRepo(p.repo) && matchesQ((p.repo||"")+" "+(p.source||"")); });   // Private tile honours the repo scope
  }
  function catalogFor(){
    return (DATA.catalog||[]).filter(function(cv){
      return cv.verdict!=="CURRENT" && matchesQ((cv.vendor||"")+" "+(cv.verdict||"")); });
  }
  function renderCatalog(list){
    if(list.length){
      var intro=document.createElement("tr"), itd=document.createElement("td");
      itd.colSpan=5; itd.className="intro";
      itd.textContent="Vendors this code calls whose retirement list nobody has checked. "+
        "Zero findings for these is UNAUDITED, not clean.";
      intro.appendChild(itd); body.appendChild(intro);
    }
    list.forEach(function(cv){
      var tr=document.createElement("tr"); tr.className="row";
      var why = cv.verdict==="UNAUDITED"
        ? (cv.catalogEntries ? cv.catalogEntries+" catalog entr(y/ies), but the vendor's page has never been reconciled"
                            : "no catalog entries at all")
        : "last checked "+esc(cv.checked||"?")+" — re-check the vendor's page";
      tr.innerHTML='<td>'+esc(cv.vendor)+'</td><td>'+why+'</td><td>'+
        esc(cv.callSites)+' call-site(s)</td><td>'+esc(cv.catalogEntries)+' entr(y/ies)</td>'+
        '<td class="sev-'+escA(cv.verdict)+'">'+esc(cv.verdict)+'</td>';
      body.appendChild(tr);
    });
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
    else if(state.mode==="catalog"){ renderCatalog(catalogFor()); }
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
                        : (f==="unaudited") ? "catalog"
                        : "actions";
             t.setAttribute("aria-pressed","true"); }
      activate("p-summary"); activate("s-sum-prev");   // a tile always drills into Summary
      render();
    });
  });

  // ---- search ----
  search.addEventListener("input", function(){ state.q=search.value.toLowerCase(); render(); });

  // ---- theme: cycle auto → light → dark, driving light-dark() via color-scheme ----
  var root=document.documentElement, tbtn=document.getElementById("theme");
  var modes=["auto","light","dark"], ti=2;   // default: dark (index 2); a saved choice wins
  try{ var s=localStorage.getItem("drift-theme"); if(s){ ti=Math.max(0,modes.indexOf(s)); } }catch(e){}
  function applyTheme(){ var m=modes[ti]; if(root.style) root.style.colorScheme = m==="auto" ? "light dark" : m;
    if(tbtn) tbtn.textContent=(m==="dark"?"●":m==="light"?"○":"◐")+" Theme: "+m;
    try{ localStorage.setItem("drift-theme", m); }catch(e){} }
  if(tbtn){ tbtn.addEventListener("click", function(){ ti=(ti+1)%3; applyTheme(); }); applyTheme(); }

  // ---- two-level tab controller (+ activate(id) for tile → Summary jumps) ----
  function activate(panelId){
    var panel=document.getElementById(panelId); if(!panel) return;
    var group=panel.parentElement.previousElementSibling;
    var btn=group && group.querySelector('[data-tab="'+panelId+'"]'); if(!btn) return;
    group.querySelectorAll('[data-tab]').forEach(function(b){ b.classList.toggle("active", b===btn); });
    Array.prototype.forEach.call(panel.parentElement.children, function(pn){
      if(pn.classList.contains("panel")) pn.classList.toggle("active", pn===panel);
    });
  }
  document.querySelectorAll(".tabgroup").forEach(function(g){
    var panels=document.getElementById(g.dataset.panels);
    g.addEventListener("click", function(e){ var b=e.target.closest("[data-tab]"); if(!b) return;
      g.querySelectorAll("[data-tab]").forEach(function(x){ x.classList.toggle("active", x===b); });
      Array.prototype.forEach.call(panels.children, function(pn){
        if(pn.classList.contains("panel")) pn.classList.toggle("active", pn.id===b.dataset.tab); });
    });
  });

  // ---- JSON views (view/copy only — the embedded blobs are the verified source) ----
  function jsonInto(id, obj){ var el=document.getElementById(id); if(el) el.textContent=JSON.stringify(obj,null,2); }
  jsonInto("json-drift", DATA);
  jsonInto("json-cdx", SBOM); jsonInto("json-spdx", SPDX); jsonInto("json-sarif", SARIF);
  document.querySelectorAll("pre").forEach(function(pre){
    var wrap=document.createElement("div"); wrap.className="jsonwrap";
    pre.parentNode.insertBefore(wrap,pre); wrap.appendChild(pre);
    var b=document.createElement("button"); b.className="copybtn"; b.textContent="Copy";
    b.addEventListener("click",function(){ var done=function(){b.textContent="Copied";setTimeout(function(){b.textContent="Copy";},1200);};
      navigator.clipboard ? navigator.clipboard.writeText(pre.textContent).then(done,done) : done(); });
    wrap.insertBefore(b,pre);
  });

  // ---- SBOM preview: components + per-component vuln severity (respects the repo scope) ----
  function componentRepos(c){ return (c.properties||[]).filter(function(p){return p.name==="drift:repo";})
    .map(function(p){return p.value;}); }
  function renderSbom(){
    var tb=document.querySelector("#sbom-table tbody"); if(!tb) return;
    tb.innerHTML="";
    var all=(SBOM.components)||[], vulns=(SBOM.vulnerabilities)||[];
    var comps = state.repo ? all.filter(function(c){ return componentRepos(c).indexOf(state.repo)>-1; }) : all;
    var worst={}, rank={critical:4,high:3,medium:2,low:1,unknown:0}, counts={};
    vulns.forEach(function(v){ (v.affects||[]).forEach(function(a){
      var s=((v.ratings||[{}])[0].severity)||"unknown";
      if(!(a.ref in worst) || rank[s]>rank[worst[a.ref]]) worst[a.ref]=s; counts[a.ref]=(counts[a.ref]||0)+1; }); });
    var h=document.getElementById("sbom-h");
    if(h) h.textContent="Components — "+comps.length+(state.repo?(" in "+repoLabelOf(state.repo)):"")+"  ·  "+vulns.length+" vulnerabilities";
    comps.forEach(function(c){
      var ref=c["bom-ref"], n=counts[ref]||0, s=worst[ref];
      var vc = n ? '<span class="pill '+escA(s==="critical"?"crit":s==="high"?"high":s==="medium"?"med":"low")+'">'+esc(n)+' '+esc(s)+'</span>' : "—";
      var repos=componentRepos(c).length;
      var tr=document.createElement("tr");
      tr.innerHTML='<td>'+esc(c.type)+'</td><td class="mono">'+esc(c.purl||c["bom-ref"])+'</td><td>'+esc(c.version||"")+
        '</td><td>'+esc(repos)+' repo'+(repos===1?"":"s")+'</td><td>'+vc+'</td>';
      tb.appendChild(tr);
    });
  }

  // ---- SARIF preview: results grouped by rule (respects the repo scope via the uri prefix) ----
  function renderSarif(){
    var host=document.getElementById("sarif-groups"); if(!host) return;
    host.innerHTML="";
    var run=(SARIF.runs||[{}])[0]||{}, all=run.results||[];
    function uriOf(r){ var l=(r.locations||[])[0]; return ((l&&l.physicalLocation||{}).artifactLocation||{}).uri||""; }
    var results = state.repo ? all.filter(function(r){ return uriOf(r).indexOf(state.repo+"/")===0; }) : all;
    var byRule={}; results.forEach(function(r){ (byRule[r.ruleId]=byRule[r.ruleId]||[]).push(r); });
    var h=document.getElementById("sarif-h");
    if(h) h.textContent="Findings — "+results.length+" results"+(state.repo?(" in "+repoLabelOf(state.repo)):"")+", grouped by rule";
    Object.keys(byRule).sort().forEach(function(rid){
      var list=byRule[rid], d=document.createElement("details"); d.className="grp";
      var rows=list.slice(0,200).map(function(r){
        var pl=((r.locations||[])[0]||{}).physicalLocation||{};
        var uri=(pl.artifactLocation||{}).uri||""; var line=(pl.region||{}).startLine;
        var where=esc(uri)+(line?(":"+esc(line)):"");
        var lvl=r.level==="error"?"crit":r.level==="warning"?"high":"low";
        return '<tr><td class="mono">'+where+'</td><td>'+esc((r.message||{}).text||"")+
          '</td><td><span class="pill '+lvl+'">'+esc(r.level||"note")+'</span></td></tr>';
      }).join("");
      d.innerHTML='<summary>'+esc(rid)+'<span class="count">'+esc(list.length)+'</span></summary>'+
        '<table class="big"><thead><tr><th>Location</th><th>Message</th><th>Level</th></tr></thead><tbody>'+rows+'</tbody></table>';
      host.appendChild(d);
    });
  }
  renderSbom(); renderSarif();

  // ---- the repo scope dropdown: populate from the data, wire to all three panels ----
  var repoLabels={};   // repo key -> clean label
  (DATA.actions||[]).forEach(function(a){ if(a.repo) repoLabels[a.repo]=a.repoLabel||a.repo; });
  (DATA.shapes||[]).forEach(function(s){ if(s.repo && !(s.repo in repoLabels)) repoLabels[s.repo]=s.repoLabel||s.repo; });
  function repoLabelOf(k){ return repoLabels[k]||k; }
  var sel=document.getElementById("repo-filter");
  if(sel){
    Object.keys(repoLabels).sort(function(a,b){ return repoLabelOf(a).localeCompare(repoLabelOf(b)); })
      .forEach(function(k){ var o=document.createElement("option"); o.value=k; o.textContent=repoLabelOf(k); sel.appendChild(o); });
    sel.addEventListener("change", function(){
      state.repo=sel.value;
      // reflect the active scope on the control itself (it shows the repo name; the accent
      // border marks "not all repos" at a glance) — replaces the old inline scope note
      if(state.repo) sel.setAttribute("data-scoped",""); else sel.removeAttribute("data-scoped");
      render(); renderSbom(); renderSarif();
    });
  }

  // ---- native <dialog> (guarded; the Summary rows use the inline accordion) ----
  var dlg=document.getElementById("detail");
  if(dlg){ var xb=dlg.querySelector("[data-close]"); if(xb) xb.addEventListener("click",function(){dlg.close();});
    dlg.addEventListener("click",function(e){ if(e.target===dlg) dlg.close(); }); }

  (function(){
    // Integration drift since the previous scan — what DRIFT.md used to carry.
    var el=document.getElementById("drift"); if(!el) return;
    var d=DATA.inventoryDrift; if(!d) return;
    var h="", added=d.reposAdded||[], removed=d.reposRemoved||[], changes=d.changes||[];
    if(added.length) h+='<div class="note">Repos added: '+added.map(esc).join(", ")+'</div>';
    if(removed.length) h+='<div class="note">Repos removed: '+removed.map(esc).join(", ")+'</div>';
    changes.forEach(function(c){
      var bits=[];
      (c.endpointsAdded||[]).forEach(function(e){ bits.push("+ endpoint "+esc(e)); });
      (c.endpointsRemoved||[]).forEach(function(e){ bits.push("− endpoint "+esc(e)); });
      (c.sdkVersionChanges||[]).forEach(function(s){
        bits.push(esc(s.pkg)+" "+esc(s.from)+" → "+esc(s.to)); });
      (c.sdksAdded||[]).forEach(function(s){ bits.push("+ "+esc(s.pkg)+" "+esc(s.ver)); });
      (c.sdksRemoved||[]).forEach(function(s){ bits.push("− "+esc(s.pkg)+" "+esc(s.ver)); });
      (c.runtimeChanges||[]).forEach(function(r){
        bits.push(esc(r.product)+" "+esc(r.from)+" → "+esc(r.to)); });
      if(bits.length) h+='<div class="note"><b>'+esc(c.repo)+'</b>: '+bits.join(" · ")+'</div>';
    });
    el.innerHTML = h ? ('<details class="grp"><summary>Changed since last scan</summary>'
                        + '<div style="padding:10px 14px">'+h+'</div></details>') : "";
  })();

  (function(){
    var cov=document.getElementById("coverage"); if(!cov) return;
    var h="";
    var uns=DATA.rootsUnscannable||[];
    if(uns.length){
      h+='<div class="note"><b>⚠ Couldn’t scan '+esc(uns.length)+' source(s) you asked '
        +'for</b> — this is NOT a clean result for them (check the path exists and the token '
        +'has access):</div><ul>';
      uns.forEach(function(u){ h+='<li>'+esc(u.root)+' — '+esc(u.reason)+'</li>'; });
      h+='</ul>';
    }
    // generic methodology (Sources / Versions / Parked tiers / catalog note) is boilerplate,
    // identical every scan — it goes to its own "methodology" footer below, NOT mixed into
    // the data-specific coverage warnings (unaudited vendors, unreachable sources, …).
    var GENERIC=[/^Sources:/,/^Versions are/,/^Parked:/,/^Vendor API sunsets:/];
    function isGeneric(n){ return GENERIC.some(function(r){return r.test(n);}); }
    (DATA.coverageNotes||[]).filter(function(n){return !isGeneric(n);})
      .forEach(function(n){ h+='<div class="note">'+esc(n)+'</div>'; });
    var unknown=(DATA.shapes||[]).filter(function(s){return s.verdict==="UNKNOWN";});
    if(unknown.length){
      h+='<div class="note"><b>'+esc(unknown.length)+' repo(s) the scan could not fully read.</b> '
        +'A repo is only KNOWN when every language present has egress rules AND nothing was '
        +'left unattributed:</div><ul>';
      unknown.forEach(function(s){
        h+='<li>'+esc(s.repo)+' — <b>'+esc(s.verdict)+'</b> ('+esc((s.reasons||[]).join(", "))+')'
          +'; languages: '+esc(Object.keys(s.languages||{}).join(", "))+'</li>';
      });
      h+='</ul>';
    }
    var grades=(DATA.coverageGrades||[]).filter(function(g){return g.grade!=="HIGH";});
    if(grades.length){
      h+='<div class="note">Coverage — repos where calls may be unattributed:</div><ul>';
      grades.forEach(function(g){ h+='<li>'+esc(g.repoLabel||g.repo)+': <b>'+esc(g.grade)+'</b> ('
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
    var cd=DATA.coveredDeps||[];
    if(cd.length){
      h+='<div class="note">'+esc(cd.length)+' private dependency(ies) are <b>scanned directly</b> '
        +'as their own fleet repo — a dependency edge, not a blind spot:</div><ul>';
      cd.forEach(function(d){ h+='<li>'+esc(d.repo)+' → '+esc(d.source)+'</li>'; });
      h+='</ul>';
    }
    cov.innerHTML = h ? ("<h2>Coverage</h2>"+h) : "";
    // the generic methodology, in its own collapsed footer container (separate from data)
    var meth=document.getElementById("methodology");
    if(meth){ var gen=(DATA.coverageNotes||[]).filter(isGeneric);
      meth.innerHTML = gen.length
        ? '<details class="grp"><summary>Scan methodology &amp; sources<span class="count">'
          +gen.length+'</span></summary><div style="padding:10px 14px">'
          +gen.map(function(n){ return '<div class="note">'+esc(n)+'</div>'; }).join("")
          +'</div></details>'
        : ""; }
  })();

  render();
})();
"""
