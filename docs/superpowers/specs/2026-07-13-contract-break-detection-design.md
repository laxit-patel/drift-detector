# Contract-Break Detection (Layer 2) — Design Spec

**Date:** 2026-07-13
**Status:** Approved design. Plan B (engine core) built + merged (Plan 09, 236 tests). Plan C next.
**Parent project:** Integration & Dependency Change-Monitoring Agent (`docs/superpowers/specs/2026-07-10-api-deprecation-agent-design.md`)

## Plan 11 (findings/report integration) design notes — from Plan 10 final review

Plan 10 (contract-scan) emits change dicts `{marketplace, api, opKey, kind, verdict,
before, after, detail}`. When Plan 11 maps these to `Finding`s, mind:
1. **Changes are ONE-SHOT.** A `ContractChange` fires only on the run where the diff
   happens; the next run's snapshot already reflects it, so it will NOT re-fire.
   Plan 11 must therefore PERSIST findings through the existing delta engine
   (NEW→ONGOING→RESOLVED), not rely on the differ re-detecting them each week.
2. **Snapshot key = the file-path-derived `api` name.** If Amazon renames/moves a
   model file, the old snapshot is orphaned and the new path starts a fresh baseline,
   so a *file rename* masks an "operation removed". Acceptable for v1; document it.
3. **Finding id** should key on `projectId | techKey | (opKey + detail)` so it is
   stable across runs for the delta engine. Diff output is already sorted (Plan 09).
4. **v1 detection scope** (proven live 2026-07-13 on 63 real SP-API models, 0 false
   positives): RESPONSE fields + query/path/header params + enums. Request BODIES are
   deferred — a change to a request-body-only definition is NOT flagged (confirmed by
   a live test that pruned a request-body field and correctly saw 0 changes).

## Plan C prerequisites (surfaced by the Plan 09 engine-core final review — do NOT skip)

The deterministic engine (`agent/lib/contract/`) is sound, but before Plan C wires
it to real SP-API specs these must be handled or it will *silently* miss breaks:
1. **Confirm the SP-API model format is OpenAPI 3.0, not Swagger 2.0.** `normalize_openapi`
   keys off `responses.2xx.content.application/json.schema` + `components.schemas`.
   Swagger 2.0 uses `responses.2xx.schema` + `definitions` → `normalize_openapi` returns
   empty operations with NO error (silent total miss). The adapter must detect/convert.
2. **`oneOf`/`anyOf` composition** is not yet flattened (`allOf` + top-level arrays ARE,
   as of Plan 09's final fix). Decide conservative handling; SP-API uses them less than
   `allOf` but they exist. A property/response using only oneOf/anyOf flattens to nothing.
3. **Diff output ordering** is now deterministic (`sorted` by opKey/kind/verdict/before/after),
   so report rendering is stable — keep it that way when Plan C maps ContractChange→Finding.
4. **Spec §4 nullability wording** ("nullable→non-null = BREAKING") is misleading vs the
   correct impl (a *response* field going non-null→nullable is the risky direction, flagged
   AMBIGUOUS). Reconcile the table wording; the code direction is right.

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
  `html-changelog` gating) so nothing misconfigures silently. Source availability
  validated 2026-07-13:
  - **Shopify**: GraphQL Admin schema via **introspection** — needs a (dev-)store
    access token + API version. (Layer 1 changelog RSS already wired.)
  - **Walmart**: Layer 2 source = the **item-spec version table** (reachable HTML,
    diffable); Layer 1 = the What's New / release-notes pages (HTTP 200, pollable
    via `html-changelog`). No OpenAPI, but the item-spec table is a real schema
    source. Feasible without credentials.
  - **eBay**: **hard bot-blocked** — both the OpenAPI contracts and the per-API
    release-notes HTML return 403 even with a browser User-Agent (edge WAF / JS
    challenge, not UA sniffing). Requires a headless-browser render or an
    authenticated download via the eBay developer program, or defers to a manual
    source. **eBay is the one marketplace that needs a heavier fetch path**;
    treat as an explicit follow-on, not a same-effort adapter.

## Relationship to Layer 1 (changelog feeds)

Layer 2 (this spec) catches *uncited* breaks via spec-diff. It complements the
existing Layer 1 changelog capability, whose per-marketplace sources were also
validated 2026-07-13 and should be completed in parallel where cheap:
- **SP-API**: official changelog **RSS** at `developer-docs.amazon.com/sp-api/changelog.rss`
  (validated real) — replace the interim GitHub-commits feed with this.
- **Shopify**: official Atom feed `shopify.dev/changelog/feed.xml` — already wired.
- **Walmart**: What's New / release-notes HTML — needs the `html-changelog` adapter
  wired into ingest (currently built but not wired).
- **eBay**: scattered per-API release-notes HTML — same bot-block as above.

## Implementation sequencing (confirmed 2026-07-13)

Build order chosen: **Layer 1 completion first (fast win), then the Layer 2
engine. eBay deferred to a follow-on** (bot-blocked; needs a headless/auth fetch).

- **Plan A — Layer 1 completion (announced changes, all reachable marketplaces).**
  Fast, reuses built adapters: (1) replace the interim SP-API GitHub-commits feed
  with the official changelog **RSS**; (2) **wire the `html-changelog` adapter into
  ingest** (built + tested, currently gated as "not wired" — thread its
  `(entries, page_hash)` return through `kb_ingest`); (3) add the **Walmart** What's
  New / release-notes feed via `html-changelog`. Shopify RSS already wired. eBay
  deferred. Deliverable: announced-change coverage for SP-API + Shopify + Walmart.
- **Plan B — Layer 2 engine core (deterministic heart).** `NormalizedSpec` model +
  OpenAPI normalizer + semantic differ + snapshot store. No network, no LLM —
  highest unit-test coverage.
- **Plan C — SP-API spec-diff end-to-end.** SP-API SpecSource adapter + usage
  scoper + findings adapter + report/delta integration → real ACTION `contract-drift`
  findings (the "Prune Orders model" integration test).
- **Plan D — AI blast-radius stage.** LLM impact narration behind the trust gate;
  deterministic fallback when the key/model is absent.
- **Plan E — additional spec sources (follow-on).** Shopify (GraphQL normalizer +
  introspection adapter, needs store token); Walmart item-spec-version table
  adapter; **eBay** via headless render or authenticated eBay-developer download.
