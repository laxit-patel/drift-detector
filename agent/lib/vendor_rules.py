"""Render the vendor catalog into an Opengrep endpoint rule pack. The AST-aware
'"=~/regex/"' string-literal pattern matches endpoint URLs in code while skipping comments."""
from __future__ import annotations

import re

import yaml

from agent.lib.vendors import vendor_slug

DEFAULT_LANGUAGES = ["php", "js", "ts", "python", "ruby", "go", "java", "csharp"]


def _rule_for(v, languages: list) -> dict:
    patterns = [{"pattern": '"=~/' + re.escape(d) + '/"'} for d in v.domains]
    return {
        "id": f"{vendor_slug(v.vendor)}-endpoint",
        "languages": list(languages),
        "message": f"{v.vendor} endpoint",
        "severity": "INFO",
        "metadata": {"vendor": v.vendor, "techKey": v.techKey, "kind": "endpoint"},
        "pattern-either": patterns,
    }


def build_ruleset(vendors: list, languages: list = DEFAULT_LANGUAGES) -> dict:
    return {"rules": [_rule_for(v, languages) for v in vendors]}


def write_ruleset(vendors: list, path: str, languages: list = DEFAULT_LANGUAGES) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(build_ruleset(vendors, languages), fh, sort_keys=False)
