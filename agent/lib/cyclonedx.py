"""Build a CycloneDX 1.6 SBOM (components + vulnerabilities) from an inventory + audit findings.

CycloneDX is the OWASP standard for 'dependencies + vulnerabilities' and is ingestible by
Dependency-Track, GitHub, Grype, etc. https://cyclonedx.org/
"""
from __future__ import annotations

from agent.lib.version_floor import floor
from agent.lib.purl import to_purl

_RATING = {"CRITICAL": "critical", "HIGH": "high", "MODERATE": "medium", "MEDIUM": "medium",
           "LOW": "low", "RATED": "unknown", "UNKNOWN": "unknown"}


def build_bom(doc: dict, findings: list, now: str) -> dict:
    components: dict = {}      # bom-ref (purl) -> component
    for r in doc.get("repos", []):
        for s in r.get("sdks", []):
            ver = floor(s.get("ver"))
            purl = to_purl(s.get("eco"), s.get("pkg"), ver)
            if not purl:
                continue
            components.setdefault(purl, {
                "type": "library", "bom-ref": purl, "name": s.get("pkg"),
                "version": ver or "", "purl": purl,
            })
    # runtimes/frameworks as 'framework' components; carry EOL status as a property
    eol_status = {(f["ref"], floor(f["version"])): f for f in findings if f["kind"] == "eol"}
    for r in doc.get("repos", []):
        for name, rt in (r.get("runtimes") or {}).items():
            _add_platform(components, name, floor((rt or {}).get("range")), eol_status)
        for name, fw in (r.get("frameworks") or {}).items():
            _add_platform(components, name, floor((fw or {}).get("ver")), eol_status)

    vulnerabilities = []
    seen = set()
    for f in findings:
        if f["kind"] != "cve":
            continue
        eco, _, pkg = f["ref"].partition("/")
        purl = to_purl(eco, pkg, floor(f["version"]))
        vid = f.get("cve") or f.get("id")
        dedup = (vid, purl)
        if not purl or not vid or dedup in seen:
            continue
        seen.add(dedup)
        vulnerabilities.append({
            "bom-ref": f"{vid}/{purl}",
            "id": vid,
            "source": {"name": "OSV", "url": f.get("source_url", "")},
            "ratings": [{"severity": _RATING.get((f.get("severity") or "").upper(), "unknown")}],
            "affects": [{"ref": purl}],
            "recommendation": f.get("recommendation", ""),
        })

    bom = {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
        "metadata": {"timestamp": f"{now}T00:00:00Z",
                     "tools": {"components": [{"type": "application", "name": "drift-detector"}]}},
        "components": list(components.values()),
    }
    if vulnerabilities:
        bom["vulnerabilities"] = vulnerabilities
    return bom


def _add_platform(components: dict, name: str, ver: str | None, eol_status: dict) -> None:
    ref = f"platform:{name}@{ver or '?'}"
    if ref in components:
        return
    comp = {"type": "framework", "bom-ref": ref, "name": name, "version": ver or ""}
    hit = eol_status.get((name, ver))
    if hit:
        comp["properties"] = [{"name": "drift:eol-status", "value": hit["status"]},
                              {"name": "drift:eol-date", "value": hit.get("date") or ""}]
    components[ref] = comp
