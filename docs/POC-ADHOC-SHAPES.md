# PoC — ephemeral / just-in-time shapes (branch `poc/ephemeral-shapes`)

**Not on master.** A proof of concept for the **middle tier** between certified findings and raw AI
leads: an idiom **authored this session**, **gate-validated against one repo**, producing
**deterministic attribution for this run** — then dated by the **same human-curated sunset catalog**.
*AI supplies the where; the reviewed catalog supplies the when.* Nothing is persisted unless the user
opts in via `absorb`.

## Status: mechanism + pipeline proven end-to-end

Fable-5 designed; built per the plan. Acceptance run on `walmart-api` (a real UNKNOWN,
config-driven-url repo, 8 blind `/v3/` paths):

| Check | Result |
|---|---|
| Baseline verdict | `UNKNOWN` (8 blind path literals) |
| `absorb --check` (the gate) | attributed **1 → 9 (+8)**, 8/8 claims met, ✓ passes |
| Ephemeral re-scan | **9 Walmart endpoints attributed** the certified scan never saw |
| `adhoc-report` | `adhoc.json` (`drift-adhoc/v1`, hash-bound) + `adhoc.html` (amber, "gate-validated (this run)") |
| **Certified `drift.json` sha** | **UNCHANGED** — the middle tier cannot contaminate the certified tier |

*(0 dated here only because walmart-api's paths aren't Walmart's specific retiring operations —
attribution is the mechanism; dating is a catalog path-match on top.)*

## What was built
- `agent/lib/adhoc.py` — `compare()` (restrict shaped actions to claimed locs, surface gate problems)
  + `bundle()` (the `drift-adhoc/v1` sibling doc, hash-bound). Pure, unit-tested.
- `agent/lib/adhoc_render.py` — standalone amber `adhoc.html` (never folded into `dashboard.html`).
- `agent/cli.py::adhoc-report` — assembles the artifact from the certified drift.json + the ad-hoc
  re-scan + staged idioms/claims + the gate DELTA. `drift.json`/`verify`/the schema are untouched.
- `agent/absorb.py::check_claims_in_scope` — the anti-gaming guard (claims ⊆ the brief's residue),
  proven to FAIL on the gaming vector (principle 5). **The single riskiest part; do not weaken it.**
- `commands/drift-detector.md` — the A–G orchestration phase + six hard rules.
- `tests/test_adhoc.py`.

## Deliberately NOT built (PoC scope, per Fable)
No federation, no persistence changes, **no `drift-v1` schema change, no `verify` change**, no
`endpoints.py` provenance plumbing (provenance = the claims set, from the gate), no IR cache-key work
(separate state dir sidesteps it), local-path roots only. Folding `adhoc-data` into `dashboard.html`
(a fourth `_blob_script` + sub-tab, + two new verify invariants) is the post-PoC step.

## To reproduce the acceptance
```
S=<certified state> ; A=$S/adhoc/<R> ; ABS=<repo abspath>
drift-scan run --root $ABS --state $S --now $(date +%F)              # UNKNOWN repo
drift-scan brief --repo <R> --state $S                              # the blind lines
#   author $A/staged/{idioms.yaml,claims.yaml}
drift-scan absorb --check --staged $A/staged --repo $ABS            # gate; save the DELTA line
mkdir -p $A/catalog; cp $A/staged/idioms.yaml $A/catalog/idioms.local.yaml
DRIFT_CATALOG_DIR=$A/catalog drift-scan run --root $ABS --state $A/state --now $(date +%F)
drift-scan adhoc-report --state $S --adhoc-state $A/state --staged $A/staged \
   --gate-delta $A/staged/gate-delta.json --repo <R> --now $(date +%F)
# ASSERT: sha256($S/drift.json) unchanged across all of the above.
```
