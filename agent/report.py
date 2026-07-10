"""Deterministic findings.json assembly + markdown rendering (business-logic-risk lead)."""
from __future__ import annotations


def assemble_findings_doc(stamped, delta, coverage, watermarks, now):
    delta = dict(delta)
    pending = delta.pop("_resolvedPending", [])
    findings = [f for f in stamped if not f.watchlist]
    watch = [f for f in stamped if f.watchlist]
    counts = {"action": 0, "review": 0, "ok": 0, "watchlist": len(watch)}
    for f in findings:
        counts[f.severity.lower()] = counts.get(f.severity.lower(), 0) + 1
    wm = dict(watermarks or {})
    wm["_resolvedPending"] = pending
    return {
        "schemaVersion": 1, "runDate": now, "counts": counts, "delta": delta,
        "findings": [f.to_dict() for f in findings],
        "watchlist": [f.to_dict() for f in watch],
        "coverage": coverage or {}, "reportedWatermarks": wm,
    }


def _line(f):
    return (f"- {f['repo']} — {f['tech']} {f.get('versionInUse','')}: {f['evidence']} "
            f"({f['changeType']}) [source]({f['sourceUrl']})")


def render_report(doc: dict) -> str:
    findings = doc["findings"]
    action = [f for f in findings if f["severity"] == "ACTION"]
    review = [f for f in findings if f["severity"] == "REVIEW"]
    d = doc["delta"]
    out = [f"# API/Integration Change Report — {doc['runDate']}", ""]

    out += ["## ⚠️ Business-logic risk (ACTION)", ""]
    out += ([_line(f) for f in action] or ["_none_"]) + [""]

    out += ["## Delta", "",
            f"🆕 {len(d.get('new',[]))} new · ✅ {len(d.get('resolved',[]))} resolved · ⏳ {len(d.get('ongoing',[]))} ongoing", ""]

    out += ["## Review", ""]
    if review:
        out += ["| Repo | Tech | Version | Change | Source |", "|---|---|---|---|---|"]
        out += [f"| {f['repo']} | {f['tech']} | {f.get('versionInUse','')} | {f['changeType']} | [src]({f['sourceUrl']}) |" for f in review]
    else:
        out += ["_none_"]
    out += [""]

    out += ["## Early-warning watchlist", ""]
    out += ([_line(f) for f in doc["watchlist"]] or ["_none_"]) + [""]

    cov = doc.get("coverage", {})
    out += ["## Coverage", "", f"Repos scanned: {cov.get('reposScanned', 0)}"]
    for key in ("reposErrored", "reposNoManifests", "manifestsUnparsed", "presenceUnavailable"):
        items = cov.get(key) or []
        if items:
            out += [f"- {key}: {len(items)}"]
    out += [""]

    c = doc["counts"]
    out += ["## Run metadata", "",
            f"Counts: {c['action']} ACTION · {c['review']} REVIEW · {c['ok']} OK · {c['watchlist']} watchlist"]
    return "\n".join(out) + "\n"
