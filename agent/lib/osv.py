"""OSV.dev client — look up known vulnerabilities for a package version.

https://api.osv.dev/v1/query : POST {package:{ecosystem,name}, version} -> {vulns:[...]}.
HTTP is injected (see http_util) so tests use canned responses.
"""
from __future__ import annotations

from agent.lib.http_util import default_http
from agent.lib.purl import osv_ecosystem

OSV_QUERY_URL = "https://api.osv.dev/v1/query"


def _severity_label(vuln: dict) -> str:
    ds = vuln.get("database_specific") or {}
    sev = ds.get("severity")
    if sev:
        return str(sev).upper()                 # GHSA: LOW / MODERATE / HIGH / CRITICAL
    if vuln.get("severity"):                     # CVSS vector present but unlabeled
        return "RATED"
    return "UNKNOWN"


def _cve(vuln: dict) -> str:
    for a in vuln.get("aliases") or []:
        if str(a).startswith("CVE-"):
            return a
    return vuln.get("id", "")


def _fixed_version(vuln: dict) -> str | None:
    for aff in vuln.get("affected") or []:
        for rng in aff.get("ranges") or []:
            for ev in rng.get("events") or []:
                if ev.get("fixed"):
                    return ev["fixed"]
    return None


def _source_url(vuln: dict) -> str:
    for r in vuln.get("references") or []:
        if r.get("url"):
            return r["url"]
    return f"https://osv.dev/vulnerability/{vuln.get('id', '')}"


def query_package(eco: str, name: str, version: str | None, *, http=default_http) -> list:
    """Return a list of normalized vuln dicts for one package version (empty if none/unsupported)."""
    osv_eco = osv_ecosystem(eco)
    if not osv_eco or not version:
        return []
    resp = http(OSV_QUERY_URL, method="POST",
                body={"package": {"ecosystem": osv_eco, "name": name}, "version": version})
    out = []
    for v in resp.get("vulns") or []:
        out.append({
            "id": v.get("id", ""),
            "cve": _cve(v),
            "severity": _severity_label(v),
            "summary": (v.get("summary") or (v.get("details") or "")[:160]).strip(),
            "fixed": _fixed_version(v),
            "url": _source_url(v),
        })
    return out


def query_all(packages, *, http=default_http) -> dict:
    """Dedupe (eco,name,version) across all repos and query each once. Returns {key: [vuln]}."""
    cache: dict = {}
    for eco, name, version in packages:
        key = (eco, name, version)
        if key not in cache:
            cache[key] = query_package(eco, name, version, http=http)
    return cache
