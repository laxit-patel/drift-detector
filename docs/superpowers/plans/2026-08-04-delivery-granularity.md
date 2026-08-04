# Delivery granularity flag + emoji issue titles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a `delivery.granularity` config flag so a deployment chooses how findings become
GitLab issues — `comprehensive` (today: 2 per repo), `per-vendor` (1 per repo×vendor), or
`per-problem` (1 per ranked action) — and give every drift-filed issue a distinctive **emoji
title** so it stands out in the tracker and encodes urgency at a glance.

**Architecture:** `ops_config.load` parses + validates the new flag (default `comprehensive`,
backward-compatible). `delivery.build_plan` gains a `granularity` param that branches the
DevOps + Developer issue construction; each mode keeps its own stable fingerprint namespace so
re-runs stay idempotent and switching modes cleanly closes the old-shape issues via `_finish`.
`cli._cmd_deliver` threads `cfg["delivery"]["granularity"]` into `build_plan`.

**Tech Stack:** Python stdlib + PyYAML. Tests: pytest (`tests/test_ops_config.py`, `tests/test_delivery.py`).

## Global Constraints

- **Default `comprehensive`** — an existing config with no `granularity` key behaves EXACTLY as
  today (2 comprehensive per-repo issues). No silent behavior change.
- **Idempotent in every mode** — each issue carries its `<!-- drift-detector:<fp> -->` marker;
  re-runs match by marker and UPDATE in place, never duplicate. Distinct fingerprint namespaces
  per mode (`action_fingerprint` for per-problem, a new `vendor_fingerprint` for per-vendor,
  `repo_fingerprint` for comprehensive) so they never collide.
- **`_finish` still closes resolved/orphaned issues** — including old-shape issues after a
  granularity switch (their fp is no longer produced → auto-closed). This is intended.
- **Assignees + labels unchanged** — DevOps findings → configured DevOps assignee + `drift:devops`;
  Developer findings → repo owner (`resolve_owner`) + `drift:developer`. Granularity changes the
  NUMBER and SCOPE of issues, never who they go to.
- **Shape + freshness maintainer streams are unaffected** by granularity (they are not findings).
- **Determinism:** titles/bodies are pure functions of the payload (no wall-clock).
- The scan/verify path is untouched; this is delivery-only.

## Emoji scheme (titles)

A single leading emoji per issue, encoding urgency (drift issues rarely share a human's leading
glyph, so they pop in the list). Helper `_emoji(a)`:

| condition | emoji | meaning |
|---|---|---|
| `kind == "sunset"` and `status == "DEPRECATED"` and `date` | 🚨 | past-due — retired NOW |
| `kind == "sunset"` (otherwise, e.g. REVIEW/upcoming) | ⏳ | upcoming sunset deadline |
| `kind == "eol"` | ☣️ | end-of-life runtime |
| `worst == "CRITICAL"` | 🛡️ | critical CVE |
| else | ⚠️ | review / other |

For AGGREGATE issues (comprehensive/per-vendor) use `_emoji_worst(acts)` = the most urgent emoji
among the actions, urgency order `🚨 > ☣️ > 🛡️ > ⏳ > ⚠️`.

---

## Task 1: `granularity` config flag + cli wiring

**Files:** `agent/lib/ops_config.py`, `agent/cli.py`, `tests/test_ops_config.py`.

**Interfaces:**
- Produces: `cfg["delivery"]["granularity"] ∈ {"comprehensive","per-vendor","per-problem"}`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests** (in `tests/test_ops_config.py`)

```python
def test_granularity_defaults_to_comprehensive(tmp_path):
    cfg = ops_config.load(_write(tmp_path, "fleet: [https://git.x/g/a]\n"))
    assert cfg["delivery"]["granularity"] == "comprehensive"

def test_granularity_parses_valid_values(tmp_path):
    for v in ("comprehensive", "per-vendor", "per-problem"):
        cfg = ops_config.load(_write(tmp_path,
            f"fleet: [https://git.x/g/a]\ndelivery:\n  granularity: {v}\n"))
        assert cfg["delivery"]["granularity"] == v

def test_bad_granularity_is_rejected(tmp_path):
    with pytest.raises(ops_config.ConfigError, match="granularity"):
        ops_config.load(_write(tmp_path,
            "fleet: [https://git.x/g/a]\ndelivery:\n  granularity: per-everything\n"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ops_config.py -k granularity -q` → FAIL.

- [ ] **Step 3: Implement in `ops_config.py`**

Add `granularity` to `_DELIVERY_COMMON` (so it's allowed in both v1/v2 forms and never counts
toward the mix check). Add `_GRANULARITIES = {"comprehensive", "per-vendor", "per-problem"}`. In
`_load_delivery`, parse `g = d.get("granularity", "comprehensive")`; if `g not in
_GRANULARITIES` raise `ConfigError(f"{path}: delivery.granularity must be one of
{sorted(_GRANULARITIES)}, got {g!r}")`. Add `"granularity": g` to the returned dict. Update the
two existing `assert cfg["delivery"] == {...}` literals in `tests/test_ops_config.py`
(test_valid_config_loads..., test_delivery_defaults_when_omitted) to include
`"granularity": "comprehensive"`.

- [ ] **Step 4: Thread it through `cli._cmd_deliver`**

Near line 842 where `shape_stream = cfg["delivery"]["shape_stream"]`, add
`granularity = cfg["delivery"]["granularity"]` (default `"comprehensive"` when no config, matching
the other flags' default handling around line 829). Pass `granularity=granularity` into the
`delivery.build_plan(...)` call (~line 894). (build_plan gains the param in Task 2 — default
`"comprehensive"` keeps this call valid before/after.)

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_ops_config.py -q` → green.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/ops_config.py agent/cli.py tests/test_ops_config.py
git commit -m "feat(delivery): delivery.granularity config flag (default comprehensive)"
```

---

## Task 2: the 3 granularity modes + emoji titles in `build_plan`

**Files:** `agent/lib/delivery.py`, `tests/test_delivery.py`.

**Interfaces:**
- Consumes: `granularity` (from Task 1, via cli).
- Produces: `build_plan(..., granularity="comprehensive")`; `vendor_fingerprint(repo, vendor, stream)`;
  `_emoji(a)` / `_emoji_worst(acts)`.

- [ ] **Step 1: Write the failing tests** (in `tests/test_delivery.py` — mirror existing helpers there)

```python
def test_per_problem_files_one_issue_per_action():
    # 3 developer actions in one repo -> 3 issues (not 1 comprehensive)
    payload = {"actions": [
        _act(repo="ebayapi", owner="developer", kind="sunset", ref="eBay", unit="GetCategories",
             status="DEPRECATED", date="2025-01-01", worst="SUNSET"),
        _act(repo="ebayapi", owner="developer", kind="sunset", ref="eBay", unit="GetCharities",
             status="DEPRECATED", date="2023-09-18", worst="SUNSET"),
        _act(repo="ebayapi", owner="developer", kind="sunset", ref="eBay", unit="AddDispute",
             status="DEPRECATED", date="2023-01-31", worst="SUNSET")]}
    plan = delivery.build_plan(payload, {"ebayapi": {"project": "r/ebayapi"}},
                               {"issues": []}, "g/ops", granularity="per-problem")
    creates = [o for o in plan["issues"] if o["op"] == "create"]
    assert len(creates) == 3
    # each keyed by its own action_fingerprint (idempotent per problem)
    fps = {delivery.markers_in(o["body"]).pop() for o in creates}
    assert len(fps) == 3
    # emoji title — a past-due sunset leads with the siren
    assert all(o["title"].startswith("🚨") for o in creates)

def test_per_problem_is_idempotent_and_updates_in_place():
    payload = {"actions": [_act(repo="ebayapi", owner="developer", kind="sunset", ref="eBay",
                 unit="GetCategories", status="DEPRECATED", date="2025-01-01", worst="SUNSET")]}
    fp = delivery.action_fingerprint(payload["actions"][0])
    existing = {"issues": [{"iid": 7, "project_id": "r/ebayapi", "state": "opened",
                            "description": delivery.marker(fp)}]}
    plan = delivery.build_plan(payload, {"ebayapi": {"project": "r/ebayapi"}}, existing,
                               "g/ops", granularity="per-problem")
    ops = [o["op"] for o in plan["issues"]]
    assert "update" in ops and "create" not in ops        # matched by marker -> update

def test_per_vendor_groups_by_vendor():
    payload = {"actions": [
        _act(repo="r", owner="developer", kind="sunset", ref="eBay", unit="A", status="DEPRECATED",
             date="2025-01-01", worst="SUNSET"),
        _act(repo="r", owner="developer", kind="sunset", ref="eBay", unit="B", status="DEPRECATED",
             date="2025-01-01", worst="SUNSET"),
        _act(repo="r", owner="developer", kind="sunset", ref="Amazon SP-API", unit="/c/v0",
             status="DEPRECATED", date="2025-01-01", worst="SUNSET")]}
    plan = delivery.build_plan(payload, {"r": {"project": "g/r"}}, {"issues": []}, "g/ops",
                               granularity="per-vendor")
    creates = [o for o in plan["issues"] if o["op"] == "create"]
    assert len(creates) == 2                               # eBay + Amazon, one each

def test_comprehensive_is_unchanged_default():
    payload = {"actions": [_act(repo="r", owner="developer", kind="sunset", ref="eBay", unit="A",
                 status="DEPRECATED", date="2025-01-01", worst="SUNSET"),
               _act(repo="r", owner="developer", kind="sunset", ref="eBay", unit="B",
                 status="DEPRECATED", date="2025-01-01", worst="SUNSET")]}
    plan = delivery.build_plan(payload, {"r": {"project": "g/r"}}, {"issues": []}, "g/ops")
    creates = [o for o in plan["issues"] if o["op"] == "create"]
    assert len(creates) == 1                               # one comprehensive developer issue
    assert creates[0]["title"].startswith("🚨")            # emoji now on comprehensive titles too
```

Define an `_act(**kw)` helper in the test if one isn't present, returning a dict with sensible
defaults for the keys `build_plan`/`_emoji` read (`repo, owner, kind, ref, unit, status, date,
worst, recommendation, files, sources`). Reuse the file's existing action-builder if it has one.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_delivery.py -k "per_problem or per_vendor or comprehensive_is_unchanged" -q` → FAIL.

- [ ] **Step 3: Implement in `delivery.py`**

1. `_emoji(a)` + `_emoji_worst(acts)` per the scheme table above.
2. Prefix EVERY drift issue title with the emoji: update `issue_title(a)` → `f"{_emoji(a)} [drift]
   {_label_of(a)}{tail}"`; and the comprehensive titles in `build_plan` (`f"{_emoji_worst(acts)}
   [drift] platform upkeep for {project}"` and `… API migrations for {project}`).
3. `vendor_fingerprint(repo, vendor, stream)` — `sha256(f"vendor|{stream}|{repo}|{vendor}")[:16]`,
   a namespace distinct from repo/action/shape/freshness.
4. In `build_plan`, extract the DevOps and Developer construction into a granularity branch. Keep
   `comprehensive` byte-identical to today (except the emoji prefix). For `per-problem`: for each
   action, `fp = action_fingerprint(a)`, `_issue_op(fp, issue_title(a), issue_body(a, project,
   links), by_fp, project, assignee=<audience assignee>)`, `op["stream"]=<audience>`; add fp to
   `live_fps`. For `per-vendor`: group each audience's acts by `a.get("ref")`; per (repo,vendor)
   `fp = vendor_fingerprint(project, vendor, audience)`, title `f"{_emoji_worst(v_acts)} [drift]
   {vendor} — {project}"`, body = the existing `migrations_md`/`devops_repo_body` rendered over just
   that vendor's acts (they already take an acts list); `op["stream"]=<audience>`. The DevOps
   audience assignee is `assignees.get("devops")`; the Developer one is
   `(assignees.get("developer") or {}).get(repo)`. `_finish` is called once at the end as today.

- [ ] **Step 4: Run the new tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_delivery.py -q` then `.venv/bin/python -m pytest -q`.
Expected: green. If the existing comprehensive-mode delivery tests now see an emoji prefix, update
their title assertions to expect it (that is the one intended visible change to comprehensive mode).

- [ ] **Step 5: Dry-run sanity on the real fleet payload** (no network — `mode: off`/dry-run plan)

Confirm per-problem produces N issues for N actions on the `.drift-fleet` payload:
```bash
.venv/bin/python -c "
import json; from agent.lib import delivery
p=json.load(open('.drift-fleet/drift.json'))
rm={a['repo']:{'project':a.get('repoLabel') or a['repo']} for a in p['actions']}
plan=delivery.build_plan(p, rm, {'issues':[]}, 'g/ops', granularity='per-problem')
creates=[o for o in plan['issues'] if o['op']=='create']
print('per-problem creates:', len(creates), '· sample titles:')
[print('  ', o['title']) for o in creates[:6]]
"
```
Expected: creates count ≈ the number of ranked actions; titles lead with emoji.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/delivery.py tests/test_delivery.py
git commit -m "feat(delivery): per-problem + per-vendor granularity modes + emoji issue titles"
```

---

## Final verification

- [ ] Full suite green: `.venv/bin/python -m pytest -q`.
- [ ] Default path unchanged: a config without `granularity` yields the same comprehensive plan
      (plus the emoji title) — `test_comprehensive_is_unchanged_default` green.
- [ ] Idempotency proven in per-problem (`update`, not `create`, on a re-run) and the switch
      transition closes old-shape issues (add a test if time permits).
- [ ] Whole-branch review before we wire the live config + trigger CI.
