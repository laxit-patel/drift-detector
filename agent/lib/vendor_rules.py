"""Render the ast-grep endpoint rule pack (discover-then-classify + allowlist recall):

- ONE broad rule matches every `http(s)://` string literal → we classify each host in
  Python (agent.lib.classify_url), so un-catalogued vendors still surface.
- PLUS one rule per catalogued vendor matching its domain literals → host-only
  references with no scheme (e.g. `'api.mailgun.net'` in a config) are still caught.
- PLUS the shape rules: versioned resource-path literals, PHP egress sinks, and the
  getHost()-concat idiom.
Matching is by tree-sitter node kind, so it is comment-safe by construction.
"""
from __future__ import annotations

import re

import yaml

from agent.lib.vendors import vendor_slug

DEFAULT_LANGUAGES = ["php", "js", "ts", "python", "ruby", "go", "java", "csharp"]


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
    # operation markers — the name of the API OPERATION being called, for vendors
    # that deprecate per-operation rather than per-host/version (eBay Trading:
    # one host, ~19 operations, independent lifecycles). classify_url.operation_of
    # pulls the name out of the matched line.
    for lang in langs:
        docs.append(_ast_literal_rule(
            "operation-marker", r"<[A-Z][A-Za-z0-9]{2,}Request\b", lang,
            {"kind": "operation-marker"}))
    docs.append({"id": "operation-call-name@php", "language": "php",
                 "metadata": {"kind": "operation-marker"},
                 "rule": {"pattern": "getEbaySession($NAME, $$$)"}})
    # structural rules — PHP only
    docs.append({"id": "php-http-sink@php", "language": "php", "metadata": {"kind": "sink"},
                 "rule": {"any": [{"pattern": "curl_exec($$$)"},
                                  {"pattern": "curl_setopt($$$, CURLOPT_URL, $$$)"},
                                  {"pattern": "new \\GuzzleHttp\\Client($$$)"}]}})
    # the concat idiom; ast-grep matches the concat expression itself (an assignment
    # pattern is not a parseable standalone PHP fragment for it)
    docs.append({"id": "path-assembly@php", "language": "php", "metadata": {"kind": "path-assembly"},
                 "rule": {"pattern": "$A->getHost() . $B"}})
    return docs


_SERIALIZED: dict = {}      # (vendors, languages) -> the rendered rule file text


def write_ruleset(vendors: list | None, path: str, languages: list = DEFAULT_LANGUAGES) -> None:
    """Write the rule pack as a multi-document ast-grep rule file.

    One rule per (vendor x language) means ~390 documents, and serializing them
    costs ~150ms — paid on every scan. The text is a pure function of its inputs,
    so it is memoized: a process that scans repeatedly renders it once.
    """
    key = (tuple((v.vendor, v.techKey, tuple(v.domains)) for v in (vendors or [])),
           tuple(languages))
    text = _SERIALIZED.get(key)
    if text is None:
        text = yaml.safe_dump_all(build_astgrep_ruleset(vendors, languages), sort_keys=False)
        _SERIALIZED[key] = text
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def rule_kinds_by_language(vendors: list | None = None,
                           languages: list = DEFAULT_LANGUAGES) -> dict:
    """language -> the set of rule kinds we actually emit for it.

    This is what makes "I have no rules here" distinguishable from "I looked and
    found nothing": the shape verdict reads it to decide whether a language is
    covered at all. Derived from the real ruleset so it can never drift from it.
    """
    out: dict = {}
    for d in build_astgrep_ruleset(vendors, languages):
        lang = d.get("language")
        kind = (d.get("metadata") or {}).get("kind")
        if lang and kind:
            out.setdefault(lang, set()).add(kind)
    return {k: sorted(v) for k, v in out.items()}
