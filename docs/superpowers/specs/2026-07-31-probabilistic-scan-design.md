# Spec — Probabilistic (AI) scan: a second, opt-in loop over the deterministic one

**Status:** design approved (brainstorm 2026-07-31), ready for implementation plan.

## Problem

The deterministic scan is trustworthy but bounded: it only flags what it can *certify*
(catalogued vendors, known idioms, readable code). This session proved AI can see into the
blind spots (config-driven URLs, exotic wrappers, inferred platforms) — but its output is
**unverified** and must never be presented as certified. We want a second, **opt-in**
probabilistic pass, powered by AI, that runs *after* the deterministic scan and offers a full
second opinion — without ever corrupting the certified report or the `verify` contract.

## Decisions (from the brainstorm)

1. **Output = both.** The AI pass produces **probabilistic leads now** (labeled unverified) AND
   any confirmable lead can be **promoted through the existing absorb gate** to become certified
   on the next deterministic run.
2. **Scope = everything.** The AI cross-checks **all** scanned repos (not just blind spots), so
   the result is a full second opinion — a three-way comparison against the certified findings.
3. **Runtime = both, plugin first.** Interactive plugin flow (`/drift-detector`) is the MVP; a
   headless SDK/CI path is banked, sharing the same promptfile + gate.
4. **Presentation = a separate artifact** (`probabilistic.html`), never a section inside
   `dashboard.html`.

## The two-loop architecture

```
LOOP 1 — DETERMINISTIC (unchanged, zero-token, verify-green)
  drift-scan run → certified findings → dashboard.html / drift.md / drift.json
        │
        ▼   "Scan complete: 33 repos, 43 findings. Run the AI cross-check? (~N tokens)"  ← opt-in
LOOP 2 — PROBABILISTIC (opt-in, AI, labeled UNVERIFIED)
  AI reads ALL repos → ai_results.json
        → probabilistic_compare(ai_results, certified drift.json) → {agree, aiOnly, toolOnly}
        → render_probabilistic → probabilistic.html   (separate artifact)
        → per AI-only lead: "promote?" → drift-absorb gate → human merge → certified next run
```

Loop 1 never waits on AI, never spends a token, stays the source of truth. Loop 2 is strictly
additive and runs only on request.

## The trust boundary (why a separate artifact)

`drift-scan verify` certifies that `dashboard.html` / `drift.md` / `drift.json` agree — the only
permissible correctness claim. If probabilistic findings lived inside `dashboard.html`, `verify`
would have to either ignore them (a hole) or certify them (wrong — they're unverified). So:

- `verify` governs **only** the certified surfaces; its meaning is unchanged.
- `probabilistic.html` is **outside** the verify contract and says so — it is structurally
  unverified, and labelled "AI · unverified" throughout.
- The two cross-link ("← certified report" / "AI cross-check →") but are never confusable.

## Components & boundaries

The one non-deterministic part (AI reading repos) is isolated behind a JSON data contract, so
everything else is pure and testable.

| Component | Kind | New? | Responsibility |
|---|---|---|---|
| `drift-scan run` | pure, zero-token | untouched | the certified scan |
| **AI cross-check driver** | non-deterministic (Claude) | new | read each repo → `ai_results.json` |
| `probabilistic_compare(ai_results, certified)` | pure, deterministic | new | three-way diff + tallies |
| `render_probabilistic(comparison, meta)` | pure renderer | new | `probabilistic.html` |
| promote lead → `drift-absorb` | deterministic gate | exists | leads → certified |

### Data contracts

`ai_results.json` — the driver's output, the ONLY interface between AI and the pure pipeline:
```json
{
  "meta": {"reposRead": 33, "tokens": 782188, "generatedNote": "AI · unverified"},
  "repos": [
    {"repo": "<clone path or identity>",
     "integrations": [
       {"vendor": "Marketplacer", "host": "", "version": "v2",
        "endpoint": "api/v2/client/adverts", "file": "src/Myer/GetProductList.php", "line": "9",
        "retired": "yes|no|unknown", "note": ""}
     ],
     "summary": "one line"}
  ]
}
```
(This is the schema the AI-vs-tool experiment already used — reuse it.)

`probabilistic_compare(ai_results, certified_drift_json) -> comparison`:
```json
{
  "tallies": {"agree": N, "aiOnly": N, "toolOnly": N, "reposReadByAI": N, "reposScanned": N},
  "byRepo": [{"repo": "...", "agree": [...], "aiOnly": [...], "toolOnly": [...]}]
}
```
Matching key: normalize `(vendor)` per repo (first-token, lowercased — the cockpit's `norm`);
an integration is `agree` if the AI vendor matches a certified vendor in that repo, `aiOnly` if
only AI has it, `toolOnly` if only the certified findings have it.

## Error handling

- **An AI agent fails / times out on a repo** → that repo is recorded as `reposReadByAI < reposScanned`
  and listed as "not cross-checked" — NEVER silently dropped (the same "cannot see ≠ clean" rule).
- **AI returns malformed output** → the driver validates against the schema; a bad repo result is
  dropped to "not cross-checked", not fed as a finding.
- **Cost/consent** → the opt-in prompt states repo count and an estimated token cost BEFORE running;
  no tokens spent without the user's yes.
- **A promoted lead** goes through `drift-absorb` unchanged — the gate already refuses unsourced
  dates / false attribution / grown residue, so a wrong AI lead cannot become a certified finding.

## Testing

- `probabilistic_compare` — pure, unit-tested with fixtures: agree/aiOnly/toolOnly classification,
  vendor normalization, the `reposReadByAI < reposScanned` honesty case, determinism (same inputs →
  same output). No network.
- `render_probabilistic` — pure, tested: the "AI · unverified" labelling is present, tallies match,
  cross-link to the certified report, XSS-safe (scan strings escaped), self-contained (no CDN).
- The AI driver is the only component not unit-covered (it's non-deterministic); it is exercised
  manually in the plugin flow and produces the schema the pure tests fixture on.

## Non-goals (YAGNI)

- **Not** the SDK/CI headless path in the MVP (banked; build the interactive plugin flow first).
- **Not** auto-promotion — a human always merges what the gate passes.
- **Not** mixing probabilistic findings into `dashboard.html` or the verify contract.
- **Not** blind-spots-only routing — the user chose a full cross-check (revisit if token cost bites).
- **Not** a new AI mechanism — the driver reuses the experiment's prompt+schema; promotion reuses
  the absorb gate.

## Definition of done (MVP = build steps 1–2)

- `probabilistic_compare` + `render_probabilistic` ship with tests; given a fixture `ai_results.json`
  + a certified `drift.json`, they produce a labelled `probabilistic.html` with correct tallies.
- `/drift-detector` runs the deterministic scan, then offers the cross-check with a cost estimate;
  on yes, reads all repos, writes `ai_results.json`, renders `probabilistic.html`, and offers to
  promote an AI-only lead through `drift-absorb`.
- `verify` still governs only the certified surfaces and stays green; the deterministic path is
  byte-identical to before (the AI pass is strictly additive).
- Full test suite green.
