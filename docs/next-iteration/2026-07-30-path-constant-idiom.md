# Design: the `path-constant` idiom family — operation-level intake for config-injected wrappers

**Goal.** Make the deterministic scanner attribute the operations of a config-injected wrapper
repo (no host literal, generic paths) at their real `file:line`, through the absorb gate.
First target: **Catch** (`catchapi`) — 0 attributed today; ~15 operation constants invisible.

**Reproduce-first (the failing observation).** Scanning `catchapi` today:
`0 classified endpoints, 0 residue pathLiterals, 6 residue sinks`. The `/api/...` constants are
wholly invisible — no rule surfaces them (they carry no version segment), and the concat idiom
can't fire (it needs a *pre-classified* vendor, which a config-injected host never yields).

## Why the existing mechanism can't reach it (grounded)

1. Concat/operation-marker attribution keys off `classified_tks` — the repo's already-classified
   vendors (`endpoints.py:125,145`). Config-injected host ⇒ `classified_tks` empty ⇒ never fires.
2. The `path-literal` rule requires a version segment (`vendor_rules.py` regex
   `/(v[0-9…]|YYYY-MM-DD)/`). `/api/orders` has none; `V1/` is capital-V. The constants are
   never even surfaced as matches.
3. Concat attributes path literals *co-located* with the assembly expression. Here the assembly
   lives in the base class, the constants in subclass files. Co-location fails.

## The family

A new **closed-set family** `path-constant` (code + PR, like every family). Its *instances* are
reviewed YAML, gate-verified. An instance is **repo-scoped and vendor-bound** — the necessary
shape when no host literal exists to classify globally:

```yaml
- id: catch-api-paths
  family: path-constant
  repo: akshit.tops/catchapi     # host-independent suffix, matched like sdk_profiles._matches
  vendor: Catch                  # bound vendor; must exist in agent/vendors.yaml
  pathRegex: '^/api/'            # which string literals are operation paths in THIS repo
  requiresSink: true            # only attribute in a repo that shows an egress sink
  evidence: 'src/CatchApi/GetOrders.php:9'   # a real file:line (required of every idiom)
```

### Mechanism
- **Rule** (`vendor_rules` via `idioms.to_rules`): a string-literal rule matching `pathRegex`,
  carrying `metadata: {kind: path-constant, vendor: Catch}`. (Engine passes `vendor`/`kind`
  through, same as the per-vendor `endpoint` rules.)
- **Attribution** (`endpoints.scan_endpoints`, new block): for each `path-constant` match, if the
  current repo matches the instance's `repo` scope **and** the repo shows ≥1 egress sink,
  attribute the path to the bound vendor as an **operation** at its `file:line`
  (`attribution: inferred`, `operation=<path>`). Repo scope is checked with a new `repo_id`
  argument (the repo's `remote_url`/path), matched via `scope_edges.identity`.
- **Residue**: any `path-constant` match not attributed is recorded (a new `residue` list) — the
  conscience stays honest.
- **Repo-scoping is mandatory**: Catch's `/api/offers` is generic and also appears in `bunnings`
  (Mirakl). Without the `repo` scope a Catch rule would mis-tag Mirakl. The scope is the guard.

### The absorb gate (extended)
`measure_against_repo` currently forbids *any* new vendor. For a vendor-bound instance the bound
vendor **is** the reviewed claim, so the gate is taught: the instance's bound vendor is allowed;
**any other** new vendor still fails, unclaimed sites still fail, residue still may not grow.
Prove-the-guard: an instance bound to the *wrong* vendor, or with `pathRegex: '^/'` (sweeps
non-API strings), must be **rejected**; the correct one accepted.

## Files
- `agent/lib/idioms.py` — `FAMILIES`, `KIND_BY_FAMILY`, `_validate` (needs `repo`,`vendor`,`pathRegex`), `to_rules`.
- `agent/lib/endpoints.py` — `repo_id` param + the `path-constant` attribution block + residue list.
- `agent/lib/repo_scan.py`, `agent/cli.py` — thread `repo_id` into `scan_endpoints`.
- `agent/absorb.py` — allow the bound vendor; count `path-constant` residue.
- `agent/vendors.yaml` — add `Catch` (detection-only, `techKey: api:catch`).
- `agent/idioms.yaml` — the `catch-api-paths` instance.

## Done =
- `catchapi` flips `0 → ~15` operations at exact `file:line`, `attribution: inferred`, vendor Catch.
- `drift-scan absorb` **accepts** the correct instance, **rejects** a wrong-vendor / over-broad one.
- Full suite green; `drift-eval run ebay` still 5/5; `amazonspapi` still 272 (no regression);
  `drift-scan verify` green.
- Generalizes: MySale / Marketplacer / Mirakl / Harvey Norman become one YAML instance each.
