"""Idiom families: the closed set of URL-assembly shapes the scanner can be taught.

A FAMILY is code (an interpreter here); an INSTANCE is data (agent/idioms.yaml).
That split is deliberate. Letting an agent author arbitrary detection logic as data
would reinvent the rule engine, worse — but letting it author a *parameter* of a
family we already implement is reviewable as a YAML diff, and the absorb gate can
verify it mechanically before it is trusted.

Adding a new family is a code change and a pull request. Say so; do not pretend
absorption is unbounded.
"""
from __future__ import annotations

import os

import yaml

from agent.lib import catalog_overlay

_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "idioms.yaml")

FAMILIES = frozenset({"url-assembly", "url-append", "operation-marker"})

# family -> the rule kind its matches carry, i.e. how endpoints.py will read them
KIND_BY_FAMILY = {"url-assembly": "path-assembly", "url-append": "path-assembly",
                  "operation-marker": "operation-marker"}


class IdiomError(ValueError):
    """A malformed instance. Raised loudly: a silently-dropped idiom is a silent blind spot."""


def _validate(inst: dict, where: str) -> None:
    if not isinstance(inst, dict):
        raise IdiomError(f"{where}: not a mapping")
    for req in ("id", "family", "evidence"):
        if not inst.get(req):
            raise IdiomError(f"{where}: missing required field `{req}`")
    fam = inst["family"]
    if fam not in FAMILIES:
        raise IdiomError(f"{where}: unknown family {fam!r} — families are a closed set "
                         f"({', '.join(sorted(FAMILIES))}); a new one is a code change")
    if fam == "url-append" and not inst.get("target"):
        raise IdiomError(f"{where}: url-append needs `target` — the NAME of the variable "
                         "appended to (e.g. \"serviceURL\" for `$serviceURL .= $path`). "
                         "Naming it is what keeps the family precise: a bare metavariable "
                         "would match every string append in the codebase.")
    if fam == "url-assembly" and not inst.get("base"):
        raise IdiomError(f"{where}: url-assembly needs `base` (an ast-grep pattern "
                         "for the base expression, e.g. \"$A->getHost()\")")
    if fam == "operation-marker" and not (inst.get("marker") or inst.get("pattern")):
        raise IdiomError(f"{where}: operation-marker needs `marker` (a regex over string "
                         "literals) or `pattern` (an ast-grep pattern)")


def load_idioms(path: str | None = None) -> list:
    with open(path or _DEFAULT, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    if not isinstance(raw, list):
        raise IdiomError("idioms file must be a YAML list of instances")
    # layer the writable overlay (baseline first) on a default load; the dup-id check below
    # then runs over the COMBINED set, so an absorbed idiom cannot silently shadow a baseline
    if path is None:
        raw = list(raw) + catalog_overlay.load_list(catalog_overlay.IDIOMS)
    for i, inst in enumerate(raw):
        _validate(inst, f"idiom #{i} ({inst.get('id') if isinstance(inst, dict) else inst!r})")
    ids = [i["id"] for i in raw]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise IdiomError(f"duplicate idiom ids: {sorted(dupes)}")
    return raw


def to_rules(inst: dict, literal_rule, languages: list) -> list:
    """Compile one instance into ast-grep rule documents.

    `literal_rule(base_id, regex, lang, metadata)` is injected so string-literal
    rules are built exactly like every other one — same node kinds, same
    comment-safety — instead of this module re-deriving them.
    """
    fam, rid = inst["family"], inst["id"]
    kind = {"kind": KIND_BY_FAMILY[fam]}
    langs = [inst["language"]] if inst.get("language") else list(languages)
    docs = []
    if fam == "url-assembly":
        for lang in langs:
            docs.append({"id": f"{rid}@{lang}", "language": lang, "metadata": dict(kind),
                         "rule": {"pattern": f'{inst["base"]} . $B'}})
    elif fam == "url-append":
        # assemble-then-append: `$base = $this->ENDPOINT;` ... `$base .= $path;`
        # The two statements are not one expression, so url-assembly's `base . $B`
        # cannot see it. The target variable is named literally — ast-grep treats
        # $UPPERCASE as a metavariable, so a lowercase/mixed name matches only itself.
        for lang in langs:
            docs.append({"id": f"{rid}@{lang}", "language": lang, "metadata": dict(kind),
                         "rule": {"pattern": f'${inst["target"]} .= $B'}})
    elif fam == "operation-marker":
        for lang in langs:
            if inst.get("marker"):
                docs.append(literal_rule(rid, inst["marker"], lang, dict(kind)))
            else:
                docs.append({"id": f"{rid}@{lang}", "language": lang, "metadata": dict(kind),
                             "rule": {"pattern": inst["pattern"]}})
    return docs
