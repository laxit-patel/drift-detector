"""Render the endpoint rule pack. Discover-then-classify: ONE broad, AST-aware rule matches every
`http(s)://` URL string literal (skipping comments); classification against the vendor catalog
happens in Python (agent.lib.classify_url), so the catalog is never the detection ceiling.
"""
from __future__ import annotations

import yaml

DEFAULT_LANGUAGES = ["php", "js", "ts", "python", "ruby", "go", "java", "csharp"]


def build_ruleset(vendors: list | None = None, languages: list = DEFAULT_LANGUAGES) -> dict:
    # `vendors` is accepted for signature compatibility but no longer shapes the rules —
    # one broad URL-literal rule replaces the per-vendor allowlist.
    return {"rules": [{
        "id": "url-literal",
        "languages": list(languages),
        "message": "URL literal",
        "severity": "INFO",
        "metadata": {"kind": "url"},
        "pattern": r'"=~/https?:\/\//"',
    }]}


def write_ruleset(vendors: list | None, path: str, languages: list = DEFAULT_LANGUAGES) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(build_ruleset(vendors, languages), fh, sort_keys=False)
