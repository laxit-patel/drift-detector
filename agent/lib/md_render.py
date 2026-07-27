"""Render the report payload as Markdown — the primary, agent-readable view.

WHY MARKDOWN IS THE PRIMARY VIEW. An LLM cannot see rendered HTML/CSS; it verifies the
dashboard only by proxy, which is how two bugs shipped (a tile reading "Sunsets 1" over
twelve findings; twelve table rows rendering the identical label). Markdown SOURCE is text
an agent reads directly, so "what the agent checks" and "what a person sees" become nearly
the same artifact — and the remaining gap (Markdown's own grammar) is policeable by a
stdlib parser, which HTML's gap never was.

That gap is real: an unescaped `|` in a table cell silently truncates the row on GitHub
(extra cells dropped). So EVERY cell goes through `_esc`, the single choke point, and
`agent/lib/verify.py::check_md_matches_payload` re-parses this output and diffs it against
the payload. This is a VERIFIED PROJECTION of drift.json, never a parallel hand-built
truth — the discipline whose absence got the old Markdown/SARIF renderers deleted in v0.5.

Deterministic: pure function of the payload, `json.dumps`-stable upstream.
"""
from __future__ import annotations

from datetime import date as _date

from agent.lib import owners

SCHEMA_VERSION = "drift/v1"


def _esc(s) -> str:
    """Escape a value for a GFM table cell. Pipes break columns; newlines break the row.
    This is the ONLY place cells are escaped — a second escaper is a second bug."""
    return (str(s if s is not None else "")
            .replace("\\", "\\\\").replace("|", "\\|")
            .replace("\r", "").replace("\n", " ").strip())


def _table(headers: list, rows: list) -> list:
    """A GFM pipe table as a list of lines. Every cell escaped; a row with the wrong
    column count is a bug the parity check will catch."""
    out = ["| " + " | ".join(_esc(h) for h in headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(_esc(c) for c in row) + " |")
    return out


def _repo(a: dict) -> str:
    """Display name for a repo: the clean project path (repoLabel, e.g. chetan/amazonspapi)
    the projection stamps, else the raw repo path."""
    return a.get("repoLabel") or a.get("repo") or ""


def _action_label(a: dict) -> str:
    """'eBay GetCategoryFeatures' for a sunset, 'composer/aws/aws-sdk-php' for a CVE."""
    ref = a.get("ref") or ""
    unit = a.get("unit")
    return f"{ref} {unit}" if unit else ref


def _first_loc(a: dict) -> str:
    files = a.get("files") or []
    if not files:
        return ""
    f0 = files[0]
    return f0.get("loc", "") if isinstance(f0, dict) else str(f0)


# Chars that break a Mermaid label even inside quotes, mapped to HTML entity codes.
# A grammar error renders as an error box that looks FINE in the source, so the only
# safe move is to make one impossible by construction: entity-encode every breaker and
# never derive node IDs from content (generated n0/n1… sidestep the o/x-prefix and
# `end`-keyword traps too).
# NB: `;` is deliberately NOT a breaker — it is fine inside a quoted label, and encoding
# it would corrupt the trailing `;` of every entity code below (#123; -> #123#59;).
_MM_BREAKERS = {"\\": "#92;", '"': "#quot;", "[": "#91;", "]": "#93;", "{": "#123;",
                "}": "#125;", "(": "#40;", ")": "#41;", "|": "#124;"}


def _mm_label(s) -> str:
    out = str(s if s is not None else "")
    for ch, rep in _MM_BREAKERS.items():
        out = out.replace(ch, rep)
    return out.replace("\n", " ").strip()


def _mermaid_exposure(actions: list, now: str) -> list:
    """A flowchart of exposure: each repo → the retiring API surfaces it calls, coloured
    by whether the removal date has passed. A COMPLEMENT to the sunsets table — every fact
    here is also a row there — so a silent Mermaid render error can never hide data.

    Returns the fenced block as lines, or [] when there is nothing retiring to draw.
    """
    sunsets = [a for a in actions if a.get("kind") == "sunset"]
    if not sunsets:
        return []

    repos, nodes, edges, dead_ids, due_ids = {}, [], [], [], []
    for a in sunsets:
        repo = _repo(a) or "?"
        if repo not in repos:
            rid = f"r{len(repos)}"
            repos[repo] = rid
            nodes.append(f'  {rid}["{_mm_label(repo)}"]')
        nid = f"n{len(edges)}"
        date = a.get("date")
        past = bool(date and str(date) <= now)
        label = f"{_mm_label(a.get('ref') or '')} {_mm_label(a.get('unit') or '')}".strip()
        when = (f"removed {_mm_label(date)}" if past else f"retires {_mm_label(date)}") if date else "deprecated"
        nodes.append(f'  {nid}["{label}<br/>{when}"]')
        edges.append(f"  {repos[repo]} --> {nid}")
        (dead_ids if past else due_ids).append(nid)

    L = ["```mermaid", "flowchart LR"]
    L += nodes
    L += edges
    L.append("  classDef dead fill:#f7e4e2,stroke:#b4232a,color:#7a1519;")
    L.append("  classDef due fill:#f6ecd8,stroke:#a2650b,color:#6b4407;")
    if dead_ids:
        L.append(f"  class {','.join(dead_ids)} dead;")
    if due_ids:
        L.append(f"  class {','.join(due_ids)} due;")
    L.append("```")
    return L


def _overdue(a: dict, now: str) -> bool:
    d = a.get("date")
    return bool(d and str(d) <= now)


def _gantt_txt(s) -> str:
    """Strip chars that break a gantt/quadrant label (':' is gantt's name/spec separator; the
    rest break mermaid generally). '/' '.' '-' are kept so API paths stay readable."""
    s = str(s if s is not None else "")
    for ch in ':#"<>[]{}\\|':
        s = s.replace(ch, " ")
    return " ".join(s.split()) or "?"


def _gantt(sunsets: list, now: str) -> list:
    """A retirement timeline: each dated surface a milestone, sectioned by vendor, crit = past."""
    dated = [a for a in sunsets if a.get("date")]
    if not dated:
        return []
    by_vendor: dict = {}
    for a in dated:
        by_vendor.setdefault(a.get("ref") or "?", []).append(a)
    L = ["```mermaid", "gantt", "  title Retirement timeline",
         "  dateFormat YYYY-MM-DD", "  axisFormat %b %Y"]
    for vendor in sorted(by_vendor):
        L.append(f"  section {_gantt_txt(vendor)}")
        for a in sorted(by_vendor[vendor], key=lambda x: str(x["date"])):
            tag = "crit" if _overdue(a, now) else "active"
            L.append(f"    {_gantt_txt(a.get('unit') or a.get('ref'))} :{tag}, milestone, {a['date']}, 0d")
    L.append("```")
    return L


def _pie(sunsets: list, now: str) -> list:
    overdue = sum(1 for a in sunsets if _overdue(a, now))
    upcoming = sum(1 for a in sunsets if a.get("date") and not _overdue(a, now))
    nodate = sum(1 for a in sunsets if not a.get("date"))
    if not (overdue or upcoming or nodate):
        return []
    L = ["```mermaid", "pie showData", "  title Retiring API surfaces"]
    if overdue:
        L.append(f'  "Already removed" : {overdue}')
    if upcoming:
        L.append(f'  "Retiring soon" : {upcoming}')
    if nodate:
        L.append(f'  "No date announced" : {nodate}')
    L.append("```")
    return L


def _quadrant(sunsets: list, now: str) -> list:
    """Priority: x = how overdue (4-yr window), y = blast radius (# repos calling it)."""
    dated = [a for a in sunsets if a.get("date")]
    try:
        nowd = _date.fromisoformat(now)
    except ValueError:
        return []
    surfaces: dict = {}
    for a in dated:
        key = (a.get("ref"), a.get("unit"))
        s = surfaces.setdefault(key, {"date": str(a["date"]), "repos": set(),
                                      "label": _action_label(a)})
        s["repos"].add(_repo(a))
    if not surfaces:
        return []
    maxr = max(len(s["repos"]) for s in surfaces.values())
    L = ["```mermaid", "quadrantChart", "  title Fix priority",
         "  x-axis Runway --> Overdue", "  y-axis One repo --> Many repos",
         "  quadrant-1 Fix first", "  quadrant-2 Plan soon",
         "  quadrant-3 Watch", "  quadrant-4 Fix (isolated)"]
    for s in surfaces.values():
        try:
            days = (nowd - _date.fromisoformat(s["date"])).days
        except ValueError:
            continue
        x = min(0.95, max(0.05, 0.5 + days / 1460.0))
        nr = len(s["repos"])
        y = 0.30 if maxr <= 1 else min(0.9, max(0.1, 0.15 + 0.75 * (nr - 1) / (maxr - 1)))
        L.append(f'  "{_gantt_txt(s["label"])}": [{x:.2f}, {y:.2f}]')
    L.append("```")
    return L


def _diagrams(actions: list, now: str) -> list:
    """A segmented gallery of the retiring-surface data, AFTER the report so it never pushes
    the tables down. Each chart answers one question; a viewer that can't render one just
    shows its fenced source (we can drop it then)."""
    sunsets = [a for a in actions if a.get("kind") == "sunset"]
    if not sunsets:
        return []
    L = ["## Diagrams", "",
         "_Views of the retiring API surfaces above — red/crit = already removed, "
         "amber/blue = still ahead._", ""]
    for title, block in (
        ("Timeline — when each surface retires", _gantt(sunsets, now)),
        ("Blast radius — which repo calls what", _mermaid_exposure(sunsets, now)),
        ("Status — removed vs. upcoming", _pie(sunsets, now)),
        ("Priority — overdue × blast radius", _quadrant(sunsets, now)),
    ):
        if block:
            L += [f"### {title}", "", *block, ""]
    return L


def render_markdown(payload: dict, now: str) -> str:
    """The report as Markdown. `now` dates the header and splits past-due from upcoming."""
    counts = payload.get("counts", {})
    actions = payload.get("actions", [])
    L: list = []

    # --- front matter: the projection self-identifies its source + contract version,
    # taken FROM the payload so the two cannot disagree ---
    L += ["---",
          f"schemaVersion: {_esc(payload.get('schemaVersion', SCHEMA_VERSION))}",
          "generatedFrom: drift.json",
          f"generated: {_esc(payload.get('generated', now))}",
          "---", ""]

    # --- headline ---
    scanned = counts.get("reposScanned", 0)
    affected = counts.get("reposAffected", 0)
    fixes = counts.get("fixes", 0)
    sunsets = [a for a in actions if a.get("kind") == "sunset"]
    past = [a for a in sunsets if a.get("date") and str(a["date"]) <= now]
    L.append("# Drift report")
    L.append("")
    if past:
        L.append(f"**{len(past)} of {len(sunsets)} retiring API surface(s) are already past "
                 f"their removal date** — calls into APIs the vendor has switched off. "
                 f"{fixes} fix(es) needed across {affected} of {scanned} repo(s).")
    elif fixes:
        L.append(f"**{fixes} fix(es) needed across {affected} of {scanned} repo(s).**")
    else:
        L.append(f"**No action-required findings across {scanned} repo(s) scanned.**")
    L.append("")

    # --- most-urgent callout: name the single most pressing surface so the reader has one
    # thing to do first. Most-overdue retired sunset wins; else the soonest deadline. Prose
    # (not parity-checked) — a pointer INTO the tables below, never a substitute for them.
    dated = [a for a in sunsets if a.get("date")]
    overdue = sorted((a for a in dated if str(a["date"]) <= now), key=lambda a: str(a["date"]))
    upcoming = sorted((a for a in dated if str(a["date"]) > now), key=lambda a: str(a["date"]))
    pick = overdue[0] if overdue else (upcoming[0] if upcoming else None)
    if pick:
        verb = "already retired" if str(pick["date"]) <= now else "retires"
        L.append(f"**Most urgent:** {_esc(_action_label(pick))} in "
                 f"`{_esc(_repo(pick))}` — {verb} {_esc(pick['date'])}.")
        L.append("")

    # --- summary (the tiles, as a table) ---
    L.append("## Summary")
    L.append("")
    L += _table(["Metric", "Count"], [
        ["Fixes needed (action-required)", counts.get("fixes", 0)],
        ["Vendor API sunsets", counts.get("sunsets", 0)],
        ["— of which already retired (past-due)", counts.get("pastDue", 0)],
        ["Runtime/framework EOL", counts.get("eol", 0)],
        ["Critical CVEs", counts.get("critical", 0)],
        ["Unaudited vendors", counts.get("unaudited", 0)],
        ["Repos affected / scanned", f"{affected} / {scanned}"],
    ])
    L.append("")

    # --- findings, split into the two delivery queues (DevOps vs Developer) ---
    # Repo is the FIRST column of every table: the same finding (a vendored SDK, a shared
    # runtime) can appear in several repos with an identical repo-relative call-site, so
    # without the repo those rows render byte-identical — a reader cannot tell which repo is
    # exposed, and the md-row-identity check (correctly) rejects the report. The repo is the
    # disambiguator AND the thing a reader most needs: which of my repos does this hit.
    def _render_group(group, cols, is_sunset):
        rows = []
        for a in group:
            when = a.get("date") or a.get("fix_version") or "—"
            # call-sites the reader can act on (the located files), not finding_count —
            # which for a family-scoped sunset is ~always 1 and tells the reader nothing
            sites = len(a.get("files") or []) or a.get("finding_count", 0)
            rows.append([_repo(a), _action_label(a), a.get("status", ""),
                         when, sites, _first_loc(a)])
        L.extend(_table(cols, rows))
        L.append("")
        # (the visual charts live in a dedicated "Diagrams" section at the end, not inline)

    _C_SUN = ["Repo", "API", "Status", "Retires", "Call-sites", "First call-site"]
    _C_EOL = ["Repo", "Component", "Status", "EOL", "Call-sites", "First call-site"]
    _C_CVE = ["Repo", "Package", "Status", "Fix", "Call-sites", "First call-site"]
    # each queue is the work ONE team owns; sub-categories keep the kind-specific columns.
    # The eol split mirrors owners.owner(): refKind runtime -> DevOps, else Developer, so no
    # eol action can fall between the two tables.
    queues = (
        ("devops", "DevOps queue — packages & runtimes", (
            ("Package vulnerabilities", _C_CVE, lambda a: a.get("kind") == "cve", False),
            ("Runtime end-of-life", _C_EOL,
             lambda a: a.get("kind") == "eol" and a.get("refKind") == "runtime", False),
        )),
        ("developer", "Developer queue — vendor APIs & frameworks", (
            ("Vendor API sunsets", _C_SUN, lambda a: a.get("kind") == "sunset", True),
            ("Framework end-of-life", _C_EOL,
             lambda a: a.get("kind") == "eol" and a.get("refKind") != "runtime", False),
        )),
    )
    for owner_key, qtitle, cats in queues:
        # honour the stored owner (a verified field); derive it only if a caller handed us
        # an action without one, so the renderer never silently drops a job
        q_actions = [a for a in actions if (a.get("owner") or owners.owner(a)) == owner_key]
        if not q_actions:
            continue
        L.append(f"## {qtitle}")
        L.append("")
        for ctitle, cols, pred, is_sunset in cats:
            group = [a for a in q_actions if pred(a)]
            if not group:
                continue
            L.append(f"### {ctitle}")
            L.append("")
            _render_group(group, cols, is_sunset)

    # --- coverage: shape + catalog verdicts (sentences + a table) ---
    grades = payload.get("coverageGrades", [])
    catalog = payload.get("catalog", [])
    if grades or catalog:
        L.append("## Coverage — what the scan is sure of")
        L.append("")
    if grades:
        L.append("**Per-repo (can we see the calls?)**")
        L.append("")
        L += _table(["Repo", "Grade", "Attributed", "Unattributed paths", "Unresolved sinks"],
                    [[g.get("repoLabel") or g.get("repo"), g.get("grade"), g.get("attributed"),
                      g.get("unattributedPaths"), g.get("unresolvedSinks")] for g in grades])
        L.append("")
    if catalog:
        L.append("**Per-vendor (have we checked the retirement list?)**")
        L.append("")
        L += _table(["Vendor", "Verdict", "Call-sites", "Catalog entries", "Checked"],
                    [[c.get("vendor"), c.get("verdict"), c.get("callSites"),
                      c.get("catalogEntries"), c.get("checked") or "never"] for c in catalog])
        L.append("")

    # --- notes (coverage caveats, plain-folder warnings, unaudited disclosures) ---
    notes = payload.get("coverageNotes", [])
    if notes:
        L.append("## Notes")
        L.append("")
        for nte in notes:
            L.append(f"- {_esc(nte)}")
        L.append("")

    # --- diagrams: a segmented visual gallery, AFTER the report ---
    L.extend(_diagrams(actions, now))

    L.append("---")
    L.append("_Rendered from `drift.json` — deterministic, 0 LLM tokens, every date sourced._")
    return "\n".join(L) + "\n"
