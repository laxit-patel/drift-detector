"""Audit an inventory doc: enrich its packages (OSV CVEs) and runtimes/frameworks (endoflife EOL)
into DEPRECATED / REVIEW / OK findings with cited sources.

Deterministic and zero-LLM-token. HTTP is injected (default = stdlib urllib) and the query
functions are injected too, so tests need no network. Degrades gracefully: if a source is
unreachable it is skipped and noted in coverage — never fabricated, never a hard failure.
"""
from __future__ import annotations

from agent.lib import osv, eol
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


def audit_inventory(doc: dict, now: str, *, http=None,
                    osv_query=osv.query_package, eol_check=eol.check) -> dict:
    http = http or default_http
    repos = doc.get("repos", [])
    findings: list = []
    coverage = {"osvErrors": 0, "eolErrors": 0, "notes": [
        "Sources: OSV.dev (CVEs, Tier 1) + endoflife.date (runtime/framework EOL, Tier 1).",
        "Versions are the DECLARED manifest floor — verify against your lockfile.",
        "Parked: Tier 2 (SDK repo archived/changelog) and Tier 3 (community/early-warning) signals.",
    ]}
    osv_cache: dict = {}
    eol_cache: dict = {}
    osv_down = eol_down = False

    for r in repos:
        path = r.get("path")
        # --- packages -> OSV ---
        for s in r.get("sdks", []):
            eco, pkg = s.get("eco"), s.get("pkg")
            ver = floor(s.get("ver"))
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
                findings.append({
                    "repo": path, "kind": "cve", "ref": f"{eco}/{pkg}", "version": s.get("ver"),
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
                    "status": res["status"], "severity": "EOL",
                    "detail": f"{product} {res['cycle']} end-of-life {res.get('eol_date') or ''}".strip(),
                    "date": res.get("eol_date"), "source_url": res["source_url"], "tier": 1,
                    "recommendation": (f"upgrade to {res['recommended']}" if res.get("recommended") else "upgrade to a supported release"),
                })

    counts = {
        "DEPRECATED": sum(1 for f in findings if f["status"] == "DEPRECATED"),
        "REVIEW": sum(1 for f in findings if f["status"] == "REVIEW"),
        "reposAffected": len({f["repo"] for f in findings}),
    }
    return {"generated": now, "findings": findings, "counts": counts, "coverage": coverage}
