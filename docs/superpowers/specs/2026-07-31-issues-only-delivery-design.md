# Spec — SP-A: Issues-only delivery (per-repo, in-repo, assigned)

**Status:** design approved (brainstorm 2026-07-31), ready for implementation plan.
**Part of:** the go-live productionization epic (SP-A of A–E). Unblocks SP-E (the end-to-end demo).

## Problem

Delivery today files **DevOps findings as one issue per finding** in a central `devops_project`,
and **Developer findings as draft MRs**. The PM wants, for go-live: **no MRs — everything is
issues**; each flagged repo gets a **comprehensive issue per audience**, filed **in that repo's own
tracker**, **assigned** so the right person acts and DevOps gets a single board/list.

## Decisions (from the brainstorm)

1. **Two comprehensive issues per flagged repo, by audience** — a **DevOps** issue (the repo's
   package CVEs + runtime EOL) and a **Developer** issue (the repo's vendor sunsets + framework
   EOL). Each bundles *all* of that repo's findings in its lane. Per-repo, per-audience,
   idempotent (create/update/skip in place by fingerprint).
2. **Both issues live IN the flagged repo's own GitLab tracker** (the ticket sits with the code).
3. **No MRs for findings** — the draft-MR path is retired; issues are the product mode.
4. **Assignment:** DevOps issue → a configured generic **DevOps account** (`drift.yml`); Developer
   issue → the **repo owner** (auto-resolved), with a config fallback.
5. **Visibility is native GitLab** — assignee + a `drift:devops`/`drift:developer` label means a
   group issue board and "issues assigned to `<devops-account>`" both aggregate across the fleet.
   The tool assigns + labels; GitLab does the board/list. Nothing is built for aggregation.
6. **Out of scope:** the maintainer/absorption flow (a repo the scanner can't read → a *reviewed
   MR on the `drift-ops` catalog*) stays as-is. That is catalog governance through the review gate
   (CLAUDE.md principle 4), not fleet delivery — converting it to issues would break the gate.

## Architecture

Three layers, unchanged in shape; the change is *what the plan targets and carries*:

```
drift.json (payload)          build_plan (PURE, no I/O)              execution (GitLab API)
  actions[] w/ owner   ──▶   group by (repo, audience) → one   ──▶  resolve assignees, fetch
  repo_meta{project}          issue op per repo per audience,        each repo's existing issues,
  existing issues             each carrying project=THE REPO,        create/update in the repo
                              assignee, labels, fingerprint          with assignee + labels
```

`build_plan` stays pure and unit-tested; all GitLab I/O stays behind `agent/lib/gitlab_api.py`
(fetch injected for tests). Assignee *resolution* is I/O (members/user lookup) done in the
execution layer and passed *into* the plan-execution, never into the pure planner.

## Component changes

### 1. Config — `agent/lib/ops_config.py`
Extend the v2 per-stream form (`_STREAM = {"target", "project"}`) so each stream can carry an
assignee:
- `delivery.devops.assignee: <username>` — the generic DevOps account every DevOps issue is
  assigned to. **Required** when `delivery.mode` files DevOps issues; a missing value is a
  `ConfigError`, not a silent skip.
- `delivery.developer.fallbackAssignee: <username>` — used only when a repo's owner can't be
  resolved. Optional; absent → the Developer issue is filed unassigned with a body note.
- `delivery.devops.project` becomes **optional/ignored for filing** (issues now file in-repo); keep
  parsing it for back-compat but the planner targets the repo's own project. Document the shift.

```yaml
delivery:
  mode: create                     # dry-run | create | off (existing)
  devops:
    assignee: ops-bot              # NEW — generic DevOps account
  developer:
    target: issues                 # MRs path retired for findings; issues is the mode
    fallbackAssignee: tech-lead    # NEW — used when repo owner unresolvable
```

### 2. Planner — `agent/lib/delivery.py`
- **DevOps becomes per-repo comprehensive** (today it is one issue per action). Group `devops`
  actions by `repo`; render ONE issue bundling them — a new `devops_repo_body(repo, actions, links)`
  mirroring the existing developer `migrations_md`/`mr_description` bundling.
- **Both streams target the repo's own project**: each issue op's `project = repo_meta[repo]["project"]`
  (fall back to the repo slug), NOT `devops_project`.
- **Fingerprints are per-repo, per-audience**: reuse `repo_fingerprint(repo)` but namespaced by
  audience so a repo's DevOps and Developer issues never collide — e.g. `repo_fingerprint(repo,
  "devops")` / `repo_fingerprint(repo, "developer")`. (Extend `repo_fingerprint` to take an optional
  stream tag; keep the marker format `<!-- drift-detector:<fp> -->`.)
- **Ops carry assignee + labels**: extend `_issue_op(...)` and the op dict with `assignee`
  (a username or None) and `labels` (`drift:devops` or `drift:developer`, plus the existing
  `drift-detector`). The planner puts the *username* on the op; the execution layer resolves it to
  an id.
- **Retire the finding-MR path**: `build_plan` no longer emits developer migration MRs — the `mrs`
  list becomes empty. (The maintainer/absorption *flag* is already an **issue** in `build_plan`
  (`shape_issue`); its human-authored catalog MR on `drift-ops` is out-of-band, never
  planner-generated — so nothing about the maintainer flow changes.)

### 3. GitLab API — `agent/lib/gitlab_api.py`
- `create_issue(project_id, *, title, description, labels, assignee_ids=None)` and
  `update_issue(project_id, iid, **fields)` — accept `assignee_ids`.
- **New** `members(project_id) -> list` — the project's members (id, username, access_level) for
  owner resolution. Uses `members/all` (inherited members) so a group-owned repo resolves.
- **New** `user_id(username) -> int | None` — resolve the configured DevOps assignee (and fallback)
  username to an id, via `/users?username=`.
- All new calls go through the existing injected `_call`/`_paged`, so they are testable with a fake
  fetch.

### 4. Execution — the `deliver` command
- **Assignee resolution (I/O, in the executor):**
  - DevOps → `user_id(devops.assignee)`.
  - Developer → the repo owner: from `members(project_id)`, first member with **Owner** access, else
    first **Maintainer**, else `developer.fallbackAssignee` (resolved via `user_id`), else unassigned.
    This rule is deterministic (members sorted by id) and documented.
- **Existing-issue fetch moves per-repo**: fetch each flagged repo's issues (`list_issues(repo_id,
  labels="drift-detector")`) for idempotency, instead of only `devops_project`.
- Execute create/update in the repo's project with the resolved `assignee_ids` + labels.

## Data flow / idempotency

Per repo per audience: fingerprint marker in the body → on re-run, `list_issues` finds it →
`_issue_op` compares normalized body → `create` / `update` / `skip` / `reopen`. Unchanged
mechanism; now keyed per-repo-per-audience and scoped to the repo's own tracker.

## Error handling ("cannot see ≠ clean", applied to delivery)

- **Owner unresolvable** → use `fallbackAssignee`; if that's also absent, file **unassigned** and
  add a body line "⚠ owner auto-assign failed — assign manually." Never block the issue.
- **Can't create/update an issue in a repo** (permissions, archived repo) → the failure is
  **collected and reported** in the command's exit summary; a run that intended N issues and filed
  fewer is NOT reported as clean. Never silently dropped.
- **Missing `devops.assignee`** while DevOps issues are due → `ConfigError` at load, before any I/O.
- **`mode: dry-run`** → the plan is computed + printed, nothing is filed (existing behavior kept).

## Testing

- **Planner (pure, no I/O):** DevOps actions for one repo → ONE per-repo issue (not per-action);
  two audiences for one repo → two ops with distinct fingerprints + correct labels; each op targets
  the repo's own project; assignee username threaded onto the op; unchanged-body → `skip`;
  determinism. Extend `tests/test_delivery.py`.
- **Config:** `delivery.devops.assignee` parsed; missing-when-required → `ConfigError`;
  `developer.fallbackAssignee` optional; v1 back-compat unaffected. Extend `tests/test_ops_config.py`.
- **GitLab API (fake fetch):** `members`/`user_id` shape + paging; `create_issue`/`update_issue`
  send `assignee_ids`. Extend `tests/test_gitlab_api.py`.
- **Assignee resolution (pure, given a members list):** Owner-first, Maintainer-next, fallback,
  unassigned — one test each.
- No network in any unit test; fetch injected throughout.

## Non-goals (YAGNI)

- **Not** GitHub delivery — the forge stays GitLab (fleet + delivery + storage are GitLab; only the
  agent's *hosting + CI runner* move to GitHub, which is SP-B).
- **Not** converting the maintainer/absorption catalog MRs to issues (breaks the review gate).
- **Not** building any list/board UI — GitLab's assignee + label + group board provide it.
- **Not** multi-assignee developer issues (pick one owner deterministically; a repo lead can add
  others manually).

## Definition of done (feeds SP-E, the demo)

- A real scan → `drift-scan deliver` files, **in each flagged repo**, a DevOps issue (assigned to the
  configured account, `drift:devops`) and/or a Developer issue (assigned to the repo owner,
  `drift:developer`), each comprehensive; re-run updates in place (no duplicates, no spam).
- `drift.yml` carries `delivery.devops.assignee` + `delivery.developer.fallbackAssignee`.
- DevOps can see every DevOps issue via a group board on `drift:devops` (or "assigned to the
  account") — verified in the demo.
- Full suite green; `verify` unaffected (delivery is downstream of drift.json, not a verified surface);
  the maintainer/absorption MR path is untouched.
