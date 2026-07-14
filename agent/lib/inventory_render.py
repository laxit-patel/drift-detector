"""Render the superset inventory doc into the PM's INVENTORY.md shape."""
from __future__ import annotations

from collections import Counter


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


def render_inventory_md(doc: dict) -> str:
    repos = doc.get("repos", [])
    out = [f"# Tech-Stack Inventory — {doc.get('generated', '')}".rstrip(), ""]

    out += ["## Scope", "", "| | Count |", "|---|---|"]
    for k, v in (doc.get("scope") or {}).items():
        out.append(f"| {k} | {v} |")
    out.append("")

    out += ["## Third-party APIs (by repo count)", "", "| Vendor | Repos |", "|---|---|"]
    for vendor, n in _ranked(_vendor_repo_counts(repos)):
        out.append(f"| {vendor} | {n} |")
    out.append("")

    out += ["## Frameworks (by repo count)", "", "| Framework | Repos |", "|---|---|"]
    for name, n in _ranked(_framework_repo_counts(repos)):
        out.append(f"| {name} | {n} |")
    out.append("")

    out += ["## Pinned API versions", "", "| Vendor | Version |", "|---|---|"]
    for av in doc.get("unique_api_versions", []):
        out.append(f"| {av.get('vendor', '')} | {av.get('version', '')} |")
    out.append("")

    out += ["## Runtimes", ""]
    for product, ranges in (doc.get("runtimes") or {}).items():
        out.append(f"- **{product}**: {', '.join(ranges)}")
    out.append("")

    out += ["## SDKs / libraries (top 30 by repo count)", "", "| Ecosystem | Package | Repos |", "|---|---|---|"]
    for (eco, pkg), n in _ranked(_pkg_repo_counts(repos))[:30]:
        out.append(f"| {eco} | {pkg} | {n} |")
    out.append("")

    cov = doc.get("coverage") or {}
    out += ["## Coverage", ""]
    out.append(f"- Repos scanned: {cov.get('reposScanned', len(repos))}")
    out.append(f"- Repos errored: {len(cov.get('reposErrored', []))}")
    out.append("")

    return "\n".join(out)
