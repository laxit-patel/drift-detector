"""Render an audit into AUDIT.md — the 'what do I mend' report.

Renders ACTIONS, not raw findings. One upgrade that resolves 30 advisories is one line, and
the top of the report is the highest-ranked job. (The previous version listed findings and
took the first 15 unsorted, which hid every CRITICAL behind an alphabetically-early repo.)
"""
from __future__ import annotations

from collections import defaultdict

from agent.lib.actions import build_actions
from agent.lib.ranking import severity_rank

_BADGE = {"DEPRECATED": "🔴", "REVIEW": "🟠"}
_TOP_N = 10
_TRANSITIVE_NOTE = ("Only manifest-declared (direct) dependencies are audited. Transitive "
                    "dependencies resolved in lockfiles are not queried.")


def _esc(s) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def _target(a) -> str:
    """Where to move to: the exact version when known, else the prose recommendation."""
    if a.get("fix_version"):
        return f"`{_esc(a['current_version'])}` → **`{_esc(a['fix_version'])}`**"
    return _esc(a.get("recommendation") or "review advisory")


def _target_cell(a) -> str:
    if a.get("fix_version"):
        return f"{_esc(a['current_version'])} → {_esc(a['fix_version'])}"
    return _esc(a.get("recommendation") or "review advisory")


def _fixes_phrase(a) -> str:
    n = a["finding_count"]
    out = f"Fixes {n} advisor{'y' if n == 1 else 'ies'}"
    if a.get("critical_count"):
        out += f" ({a['critical_count']} critical)"
    return out


def _render_top(out, actions):
    urgent = [a for a in actions if a["status"] == "DEPRECATED"]
    if not urgent:
        return
    out += ["## Do this first", ""]
    for i, a in enumerate(urgent[:_TOP_N], 1):
        out.append(f"{i}. {_BADGE['DEPRECATED']} **{_esc(a['repo'])}** — "
                   f"`{_esc(a['ref'])}` {_target(a)}")
        line = f"   {_fixes_phrase(a)}."
        if a.get("first_seen"):
            line += f" Open since {_esc(a['first_seen'])}."
        out.append(line)
        if a.get("command"):
            out.append(f"   `{a['command']}`")
        if a.get("files"):
            out.append(f"   Used at: {', '.join(_esc(p) for p in a['files'])}")
        out.append("")
    if len(urgent) > _TOP_N:
        out += [f"_{_TOP_N} shown of {len(urgent)}. Full queue below._", ""]


def _render_queue(out, actions):
    urgent = [a for a in actions if a["status"] == "DEPRECATED"]
    if not urgent:
        return
    out += ["## Fix queue", "",
            "| # | Repo | Package | Now → Fix | Fixes | Worst |",
            "|---|---|---|---|---|---|"]
    for i, a in enumerate(urgent, 1):
        out.append(f"| {i} | {_esc(a['repo'])} | {_esc(a['ref'])} | {_target_cell(a)} "
                   f"| {a['finding_count']} | {_BADGE['DEPRECATED']} {_esc(a['worst'])} |")
    out.append("")


def _render_by_repo(out, actions):
    by_repo = defaultdict(list)
    for a in actions:
        by_repo[a["repo"]].append(a)
    # worst repo first; the actions within a repo are already ranked
    order = sorted(by_repo, key=lambda r: (
        -severity_rank(by_repo[r][0]["worst"], by_repo[r][0]["status"]), r))
    out += ["## By repo", ""]
    for repo in order:
        out.append(f"### {repo}")
        out.append("| Package | Now → Fix | Fixes | Worst | Advisories |")
        out.append("|---|---|---|---|---|")
        for a in by_repo[repo]:
            links = ", ".join(f"[{i}]({u})" for i, u in enumerate(a["sources"][:6], 1)) or "—"
            out.append(f"| {_esc(a['ref'])} | {_target_cell(a)} | {a['finding_count']} "
                       f"| {_BADGE.get(a['status'], '')} {_esc(a['worst'])} | {links} |")
        out.append("")


def render_audit_md(audit: dict) -> str:
    actions = audit.get("actions")
    if actions is None:                       # tolerate a raw audit that skipped apply_lifecycle
        actions = build_actions([f for f in audit.get("findings", []) if not f.get("suppressed")])
    counts = audit.get("counts", {})
    delta = audit.get("delta")
    now = audit.get("generated", "")

    urgent_n = sum(1 for a in actions if a["status"] == "DEPRECATED")
    review_n = len(actions) - urgent_n
    scanned = ((audit.get("coverage") or {}).get("repos") or {}).get("scanned")
    repos_txt = (f"{counts.get('reposAffected', 0)} of {scanned} repos" if scanned
                 else f"{counts.get('reposAffected', 0)} repos")

    out = [f"# Deprecation & Vulnerability Audit — {now}".rstrip(), ""]
    out.append(f"**🔴 {urgent_n} fixes needed · 🟠 {review_n} to review · across {repos_txt}**")

    if delta is not None:
        new_actions = build_actions(delta.get("new", []))
        out += ["", (f"_Since last scan: 🆕 {len(new_actions)} new · "
                     f"✅ {len(delta.get('resolved', []))} resolved · "
                     f"⏳ {len(delta.get('persisting', []))} still open"
                     + (f" · 🔕 {delta.get('mutedCount', 0)} muted"
                        if delta.get("mutedCount") else "") + "_")]
        if new_actions:
            out += ["", "## 🆕 New since last scan", ""]
            for a in new_actions:
                out.append(f"- {_BADGE.get(a['status'], '')} **{_esc(a['ref'])}** in "
                           f"`{_esc(a['repo'])}` — {_target_cell(a)}")
        resolved = delta.get("resolved", [])
        if resolved:
            out += ["", "## ✅ Resolved since last scan", ""]
            for r in resolved:
                out.append(f"- {_esc(r.get('ref'))} ({_esc(r.get('kind'))})")
    out.append("")

    if not actions:
        out += ["_No open deprecation or vulnerability findings._", ""]
    else:
        _render_top(out, actions)
        _render_queue(out, actions)
        _render_by_repo(out, actions)

    out += ["## Coverage & notes", ""]
    for n in (audit.get("coverage", {}) or {}).get("notes", []):
        out.append(f"- {n}")
    out.append(f"- {_TRANSITIVE_NOTE}")
    out.append("")
    return "\n".join(out)
