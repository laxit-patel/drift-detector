"""Render an audit result into the human-readable AUDIT.md (the 'what to mend' report)."""
from __future__ import annotations

from collections import defaultdict

_BADGE = {"DEPRECATED": "🔴", "REVIEW": "🟠"}
_ORDER = {"DEPRECATED": 0, "REVIEW": 1}


def _esc(s) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def render_audit_md(audit: dict) -> str:
    findings = [f for f in audit.get("findings", []) if not f.get("suppressed")]
    counts = audit.get("counts", {})
    delta = audit.get("delta")
    now = audit.get("generated", "")
    out = [f"# Deprecation & Vulnerability Audit — {now}".rstrip(), ""]
    out.append(f"**🔴 {counts.get('DEPRECATED', 0)} action-required · "
               f"🟠 {counts.get('REVIEW', 0)} to review · across {counts.get('reposAffected', 0)} repos**")
    if delta is not None:
        out.append("")
        out.append(f"_Since last scan: 🆕 {len(delta.get('new', []))} new · "
                   f"✅ {len(delta.get('resolved', []))} resolved · "
                   f"⏳ {len(delta.get('persisting', []))} still open"
                   + (f" · 🔕 {delta.get('mutedCount', 0)} muted" if delta.get("mutedCount") else "") + "_")
        newf = delta.get("new", [])
        if newf:
            out += ["", "## 🆕 New since last scan", ""]
            for f in sorted(newf, key=lambda x: (_ORDER.get(x["status"], 9), x["repo"])):
                out.append(f"- {_BADGE.get(f['status'], '')} **{_esc(f['ref'])}** `{_esc(f['version'])}` in "
                           f"`{_esc(f['repo'])}` — {_esc(f['detail'])}")
        resolved = delta.get("resolved", [])
        if resolved:
            out += ["", "## ✅ Resolved since last scan", ""]
            for r in resolved:
                out.append(f"- {_esc(r.get('ref'))} ({_esc(r.get('kind'))})")
    out.append("")

    if not findings:
        out += ["_No open deprecation or vulnerability findings._", ""]
    else:
        urgent = [f for f in findings if f["status"] == "DEPRECATED"]
        if urgent:
            out += ["## Most urgent (action required)", ""]
            for f in urgent[:15]:
                d = f" — fix: {_esc(f['recommendation'])}" if f.get("recommendation") else ""
                out.append(f"- {_BADGE['DEPRECATED']} **{_esc(f['ref'])}** `{_esc(f['version'])}` in "
                           f"`{_esc(f['repo'])}` — {_esc(f['detail'])}{d}")
            if len(urgent) > 15:
                out.append(f"- …and {len(urgent) - 15} more")
            out.append("")

        by_repo = defaultdict(list)
        for f in findings:
            by_repo[f["repo"]].append(f)
        out += ["## Findings by repo", ""]
        for repo in sorted(by_repo):
            out.append(f"### {repo}")
            out.append("| Tech / package | Version | Status | Detail | Fix | Source |")
            out.append("|---|---|---|---|---|---|")
            for f in sorted(by_repo[repo], key=lambda x: (_ORDER.get(x["status"], 9), x["ref"])):
                out.append(f"| {_esc(f['ref'])} | {_esc(f['version'])} | {_BADGE.get(f['status'], '')} {f['status']} "
                           f"| {_esc(f['detail'])} | {_esc(f.get('recommendation'))} "
                           f"| [{f['tier']}]({f['source_url']}) |")
            out.append("")

    cov = audit.get("coverage", {})
    out += ["## Coverage & notes", ""]
    for n in cov.get("notes", []):
        out.append(f"- {n}")
    out.append("")
    return "\n".join(out)
