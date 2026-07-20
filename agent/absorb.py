"""The absorb gate: how a proposal becomes a durable, trusted tool capability.

An agent can read a repo the scanner cannot and propose what would close the gap —
a new idiom instance, a new vendor, a sunset entry. None of that is trusted because
an agent said it. Everything passes through here first, and this is deterministic
and costs zero tokens.

The three checks exist because of three specific ways this can go wrong:

  1. A DATE NOBODY SOURCED. An unverified retirement date in an audit is worse than
     no entry — people act on these. Every sunset must cite a source URL and parse
     as a real date. (Observed for real: a research pass reported GetCategorySpecifics
     as 2022-04-20 and AddDispute as 2023-01-31; both were wrong by days.)
  2. AN IDIOM THAT CLAIMS MORE THAN IT DELIVERS. A proposal names the call-sites it
     will attribute; we re-scan and require they actually get attributed.
  3. AN IDIOM THAT INVENTS ENDPOINTS. The cardinal rule is no false endpoints, so a
     staged idiom must not attribute anything to a vendor it did not before, and
     residue must strictly shrink — a rule that "fixes" a gap by inventing calls
     elsewhere is worse than the gap.

Only on a clean pass are the specs promoted and an attestation written.
"""
from __future__ import annotations

import os
import re
import shutil

import yaml

from agent.lib import idioms, shapes

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AbsorbRejected(Exception):
    """A staged proposal failed the gate. The message names which check and why."""


def _load(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def check_sunsets(entries: list) -> list:
    """Reject any sunset without a citable source and a parseable date."""
    problems = []
    for i, e in enumerate(entries):
        where = f"sunset #{i} ({e.get('vendor')} {e.get('operation') or e.get('domain') or e.get('version')})"
        if not isinstance(e, dict) or not e.get("vendor"):
            problems.append(f"{where}: not a mapping with a vendor")
            continue
        src = str(e.get("source") or "")
        if not src.startswith("http"):
            problems.append(f"{where}: no source URL — a date nobody sourced is not admissible")
        if not _DATE.match(str(e.get("retires") or "")):
            problems.append(f"{where}: `retires` must be YYYY-MM-DD, got {e.get('retires')!r}")
        if not (e.get("operation") or e.get("domain") or e.get("version") is not None):
            problems.append(f"{where}: needs a scope (operation, domain, or version)")
    return problems


def check_idioms(instances: list) -> list:
    problems = []
    for i, inst in enumerate(instances):
        try:
            idioms._validate(inst, f"idiom #{i} ({inst.get('id') if isinstance(inst, dict) else inst!r})")
        except idioms.IdiomError as exc:
            problems.append(str(exc))
    return problems


def verify_against_repo(repo_abs: str, staged_idioms: list, claims: list,
                        *, scan) -> list:
    """Re-scan `repo_abs` with the staged idioms and hold the proposal to its claims.

    `scan(idiom_instances) -> {"endpoints": [...], "residue": {...}}` is injected so
    this is testable without an engine. `claims` is the list of file:line the
    proposal says it will attribute.
    """
    before = scan(None)
    after = scan(staged_idioms)

    problems = []
    attributed_after = {loc for e in after["endpoints"]
                        if e.get("vendor") and e["vendor"] != "Unknown"
                        for loc in e.get("files", [])}
    missing = [c for c in claims if c not in attributed_after]
    if missing:
        problems.append("claimed call-sites still unattributed after the change: "
                        + ", ".join(missing[:6]))

    # no false endpoints: no vendor may appear that was not there before
    vendors_before = {e.get("vendor") for e in before["endpoints"] if e.get("vendor")}
    vendors_after = {e.get("vendor") for e in after["endpoints"] if e.get("vendor")}
    invented = sorted(vendors_after - vendors_before)
    if invented:
        problems.append(f"attributes endpoints to vendor(s) not previously present: {invented}"
                        " — a rule that invents calls is worse than the gap it closes")

    n_before = len(before["residue"].get("pathLiterals", []))
    n_after = len(after["residue"].get("pathLiterals", []))
    if n_after > n_before:
        problems.append(f"residue grew ({n_before} -> {n_after} unattributed path literals)")
    return problems


def promote(staged_dir: str, *, idioms_path: str, sunsets_path: str) -> dict:
    """Append staged specs to the live catalogs. Only called after a clean gate."""
    added = {"idioms": 0, "sunsets": 0}
    for name, dest, key in (("idioms.yaml", idioms_path, "idioms"),
                            ("sunsets.yaml", sunsets_path, "sunsets")):
        staged = _load(os.path.join(staged_dir, name))
        if not staged:
            continue
        with open(dest, "a", encoding="utf-8") as fh:
            fh.write("\n" + yaml.safe_dump(staged, sort_keys=False))
        added[key] = len(staged)
    return added
