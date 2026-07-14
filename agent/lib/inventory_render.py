"""Render the superset inventory doc into a comprehensive, drift-first Markdown report.

One self-contained report meant to be opened in a Markdown viewer (VS Code
preview, GitHub, etc.), not pasted into chat: it leads with what changed since
the last scan, then the summary, the by-vendor/framework/runtime/SDK tables, and
a per-repo section with each third-party endpoint at `file:line`.
"""
from __future__ import annotations

from collections import Counter, defaultdict


def _vendor_repo_counts(repos: list) -> Counter:
    c: Counter = Counter()
    for r in repos:
        for v in {ep.get("vendor", "") for ep in r.get("endpoints", []) if ep.get("vendor")}:
            c[v] += 1
    return c


def _pkg_repo_counts(repos: list) -> Counter:
    c: Counter = Counter()
    for r in repos:
        for pkg in {(s["eco"], s["pkg"]) for s in r.get("sdks", [])}:
            c[pkg] += 1
    return c


def _framework_repo_counts(repos: list) -> Counter:
    c: Counter = Counter()
    for r in repos:
        for name in set((r.get("frameworks") or {}).keys()):
            c[name] += 1
    return c


def _ranked(counter: Counter) -> list:
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0] if isinstance(kv[0], str) else str(kv[0])))


def _versions_by_vendor(doc: dict) -> dict:
    m: dict = defaultdict(list)
    for av in doc.get("unique_api_versions", []):
        v, vendor = av.get("version"), av.get("vendor", "")
        if v and v not in m[vendor]:
            m[vendor].append(v)
    return m


def _drift_section(diff: dict) -> list:
    added = diff.get("reposAdded", [])
    removed = diff.get("reposRemoved", [])
    changes = diff.get("changes", [])
    if not (added or removed or changes):
        return []
    n = len(added) + len(removed) + len(changes)
    out = [f"## ⚠ Drift since last scan ({n})", ""]
    if added:
        out.append(f"- **Repos added:** {', '.join(added)}")
    if removed:
        out.append(f"- **Repos removed:** {', '.join(removed)}")
    if added or removed:
        out.append("")
    for ch in changes:
        out.append(f"**{ch['repo']}**")
        for e in ch.get("endpointsAdded", []):
            out.append(f"- 🆕 API {e['techKey']} {e.get('version') or ''} ({e['domain']})")
        for e in ch.get("endpointsRemoved", []):
            out.append(f"- ❌ API removed {e['techKey']} {e.get('version') or ''} ({e['domain']})")
        for s in ch.get("sdkVersionChanges", []):
            out.append(f"- ⬆️ {s['eco']} {s['pkg']}: {s['from']} → {s['to']}")
        for s in ch.get("sdksAdded", []):
            out.append(f"- 🆕 dep {s['eco']} {s['pkg']} {s['ver']}")
        for s in ch.get("sdksRemoved", []):
            out.append(f"- ❌ dep removed {s['eco']} {s['pkg']}")
        for r in ch.get("runtimeChanges", []):
            out.append(f"- 🔧 runtime {r['product']}: {r['from']} → {r['to']}")
        out.append("")
    return out


def _per_repo_section(repos: list, *, max_files: int = 6) -> list:
    out = ["## Per repo", ""]
    for r in sorted(repos, key=lambda x: x.get("path", "")):
        head = r.get("head_sha", "") or ""
        meta = " · ".join(x for x in (r.get("ref", ""), head[:7]) if x)
        out.append(f"### {r.get('path', '?')}" + (f"  ·  {meta}" if meta else ""))
        rts = r.get("runtimes") or {}
        if rts:
            out.append("- **Runtimes:** " + ", ".join(
                f"{name} {(rt or {}).get('range', '')}".strip() for name, rt in sorted(rts.items())))
        fws = r.get("frameworks") or {}
        if fws:
            out.append("- **Frameworks:** " + ", ".join(
                f"{name} {(fw or {}).get('ver', '')}".strip() for name, fw in sorted(fws.items())))
        eps = r.get("endpoints", [])
        if eps:
            out.append("- **Third-party APIs:**")
            for e in eps:
                ver = e.get("version") or "?"
                where = ", ".join(e.get("files", [])[:max_files]) or e.get("domain", "")
                extra = "" if len(e.get("files", [])) <= max_files else f" (+{len(e['files']) - max_files} more)"
                out.append(f"    - **{e.get('vendor', '?')}** `{ver}` — `{where}`{extra}")
        sdks = r.get("sdks", [])
        if sdks:
            shown = ", ".join(f"{s.get('eco')}/{s.get('pkg')} {s.get('ver', '')}".strip() for s in sdks[:12])
            more = "" if len(sdks) <= 12 else f" (+{len(sdks) - 12} more)"
            out.append(f"- **SDKs:** {shown}{more}")
        if not (rts or fws or eps or sdks):
            out.append("- _no third-party usage detected_")
        out.append("")
    return out


def render_inventory_md(doc: dict, diff: dict | None = None) -> str:
    repos = doc.get("repos", [])
    gen = doc.get("generated", "")
    vendor_counts = _vendor_repo_counts(repos)
    versions = _versions_by_vendor(doc)

    out = [f"# Integration Inventory & Drift — {gen}".rstrip(), ""]

    # one-line summary
    n_drift = 0
    if diff:
        n_drift = len(diff.get("reposAdded", [])) + len(diff.get("reposRemoved", [])) + len(diff.get("changes", []))
    summary = (f"**{len(repos)} repos · {len(vendor_counts)} third-party APIs · "
               f"{len(_pkg_repo_counts(repos))} packages · {len(doc.get('runtimes') or {})} runtimes**")
    if n_drift:
        summary += f" · **⚠ {n_drift} drifted**"
    out += [summary, ""]

    # drift first (only when there is a prior scan with changes)
    if diff:
        out += _drift_section(diff)

    out += ["## Scope", "", "| | Count |", "|---|---|"]
    for k, v in (doc.get("scope") or {}).items():
        out.append(f"| {k} | {v} |")
    out.append("")

    out += ["## Third-party APIs (by repo count)", "", "| API | Version(s) | Repos |", "|---|---|---|"]
    for vendor, n in _ranked(vendor_counts):
        out.append(f"| {vendor} | {', '.join(versions.get(vendor, [])) or '—'} | {n} |")
    out.append("")

    out += ["## Frameworks (by repo count)", "", "| Framework | Repos |", "|---|---|"]
    for name, n in _ranked(_framework_repo_counts(repos)):
        out.append(f"| {name} | {n} |")
    out.append("")

    out += ["## Runtimes", ""]
    for product, ranges in (doc.get("runtimes") or {}).items():
        out.append(f"- **{product}**: {', '.join(ranges)}")
    out.append("")

    out += ["## SDKs / libraries (top 30 by repo count)", "", "| Ecosystem | Package | Repos |", "|---|---|---|"]
    for (eco, pkg), n in _ranked(_pkg_repo_counts(repos))[:30]:
        out.append(f"| {eco} | {pkg} | {n} |")
    out.append("")

    if repos:
        out += _per_repo_section(repos)

    cov = doc.get("coverage") or {}
    out += ["## Coverage", ""]
    out.append(f"- Repos scanned: {cov.get('reposScanned', len(repos))}")
    errored = cov.get("reposErrored", [])
    out.append(f"- Repos errored: {len(errored)}")
    for e in errored:
        out.append(f"    - {e.get('repo', '?')}: {e.get('reason', '')}")
    out.append("")

    return "\n".join(out)
