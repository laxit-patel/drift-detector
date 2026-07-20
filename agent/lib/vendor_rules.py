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


# ---------------------------------------------------------------- ast-grep ----
# ast-grep rules are per-language and match by tree-sitter NODE KIND, so a
# string-literal rule must name the kinds that actually hold a string in each
# grammar. These were verified empirically against ast-grep 0.44.1 — do not
# guess them: a wrong kind means the scanner goes silently blind for that
# language (getting `encapsed_string` wrong lost 9 real PHP call-sites).
# Only CONTAINER kinds are listed; inner-content kinds (string_fragment,
# string_content, heredoc_body) are excluded because matching both double-counts.
AST_STRING_KINDS = {
    "php": ["string", "encapsed_string", "heredoc"],
    "javascript": ["string", "template_string"],
    "typescript": ["string", "template_string"],
    "python": ["string"],
    "ruby": ["string"],
    "go": ["interpreted_string_literal", "raw_string_literal"],
    "java": ["string_literal"],
    "csharp": ["string_literal", "verbatim_string_literal"],
}
_AST_LANG = {"js": "javascript", "ts": "typescript"}      # our short names -> ast-grep's


def _ast_lang(lang: str) -> str:
    return _AST_LANG.get(lang, lang)


def _ast_literal_rule(base_id: str, regex: str, lang: str, metadata: dict) -> dict:
    """A comment-safe string-literal match: any container string kind whose text matches."""
    kinds = AST_STRING_KINDS[lang]
    return {"id": f"{base_id}@{lang}", "language": lang, "metadata": dict(metadata),
            "rule": {"any": [{"kind": k, "regex": regex} for k in kinds]}}


def build_astgrep_ruleset(vendors: list | None = None,
                          languages: list = DEFAULT_LANGUAGES) -> list:
    """The same rule pack in ast-grep's dialect, as a list of rule documents.

    Rule ids are `{base}@{language}` because ast-grep rules are single-language;
    `run_scan` strips the suffix so downstream code still sees the base id.
    """
    langs = [l for l in (_ast_lang(x) for x in languages) if l in AST_STRING_KINDS]
    docs = []
    for lang in langs:
        docs.append(_ast_literal_rule("url-literal", r"https?://", lang, {"kind": "url"}))
    for v in (vendors or []):
        rx = "|".join(re.escape(d) for d in v.domains)
        meta = {"vendor": v.vendor, "techKey": v.techKey, "kind": "endpoint"}
        for lang in langs:
            docs.append(_ast_literal_rule(f"{vendor_slug(v.vendor)}-endpoint", rx, lang, meta))
    for lang in langs:
        docs.append(_ast_literal_rule(
            "path-literal", r"/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})/", lang,
            {"kind": "path-literal"}))
    # structural rules — PHP only, same scope as the semgrep pack
    docs.append({"id": "php-http-sink@php", "language": "php", "metadata": {"kind": "sink"},
                 "rule": {"any": [{"pattern": "curl_exec($$$)"},
                                  {"pattern": "curl_setopt($$$, CURLOPT_URL, $$$)"},
                                  {"pattern": "new \\GuzzleHttp\\Client($$$)"}]}})
    # the concat idiom; ast-grep matches the concat expression itself (an assignment
    # pattern is not a parseable standalone PHP fragment for it)
    docs.append({"id": "path-assembly@php", "language": "php", "metadata": {"kind": "path-assembly"},
                 "rule": {"pattern": "$A->getHost() . $B"}})
    return docs


def write_ruleset(vendors: list | None, path: str, languages: list = DEFAULT_LANGUAGES,
                  *, engine: str = "semgrep") -> None:
    """Write the rule pack in the dialect the resolved engine speaks."""
    from agent.lib.scan_util import engine_family
    if engine_family(engine) == "ast-grep":
        docs = build_astgrep_ruleset(vendors, languages)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n---\n".join(yaml.safe_dump(d, sort_keys=False) for d in docs))
        return
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(build_ruleset(vendors, languages), fh, sort_keys=False)
