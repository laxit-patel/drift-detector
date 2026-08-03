# Issues-only Delivery (SP-A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver findings as two comprehensive, idempotent issues per flagged repo — a DevOps issue and a Developer issue — filed **in that repo's own GitLab tracker**, each **assigned** (DevOps → a configured account; Developer → the repo owner), with the draft-MR path retired.

**Architecture:** Keep the pure `build_plan` / `execute_plan` split. The planner groups actions by (repo, audience) into one issue op each, targeting the repo's own project, carrying a pre-resolved assignee id + a stream tag. All GitLab I/O (members/user lookup, per-repo issue fetch, create/update with assignee) stays behind `agent/lib/gitlab_api.py` with `fetch` injected. Owner resolution is pure given a members list.

**Tech Stack:** Python 3.12 (stdlib + PyYAML), pytest, GitLab REST v4.

## Global Constraints

- Python 3.12 in `.venv`. Run tests with `.venv/bin/python -m pytest -q`. Stdlib + PyYAML only — NO new dependency.
- `build_plan` and all fingerprint/body/owner-resolution helpers stay **PURE** (no I/O); GitLab I/O only in `gitlab_api.py` and the `deliver` executor, with `fetch`/`gl` injected in every test. **No network in any unit test.**
- ADDITIVE config: the new `delivery.devops.assignee` / `delivery.developer.fallbackAssignee` are v2-stream keys; the v1 form (`dev_as_issues`, `devops_project`) still parses. `verify` is unaffected (delivery is downstream of drift.json, not a verified surface).
- Two issues per flagged repo, **by audience**, **in the repo's own project**, idempotent (per-repo, per-audience fingerprint → create/update/skip/close in place). Labels: `drift:devops` / `drift:developer` (+ existing `drift-detector`).
- Assignment: DevOps → the configured account; Developer → repo owner via members API (first **Owner** role, else first **Maintainer**, else `fallbackAssignee`, else unassigned + a body note). Resolution is deterministic (members sorted by `id`).
- The maintainer/absorption + freshness streams (shape/freshness issues, catalog MRs) are **UNTOUCHED**.
- "Cannot see ≠ clean": a repo whose issue fails to file is **reported in the exit summary**, never silently dropped.
- TDD, frequent commits, DRY, YAGNI.

**Existing signatures this plan builds on (do not change their behavior except as stated):**
- `agent/lib/delivery.py`: `repo_fingerprint(repo)`, `action_fingerprint(a)`, `migrations_md(repo, actions, links)`, `_issue_op(fp, title, body, by_fp, project)`, `_issue_labels(stream)`, `build_plan(payload, repo_meta, existing, devops_project, *, dev_as_issues, links, shape_stream, freshness_stream)`, `fetch_existing(gl, devops_project, dev_projects)`, `execute_plan(gl, plan)`, `LABEL`, `DEVOPS_LABEL`, `DEVELOPER_LABEL`, `marker(fp)`.
- `agent/lib/gitlab_api.py`: `GitLab(host, token, *, fetch)`, `_call`, `_paged`, `create_issue(project_id, *, title, description, labels)`, `update_issue(project_id, iid, **fields)`, `list_issues(project_id, *, labels)`.
- `agent/lib/ops_config.py`: `_STREAM = {"target","project"}`, `_stream(where, block, *, default_target)`, `_load_delivery`, v2 keys `delivery.devops`/`delivery.developer`.

---

### Task 1: GitLab API — members, user lookup, assignee on issues

**Files:**
- Modify: `agent/lib/gitlab_api.py` (add `members`, `user_id`; extend `create_issue`/`update_issue`)
- Test: `tests/test_gitlab_api.py`

**Interfaces:**
- Produces: `GitLab.members(project_id) -> list[dict]` (each `{id, username, access_level}`); `GitLab.user_id(username) -> int | None`; `create_issue(..., assignee_ids=None)`; `update_issue` already accepts `**fields` (pass `assignee_ids=[...]`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gitlab_api.py  (add)
from agent.lib.gitlab_api import GitLab


def _fake(routes):
    calls = []
    def fetch(url, *, method="GET", token=None, body=None):
        calls.append((method, url, body))
        for frag, resp in routes.items():
            if frag in url:
                return resp
        return []
    return fetch, calls


def test_members_lists_inherited_members():
    fetch, _ = _fake({"/members/all": [{"id": 5, "username": "ann", "access_level": 50},
                                        {"id": 6, "username": "bo", "access_level": 40}]})
    gl = GitLab("git.x", "t", fetch=fetch)
    assert gl.members("g/r") == [{"id": 5, "username": "ann", "access_level": 50},
                                 {"id": 6, "username": "bo", "access_level": 40}]


def test_user_id_resolves_username():
    fetch, _ = _fake({"/users?username=ann": [{"id": 5, "username": "ann"}]})
    assert GitLab("git.x", "t", fetch=fetch).user_id("ann") == 5
    fetch2, _ = _fake({"/users?username=ghost": []})
    assert GitLab("git.x", "t", fetch=fetch2).user_id("ghost") is None


def test_create_issue_sends_assignee_ids():
    fetch, calls = _fake({"/issues": {"iid": 1}})
    GitLab("git.x", "t", fetch=fetch).create_issue("g/r", title="T", description="B",
                                                    labels="drift-detector", assignee_ids=[5])
    method, url, body = calls[-1]
    assert method == "POST" and body.get("assignee_ids") == [5]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_gitlab_api.py -q -k "members or user_id or assignee"`
Expected: FAIL (`AttributeError: 'GitLab' object has no attribute 'members'`)

- [ ] **Step 3: Write minimal implementation**

In `agent/lib/gitlab_api.py`, add methods to the `GitLab` class and extend `create_issue`:

```python
    def members(self, project_id) -> list:
        # members/all includes inherited (group) members, so a group-owned repo resolves an owner
        return self._paged(f"/projects/{_enc(str(project_id))}/members/all")

    def user_id(self, username: str):
        if not username:
            return None
        res = self._call("GET", f"/users?username={_enc(username)}")
        return res[0]["id"] if isinstance(res, list) and res else None

    def create_issue(self, project_id, *, title, description, labels, assignee_ids=None) -> dict:
        body = {"title": title, "description": description, "labels": labels}
        if assignee_ids:
            body["assignee_ids"] = assignee_ids
        return self._call("POST", f"/projects/{_enc(str(project_id))}/issues", body=body)
```
(`update_issue(project_id, iid, **fields)` already forwards arbitrary fields, so `assignee_ids=[...]` needs no change — verify it does in the test if unsure.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_gitlab_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/lib/gitlab_api.py tests/test_gitlab_api.py
git commit -m "feat(gitlab): members() + user_id() + assignee_ids on issue create"
```

---

### Task 2: Delivery pure helpers — owner resolution, per-audience fingerprint, DevOps body

**Files:**
- Modify: `agent/lib/delivery.py` (add `resolve_owner`, extend `repo_fingerprint`, add `devops_repo_body`)
- Test: `tests/test_delivery.py`

**Interfaces:**
- Produces: `resolve_owner(members: list, fallback_id: int | None) -> int | None`; `repo_fingerprint(repo, stream="")` (namespaced, back-compat when `stream==""`); `devops_repo_body(repo, actions, links=None) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_delivery.py  (add)
from agent.lib.delivery import resolve_owner, repo_fingerprint, devops_repo_body


def test_resolve_owner_prefers_owner_then_maintainer_then_fallback():
    members = [{"id": 6, "username": "bo", "access_level": 40},   # Maintainer
               {"id": 5, "username": "ann", "access_level": 50}]  # Owner
    assert resolve_owner(members, 99) == 5                        # Owner (50) wins
    assert resolve_owner([{"id": 6, "access_level": 40}], 99) == 6   # Maintainer (40)
    assert resolve_owner([{"id": 7, "access_level": 30}], 99) == 99  # Developer -> fallback
    assert resolve_owner([], None) is None                       # nothing -> unassigned


def test_resolve_owner_is_deterministic_across_equal_access():
    members = [{"id": 8, "access_level": 50}, {"id": 3, "access_level": 50}]
    assert resolve_owner(members, None) == 3                      # lowest id among equal Owners


def test_repo_fingerprint_namespaced_by_stream_and_backcompat():
    assert repo_fingerprint("g/r") == repo_fingerprint("g/r", "")   # back-compat
    assert repo_fingerprint("g/r", "devops") != repo_fingerprint("g/r", "developer")


def test_devops_repo_body_bundles_actions_with_marker():
    acts = [{"kind": "eol", "ref": "php", "status": "DEPRECATED", "recommendation": "upgrade php"},
            {"kind": "cve", "ref": "guzzle", "status": "DEPRECATED"}]
    body = devops_repo_body("g/r", acts)
    assert "php" in body and "guzzle" in body
    from agent.lib.delivery import marker, repo_fingerprint as rfp
    assert marker(rfp("g/r", "devops")) in body                  # idempotency marker present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_delivery.py -q -k "resolve_owner or namespaced or devops_repo_body"`
Expected: FAIL (`ImportError: cannot import name 'resolve_owner'`)

- [ ] **Step 3: Write minimal implementation**

In `agent/lib/delivery.py`:

```python
def resolve_owner(members: list, fallback_id):
    """The repo owner to assign a Developer issue to: highest GitLab access_level (Owner=50 >
    Maintainer=40), ties broken by lowest id (deterministic), else the config fallback, else None
    (unassigned). Pure — the members list is fetched by the caller."""
    eligible = [m for m in members if (m.get("access_level") or 0) >= 40]   # Maintainer+
    if eligible:
        best = min(eligible, key=lambda m: (-(m.get("access_level") or 0), m.get("id", 1 << 62)))
        return best.get("id")
    return fallback_id
```

Change `repo_fingerprint` to namespace by stream (keeping `stream=""` identical to today):

```python
def repo_fingerprint(repo: str, stream: str = "") -> str:
    raw = f"repo|{stream}|{repo}" if stream else f"repo|{repo}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

Add the DevOps per-repo body (mirrors `migrations_md`, DevOps framing, its own marker):

```python
def devops_repo_body(repo: str, actions: list, links: dict | None = None) -> str:
    fp = repo_fingerprint(repo, "devops")
    out = ["# Platform upkeep — Drift Detector", "",
           "Package vulnerabilities and runtime end-of-life for this repo. Bump the "
           "manifest/lockfile or base image; this list is regenerated each scan.", "",
           marker(fp), ""]
    for a in actions:
        out.append(f"## {_label_of(a)} — {a.get('status')}"
                   + (f" · retires {a['date']}" if a.get("date") else ""))
        if a.get("recommendation"):
            out.append(a["recommendation"])
        if a.get("cves"):
            out += ["", "CVEs: " + ", ".join(str(c.get("id")) for c in a["cves"])]
        if a.get("sources"):
            out.append("Source(s): " + ", ".join(a["sources"]))
        out.append("")
    out.append(_footer(links))
    return "\n".join(out)
```

Also update `migrations_md` to namespace its marker as the developer stream: change its first line
`fp = repo_fingerprint(repo)` → `fp = repo_fingerprint(repo, "developer")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_delivery.py -q`
Expected: PASS (existing delivery tests + new — note `migrations_md`'s marker changed, so update any existing test asserting its exact fingerprint)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/delivery.py tests/test_delivery.py
git commit -m "feat(delivery): resolve_owner + per-audience repo_fingerprint + devops_repo_body"
```

---

### Task 3: Planner — two per-repo, in-repo, assigned issues; retire developer MRs

**Files:**
- Modify: `agent/lib/delivery.py` (`build_plan` DevOps + Developer branches; `_issue_op` + `_issue_labels`)
- Test: `tests/test_delivery.py`

**Interfaces:**
- Consumes: `resolve_owner`, `devops_repo_body`, `repo_fingerprint(repo, stream)` (Task 2).
- Produces: `build_plan(..., *, assignees=None)` where `assignees = {"devops": id|None, "developer": {repo: id|None}}`. Each issue op gains `"assignee": id|None` and `"stream": "devops"|"developer"`. Ops target the repo's own project. `plan["mrs"]` is empty for findings.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_delivery.py  (add)
from agent.lib.delivery import build_plan


def _payload(actions):
    return {"actions": actions}


def test_devops_is_one_issue_per_repo_in_repo_assigned():
    payload = _payload([
        {"owner": "devops", "repo": "r1", "kind": "eol", "ref": "php", "status": "DEPRECATED"},
        {"owner": "devops", "repo": "r1", "kind": "cve", "ref": "guzzle", "status": "DEPRECATED"}])
    repo_meta = {"r1": {"project": "g/r1"}}
    plan = build_plan(payload, repo_meta, {"issues": {}, "mrs": {}}, "g/ops",
                      dev_as_issues=True, assignees={"devops": 5, "developer": {}})
    devops_issues = [i for i in plan["issues"] if i.get("stream") == "devops"]
    assert len(devops_issues) == 1                      # ONE per repo, not per action
    it = devops_issues[0]
    assert it["project"] == "g/r1" and it["assignee"] == 5    # in-repo + assigned to DevOps acct
    assert "php" in it["body"] and "guzzle" in it["body"]     # comprehensive


def test_developer_issue_in_repo_assigned_to_owner_no_mrs():
    payload = _payload([{"owner": "developer", "repo": "r1", "kind": "sunset", "ref": "Catch",
                         "status": "DEPRECATED"}])
    repo_meta = {"r1": {"project": "g/r1"}}
    plan = build_plan(payload, repo_meta, {"issues": {}, "mrs": {}}, "g/ops",
                      dev_as_issues=True, assignees={"devops": 5, "developer": {"r1": 7}})
    dev = [i for i in plan["issues"] if i.get("stream") == "developer"]
    assert len(dev) == 1 and dev[0]["project"] == "g/r1" and dev[0]["assignee"] == 7
    assert plan["mrs"] == []                            # no finding MRs


def test_devops_and_developer_for_one_repo_have_distinct_fingerprints():
    payload = _payload([
        {"owner": "devops", "repo": "r1", "kind": "cve", "ref": "guzzle", "status": "DEPRECATED"},
        {"owner": "developer", "repo": "r1", "kind": "sunset", "ref": "Catch", "status": "DEPRECATED"}])
    plan = build_plan(payload, {"r1": {"project": "g/r1"}}, {"issues": {}, "mrs": {}}, "g/ops",
                      dev_as_issues=True, assignees={"devops": 5, "developer": {"r1": 7}})
    fps = {i["fp"] for i in plan["issues"] if i.get("stream") in ("devops", "developer")}
    assert len(fps) == 2                                # no collision between the two audiences
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_delivery.py -q -k "one_issue_per_repo or in_repo_assigned or distinct_fingerprints"`
Expected: FAIL (DevOps still per-action / no `assignees` kwarg)

- [ ] **Step 3: Write minimal implementation**

In `agent/lib/delivery.py`:

Add `assignee` to `_issue_op` output (default None; the DevOps/Developer branches set it):

```python
def _issue_op(fp, title, body, by_fp, project, *, assignee=None) -> dict:
    iss = by_fp.get(fp)
    if iss is None:
        return {"op": "create", "fp": fp, "project": project, "title": title, "body": body,
                "assignee": assignee}
    changed = (_norm(iss.get("description")) != _norm(body)) or (iss.get("state") == "closed")
    return {"op": "update" if changed else "skip", "fp": fp, "project": project,
            "iid": iss.get("iid"), "title": title, "body": body, "assignee": assignee,
            "reopen": iss.get("state") == "closed"}
```

Add the `developer` label branch to `_issue_labels`:

```python
def _issue_labels(stream: str) -> str:
    if stream == "shape":
        return f"{LABEL},{MAINTAINER_LABEL},{SHAPE_LABEL}"
    if stream == "freshness":
        return f"{LABEL},{MAINTAINER_LABEL},{FRESHNESS_LABEL}"
    if stream == "developer":
        return f"{LABEL},{DEVELOPER_LABEL}"
    return f"{LABEL},{DEVOPS_LABEL}"
```

Change `build_plan`'s signature to accept `assignees` and rewrite the DevOps + Developer branches
(the shape/freshness blocks between them are UNCHANGED):

```python
def build_plan(payload, repo_meta, existing, devops_project, *, dev_as_issues=False,
               links=None, shape_stream=False, freshness_stream=False, assignees=None):
    assignees = assignees or {"devops": None, "developer": {}}
    actions = payload.get("actions", [])
    devops = [a for a in actions if a.get("owner") == "devops"]
    developer = [a for a in actions if a.get("owner") == "developer"]
    existing_issues = existing.get("issues", [])
    by_fp = {}
    for iss in existing_issues:
        for fp in markers_in(iss.get("description", "")):
            by_fp[fp] = iss
    issue_plan, live_fps = [], set()

    # ---- DevOps: ONE comprehensive issue per repo, IN the repo, assigned to the DevOps account ----
    devops_by_repo = {}
    for a in devops:
        devops_by_repo.setdefault(a.get("repo"), []).append(a)
    for repo, acts in devops_by_repo.items():
        project = (repo_meta.get(repo) or {}).get("project") or repo
        fp = repo_fingerprint(project, "devops")
        live_fps.add(fp)
        op = _issue_op(fp, f"[drift] platform upkeep for {project}",
                       devops_repo_body(project, acts, links), by_fp, project,
                       assignee=assignees.get("devops"))
        op["stream"] = "devops"
        issue_plan.append(op)

    # ---- shape/freshness maintainer streams: UNCHANGED (keep the existing two blocks verbatim) ----
    # (they still target devops_project and use their own fingerprints/labels)

    # ---- Developer: ONE comprehensive issue per repo, IN the repo, assigned to the repo owner ----
    dev_by_repo = {}
    for a in developer:
        dev_by_repo.setdefault(a.get("repo"), []).append(a)
    for repo, acts in dev_by_repo.items():
        project = (repo_meta.get(repo) or {}).get("project") or repo
        fp = repo_fingerprint(project, "developer")
        live_fps.add(fp)
        op = _issue_op(fp, f"[drift] API migrations for {project}",
                       migrations_md(project, acts, links), by_fp, project,
                       assignee=(assignees.get("developer") or {}).get(repo))
        op["stream"] = "developer"
        issue_plan.append(op)

    return _finish(issue_plan, [], by_fp, live_fps, devops_project)
```

Keep the shape/freshness blocks exactly as they are today (paste them back between the DevOps and
Developer branches). The old `dev_as_issues`-vs-MR fork and the MR-building loop are **removed** —
findings are always in-repo issues now; `plan["mrs"]` is `[]`. `_finish` still closes stale fps.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_delivery.py -q`
Expected: PASS (update/remove any existing test that asserted per-action DevOps issues or developer MRs — those behaviors are intentionally replaced per the spec)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/delivery.py tests/test_delivery.py
git commit -m "feat(delivery): two per-repo in-repo assigned issues; retire developer MRs"
```

---

### Task 4: I/O layer — per-repo existing fetch + assignee on writes

**Files:**
- Modify: `agent/lib/delivery.py` (`fetch_existing`, `execute_plan`)
- Test: `tests/test_delivery.py`

**Interfaces:**
- Consumes: `GitLab.members`/`user_id`/`create_issue(assignee_ids=)` (Task 1); ops with `assignee` (Task 3).
- Produces: `fetch_existing(gl, devops_project, dev_projects)` now also fetches each dev project's issues; `execute_plan` sends `assignee_ids`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_delivery.py  (add)
from agent.lib.delivery import execute_plan, fetch_existing


class _FakeGL:
    def __init__(self, issues_by_project=None):
        self._issues = issues_by_project or {}
        self.created = []
    def list_issues(self, project, *, labels): return self._issues.get(project, [])
    def list_mrs(self, project, *, labels): return []
    def create_issue(self, project, *, title, description, labels, assignee_ids=None):
        self.created.append({"project": project, "assignee_ids": assignee_ids, "labels": labels})
        return {"iid": 1}
    def update_issue(self, project, iid, **fields): pass


def test_execute_plan_sends_assignee_ids():
    gl = _FakeGL()
    execute_plan(gl, {"issues": [{"op": "create", "project": "g/r1", "title": "T", "body": "B",
                                  "assignee": 7, "stream": "developer"}], "mrs": []})
    assert gl.created[0]["assignee_ids"] == [7]
    assert "drift:developer" in gl.created[0]["labels"]


def test_fetch_existing_reads_each_repo_tracker():
    gl = _FakeGL({"g/r1": [{"iid": 9, "description": "x"}], "g/ops": []})
    got = fetch_existing(gl, "g/ops", ["g/r1"])
    assert any(i["iid"] == 9 for i in got["issues"])         # the repo's own issue is seen
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_delivery.py -q -k "sends_assignee_ids or each_repo_tracker"`
Expected: FAIL (`create_issue` called without `assignee_ids`; `fetch_existing` reads only `devops_project`)

- [ ] **Step 3: Write minimal implementation**

`fetch_existing` — union the DevOps project's issues (for the still-central maintainer streams) with each dev project's issues:

```python
def fetch_existing(gl, devops_project: str, dev_projects: list) -> dict:
    issues = list(gl.list_issues(devops_project, labels=LABEL))
    for p in dev_projects:
        issues += gl.list_issues(p, labels=LABEL)
    return {"issues": issues, "mrs": {}}
```

`execute_plan` create/update — pass `assignee_ids`:

```python
    done["failed"] = []                              # (repo/project, reason) — "cannot see ≠ clean"
    for it in plan["issues"]:
        aid = [it["assignee"]] if it.get("assignee") else None
        try:
            if it["op"] == "create":
                gl.create_issue(it["project"], title=it["title"], description=it["body"],
                                labels=_issue_labels(it.get("stream")), assignee_ids=aid)
                done["created"] += 1
            elif it["op"] == "update":
                fields = {"description": it["body"], "title": it["title"]}
                if aid:
                    fields["assignee_ids"] = aid
                if it.get("reopen"):
                    fields["state_event"] = "reopen"
                gl.update_issue(it["project"], it["iid"], **fields)
                done["updated"] += 1
            elif it["op"] == "close":
                gl.update_issue(it["project"], it["iid"], state_event="close")
                done["closed"] += 1
            else:
                done["skipped"] += 1
        except Exception as exc:                     # a failed file is REPORTED, never dropped
            done["failed"].append((it.get("project"), str(exc)))
```
(The `plan["mrs"]` loop stays for the maintainer flow, which still emits none here; leave it intact.)

Add a test that a `create_issue` raising for one repo lands in `done["failed"]` and does NOT abort
the other repos' issues:

```python
def test_execute_plan_reports_a_failed_file_without_aborting():
    class _Boom(_FakeGL):
        def create_issue(self, project, **k):
            if project == "g/bad":
                raise RuntimeError("403")
            return super().create_issue(project, **k)
    gl = _Boom()
    done = execute_plan(gl, {"issues": [
        {"op": "create", "project": "g/bad", "title": "T", "body": "B", "stream": "devops"},
        {"op": "create", "project": "g/ok", "title": "T", "body": "B", "stream": "devops"}], "mrs": []})
    assert done["failed"] and done["failed"][0][0] == "g/bad"
    assert done["created"] == 1                       # g/ok still filed
```

Task 6's executor must **print `done["failed"]` and return a non-zero exit** when it is non-empty —
a delivery that intended N issues and filed fewer is not a clean run.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_delivery.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/lib/delivery.py tests/test_delivery.py
git commit -m "feat(delivery): fetch each repo's issues + send assignee_ids on writes"
```

---

### Task 5: Config — `devops.assignee` + `developer.fallbackAssignee`

**Files:**
- Modify: `agent/lib/ops_config.py` (`_STREAM`, `_stream`, `_load_delivery`)
- Test: `tests/test_ops_config.py`

**Interfaces:**
- Produces: `load(path)["delivery"]` gains `devopsAssignee: str | None` and `developerFallbackAssignee: str | None`. A missing `devops.assignee` while delivery would file DevOps issues is a `ConfigError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ops_config.py  (add)
import pytest
from agent.lib import ops_config


def _write(tmp_path, body):
    p = tmp_path / "drift.yml"; p.write_text(body); return str(p)


def test_delivery_parses_assignees(tmp_path):
    cfg = ops_config.load(_write(tmp_path, """
fleet: [https://git.x/g/r]
delivery:
  mode: create
  devops: { assignee: ops-bot }
  developer: { target: issues, fallbackAssignee: lead }
"""))
    assert cfg["delivery"]["devopsAssignee"] == "ops-bot"
    assert cfg["delivery"]["developerFallbackAssignee"] == "lead"


def test_missing_devops_assignee_when_creating_is_rejected(tmp_path):
    with pytest.raises(ops_config.ConfigError, match="devops.assignee"):
        ops_config.load(_write(tmp_path, """
fleet: [https://git.x/g/r]
delivery:
  mode: create
  developer: { target: issues }
"""))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ops_config.py -q -k assignee`
Expected: FAIL (`devopsAssignee` KeyError / no ConfigError raised)

- [ ] **Step 3: Write minimal implementation**

In `agent/lib/ops_config.py`: extend the stream key set and the delivery loader.

```python
_STREAM = {"target", "project", "assignee", "fallbackAssignee"}
```

In `_load_delivery`, in the `if v2:` branch, after resolving `devops`/`developer` streams:

```python
        devops_assignee = d.get("devops", {}).get("assignee")
        developer_fallback = d.get("developer", {}).get("fallbackAssignee")
        if mode == "create" and not devops_assignee:
            raise ConfigError(f"{path}: delivery.devops.assignee is required when delivery.mode "
                              "is 'create' (every DevOps issue is assigned to it)")
```

Add both to the returned delivery dict (both v1 and v2 return paths — v1 has no assignee, so
default to `None`):

```python
    # ... in the returned dict:
        "devopsAssignee": devops_assignee if v2 else None,
        "developerFallbackAssignee": developer_fallback if v2 else None,
```
(Keep every existing delivery key. `_stream` already tolerates the new keys via the widened
`_STREAM`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ops_config.py -q`
Expected: PASS (v1 back-compat tests unaffected)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/ops_config.py tests/test_ops_config.py
git commit -m "feat(config): delivery.devops.assignee + developer.fallbackAssignee"
```

---

### Task 6: Executor wiring + end-to-end verification

**Files:**
- Modify: `agent/cli.py` (`_cmd_deliver` — resolve assignees, thread into `build_plan`)
- Test: `tests/test_cli_deliver.py` (extend or create — a fake `gitlab_api.GitLab`)

**Interfaces:**
- Consumes: everything above. Resolves the DevOps account id once (`gl.user_id(devopsAssignee)`) and each repo's owner id (`resolve_owner(gl.members(project), fallback_id)`), builds `assignees`, passes it to `build_plan`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_deliver.py  (add; mirror existing deliver test scaffolding if present)
from agent.lib import delivery


def test_resolve_assignees_maps_devops_and_repo_owner():
    # a thin unit over the resolution the executor performs (extract it to a helper if cleaner)
    from agent.lib.delivery import resolve_owner
    devops_id = 5
    members = [{"id": 7, "access_level": 50}]
    assignees = {"devops": devops_id, "developer": {"r1": resolve_owner(members, 99)}}
    assert assignees["devops"] == 5 and assignees["developer"]["r1"] == 7
```

(If a `tests/test_cli_deliver.py` with a fake `GitLab` already exists, add an end-to-end case:
a payload with a devops + a developer action for `r1` → `execute_plan` creates two issues in
`g/r1` with assignees 5 and 7.)

- [ ] **Step 2: Run test to verify it fails / passes minimally**

Run: `.venv/bin/python -m pytest tests/test_cli_deliver.py -q`
Expected: the unit above passes on Task 2/3 code; the executor change is exercised in Step 4.

- [ ] **Step 3: Write minimal implementation**

In `agent/cli.py` `_cmd_deliver`, after `gl = gitlab_api.GitLab(host, token)` and building
`repo_meta`, resolve assignees and pass them in:

```python
    devops_assignee = (cfg["delivery"].get("devopsAssignee") if getattr(args, "config", None) else None)
    dev_fallback = (cfg["delivery"].get("developerFallbackAssignee") if getattr(args, "config", None) else None)
    devops_id = gl.user_id(devops_assignee) if devops_assignee else None
    fallback_id = gl.user_id(dev_fallback) if dev_fallback else None
    dev_owner = {}
    for repo, meta in repo_meta.items():
        try:
            dev_owner[repo] = delivery.resolve_owner(gl.members(meta["project"]), fallback_id)
        except Exception:
            dev_owner[repo] = fallback_id            # owner lookup failed -> fallback, never crash
    assignees = {"devops": devops_id, "developer": dev_owner}
```

Then pass `assignees=assignees` into the existing `delivery.build_plan(...)` call, and drop
`dev_as_issues` from that call (findings are always issues now — leave the arg accepted for
back-compat but it no longer forks behavior).

- [ ] **Step 4: Full-suite + real dry-run verification**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (whole suite).

Then a real **dry-run** proving the shape end-to-end (no writes, no token needed):
```bash
./bin/drift-scan run --root ~/gitlab-fleet/rushikesh/ebayapi --state /tmp/deliv --now 2026-07-31
./bin/drift-scan verify --state /tmp/deliv
./bin/drift-scan deliver --state /tmp/deliv --gitlab-host git.topsdemo.in \
  --devops-project x/ops --dry-run
```
Expected: the plan summary shows, per flagged repo, a **DevOps** and/or **Developer** issue
targeting the repo's own project (not a central project), labelled by audience — printed, nothing
filed.

- [ ] **Step 5: Commit**

```bash
git add agent/cli.py tests/test_cli_deliver.py
git commit -m "feat(cli): resolve DevOps + repo-owner assignees and thread into delivery"
```

---

## Notes for the implementer

- Do NOT touch the shape/freshness maintainer blocks in `build_plan` or their labels — paste them back unchanged between the DevOps and Developer branches.
- Existing `test_delivery.py` cases that assert per-action DevOps issues or developer MRs encode the OLD behavior the spec intentionally replaces — update them to the new model (per-repo issues, no MRs), don't preserve them.
- `verify` is not affected: delivery reads drift.json, it does not write any verified surface.
- `dev_as_issues` / `devops_project` config keys stay parseable (v1 back-compat) but no longer fork behavior — findings are always in-repo issues.
