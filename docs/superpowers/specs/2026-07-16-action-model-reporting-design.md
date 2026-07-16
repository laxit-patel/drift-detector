# Action Model & Report Ranking — Design

**Date:** 2026-07-16
**Status:** approved for planning
**Scope:** the deterministic rollup that turns findings into ranked actions, and the markdown report rendered from it.

## Problem

The scan and audit data are correct. The report is not usable.

Grounded in a real 60-repo run (`~/drift-report-2026-07-15/`, 320 findings / 35 repos):

1. **The urgency section is not sorted by urgency.** `agent/lib/audit_render.py:47` reads
   `for f in urgent[:15]` — no sort. It takes the first 15 in scan order, which is alphabetical
   by repo. The `severity` field is computed on every finding and ignored by the renderer.
   Consequence: all 10 CRITICALs — including 4 remote-code-execution advisories against
   `python/torch 1.1.0` in `backup/Projects/heygen/backend/Wav2Lip` — are hidden below
   `…and 104 more`. The section that exists to say "act on this" conceals the worst item.

2. **The report is finding-centric, not action-centric.** `npm/axios 0.21.1` in
   `backup/Projects/Privilee/schedule` emits 22 separate bullets. It is one action: upgrade axios.
   Measured collapse over the real run:

   | | count |
   |---|---|
   | findings | 320 |
   | distinct `(repo, ref)` actions | 90 |
   | actions containing ≥1 `DEPRECATED` | **50** |

   The user's real to-do list is 50 items, not 320. Worst offenders: `npm/hono` 31→1,
   `python/torch` 30→1, `npm/axios` 22→1, `python/opencv-python` 18→1.

3. **The ranking logic already exists, in the wrong place.** `agent/lib/facade.py:14` defines
   `_SEV_RANK` and `:17` defines `_semver_key` — correct and tested. Both are private to the MCP
   facade. The renderer cannot reach them, so it ranks nothing. This is the root cause of (1):
   not missing logic, but unshared logic.

## Goals

- One deterministic rollup from `findings[]` to ranked `actions[]`, consumed by every renderer.
- An `AUDIT.md` whose first screen answers "what do I do first" correctly.
- A Chat card that reports actions ("3 urgent fixes"), not raw findings ("119 action-required").
- One shared definition of "worse" and "newer", used by both the facade and the report.

## Non-goals (explicitly deferred)

- **The HTML dashboard.** Designed next, after the ranked markdown is visible. Not in this spec.
- **Scan history / run archive.** Dropped by decision — not built.
- **Connectors** (Dependency-Track, SARIF upload, GitLab issues). The `deliver` step keeps its
  current shape so they remain addable later. None built now.
- **Transitive dependency coverage.** See "Known coverage gap" below. Reported, not fixed.
- **The cognition/LLM layer.** Deferred by prior decision. Everything here is deterministic.

## Architecture

Three changes, smallest first:

```
agent/audit.py         (edit)  EOL findings carry a structured `fixed`, like CVE findings already do
agent/lib/ranking.py   (new)   severity_rank() + semver_key() — extracted from facade.py, shared
agent/lib/actions.py   (new)   build_actions(findings) -> ranked actions[]
agent/lib/audit_render.py (rewrite)  renders actions[], not findings[]
agent/lib/chat.py      (edit)  card reports action counts
agent/lib/facade.py    (edit)  imports from ranking.py instead of defining privates
```

Data flow: `audit.py` produces `findings[]` → `actions.build_actions()` rolls up and ranks →
renderers (markdown, chat card) consume `actions[]`. `audit.json` gains an `actions` key alongside
the existing `findings` key; `findings` is unchanged so SARIF/BOM/MCP consumers keep working.

## The action model

**Unit of action:** `(repo, ref)` — "in this repo, upgrade this one thing."

```python
{
  "repo": "backup/Projects/heygen/backend/Wav2Lip",
  "ref": "python/torch",
  "eco": "python",
  "pkg": "torch",
  "kind": "cve",                  # or "eol" — from the findings; mixed -> "cve"
  "current_version": "1.1.0",
  "fix_version": "2.8.0",         # max of all findings' `fixed`, by semver_key
  "command": "pip install 'torch>=2.8.0'",   # None when not derivable (see below)
  "worst": "CRITICAL",            # max severity across findings, by severity_rank
  "status": "DEPRECATED",         # DEPRECATED if any finding is; else REVIEW
  "finding_count": 30,
  "critical_count": 4,            # findings at CRITICAL, for the "(4 RCE)" style summary
  "first_seen": "2026-07-15",     # min across findings — how long this has been open
  "fixes": [ ...the finding dicts... ],
  "sources": ["https://…", …]     # deduped source_urls, order-stable
}
```

### Rollup rules

- Group findings by `(repo, ref)`. Both fields are present on all 320 findings.
- `fix_version` = `max((f["fixed"] for f in group if f.get("fixed")), key=semver_key)`, else `None`.
  This is the load-bearing computation: `python/torch` carries **16 distinct** `fixed` values and
  `npm/axios` carries **8**. The maximum satisfies every advisory in the group at once.
  A string sort gets this wrong (`"1.10.0" < "1.7.4"`); that exact bug has already occurred once in
  `facade.py` and is the reason `semver_key` exists.
- `worst` = `max(f["severity"], key=severity_rank)`.
- `status` = `"DEPRECATED"` if any finding in the group is `DEPRECATED`, else `"REVIEW"`.
- `first_seen` = `min(f["first_seen"])` (ISO date strings; lexicographic min is correct for ISO-8601).
- An action with `fix_version is None` (all advisories unfixed — 13 findings in the real run have
  no `fixed`) is still emitted, with `command: None` and `fix_version: None`. The report shows it
  as "no fix available — review advisory". It must not be silently dropped.

### Ranking

Actions sort by, in order:

1. `status` — `DEPRECATED` before `REVIEW`
2. `severity_rank(worst)` — descending
3. `finding_count` — descending (an upgrade fixing 30 CVEs beats one fixing 1)
4. `repo`, then `ref` — ascending, for a stable, deterministic tie-break

Determinism matters: the same input must always produce byte-identical output, so runs are
diffable and tests are not flaky.

### Severity ranks (`agent/lib/ranking.py`)

Extracted verbatim from `facade.py:14`, plus the EOL rule this spec adds:

```python
_SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0, "": 0}

def severity_rank(severity, status=None):
    """Rank a finding's severity. EOL has no CVSS score, so it is ranked by overdue-ness:
    past its EOL date (audit marks these DEPRECATED) ranks as HIGH; approaching (REVIEW)
    ranks as MODERATE."""
    if severity == "EOL":
        return _SEV_RANK["HIGH"] if status == "DEPRECATED" else _SEV_RANK["MODERATE"]
    return _SEV_RANK.get(str(severity or "").upper(), 0)
```

Rationale, confirmed with the user: `php 7.4` has been end-of-life since 2022-11-28. With no CVSS
score it currently ranks below a LOW CVE. Ranking past-due EOL as HIGH matches how a team actually
triages it. The `DEPRECATED`/`REVIEW` split already exists on EOL findings (`audit.py:138`,
`res["status"]`), so this needs no new data and no new judgement.

`semver_key` moves unchanged from `facade.py:17`:

```python
def semver_key(s):
    return [int(p) for p in re.findall(r"\d+", str(s))] or [0]
```

`facade.py` then imports both from `ranking.py` and deletes its private copies:

- `facade.py:81` currently ranks with an inline lambda,
  `key=lambda s: _SEV_RANK.get(str(s).upper(), 0)`. It becomes `key=severity_rank`.
- `facade.py:82` `key=_semver_key` becomes `key=semver_key`.

This is behaviour-preserving. `severity_rank(s)` with the default `status=None` is identical to
the old lambda for every non-EOL severity, and `facade.py:81` only ever sees OSV CVE severities
(`CRITICAL`/`HIGH`/`MODERATE`/`LOW`/`UNKNOWN`) — never `EOL`, which is produced solely by the
endoflife.date path in `audit.py`. `facade.py`'s existing tests must still pass unchanged.

### Fix commands

Every audited package is a **direct dependency** — `audit.py:88` iterates `r["sdks"]`, which are
manifest declarations; a lockfile only supplies the resolved exact version for an
already-declared package. So a copy-paste command is safe: it can never instruct the user to
install a transitive package directly.

`ref` is `f"{eco}/{pkg}"`; split on the **first** `/` only (`composer/aws/aws-sdk-php` →
eco `composer`, pkg `aws/aws-sdk-php`).

| eco | command |
|---|---|
| `npm` | `npm install {pkg}@^{fix_version}` |
| `composer` | `composer require {pkg}:^{fix_version}` |
| `python` | `pip install '{pkg}>={fix_version}'` |
| anything else | `None` — no command rendered |

`kind == "eol"` actions never get a command: upgrading a language runtime or framework major is
not a one-liner. They render the target version only (e.g. `php ^7.4 → 8.5.8`).

When `fix_version is None`, `command` is `None`. Never emit a command with a `None` version in it.

## Changes to `agent/audit.py`

EOL findings are the only ones lacking a structured fix. Measured: 273 of 320 findings carry
`fixed`; all 34 EOL findings carry the target **only inside prose** (`"upgrade to 8.5.8"`).

At `audit.py:139-145`, add one key to the EOL finding dict:

```python
"fixed": res.get("recommended"),
```

`res["recommended"]` is already read on the very next line to build the prose string, so the value
is in hand. The prose `recommendation` stays as-is for backward compatibility. After this change
all findings are uniform and `actions.py` never parses English.

## The new `AUDIT.md`

Rendered from `actions[]`. Structure:

```markdown
# Deprecation & Vulnerability Audit — 2026-07-15

**🔴 50 fixes needed · 🟠 40 to review · across 35 of 60 repos**

_Since last scan: 🆕 4 new · ✅ 12 resolved · ⏳ 38 still open_

## Do this first

1. 🔴 **backup/Projects/heygen/backend/Wav2Lip** — `python/torch` `1.1.0` → **`2.8.0`**
   Fixes 30 advisories (4 critical). Open since 2026-07-15.
   `pip install 'torch>=2.8.0'`

2. 🔴 **backup/Projects/Privilee/schedule** — `npm/axios` `0.21.1` → **`1.16.0`**
   Fixes 22 advisories (0 critical). Open since 2026-07-15.
   `npm install axios@^1.16.0`

…10 shown of 50. Full queue below.

## Fix queue

| # | Repo | Package | Now → Fix | Fixes | Worst |
|---|---|---|---|---|---|
| 1 | heygen/backend/Wav2Lip | python/torch | 1.1.0 → 2.8.0 | 30 | 🔴 CRITICAL |

## By repo

### backup/Projects/Privilee/schedule
| Package | Now → Fix | Fixes | Worst | Advisories |
|---|---|---|---|---|
| npm/axios | 0.21.1 → 1.16.0 | 22 | 🟠 MODERATE | [1](url), [2](url) … |

## Coverage & notes
- …existing coverage notes…
- Only manifest-declared (direct) dependencies are audited. Transitive dependencies
  resolved in lockfiles are not queried.
```

Rules:

- **"Do this first"** shows the top **10** ranked actions, and states the total
  (`…10 shown of 50`) so nothing is silently truncated.
- **"Fix queue"** lists every `DEPRECATED` action, ranked. No truncation.
- **"By repo"** keeps the existing per-repo tables, but rows are actions, not findings; the
  collapsed advisories become source links in the last column. Repos sorted by their worst action.
- The `## 🆕 New since last scan` / `## ✅ Resolved` delta sections stay, but list **actions**.
- The individual findings remain available in `audit.json` and `findings.sarif`; the markdown is
  the human view and does not need to enumerate all 320.

## Chat card

`agent/lib/chat.py` reports actions: header becomes
`"🔴 50 fixes needed · 35 of 60 repos"` and the body lists the **top 5 actions** with
`repo · pkg cur → fix · fixes N` instead of raw finding counts. The standing rule — every run
posts to the Google Chat "Drift" space — is unchanged.

## Known coverage gap (report it, don't fix it)

`audit.py:88` audits only manifest-declared packages. The real run's 720 packages are all direct
declarations. Transitive dependencies present in lockfiles are never queried against OSV, so the
true vulnerable-package count is higher than reported. This spec adds the coverage note quoted
above. Widening to transitive audit is a separate unit, not in this scope.

## Testing

Unit tests only; no network, consistent with the repo's injected-seam pattern.

**`tests/test_ranking.py`**
- `semver_key` orders `1.7.4 < 1.10.0` (the real prior bug).
- `severity_rank`: CRITICAL > HIGH > MODERATE > LOW > UNKNOWN.
- EOL past-due (`status="DEPRECATED"`) ranks equal to HIGH; EOL approaching (`REVIEW`) ranks
  equal to MODERATE; a past-due EOL outranks a LOW CVE.
- `facade.py` behaviour is unchanged after the import swap (its existing tests must still pass).

**`tests/test_actions.py`**
- 16 `fixed` values including `2.8.0` and `1.10.0` → `fix_version == "2.8.0"` (max, not last, not
  string-max). This is the torch case, from real data.
- Findings for two different repos with the same `ref` produce two actions, not one.
- An action with no `fixed` anywhere → `fix_version is None`, `command is None`, still emitted.
- `worst` picks CRITICAL out of a mixed group; `status` is DEPRECATED if any finding is.
- Ranking: a DEPRECATED/MODERATE action with 30 findings outranks a DEPRECATED/MODERATE action
  with 1; a CRITICAL outranks both; ties break stably by `(repo, ref)`.
- Command mapping per eco, including `composer/aws/aws-sdk-php` splitting on the first `/` only.
- `kind == "eol"` → `command is None`.
- Rendering the same input twice is byte-identical.

**`tests/test_audit.py`** (extend)
- An EOL finding carries structured `fixed` equal to the endoflife `recommended` value.

**`tests/test_audit_render.py`** (rewrite)
- The first action under "Do this first" is the highest-ranked one — assert the CRITICAL torch
  action appears before the alphabetically-first repo's action. This is the regression test for
  the original bug.
- "…N shown of M" appears when the queue exceeds 10.
- No action is dropped from the fix queue.
- Structural assertions (headings present, row counts match action counts) rather than golden files.

## Success criteria

Re-rendering the existing `~/drift-report-2026-07-15/audit.json` through the new pipeline yields
an `AUDIT.md` whose "Do this first" begins with the `python/torch` CRITICAL RCE action in
`heygen/backend/Wav2Lip`, and whose fix queue holds 50 actions rather than 119 findings.
