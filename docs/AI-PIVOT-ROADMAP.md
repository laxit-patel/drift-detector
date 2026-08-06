# AI-driven pivot — roadmap & parked work

Decision record for the 2026-08-06 pivot (Fable-5 reviewed, two passes). **Shipped today** in
`0.14.0-beta`: the Claude plugin restored + rewired to the PyPI package via `uvx`, a persistent
`~/.drift/catalog` (learned catalog survives upgrades), and the two-tier flow (certified findings +
a *separate* AI cross-check). The `absorb`-writes-to-site-packages bug is fixed. Everything below is
**deliberately deferred**, ordered by leverage.

## The reframe (why the order below)
The deterministic tool is the **aid**, not the product. Two assets with opposite economics were
being conflated: **idiom shapes saturate** (4 families, ~a closed set of SDK URL-assembly patterns —
enumerable by a maintainer in a week, no crowd needed) while **vendor sunsets compound forever**
(unbounded, perishable, genuinely missing — there is no OSV for "vendor X retires operation Y on
date Z"). OSV/endoflife.date are **not** user-crowd-sourced; they aggregate authoritative vendor
pages — which `catalog_check.py` + `version_lifecycle.py` already do. **So: publish the data before
soliciting it.** The product story is *a deprecation-intelligence feed, with the scanner + plugin as
its delivery vehicle and contribution funnel* (feed free, fleet-scale delivery paid).

## Parked work, ranked by leverage

1. **Publish the sunset feed** (~1–2d, highest value/effort). Cut a public `drift-catalog` repo
   holding `vendor_sunsets.yaml` + `catalog_attestations.yaml` at a **pinned tag**; make the tool a
   client of that tag exactly as it is OSV's. Add **`catalogVersion` to `drift.json`** + a `verify`
   invariant (reproducibility). Establishes maintainer-of-record with zero contributors.

2. **The structural firewall** (1–2d, do *before* the two tiers share one page). A
   `drift-leads/v1` schema where a **date is unrepresentable** (`additionalProperties:false`, no
   `date` field), hash-bound to the scan (`meta.driftJsonSha256`), reject-on-load for date-shaped
   strings. Then 4 new `verify` invariants — no dates in leads, hash-bound, counts unchanged with
   leads present/absent, every rendered lead badged — **each proven to FAIL on a seeded bug**
   (principle 5). **A lead must NEVER enter `drift.json`** (or a green `verify` starts lying).

3. **The integrated single-page two-tier dashboard** (2–4d). `leads-data` as a fourth
   `_blob_script` (leaving `check_blob_matches_payload` byte-identical), a **`Leads (AI · unverified)`**
   peer sub-tab in the probabilistic blue, counts untouched. Today ships as two separate views
   (`dashboard.html` + `probabilistic.html`) — a *stronger* separation; the merged page is polish.

4. **Fix "beyond PHP" deterministically** (ongoing, code — no crowd can do this). New egress idiom
   **families** for JS/TS (`axios.create({baseURL})`, `` fetch(`${base}/x`) `` template literals) and
   Python (`requests`/`httpx` session base) — none fit the 4 PHP-shaped families. Plus more **encoded
   vendor rules** (the Shopify `version_lifecycle` pattern: one rule dates every version forever and
   can't go stale). One encoded rule beats fifty crowd-sourced entries.

5. **Measure the funnel before building the network.** `absorptions.yaml` already logs every
   absorption with its attributed-call delta. Report **lead→absorb conversion rate**. Near-zero for a
   few weeks ⇒ the federated catalog has no fuel and item 6 should not be built.

6. **Federated contribution — only after 5 proves out.** A one-way `drift-scan contribute` that emits
   a **PR** (never an auto-POST); shareability decided by family (`url-assembly`/`url-append`/
   `operation-marker` public; `path-constant` structurally local — `repo`-scoped); replace `evidence`
   (a client `file:line`) with a public **`corroboration` URL** (requiring one *is* the public/private
   classifier). Merge gate: **`drift-eval` recall-non-regression over the pinned corpus** for idioms
   (the one property the local absorb gate structurally cannot test); **source-fetch + the date-string
   found in the document + 2 human approvals** for dated sunsets, forever. Deny-by-default, human
   opt-in.

## Shelved (enterprise lane — do NOT delete, stop investing)
Private GitLab runner, fleet CI templates, the whole delivery layer (issue-filing — a solo plugin
user has no fleet), and the fresh public-repo cutover (now *actively harmful* — this repo IS the
marketplace source and holds the PyPI Trusted-Publisher binding).
