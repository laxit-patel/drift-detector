"""Mechanical invariants over the dashboard payload — the checks that replace "looks right".

Rendered HTML cannot be checked by anything without eyes. Two bugs shipped in one
session because their tests ran a layer below the artifact a person reads:

  1. a tile reading `Sunsets 1` above twelve sunset findings, because actions grouped
     on (repo, vendor) and a vendor is not a job;
  2. twelve rows all labelled "eBay" — four of them identical — because the projection
     whitelists fields by hand and silently dropped the one carrying the operation.

Both are caught below WITHOUT rendering anything. Every check is a statement about the
payload that must hold no matter how the page is styled, so they survive CSS edits in a
way golden files do not.

Deterministic and dependency-free: pure Python over a dict.
"""
from __future__ import annotations

import re


class Violation(ValueError):
    """An invariant failed. Carries the check name so `drift verify` can report it."""

    def __init__(self, check: str, detail: str):
        self.check, self.detail = check, detail
        super().__init__(f"{check}: {detail}")


# Action fields deliberately NOT projected into the page. Naming them is the point: a new
# field added to build_actions must be either projected or listed here, so it can never be
# dropped by forgetting. This frozenset is what turns bug #2 into a test failure.
DECLARED_DROPS = frozenset({"fixes", "eco", "unit_kind", "sources_raw"})


def check_projection_parity(action: dict, projected: dict) -> None:
    """Every field an action carries is either projected or explicitly declared dropped."""
    lost = set(action) - set(projected) - DECLARED_DROPS
    if lost:
        raise Violation("projection-parity",
                        f"build_actions emits {sorted(lost)} but the projection neither "
                        f"carries nor declares them dropped — add to the projection, or to "
                        f"DECLARED_DROPS if the page genuinely does not need it. "
                        f"(This is how `unit` was lost and twelve rows rendered as 'eBay'.)")


_ACCESSOR = re.compile(r"\b([aep])\.([A-Za-z_]\w*)\b")
# JS built-ins and locals that are not payload fields
_NOT_FIELDS = frozenset({"length", "forEach", "map", "filter", "push", "join", "slice",
                         "indexOf", "toLowerCase", "toUpperCase", "concat", "sort"})


def check_accessor_coverage(client_js: str, samples: dict) -> None:
    """Every `a.foo` / `e.foo` / `p.foo` the page reads must exist in the payload.

    The other direction from projection-parity: that check catches a field the projection
    forgot, this catches the page reading a field nothing emits. Between them a rename
    cannot silently blank a column.
    """
    for var, keys in (("a", samples.get("actions")), ("e", samples.get("endpoints")),
                      ("p", samples.get("private"))):
        if not keys:
            continue
        read = {m.group(2) for m in _ACCESSOR.finditer(client_js)
                if m.group(1) == var and m.group(2) not in _NOT_FIELDS}
        missing = read - set(keys)
        if missing:
            raise Violation("accessor-coverage",
                            f"the page reads {var}.{sorted(missing)} but the payload has "
                            f"no such field — the column renders blank")


def sunset_unit(f: dict) -> str:
    return f.get("operation") or f.get("path") or f.get("domain") or f.get("version") or ""


def check_tile_counts(payload: dict, findings: list) -> None:
    """Each tile number must equal the rows its own filter yields, AND be reachable
    independently from the findings.

    The second half is what catches bug #1: `counts` is computed from actions, so if the
    grouping collapses, the tile and the table agree with each other and are both wrong.
    Recomputing from findings is an independent path, so a collapse shows up as a
    disagreement instead of a consistent lie.
    """
    counts, actions = payload["counts"], payload["actions"]

    # tile <-> table: replicate the page's own filters
    pairs = [("sunsets", [a for a in actions if a["kind"] == "sunset"]),
             ("eol", [a for a in actions if a["kind"] == "eol"]),
             ("private", payload.get("private", []))]
    for name, rows in pairs:
        if counts.get(name, 0) != len(rows):
            raise Violation("tile-vs-table",
                            f"tile '{name}' says {counts.get(name)} but its filter yields "
                            f"{len(rows)} rows")

    # independent path: one job per (repo, vendor, thing-retiring)
    expected = {(f["repo"], f["ref"], sunset_unit(f))
                for f in findings if f.get("kind") == "sunset"}
    if counts.get("sunsets", 0) != len(expected):
        raise Violation("sunset-grouping",
                        f"tile says {counts.get('sunsets')} sunsets but the findings hold "
                        f"{len(expected)} distinct (repo, vendor, operation|host) jobs — "
                        f"retirements are being merged, hiding dead calls behind one row")


def check_row_labels_distinct(payload: dict) -> None:
    """No two sunset rows may render an identical label.

    Four rows reading 'eBay · migrate to Sell Feed API before 2022-04-30' are
    indistinguishable to a reader even though they are four different hosts.
    """
    seen = {}
    for a in payload["actions"]:
        if a["kind"] != "sunset":
            continue
        label = (a.get("repo"), a.get("ref"), a.get("unit"), a.get("recommendation"))
        if label in seen:
            raise Violation("row-identity",
                            f"two sunset rows render identically: {label} — a reader "
                            f"cannot tell which call each one refers to")
        seen[label] = True


def check_blob_matches_payload(html: str, payload_json: str) -> None:
    """The data embedded in the page is the data in dashboard.json.

    This is what makes asserting on dashboard.json equivalent to asserting on the
    dashboard, and it is the only reason the checks above are trustworthy.

    Compared as parsed JSON, not as bytes: the embedded copy escapes `<` to \\u003c so a
    scan string containing </script> cannot close the element, and dashboard.json is
    written indented for humans. Both are presentation; the DATA must be identical.
    """
    import json
    m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>',
                  html, re.S)
    if not m:
        raise Violation("blob-present", "the page carries no #drift-data payload")
    try:
        embedded = json.loads(m.group(1))
    except ValueError as exc:
        raise Violation("blob-parity", f"the embedded payload is not valid JSON ({exc})")
    if embedded != json.loads(payload_json):
        raise Violation("blob-parity",
                        "the data embedded in dashboard.html differs from dashboard.json "
                        "— the file being verified is not the file being read")


def verify_payload(payload: dict, findings: list) -> list:
    """Run every payload invariant. Returns the violations rather than raising, so
    `drift verify` can report all of them in one pass instead of one per run."""
    out = []
    for fn, args in ((check_tile_counts, (payload, findings)),
                     (check_row_labels_distinct, (payload,))):
        try:
            fn(*args)
        except Violation as v:
            out.append(v)
    return out
