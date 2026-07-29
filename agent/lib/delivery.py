"""Turn drift.json findings into GitLab issues (DevOps stream) and draft MRs (Developer
stream), idempotently.

The delivery is a PROJECTION of the verified payload, so it only ever runs after a green
`verify`. Two streams (agent/lib/owners.py):
  • DevOps actions (packages + runtime EOL) -> one ISSUE each, in a configured project
    (for now the drift-ops repo; the central DevOps repo once it's assigned).
  • Developer actions (vendor API sunsets + framework EOL) -> one DRAFT MERGE REQUEST per
    scanned repo, on a `drift/migrations` branch carrying a `.drift/MIGRATIONS.md` checklist
    (which gives the MR a diff and the developer a place to do the actual migration).

Idempotency is the whole game — a re-scan must UPDATE, never duplicate. Issues carry a hidden
marker `<!-- drift-detector:<fp> -->` and a `drift-detector` label; MRs are keyed by their
stable `drift/migrations` source branch. `build_plan` is PURE (payload + what already exists
-> the create/update/close plan), so it is testable without any network.
"""
from __future__ import annotations

import hashlib
import re

LABEL = "drift-detector"
DEVOPS_LABEL = "drift:devops"
DEV_LABEL = "drift:developer"
# MAINTAINER audience (tool/catalog upkeep) — carried ALONGSIDE a stream label so all
# maintainer work filters as one queue, while shape vs freshness stay distinguishable.
MAINTAINER_LABEL = "drift:maintainer"
SHAPE_LABEL = "drift:shape"           # absorption: a repo shape the scanner can't read
FRESHNESS_LABEL = "drift:freshness"   # a catalogued vendor's retirements went stale / need a re-check
MR_BRANCH = "drift/migrations"
MIGRATIONS_PATH = ".drift/MIGRATIONS.md"
_MARKER = re.compile(r"<!--\s*drift-detector:([0-9a-f]{16})\s*-->")


def _sunset_unit(a: dict) -> str:
    return a.get("unit") or ""


def action_fingerprint(a: dict) -> str:
    """Stable, version-INDEPENDENT identity of a job: (repo, kind, ref, retiring-unit). A
    version bump updates the same issue instead of spawning a sibling."""
    raw = f"{a.get('repo')}|{a.get('kind')}|{a.get('ref')}|{_sunset_unit(a)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def repo_fingerprint(repo: str) -> str:
    return hashlib.sha256(f"repo|{repo}".encode()).hexdigest()[:16]


def shape_fingerprint(repo: str) -> str:
    """Repo-keyed identity for an absorption flag: ONE issue per repo that UPDATES in place as
    the residue drifts (a new residueFingerprint rewrites the body, the marker stays), rather
    than a sibling per code change. Distinct namespace from repo_fingerprint / action_fingerprint."""
    return hashlib.sha256(f"shape|{repo}".encode()).hexdigest()[:16]


def freshness_fingerprint() -> str:
    """Constant identity for THE catalog-freshness work-order: one issue for the whole catalog
    (the work-order is one maintainer queue, not an issue per vendor) that updates in place as
    vendors go stale/current and closes itself via `_finish` when nothing is due."""
    return hashlib.sha256(b"freshness|catalog").hexdigest()[:16]


def marker(fp: str) -> str:
    return f"<!-- drift-detector:{fp} -->"


def markers_in(text: str) -> set:
    return set(_MARKER.findall(text or ""))


def project_path(remote_url: str) -> str | None:
    """`https://host/group/repo` -> `group/repo`; None if unparseable."""
    m = re.match(r"^https?://[^/]+/(.+?)(?:\.git)?/?$", str(remote_url or ""))
    return m.group(1) if m else None


def _label_of(a: dict) -> str:
    return a.get("ref", "") + (f" {a['unit']}" if a.get("unit") else "")


def _when(a: dict) -> str:
    d = a.get("date")
    if not d:
        return a.get("fix_version") or ""
    return d


def _sites_md(a: dict) -> list:
    lines = []
    for f in (a.get("files") or [])[:12]:
        loc = f.get("loc") if isinstance(f, dict) else str(f)
        href = f.get("href") if isinstance(f, dict) else None
        lines.append(f"  - [`{loc}`]({href})" if href else f"  - `{loc}`")
    return lines


# ------------------------------------------------------------------ issue bodies (DevOps)
def issue_title(a: dict) -> str:
    when = _when(a)
    tail = f" — by {when}" if when else ""
    return f"[drift] {_label_of(a)}{tail}"


def _footer(links: dict | None = None, *, draft: bool = False) -> str:
    """The provenance line — 'what stemmed this': a link back to the scan run that filed it
    and to the full report, so a reader can trace any issue/MR to its source."""
    parts = ["Draft, filed by Drift Detector" if draft else "Filed by Drift Detector"]
    if links:
        if links.get("run"):
            parts.append(f"[scan run]({links['run']})")
        if links.get("report"):
            parts.append(f"[full report]({links['report']})")
    return "_" + " · ".join(parts) + " — updates in place on the next scan._"


def issue_body(a: dict, display: str | None = None, links: dict | None = None) -> str:
    fp = action_fingerprint(a)
    lines = [marker(fp), "",
             f"**{_label_of(a)}** in `{display or a.get('repo')}` — {a.get('status')}", ""]
    if a.get("recommendation"):
        lines += [f"➡️ {a['recommendation']}", ""]
    if a.get("command"):
        lines += [f"```\n{a['command']}\n```", ""]
    sites = _sites_md(a)
    if sites:
        lines += ["Call-sites:", *sites, ""]
    if a.get("sources"):
        lines += ["Source(s): " + ", ".join(a["sources"]), ""]
    lines += [_footer(links)]
    return "\n".join(lines)


# ----------------------------------------------------- absorption flags (shape stream, maintainer)
def shape_issue_title(shape: dict, display: str | None = None) -> str:
    n = shape.get("unattributedPaths", 0)
    reasons = ", ".join(shape.get("reasons", [])) or "unreadable shape"
    return (f"[drift] absorption needed: {display or shape.get('repo')} "
            f"— {n} unattributed path(s) ({reasons})")


def shape_issue_body(shape: dict, display: str | None = None,
                     samples: list | None = None, links: dict | None = None) -> str:
    """A maintainer-facing flag: this repo has a shape the scanner can't fully read. Carries
    the WHY (verdict + reasons), the exact blind-spot file:lines, the residueFingerprint (the
    token the resolving MR cites), and the bootstrap to absorb it. This is NOT a finding — it's
    a request to teach the scanner. Closes itself once the repo goes KNOWN (see _finish)."""
    fp = shape_fingerprint(shape.get("repo"))
    langs = ", ".join((shape.get("languages") or {}).keys())
    lines = [marker(fp), "",
             f"**Absorption needed** — `{display or shape.get('repo')}` came back "
             f"**{shape.get('verdict')}**: the deterministic scanner could not fully read its "
             f"integration calls, so its findings are incomplete (“cannot see” is not "
             f"“clean”).", "",
             f"- **Why:** {', '.join(shape.get('reasons', [])) or 'unreadable shape'}",
             f"- **Languages:** {langs or '?'}",
             f"- **Attributed / unattributed:** {shape.get('attributed', 0)} attributed · "
             f"{shape.get('unattributedPaths', 0)} path(s) + {shape.get('unresolvedSinks', 0)} "
             f"sink(s) unread",
             f"- **Residue fingerprint:** `{shape.get('residueFingerprint', '')}` "
             f"_(the absorption MR that resolves this should cite it)_", ""]
    caps = (samples or [])[:12]
    if caps:
        lines.append("**Blind spots** — versioned paths seen but not attributed:")
        for s in caps:
            loc, samp = s.get("loc"), s.get("sample")
            lines.append(f"  - `{loc}` — `{samp}`" if samp else f"  - `{loc}`")
        if len(samples) > 12:
            lines.append(f"  - …and {len(samples) - 12} more (see the report)")
        lines.append("")
    lines += ["**To absorb this shape** (a maintainer with access to the flagged repo):",
              "```",
              "git clone <the flagged repo> && cd <repo>",
              "export DRIFT_OPS_DIR=<your drift-ops checkout>   # where the learned overlay lives",
              "/drift-detector .        # scan it locally",
              "/drift-absorb .          # investigate the blind spots, teach the scanner",
              "```",
              "_The absorbed idioms/sunsets land as a reviewed MR on drift-ops; the next fleet "
              "scan then sees this repo KNOWN and closes this issue on its own._", "",
              _footer(links)]
    return "\n".join(lines)


# --------------------------------------------------------------- MR content (Developer)
def migrations_md(repo: str, actions: list, links: dict | None = None) -> str:
    fp = repo_fingerprint(repo)
    out = ["# API migrations — Drift Detector", "",
           "Retiring vendor APIs / end-of-life frameworks this repo calls. Do the migration "
           "on this branch; this checklist is regenerated each scan.", "", marker(fp), ""]
    for a in actions:
        out.append(f"## {_label_of(a)} — {a.get('status')}"
                   + (f" · retires {a['date']}" if a.get("date") else ""))
        if a.get("recommendation"):
            out.append(a["recommendation"])
        sites = _sites_md(a)
        if sites:
            out += ["", "Call-sites:", *sites]
        if a.get("sources"):
            out.append("Source(s): " + ", ".join(a["sources"]))
        out.append("")
    out.append(_footer(links))
    return "\n".join(out)


def mr_title(repo: str) -> str:
    return f"Draft: [drift] API migrations for {repo}"


def mr_description(repo: str, actions: list, links: dict | None = None) -> str:
    fp = repo_fingerprint(repo)
    n = len(actions)
    lines = [marker(fp), "",
             f"Drift Detector found **{n}** retiring API surface(s) / EOL framework(s) this "
             f"repo calls. The checklist is in `{MIGRATIONS_PATH}` on this branch; migrate "
             f"here and this draft becomes your fix.", ""]
    for a in actions:
        when = f" (retires {a['date']})" if a.get("date") else ""
        lines.append(f"- **{_label_of(a)}**{when} — {a.get('recommendation') or a.get('status')}")
    lines += ["", _footer(links, draft=True)]
    return "\n".join(lines)


def _norm(s: str) -> str:
    """Normalise for the change-check: GitLab returns descriptions with CRLF and can trim
    trailing whitespace, so a raw compare against our LF body always looks 'changed' and the
    issue gets rewritten every run (noise, notifications). Compare on normalised text so an
    unchanged issue truly SKIPS."""
    return "\n".join(line.rstrip() for line in
                     str(s or "").replace("\r\n", "\n").split("\n")).strip()


def _issue_op(fp: str, title: str, body: str, by_fp: dict, project: str) -> dict:
    """create / update / skip / reopen an issue by its marker fingerprint."""
    iss = by_fp.get(fp)
    if iss is None:
        return {"op": "create", "fp": fp, "project": project, "title": title, "body": body}
    changed = (_norm(iss.get("description")) != _norm(body)) or (iss.get("state") == "closed")
    return {"op": "update" if changed else "skip", "fp": fp, "project": project,
            "iid": iss.get("iid"), "title": title, "body": body,
            "reopen": iss.get("state") == "closed"}


# ----------------------------------------------------------------------- the planner (pure)
def build_plan(payload: dict, repo_meta: dict, existing: dict, devops_project: str,
               *, dev_as_issues: bool = False, links: dict | None = None,
               shape_stream: bool = False, freshness_stream: bool = False) -> dict:
    """Compute the create/update/close plan. PURE: no I/O.

    `repo_meta`   : {repo -> {"project": "group/repo"}} for the scanned repos.
    `existing`    : {"issues": [issue dicts from devops_project],
                     "mrs": {project -> [mr dicts]}} already on GitLab.
    `dev_as_issues`: file the Developer stream as ISSUES (one per repo, in devops_project)
                     instead of draft MRs — the Reporter-friendly fallback when we lack
                     Developer access on the scanned repos.
    `shape_stream`: also file a MAINTAINER-facing "absorption needed" issue (one per repo) for
                    every UNKNOWN shape in the payload — the repo has integration calls the
                    scanner could not read. Repo-keyed, updates in place, and closes itself via
                    `_finish` once the repo goes KNOWN.
    `freshness_stream`: also file THE maintainer catalog-freshness work-order (one issue for
                    the whole catalog) while any DETECTED vendor is STALE/unaudited and off the
                    auto lane — the drift:freshness label's producer. Constant-keyed, updates
                    in place, closes itself via `_finish` when the due-list empties.
    Returns {"issues": [...], "mrs": [...]} where each item has an `op`
    (create|update|close|skip) and the rendered content.
    """
    actions = payload.get("actions", [])
    devops = [a for a in actions if a.get("owner") == "devops"]
    developer = [a for a in actions if a.get("owner") == "developer"]

    existing_issues = existing.get("issues", [])
    by_fp = {}
    for iss in existing_issues:
        for fp in markers_in(iss.get("description", "")):
            by_fp[fp] = iss
    issue_plan, live_fps = [], set()

    # ---- issues (DevOps: one per action) ----
    for a in devops:
        fp = action_fingerprint(a)
        live_fps.add(fp)
        display = (repo_meta.get(a.get("repo")) or {}).get("project") or a.get("repo")
        issue_plan.append(_issue_op(fp, issue_title(a), issue_body(a, display, links),
                                    by_fp, devops_project))

    # ---- absorption flags (maintainer: one per UNKNOWN shape) ----
    # Placed before the dev branch so it lands in issue_plan + live_fps for BOTH return paths;
    # a repo that goes KNOWN drops out of live_fps and _finish closes its flag automatically.
    if shape_stream:
        samples_by_repo: dict = {}
        for s in payload.get("residueSamples", []):
            samples_by_repo.setdefault(s.get("repo"), []).append(s)
        for sh in payload.get("shapes", []):
            if sh.get("verdict") != "UNKNOWN":
                continue
            repo = sh.get("repo")
            fp = shape_fingerprint(repo)
            live_fps.add(fp)
            display = (repo_meta.get(repo) or {}).get("project") or sh.get("repoLabel") or repo
            op = _issue_op(fp, shape_issue_title(sh, display),
                           shape_issue_body(sh, display, samples_by_repo.get(repo), links),
                           by_fp, devops_project)
            op["stream"] = "shape"          # so execute_plan labels it drift:shape
            issue_plan.append(op)

    # ---- freshness work-order (maintainer: ONE issue while any vendor is due) ----
    # The human-lane twin of catalog-check, DELIVERED: which detected vendors' retirement
    # audit is STALE or never done and no machine can re-fetch their source, with the right
    # action per vendor (freshness.work_order_md — the same body `drift-scan freshness`
    # renders). Until this block existed the drift:freshness label had a taxonomy and an
    # execute_plan branch but no producer — the due-list lived only in a CLI nobody was
    # required to run. Placed with the shape block so it lands in live_fps for both return
    # paths; an emptied due-list drops the fp and _finish closes the work-order on its own.
    if freshness_stream:
        from agent import catalog_check
        from agent.lib import freshness as freshness_mod
        due = freshness_mod.due_for_refresh(payload.get("catalog", []),
                                            set(catalog_check.CHECKS),
                                            catalog_check.UNAUTOMATED)
        if due:
            fp = freshness_fingerprint()
            live_fps.add(fp)
            # `generated` (the scan date in the payload) — never wall-clock — keeps the
            # body a pure function of the payload, so an unchanged due-list SKIPS.
            body = (marker(fp) + "\n\n"
                    + freshness_mod.work_order_md(due, payload.get("generated", "")))
            op = _issue_op(fp, f"[drift] catalog freshness: {len(due)} vendor(s) due a re-check",
                           body, by_fp, devops_project)
            op["stream"] = "freshness"      # so execute_plan labels it drift:freshness
            issue_plan.append(op)

    # ---- Developer stream: one per scanned repo, as a draft MR OR (fallback) an issue ----
    by_repo = {}
    for a in developer:
        by_repo.setdefault(a.get("repo"), []).append(a)
    mr_plan = []

    if dev_as_issues:
        for repo, acts in by_repo.items():
            project = (repo_meta.get(repo) or {}).get("project") or repo
            fp = repo_fingerprint(project)          # same key the body marker uses
            live_fps.add(fp)
            title = f"[drift] API migrations for {project}"
            issue_plan.append(_issue_op(fp, title, migrations_md(project, acts, links),
                                        by_fp, devops_project))
        return _finish(issue_plan, mr_plan, by_fp, live_fps, devops_project)

    for repo, acts in by_repo.items():
        meta = repo_meta.get(repo) or {}
        project = meta.get("project")
        if not project:
            mr_plan.append({"op": "unroutable", "repo": repo, "count": len(acts)})
            continue
        mrs = existing.get("mrs", {}).get(project, [])
        mine = next((m for m in mrs if m.get("source_branch") == MR_BRANCH), None)
        # display by the clean project path, not the internal clone slug (chetan/amazonspapi,
        # not chetan-amazonspapi-f5043548)
        item = {"repo": repo, "project": project, "branch": MR_BRANCH,
                "title": mr_title(project), "description": mr_description(project, acts, links),
                "file_path": MIGRATIONS_PATH, "file_content": migrations_md(project, acts, links),
                "count": len(acts)}
        if mine is None:
            item["op"] = "create"
        else:
            item["op"] = "update"
            item["iid"] = mine.get("iid")
        mr_plan.append(item)

    return _finish(issue_plan, mr_plan, by_fp, live_fps, devops_project)


def _finish(issue_plan, mr_plan, by_fp, live_fps, devops_project) -> dict:
    """Close issues we filed whose fingerprint is no longer among the findings — a resolved
    finding must not leave a stale open issue (the human 'cannot see = clean' trap)."""
    for fp, iss in by_fp.items():
        if fp not in live_fps and iss.get("state") != "closed":
            issue_plan.append({"op": "close", "fp": fp, "project": devops_project,
                               "iid": iss.get("iid"), "title": iss.get("title")})
    return {"issues": issue_plan, "mrs": mr_plan}


def plan_summary(plan: dict) -> str:
    def tally(items):
        c = {}
        for it in items:
            c[it["op"]] = c.get(it["op"], 0) + 1
        return ", ".join(f"{v} {k}" for k, v in sorted(c.items())) or "nothing"
    return (f"issues: {tally(plan['issues'])}\n"
            f"draft MRs: {tally(plan['mrs'])}")


def plan_detail(plan: dict) -> str:
    """A human-readable, line-per-item view for --dry-run."""
    lines = ["── DevOps issues " + "─" * 40]
    for it in plan["issues"]:
        loc = f"#{it['iid']}" if it.get("iid") else "new"
        lines.append(f"  {it['op']:7} [{loc}] {it.get('title', '')}  → {it['project']}")
    lines.append("── Developer draft MRs " + "─" * 34)
    for it in plan["mrs"]:
        if it["op"] == "unroutable":
            lines.append(f"  UNROUTABLE  {it['repo']} ({it['count']} finding(s)) — "
                         f"no GitLab project known for this repo")
            continue
        loc = f"!{it['iid']}" if it.get("iid") else "new"
        lines.append(f"  {it['op']:7} [{loc}] {it['title']}  "
                     f"({it['count']} finding(s), branch {it['branch']})")
    return "\n".join(lines)


# ------------------------------------------------------------------------------- I/O
def fetch_existing(gl, devops_project: str, dev_projects: list) -> dict:
    """What drift-detector has already filed: labelled issues in the DevOps project, and
    labelled MRs in each scanned project. Read-only — safe in --dry-run."""
    return {"issues": gl.list_issues(devops_project, labels=LABEL),
            "mrs": {p: gl.list_mrs(p, labels=LABEL) for p in dev_projects}}


def _issue_labels(stream: str) -> str:
    """The label set for an issue by stream. Maintainer streams (shape, freshness) carry the
    shared `drift:maintainer` audience tag AND their own stream tag, so all tool-upkeep work
    filters as one queue while staying distinguishable; the DevOps finding stream stands alone."""
    if stream == "shape":
        return f"{LABEL},{MAINTAINER_LABEL},{SHAPE_LABEL}"
    if stream == "freshness":
        return f"{LABEL},{MAINTAINER_LABEL},{FRESHNESS_LABEL}"
    return f"{LABEL},{DEVOPS_LABEL}"


def execute_plan(gl, plan: dict) -> dict:
    """Perform the writes. Every op is idempotent given the same plan."""
    done = {"created": 0, "updated": 0, "closed": 0, "skipped": 0, "unroutable": 0}
    for it in plan["issues"]:
        if it["op"] == "create":
            gl.create_issue(it["project"], title=it["title"], description=it["body"],
                            labels=_issue_labels(it.get("stream")))
            done["created"] += 1
        elif it["op"] == "update":
            fields = {"description": it["body"], "title": it["title"]}
            if it.get("reopen"):
                fields["state_event"] = "reopen"
            gl.update_issue(it["project"], it["iid"], **fields)
            done["updated"] += 1
        elif it["op"] == "close":
            gl.update_issue(it["project"], it["iid"], state_event="close")
            done["closed"] += 1
        else:
            done["skipped"] += 1
    for it in plan["mrs"]:
        if it["op"] == "unroutable":
            done["unroutable"] += 1
            continue
        project, branch = it["project"], it["branch"]
        default = (gl.project(project) or {}).get("default_branch") or "main"
        if gl.branch(project, branch) is None:
            gl.create_branch(project, branch, default)
        existing_file = gl.get_file(project, it["file_path"], branch)
        gl.set_file(project, it["file_path"], branch=branch, content=it["file_content"],
                    message="drift: update migration checklist",
                    exists=existing_file is not None)
        if it["op"] == "create":
            gl.create_mr(project, source_branch=branch, target_branch=default,
                         title=it["title"], description=it["description"],
                         labels=f"{LABEL},{DEV_LABEL}")
            done["created"] += 1
        else:
            gl.update_mr(project, it["iid"], description=it["description"], title=it["title"])
            done["updated"] += 1
    return done
