"""Check a package techKey against its registry for a deprecation/abandoned flag."""
from __future__ import annotations

from agent.lib.models import ChangeEntry


def _entry(tech_key, summary, url, now):
    return ChangeEntry(
        techKey=tech_key, date=now, changeType="deprecation",
        title=f"{tech_key} flagged deprecated by its registry",
        summary=summary, sourceUrl=url, sourceTier=1,
        evidence=summary, feedAdapter="registry",
    )


def _npm(name, fetch_json, now):
    url = f"https://registry.npmjs.org/{name}"
    data = fetch_json(url)
    dep = data.get("deprecated")
    if not dep:
        latest = (data.get("dist-tags") or {}).get("latest")
        ver = (data.get("versions") or {}).get(latest, {}) if latest else {}
        dep = ver.get("deprecated")
    return [_entry(f"lib:npm/{name}", f"npm: {dep}", url, now)] if dep else []


def _packagist(name, fetch_json, now):
    url = f"https://repo.packagist.org/p2/{name}.json"
    data = fetch_json(url)
    versions = (data.get("packages") or {}).get(name, [])
    for v in versions:
        if v.get("abandoned"):
            repl = v["abandoned"] if isinstance(v["abandoned"], str) else ""
            note = f"Packagist: package abandoned{f'; use {repl}' if repl else ''}"
            return [_entry(f"lib:composer/{name}", note, url, now)]
    return []


def _pypi(name, fetch_json, now):
    url = f"https://pypi.org/pypi/{name}/json"
    info = (fetch_json(url) or {}).get("info", {})
    if info.get("yanked") or "Development Status :: 7 - Inactive" in (info.get("classifiers") or []):
        return [_entry(f"lib:python/{name}", "PyPI: package inactive/yanked", url, now)]
    return []


def check_package(tech_key: str, *, fetch_json, now: str) -> list:
    if not tech_key.startswith("lib:"):
        return []
    body = tech_key[len("lib:"):]
    eco, _, name = body.partition("/")
    if not name:
        return []
    try:
        if eco == "npm":
            return _npm(name, fetch_json, now)
        if eco == "composer":
            return _packagist(name, fetch_json, now)
        if eco == "python":
            return _pypi(name, fetch_json, now)
    except Exception:
        return []
    return []
