"""Render the endpoint rule pack (discover-then-classify + allowlist recall):

- ONE broad, AST-aware rule matches every `http(s)://` URL string literal → we classify each
  host in Python (agent.lib.classify_url), so un-catalogued vendors still surface.
- PLUS one rule per catalogued vendor matching its domain string literals → so host-only
  references with no URL scheme (e.g. `'api.mailgun.net'` in a config) are still caught.
Both are comment-safe (string-literal `"=~/regex/"`, not raw pattern-regex).
"""
from __future__ import annotations

import re

import yaml

from agent.lib.vendors import vendor_slug

DEFAULT_LANGUAGES = ["php", "js", "ts", "python", "ruby", "go", "java", "csharp"]


def _url_rule(languages: list) -> dict:
    return {"id": "url-literal", "languages": list(languages), "message": "URL literal",
            "severity": "INFO", "metadata": {"kind": "url"}, "pattern": r'"=~/https?:\/\//"'}


def _vendor_rule(v, languages: list) -> dict:
    return {"id": f"{vendor_slug(v.vendor)}-endpoint", "languages": list(languages),
            "message": f"{v.vendor} endpoint", "severity": "INFO",
            "metadata": {"vendor": v.vendor, "techKey": v.techKey, "kind": "endpoint"},
            "pattern-either": [{"pattern": '"=~/' + re.escape(d) + '/"'} for d in v.domains]}


def _path_literal_rule(languages: list) -> dict:
    # Version-bearing resource-path literals ("/orders/2026-01-01/orders", "/catalog/v0/items").
    # String-literal (comment-safe) regex, same as the url-literal rule. Classified in Python.
    return {"id": "path-literal", "languages": list(languages), "message": "resource-path literal",
            "severity": "INFO", "metadata": {"kind": "path-literal"},
            "pattern": r'"=~/\/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})\//"'}


def _sink_rule() -> dict:
    # PHP HTTP egress sinks — unambiguous only (curl_exec, CURLOPT_URL, Guzzle client).
    # file_get_contents/fopen deferred (noisy without argument-shape analysis).
    return {"id": "php-http-sink", "languages": ["php"], "message": "HTTP egress sink",
            "severity": "INFO", "metadata": {"kind": "sink"},
            "pattern-either": [
                {"pattern": "curl_exec(...)"},
                {"pattern": "curl_setopt($CH, CURLOPT_URL, $U)"},
                {"pattern": r"new \GuzzleHttp\Client(...)"},
            ]}


def _path_assembly_rule() -> dict:
    # The concat idiom: a config host getter concatenated with a path variable/literal.
    return {"id": "path-assembly", "languages": ["php"], "message": "URL assembled from getHost() + path",
            "severity": "INFO", "metadata": {"kind": "path-assembly"},
            "pattern": "$URL = $OBJ->getHost() . $PATH"}


def build_ruleset(vendors: list | None = None, languages: list = DEFAULT_LANGUAGES) -> dict:
    rules = [_url_rule(languages)]
    rules += [_vendor_rule(v, languages) for v in (vendors or [])]
    rules += [_path_literal_rule(languages), _sink_rule(), _path_assembly_rule()]
    return {"rules": rules}


def write_ruleset(vendors: list | None, path: str, languages: list = DEFAULT_LANGUAGES) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(build_ruleset(vendors, languages), fh, sort_keys=False)
