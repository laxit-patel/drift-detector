# Eval Harness — Phase 0 + Phase 1 Design

**Date:** 2026-07-16
**Status:** approved for planning
**Scope:** a `~/.drift/` home (Phase 0) and an eBay-category evaluation/regression scorecard (Phase 1). Strategy by Fable 5; scope confirmed by the user (Phase 0 + Phase 1 only).

## Problem

The tool is evaluated ad-hoc against `/backup` projects, with results copied by hand into
`~/drift-report-*` folders (litter). There is no way to measure whether a change to the scanner
**improves or regresses** its real-world detection, and no signal for *what to improve*. We want
a prompt-eval-style harness: run the tool over a curated corpus of real public PHP repos grouped
by the integration they use, score the output against ground truth, and turn misses into a
ranked improvement backlog — reproducibly, deterministically, zero-LLM.

## Goals

- **Phase 0:** one home, `~/.drift/`, for eval artifacts and central/demo runs. Stop the
  ad-hoc `~/drift-report-*` copying. Clean up the existing litter.
- **Phase 1:** `drift-eval run ebay` clones a **pinned** corpus of real eBay PHP repos, runs the
  scan + sunset audit over each, and prints a **scorecard** — recall (a hard gate), plus
  informational noise / version-rate / sunset-match — writing `scorecard.json` and a history line.
- Deterministic and reproducible: same pinned corpus + fixed `--now` → byte-identical scorecard.
- Category-generic in design; PHP/eBay is only the first corpus.

## Non-goals (explicitly deferred to Phase 2/3)

- Golden-fact per-repo assertions, forbid lists, persisted per-miss failure-mode triage.
- Accepted-snapshot regression, `drift-eval diff` / `accept`.
- The precision label-bank; walmart + sp categories.
- OSV/EOL HTTP cassettes (Phase 1 does not score the CVE layer — see Determinism).
- Any change to the tool's in-place `<folder>/.drift-detector/` behavior (it is correct and stays).

## Phase 0 — the `~/.drift/` home

A small path resolver, `agent/lib/drift_home.py`, is the single source of truth for where
central artifacts live. It does **not** change how the plugin writes in-place reports.

```python
def drift_root() -> str:            # ~/.drift  (honors $DRIFT_HOME override; created on demand)
def reports_home(slug: str) -> str: # ~/.drift/reports/<slug>   (latest/ + history/)
def eval_home() -> str:             # ~/.drift/eval
```

Layout established:

```
~/.drift/
  reports/<slug>/latest/            central/demo scan outputs (overwritten each run)
  reports/<slug>/history/<date>/    dated snapshots
  eval/
    runs/<ts>/<category>/           inventory.json, audit.json, scorecard.json per run
    scorecards/history.jsonl        one summary line per eval run (the trend)
```

`<ts>` is supplied by the caller (the CLI passes a fixed `--now`-derived stamp), never read from
the wall clock inside a scored function — determinism.

**Cleanup:** the three existing `~/drift-report-2026-07-15`, `~/drift-report-ebay-2026-07-16`,
`~/drift-report-fleet-2026-07-16` folders are moved under `~/.drift/reports/` (as `history/`
entries) or removed. This is a one-time operational step in the plan, not code.

Phase 0 ships independently and is a dependency of Phase 1 (which writes under `eval_home()`).

## Phase 1 — the eval harness

### Module layout (mirrors the `agent/` injected-seam style)

```
agent/eval/corpus.py    load + validate eval/corpus.yaml -> list[CorpusEntry dict]
agent/eval/clone.py     pin-verifying clone into ~/Projects/sandbox/<category>/<name>  (git injected)
agent/eval/score.py     PURE: (entries, inventory, audit) -> scorecard dict          (the tested core)
agent/eval/render.py    scorecard dict -> terminal table string                       (pure)
agent/eval/runner.py    orchestrate: load -> clone -> scan+audit(offline) -> score -> render -> write
agent/eval/cli.py       argparse: `run <category>` -> runner; exit code from the recall gate
bin/drift-eval          self-bootstrapping entrypoint (mirrors bin/drift-scan) -> python -m agent.eval.cli
eval/corpus.yaml        the versioned corpus (real pinned eBay repos)
eval/taxonomy.md        the failure-mode enum (reference doc)
```

The runner **imports the pipeline in-process**: `agent.inventory_scan.scan_folder(root, state, now,
engine="semgrep")` then `agent.audit.audit_inventory(doc, now, osv_query=_noop_osv,
eol_check=_noop_eol)` (see Determinism — the CVE/EOL sources are stubbed so only the offline sunset
join runs). It does not shell out. `score.py` never touches git, network, or the scanner — it takes
already-produced dicts, so it is fully unit-testable with fakes.

### `eval/corpus.yaml` schema (Phase 1 — minimal)

```yaml
- repo: davidtsadler/ebay-sdk-php          # owner/name; also the sandbox dir name (last segment)
  url: https://github.com/davidtsadler/ebay-sdk-php.git
  sha: "<40-hex pinned commit>"            # quoted so YAML keeps it a string
  license: MIT                             # SPDX id, recorded from the repo
  category: ebay
  expect:
    vendor: eBay                           # the classified-endpoint vendor name to detect
    sdk_keywords: [ebay]                    # optional; sdk pkg name match for sdk-only recall (default: [<category>])
    sunset_host: svcs.ebay.com             # optional; a sunset finding on this host is expected (informational)
  known_gaps: [sdk-only-no-callsite]       # optional; declared expected failure modes -> scored "known-miss", not a fail
  holdout: false                           # recorded for the Phase-2 overfitting guard; recall-gated like the rest in Phase 1
  fetched_at: "2026-07-16"
```

Loader validates: `repo`, `url`, `sha` (40-hex), `category`, `expect.vendor` are required; `sha`
coerced to str; unknown top-level keys tolerated; a malformed entry is a hard error (not skipped —
a broken corpus must be loud). `known_gaps` values must be members of the taxonomy enum.

### `eval/taxonomy.md` — failure-mode enum (closed set)

`url-split-version` · `sdk-only-no-callsite` · `uncatalogued-vendor` · `wrong-host-attribution` ·
`config-driven-url` · `env-var-host` · `private-source` · `scan-error` · `label-wrong`

Phase 1 consumes these only as `known_gaps` values (pre-declared expected failures). Runtime
triage of *unexpected* misses into these buckets is Phase 2.

### The scorecard

`score.py::score(entries, inventory, audit) -> dict`. `inventory` is the scan doc (`repos[]` with
`endpoints[{vendor,classified,version}]`, `sdks[{eco,pkg}]`, `coverage`); `audit` is the audit doc
(`findings[]` incl. `kind=="sunset"` with `domain`). Per repo, matched by path/name to its corpus
entry:

- **recall.detected** — `True` if the repo has **either** a classified endpoint with
  `vendor == expect.vendor` **or** an sdk whose `pkg` (lowercased) contains any `expect.sdk_keywords`
  token (default `[category]`). Record which of the two fired (`via: "endpoint" | "sdk" | None`).
- **noise** — count of that repo's endpoints with `vendor == "Unknown"` (unclassified external hosts).
- **version** — (classified endpoints with `version` not null) / (classified endpoints), per repo.
- **sunset** — if `expect.sunset_host` set: `True` iff a `kind=="sunset"` finding has that `domain`.
- **errored** — repo appears in `coverage.repos.errored` / scan raised.

Scorecard dict:

```python
{
  "category": "ebay",
  "now": "2026-07-16",
  "repos": [ {repo, detected, via, miss_mode, noise, version_rate, sunset_expected, sunset_hit, errored}, ... ],
  "summary": {
    "recall": {"passed": 5, "total": 6, "endpoint": 4, "sdk_only": 1, "known_miss": 1, "holdout": 1},
    "noise": {"median": 3, "max": 9},
    "version_rate": 0.62,          # over all classified endpoints in the corpus
    "sunset_match": {"expected": 2, "hit": 2},
    "errored": 0,
  },
  "gate": {"passed": true, "failures": []},   # failures = repos that missed with a NON-known-gap mode
}
```

**The gate:** `gate.passed` is `False` if any repo has `detected == False` **and** its miss is
**not** covered by `known_gaps`. A repo that misses with a declared `known_gaps` mode is a
"known-miss" (counted, not failed). The CLI exits `1` when `gate.passed` is `False`, else `0`.
Noise / version / sunset are **informational** — reported and trended, never gating.

Assigning `miss_mode` to a failing repo in Phase 1: if the repo declared `known_gaps`, the miss is
attributed to the first declared gap; otherwise it is `unattributed` (surfaced verbatim for the
human to triage — Phase 2 will persist the triage). Phase 1 does not auto-classify.

### Determinism & the clone flow

- **Clone (`clone.py`, git injected):** for each entry, into `~/Projects/sandbox/<category>/<name>`:
  clone (`git clone --filter=blob:none <url> <dest>` if absent, else `git fetch`), `git checkout <sha>`,
  then assert `git rev-parse HEAD == sha` — **hard-fail on mismatch** (corpus drift), and refuse a
  dirty working tree. No network in unit tests (git is a passed-in callable).
- **Offline audit:** the runner passes stub sources — `audit_inventory(doc, now,
  osv_query=lambda *a, **k: [], eol_check=lambda *a, **k: None)` — the exact seams
  `audit_inventory` already exposes (the sunset tests use this `_NOOP` pattern today). OSV/EOL
  contribute nothing; the sunset catalog join (no network) still produces findings. So sunset-match
  is scored deterministically; the CVE layer is not scored in Phase 1 (Phase 3 cassettes). This is
  cleaner than a raising `http` and guarantees no socket is opened.
- **Fixed time:** `--now` is passed through to `scan_folder` and `audit_inventory` and stamped into
  the scorecard; nothing reads the wall clock. Same pinned corpus + same `--now` → identical scorecard.

### CLI

`bin/drift-eval run <category> [--now YYYY-MM-DD] [--sandbox ~/Projects/sandbox] [--no-clone]`.
`--no-clone` scores already-present pinned checkouts (skips fetch, still verifies SHA). Output: the
terminal table (via `render.py`) + `scorecard.json` under `eval_home()/runs/<now>/<category>/` + an
appended line in `eval_home()/scorecards/history.jsonl`. Exit code from the gate.

## Testing

Unit tests, no network, no real clones:

**`tests/test_eval_score.py`** (the core):
- recall via classified endpoint; recall via sdk keyword; miss when neither.
- `via` correctly records endpoint vs sdk; a repo with both counts once, `via == "endpoint"`.
- gate FAILS on an unattributed miss; gate PASSES when that same miss is declared in `known_gaps`
  (counted as `known_miss`).
- noise counts only `vendor == "Unknown"` endpoints; version_rate math over classified endpoints
  (incl. the zero-classified-endpoints edge → rate reported as `None`, not a divide-by-zero).
- sunset_hit true only when a `kind=="sunset"` finding matches `expect.sunset_host`; false when the
  host differs; not evaluated when `sunset_host` absent.
- an errored repo is reported and does not crash scoring.
- scoring the same inputs twice is equal (determinism).

**`tests/test_eval_corpus.py`:** loads a valid fixture; rejects a missing `sha`/`vendor`; rejects a
`known_gaps` value outside the taxonomy; coerces an unquoted sha-like value to str.

**`tests/test_eval_clone.py`:** with an injected fake git, verifies the clone→checkout→verify
sequence, the hard-fail on `HEAD != sha`, and the dirty-tree refusal — no real git.

**`tests/test_drift_home.py`:** path resolution honors `$DRIFT_HOME`; `reports_home`/`eval_home`
return the documented subpaths.

**Opt-in live smoke** (`@pytest.mark.skipif` on an env flag, off by default): clone one small real
pinned eBay repo, run the real scan+audit, assert `gate.passed` and `recall.detected`. This is the
only test that touches the network/engine; it mirrors the repo's existing live-semgrep-smoke pattern.

## Success criteria

`drift-eval run ebay` over a corpus of ~5 real pinned eBay PHP repos prints a scorecard whose
**recall gate passes** (every non-known-gap repo detects eBay), reports a non-zero **sunset-match**
(the legacy repo fires `svcs.ebay.com`), shows the **noise** and **version-rate** numbers, writes
`scorecard.json` + a `history.jsonl` line under `~/.drift/eval/`, and exits `0`. Re-running with
the same pins and `--now` reproduces the scorecard byte-for-byte. Corpus discovery (finding and
SHA-pinning the real repos) is a plan task, done via Packagist download-rank + GitHub code-search
for `svcs.ebay.com` in PHP — never invented.
