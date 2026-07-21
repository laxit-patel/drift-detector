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


# `r` is deliberately NOT tracked: it is already a loop variable for other
# records in the page, and conflating them makes this check lie in both
# directions. A payload-backed loop uses a distinct name (cv for catalog).
_ACCESSOR = re.compile(r"\b(a|e|p|cv)\.([A-Za-z_]\w*)\b")
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
                      ("p", samples.get("private")), ("cv", samples.get("catalog"))):
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
             ("private", payload.get("private", [])),
             # the panel lists vendors nobody has checked; CURRENT ones are not rows
             ("unaudited", [r for r in payload.get("catalog", [])
                            if r.get("verdict") != "CURRENT"])]
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


_CELL_SPLIT = re.compile(r"(?<!\\)\|")   # a pipe NOT preceded by a backslash


def _parse_md_tables(md_text: str) -> list:
    """Every GFM pipe table in `md_text` as {header:[...], rows:[[...]]}. Cells are split
    on UNESCAPED pipes, so a raw `|` that slipped past the escaper shows up as an extra
    cell — which is exactly the silent-truncation bug we want to catch, not hide."""
    tables, cur = [], None

    def cells(line):
        parts = _CELL_SPLIT.split(line.strip())
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1] == "":
            parts = parts[:-1]
        return [c.strip() for c in parts]

    lines = md_text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|"):
            row = cells(line)
            if cur is None:
                # header row must be followed by a --- separator row
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if set(nxt.replace("|", "").replace(" ", "")) <= {"-", ":"} and nxt.strip():
                    cur = {"header": row, "rows": [], "_sep": True}
                continue
            if cur.get("_sep"):                 # this line IS the separator, skip it once
                cur["_sep"] = False
                continue
            cur["rows"].append(row)
        else:
            if cur is not None:
                cur.pop("_sep", None)
                tables.append(cur)
                cur = None
    if cur is not None:
        cur.pop("_sep", None)
        tables.append(cur)
    return tables


def check_md_matches_payload(md_text: str, payload: dict) -> None:
    """The Markdown view agrees with the payload it was rendered from.

    The Markdown analog of check_blob_matches_payload, and the reason drift.md is a
    TRUSTED projection rather than a hopeful one. Three checks, each catching a real
    failure class:
      • column integrity — every row has the header's column count, so an unescaped `|`
        (which GitHub renders as dropped cells) fails here instead of silently;
      • summary parity — the numbers in the Summary table equal the payload counts, so a
        headline number cannot drift from the data (bug #1's class);
      • row identity — no two rows in a findings table are byte-identical (bug #2's class).
    """
    tables = _parse_md_tables(md_text)

    for t in tables:
        ncol = len(t["header"])
        for row in t["rows"]:
            if len(row) != ncol:
                raise Violation("md-column-integrity",
                                f"a row under {t['header']} has {len(row)} cells, not "
                                f"{ncol} — an unescaped '|' truncates it on GitHub: {row}")

    counts = payload.get("counts", {})
    summary = next((t for t in tables if t["header"][:2] == ["Metric", "Count"]), None)
    if summary:
        by_label = {r[0]: r[1] for r in summary["rows"] if len(r) >= 2}
        checks = {"Vendor API sunsets": counts.get("sunsets", 0),
                  "Runtime/framework EOL": counts.get("eol", 0),
                  "Fixes needed (action-required)": counts.get("fixes", 0),
                  "Unaudited vendors": counts.get("unaudited", 0)}
        for label, expected in checks.items():
            if label in by_label and by_label[label] != str(expected):
                raise Violation("md-summary-parity",
                                f"Summary says {label!r} = {by_label[label]}, payload says "
                                f"{expected} — the Markdown disagrees with drift.json")

    for t in tables:
        if t["header"][0] in ("API", "Component", "Package"):
            seen = set()
            for row in t["rows"]:
                key = tuple(row)
                if key in seen:
                    raise Violation("md-row-identity",
                                    f"two findings rows render identically: {row} — a "
                                    f"reader cannot tell them apart")
                seen.add(key)


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
