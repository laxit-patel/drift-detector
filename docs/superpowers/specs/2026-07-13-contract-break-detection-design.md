# Contract-Break Detection (Layer 2) — Design Spec

**Date:** 2026-07-13
**Status:** Approved design, ready for implementation planning
**Parent project:** Integration & Dependency Change-Monitoring Agent (`docs/superpowers/specs/2026-07-10-api-deprecation-agent-design.md`)

## Problem

The user's e-commerce seller-portal integrations (Amazon SP-API, eBay, Walmart,
Shopify) **fail silently in production with straight errors** because API/contract
breaks are often **not cited in any changelog**. The existing changelog-monitoring
capability (feeds → KB → classify) cannot catch a break that the vendor never
announced. Concrete example already observed: SP-API commit *"Prune Orders model"*
(2026-05-27) removes fields from the Orders contract but is announced only as a
terse commit message tagged `additive`.

**Layer 2 watches the contract itself, not the announcement about it.** It
snapshots each marketplace's published machine-readable API spec every run, diffs
it against the previous snapshot, deterministically classifies structural breaks,
scopes them to what each repo actually uses, and (for the relevant subset) has one
LLM stage explain the blast-radius. This catches uncited breaks **before**
production does.

Layer 3 (reactive production-error / synthetic-probe signal) is a separate
subsystem with its own spec and infra; explicitly out of scope here.

## Goals / Non-goals

**Goals**
- Detect structural contract changes (breaking / additive / ambiguous) in
  marketplace API specs deterministically, with the before/after as evidence.
- Never miss a change: diff the whole spec; a break in a currently-unused API is
  recorded (watchlist), not dropped.
- Prioritize by usage: repos that use the affected surface get ACTION/REVIEW; the
  LLM explains impact only for that relevant subset.
- Reuse the existing Finding → delta → report → Chat delivery pipeline unchanged.
- Fit the existing ephemeral weekly-container infra (git-backed state); no new
  always-on infra.

**Non-goals (v1)**
- Layer 3 (production-error ingestion, synthetic probes, Lambda/webhook receiver).
- Operation-level static usage extraction across all languages (v1 uses
  presence + cheap operation-name hints; deeper extraction is a later lever).
- Auto-fixing code or opening MRs (the parent project's action router is separate).

## Chosen approach

**Hybrid (Approach C):** deterministic whole-spec diff for completeness, tagged by
used-surface for relevance, LLM blast-radius only on used breaking/ambiguous
changes. Rejected alternatives: A (whole-spec + AI on every change) — too noisy,
wastes LLM on unused APIs; B (used-surface-only diff) — needs brittle
operation-level extraction and can under-detect.

## Architecture

A marketplace-agnostic **engine** operating on a canonical `NormalizedSpec`, fed by
pluggable per-marketplace **SpecSource adapters** (same seam style as the existing
feed adapters and the SourceProvider). Everything downstream of the normalizer is
format-agnostic — OpenAPI and GraphQL both collapse to `NormalizedSpec`.

```
SpecSource adapter ─► Normalizer ─► Snapshot store ─► Semantic differ ─► Usage scoper
  (per marketplace)    (→canonical)   (git state)       (deterministic)     (used/unused)
                                                                                  │
                                              AI blast-radius (one LLM stage, evidence-gated)
                                                                                  │
                                        existing Finding ─► delta ─► report ─► Chat/commit
```

### Components (each a focused, independently testable unit)

1. **SpecSource adapters** — `fetch_spec(source_config, *, fetch=…) -> dict[str, RawDoc]`.
   Returns a map of `{api_name: raw spec document}`. HTTP injected for tests.
   - **SP-API** (v1, public): fetch the OpenAPI JSON model files from
     `amzn/selling-partner-api-models` (63 files under `models/**/*.json`) via the
     existing GitHub read path at a resolved ref. No auth beyond the read token.
   - **eBay / Shopify / Walmart**: adapter slots, gated on access (see Prerequisites).

2. **Normalizer** — `normalize(raw_doc, format) -> NormalizedSpec`. Reduces an
   OpenAPI or GraphQL document to the canonical shape:
   - `NormalizedSpec = { operations: { op_key: Operation } }`
   - `Operation = { key, requestParams: [Param], responseFields: [Field], enums: {name: [values]} }`
   - `Param = { name, type, required }`; `Field = { path, type, nullable }`.
   - `op_key` = `"{method} {path}"` (OpenAPI) or `"{type}.{field}"` (GraphQL).
   Two format-specific front-ends (`normalize_openapi`, `normalize_graphql`) target
   the same structure so the differ is written once.

3. **Snapshot store** — persists the `NormalizedSpec` per marketplace/api under the
   git-backed state branch: `spec-snapshots/<marketplace>/<api>.json`. Load returns
   the previous snapshot or `None`. First run for an api = establish baseline, emit
   no changes (avoid a first-run flood).

4. **Semantic differ** — `diff(prev: NormalizedSpec, curr: NormalizedSpec) -> [ContractChange]`.
   Deterministic classification (no LLM). `ContractChange = { opKey, kind, verdict,
   before, after, detail }`. **Break taxonomy:**
   - **BREAKING**: response field removed · param removed · optional param made
     required · new required param · operation/endpoint removed · enum value
     removed · type narrowed (e.g. `string`→`integer`, nullable→non-null response).
   - **ADDITIVE**: response field added · optional param added · new enum value ·
     new operation.
   - **AMBIGUOUS**: type changed in a non-narrowing/undecidable way · format change
     → routed to REVIEW / AI.
   `before`/`after` carry the exact schema fragments (the evidence).

5. **Usage scoper** — `tag(change, inventory) -> relevance`. Marks each change
   `used` or `unused`:
   - marketplace-level presence from the existing inventory `usedTechs` (techKey
     e.g. `api:amazon-sp-api`), AND
   - cheap operation-level hint: blob-search the repos for the operation name /
     model id (`getOrders`, `ordersV0`) from the changed `opKey`.
   `used` = marketplace present AND (no operation hint available OR operation hint
   matches). Conservative: when the operation hint is indeterminate, treat as
   `used` (never silently downgrade a real risk).

6. **AI blast-radius** — the single LLM stage, run **only** on `used` +
   BREAKING/AMBIGUOUS changes. Input: the `ContractChange` (with before/after) +
   the repo's usage context. Output: `{ isBreakingForUsage: bool, impact: str,
   recommendedAction: str, evidenceQuote: str }`. Reuses the existing injected
   `classify_fn` seam and the **trust gate** (evidenceQuote must appear in the
   actual before/after fragment — no hallucinated fields; else quarantine to
   REVIEW). Model pinned; `ANTHROPIC_API_KEY` required for the live path, absent →
   deterministic fallback (below).

7. **Findings adapter** — `to_findings(changes, ai_results, now) -> [Finding]`.
   Maps into the **existing** `Finding` model with a new `findingType="contract-drift"`:
   - **Severity is deterministic:** BREAKING + used → **ACTION**; AMBIGUOUS + used →
     **REVIEW**; BREAKING + unused → **watchlist**; ADDITIVE → **OK** (audit trail).
   - `evidence` = the AI impact string when present, else the deterministic
     before/after summary. `sourceUrl` = the spec file URL at the diffed ref.

## Data flow (per run)

```
for each marketplace spec-source:
    raw     = adapter.fetch_spec()                 # {api_name: raw doc}
    for api, doc in raw:
        curr    = normalize(doc, format)
        prev    = snapshot_store.load(marketplace, api)
        changes = [] if prev is None else differ.diff(prev, curr)   # first run: baseline only
        for c in changes: c.relevance = scoper.tag(c, inventory)
        snapshot_store.save(marketplace, api, curr)                 # new baseline
        all_changes += changes

used_breaking = [c for c in all_changes if c.relevance=='used' and c.verdict in ('BREAKING','AMBIGUOUS')]
ai_results    = ai_blast_radius(used_breaking)      # one LLM stage, evidence-gated
findings      = to_findings(all_changes, ai_results, now)
# -> existing delta engine (NEW/RESOLVED/ONGOING) -> report ("Contract breaks" section) -> deliver
```

## Error handling

- **Adapter fetch failure** (network / 4xx / unparseable): that marketplace (or
  api) is skipped this run and recorded as a **coverage gap** — never aborts the run
  (mirrors the existing per-repo degradation contract).
- **No baseline** (first run for an api, or a newly added api): establish the
  snapshot, emit **no** changes.
- **API-file disappearance** (an api present in snapshots but absent from the
  current fetch): flagged as a whole-api **BREAKING** removal **only when the
  marketplace fetch itself succeeded** (the adapter returned other apis) — so a
  transient fetch failure is a coverage gap, not a false "API removed" alarm.
  The snapshot for a genuinely-removed api is retained one cycle for evidence,
  then pruned.
- **Malformed / non-spec response**: skip + coverage note; do not diff garbage.
- **LLM failure / no `ANTHROPIC_API_KEY`**: deterministic fallback — BREAKING+used
  still yields **ACTION**, just without the prose impact; AMBIGUOUS+used →
  **REVIEW** flagged `needsReview`.
- **Trust gate**: an AI result whose `evidenceQuote` is not found in the actual
  before/after fragment is quarantined (downgraded to REVIEW, `needsReview=true`).

## Testing strategy

- **Differ (the deterministic heart): heavy unit coverage.** Crafted before/after
  `NormalizedSpec` pairs for every taxonomy row — field removed, field added, param
  required-added, param removed, type narrowed, enum value removed/added, operation
  removed/added, ambiguous type change. Assert exact `verdict`.
- **Normalizer**: golden fixtures — a small real OpenAPI doc and a small GraphQL
  schema → expected `NormalizedSpec`.
- **Adapters**: injected-HTTP fixtures; SP-API adapter tested against a captured
  models-tree + file fixtures. No network in tests.
- **Snapshot store**: round-trip + first-run-returns-None.
- **Scoper**: inventory fixtures (present/absent; operation hint hit/miss/indeterminate).
- **AI stage**: injected `classify_fn` fake; trust-gate rejection test (hallucinated
  field quarantined).
- **Integration**: simulate the real *"Prune Orders model"* change — a before/after
  SP-API Orders snapshot with `buyerEmail` removed, an inventory that uses
  `api:amazon-sp-api` → assert exactly one **ACTION** `contract-drift` finding with
  the field in the evidence.

## State & infra

- Adds `spec-snapshots/<marketplace>/<api>.json` to the git-backed state branch
  (alongside `kb/`, `findings.json`, `reports/`). Snapshots are normalized (small,
  diff-friendly text).
- Runs inside the **existing ephemeral weekly container** — no new always-on infra.
  Cadence can increase to daily for faster detection without design changes.

## Scope & prerequisites (v1)

- **SP-API — fully implemented in v1.** Public OpenAPI models; works with the
  existing GitHub read path and read token.
- **eBay / Shopify / Walmart — adapter slots, implemented as access allows.** Each
  config-gated with an explicit "needs credential/access" error (like the existing
  `html-changelog` gating) so nothing misconfigures silently:
  - **Shopify**: GraphQL Admin schema via **introspection** — needs a (dev-)store
    access token + API version.
  - **eBay**: OpenAPI contracts exist but direct hot-linking returns 403 — needs
    proper request headers or a mirror/download step.
  - **Walmart**: no clean public machine-readable spec confirmed — may defer to
    Layer 1 (release-notes feed) / Layer 3 until a spec source is secured.

## Decomposition hint for planning

Natural plan boundaries (each independently testable/shippable):
1. **Engine core**: `NormalizedSpec` model + OpenAPI normalizer + semantic differ +
   snapshot store. (Deterministic, no network, no LLM — the highest-value,
   highest-coverage core.)
2. **SP-API adapter + usage scoper + findings adapter + report/delta integration**:
   end-to-end deterministic detection producing real ACTION findings.
3. **AI blast-radius stage** (LLM + trust gate) — the impact narration.
4. **Additional spec sources**: Shopify (GraphQL normalizer + introspection
   adapter), eBay, Walmart — as access permits.
