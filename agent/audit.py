"""Audit an inventory doc: enrich its packages (OSV CVEs) and runtimes/frameworks (endoflife EOL)
into DEPRECATED / REVIEW / OK findings with cited sources.

Deterministic and zero-LLM-token. HTTP is injected (default = stdlib urllib) and the query
functions are injected too, so tests need no network. Degrades gracefully: if a source is
unreachable it is skipped and noted in coverage — never fabricated, never a hard failure.
"""
from __future__ import annotations

from agent.lib import osv, eol, vendor_sunsets
from agent.lib.http_util import default_http
from agent.lib.version_floor import floor
from agent.lib.purl import osv_ecosystem
from agent.lib.eol import product_slug

_DEPRECATED_SEVERITIES = {"CRITICAL", "HIGH"}


def _cve_status(severity: str) -> str:
    # a known vulnerability is at least REVIEW; high/critical is action-required
    return "DEPRECATED" if (severity or "").upper() in _DEPRECATED_SEVERITIES else "REVIEW"


def _runtime_products(repo: dict):
    for name, rt in (repo.get("runtimes") or {}).items():
        yield name, (rt or {}).get("range")
    for name, fw in (repo.get("frameworks") or {}).items():
        yield name, (fw or {}).get("ver")


def _sunset_findings(repo: dict, sun_index: dict, now: str) -> list:
    """Join the repo's endpoints against the vendor-sunset catalog (the file:line layer)."""
    path, eps, out = repo.get("path"), repo.get("endpoints", []), []
    for vendor, entries in sun_index.items():
        vendor_eps = [e for e in eps if e.get("vendor") == vendor]
        if not vendor_eps:
            continue
        for entry in entries:
            edomain = entry.get("domain")            # optional: scope to a specific dead host
            cver = entry.get("version")
            files, confirmed = [], False
            for e in vendor_eps:
                if edomain:                          # domain-scoped: the host IS the API
                    if e.get("domain") != edomain:
                        continue                     # a different host of the same vendor -> skip
                    confirmed = True                 # host match confirms it's the retired API
                    files += e.get("files", [])
                    continue
                ev = e.get("version")
                if cver == "*" or (ev and ev != "?" and str(ev) == str(cver)):
                    confirmed = True
                    files += e.get("files", [])
                elif not ev or ev == "?":            # version-specific entry, unknown usage -> verify
                    files += e.get("files", [])
            if not files:
                continue
            files = list(dict.fromkeys(files))[:6]
            status = vendor_sunsets.status_for(entry.get("retires"), now, confirmed=confirmed)
            if edomain:
                vlabel = edomain
            elif cver == "*":
                vlabel = "(all versions)"
            else:
                vlabel = str(cver) if confirmed else f"{cver}?"
            when = f"retires {entry['retires']}" if entry.get("retires") else "deprecated"
            verify = "" if confirmed else " — version undetermined, verify"
            rec = f"migrate to {entry['replacement']}" if entry.get("replacement") else "plan migration"
            if entry.get("retires"):
                rec += f" before {entry['retires']}"
            out.append({
                "repo": path, "kind": "sunset", "ref": vendor, "version": cver, "domain": edomain,
                "status": status, "severity": "SUNSET",
                "detail": f"{vendor} {vlabel} {when}{verify} · used at " + ", ".join(files),
                "date": entry.get("retires"), "source_url": entry.get("source", ""), "tier": 1,
                "recommendation": rec, "files": files,
            })
    return out


def audit_inventory(doc: dict, now: str, *, http=None,
                    osv_query=None, eol_check=None, sunsets=None) -> dict:
    http = http or default_http
    osv_query = osv_query or osv.query_package     # resolve at call time (monkeypatch-friendly)
    eol_check = eol_check or eol.check
    sun_index = vendor_sunsets.by_vendor(sunsets if sunsets is not None else vendor_sunsets.load_sunsets())
    repos = doc.get("repos", [])
    findings: list = []
    coverage = {"osvErrors": 0, "eolErrors": 0, "notes": [
        "Sources: OSV.dev (CVEs, Tier 1) + endoflife.date (runtime/framework EOL, Tier 1).",
        "Versions are lockfile-exact where a lockfile exists (versionSource: lockfile), else the declared manifest floor — verify against your lockfile.",
        "Parked: Tier 2 (SDK repo archived/changelog) and Tier 3 (community/early-warning) signals.",
    ]}
    osv_cache: dict = {}
    eol_cache: dict = {}
    osv_down = eol_down = False

    for r in repos:
        path = r.get("path")
        seen_cve: set = set()          # dedupe a vuln within one repo (same pkg in 2 manifests)
        # --- packages -> OSV ---
        for s in r.get("sdks", []):
            eco, pkg = s.get("eco"), s.get("pkg")
            resolved = s.get("resolved")                 # exact version from a lockfile, if any
            ver = resolved or floor(s.get("ver"))        # else the declared manifest floor
            vsource = "lockfile" if resolved else "manifest"
            if osv_ecosystem(eco) is None or ver is None:
                continue
            key = (eco, pkg, ver)
            if key not in osv_cache:
                if osv_down:
                    continue
                try:
                    osv_cache[key] = osv_query(eco, pkg, ver, http=http)
                except Exception as exc:          # network/parse -> skip source, note once
                    osv_down = True
                    coverage["osvErrors"] += 1
                    coverage["notes"].append(f"OSV unreachable — package audit skipped ({exc}).")
                    continue
            for v in osv_cache.get(key) or []:
                dk = (v["id"], eco, pkg)
                if dk in seen_cve:
                    continue
                seen_cve.add(dk)
                findings.append({
                    "repo": path, "kind": "cve", "ref": f"{eco}/{pkg}",
                    "version": ver, "versionSource": vsource,
                    "id": v["id"], "cve": v["cve"], "fixed": v.get("fixed"),
                    "status": _cve_status(v["severity"]), "severity": v["severity"],
                    "detail": v["summary"] or v["cve"], "date": None,
                    "source_url": v["url"], "tier": 1,
                    "recommendation": (f"upgrade to >= {v['fixed']}" if v.get("fixed") else "review advisory"),
                })
        # --- runtimes + frameworks -> endoflife ---
        for product, spec in _runtime_products(r):
            fl = floor(spec)
            if product_slug(product) is None or fl is None:
                continue
            key = (product, fl)
            if key not in eol_cache:
                if eol_down:
                    continue
                try:
                    eol_cache[key] = eol_check(product, fl, now, http=http)
                except Exception as exc:
                    eol_down = True
                    coverage["eolErrors"] += 1
                    coverage["notes"].append(f"endoflife.date unreachable — EOL audit skipped ({exc}).")
                    continue
            res = eol_cache.get(key)
            if res and res["status"] != "OK":
                findings.append({
                    "repo": path, "kind": "eol", "ref": product, "version": spec,
                    "fixed": res.get("recommended"),
                    "status": res["status"], "severity": "EOL",
                    "detail": f"{product} {res['cycle']} end-of-life {res.get('eol_date') or ''}".strip(),
                    "date": res.get("eol_date"), "source_url": res["source_url"], "tier": 1,
                    "recommendation": (f"upgrade to {res['recommended']}" if res.get("recommended") else "upgrade to a supported release"),
                })
        # --- endpoints -> vendor-sunset catalog (the code-level layer) ---
        findings.extend(_sunset_findings(r, sun_index, now))

    coverage["notes"].append("Vendor API sunsets: curated catalog (agent/vendor_sunsets.yaml) joined against endpoints — extend it with your vendors' announcements.")
    counts = {
        "DEPRECATED": sum(1 for f in findings if f["status"] == "DEPRECATED"),
        "REVIEW": sum(1 for f in findings if f["status"] == "REVIEW"),
        "reposAffected": len({f["repo"] for f in findings}),
    }
    return {"generated": now, "findings": findings, "counts": counts, "coverage": coverage}
