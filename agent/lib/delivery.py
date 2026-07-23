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


def issue_body(a: dict, display: str | None = None) -> str:
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
    lines += ["_Filed by Drift Detector — updates in place on the next scan._"]
    return "\n".join(lines)


# --------------------------------------------------------------- MR content (Developer)
def migrations_md(repo: str, actions: list) -> str:
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
    return "\n".join(out)


def mr_title(repo: str) -> str:
    return f"Draft: [drift] API migrations for {repo}"


def mr_description(repo: str, actions: list) -> str:
    fp = repo_fingerprint(repo)
    n = len(actions)
    lines = [marker(fp), "",
             f"Drift Detector found **{n}** retiring API surface(s) / EOL framework(s) this "
             f"repo calls. The checklist is in `{MIGRATIONS_PATH}` on this branch; migrate "
             f"here and this draft becomes your fix.", ""]
    for a in actions:
        when = f" (retires {a['date']})" if a.get("date") else ""
        lines.append(f"- **{_label_of(a)}**{when} — {a.get('recommendation') or a.get('status')}")
    lines += ["", "_Draft, filed by Drift Detector — updates in place on the next scan._"]
    return "\n".join(lines)


# ----------------------------------------------------------------------- the planner (pure)
def build_plan(payload: dict, repo_meta: dict, existing: dict, devops_project: str) -> dict:
    """Compute the create/update/close plan. PURE: no I/O.

    `repo_meta`   : {repo -> {"project": "group/repo"}} for the scanned repos.
    `existing`    : {"issues": [issue dicts from devops_project],
                     "mrs": {project -> [mr dicts]}} already on GitLab.
    Returns {"issues": [...], "mrs": [...]} where each item has an `op`
    (create|update|close|skip) and the rendered content.
    """
    actions = payload.get("actions", [])
    devops = [a for a in actions if a.get("owner") == "devops"]
    developer = [a for a in actions if a.get("owner") == "developer"]

    # ---- issues (DevOps) ----
    existing_issues = existing.get("issues", [])
    by_fp = {}
    for iss in existing_issues:
        for fp in markers_in(iss.get("description", "")):
            by_fp[fp] = iss
    issue_plan, live_fps = [], set()
    for a in devops:
        fp = action_fingerprint(a)
        live_fps.add(fp)
        display = (repo_meta.get(a.get("repo")) or {}).get("project") or a.get("repo")
        title, body = issue_title(a), issue_body(a, display)
        iss = by_fp.get(fp)
        if iss is None:
            issue_plan.append({"op": "create", "fp": fp, "project": devops_project,
                               "title": title, "body": body})
        else:
            changed = (iss.get("description") != body) or (iss.get("state") == "closed")
            issue_plan.append({"op": "update" if changed else "skip", "fp": fp,
                               "project": devops_project, "iid": iss.get("iid"),
                               "title": title, "body": body,
                               "reopen": iss.get("state") == "closed"})
    # close issues we filed that no longer correspond to a finding
    for fp, iss in by_fp.items():
        if fp not in live_fps and iss.get("state") != "closed":
            issue_plan.append({"op": "close", "fp": fp, "project": devops_project,
                               "iid": iss.get("iid"), "title": iss.get("title")})

    # ---- draft MRs (Developer), one per scanned repo ----
    by_repo = {}
    for a in developer:
        by_repo.setdefault(a.get("repo"), []).append(a)
    mr_plan = []
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
                "title": mr_title(project), "description": mr_description(project, acts),
                "file_path": MIGRATIONS_PATH, "file_content": migrations_md(project, acts),
                "count": len(acts)}
        if mine is None:
            item["op"] = "create"
        else:
            item["op"] = "update"
            item["iid"] = mine.get("iid")
        mr_plan.append(item)

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


def execute_plan(gl, plan: dict) -> dict:
    """Perform the writes. Every op is idempotent given the same plan."""
    done = {"created": 0, "updated": 0, "closed": 0, "skipped": 0, "unroutable": 0}
    for it in plan["issues"]:
        if it["op"] == "create":
            gl.create_issue(it["project"], title=it["title"], description=it["body"],
                            labels=f"{LABEL},{DEVOPS_LABEL}")
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
