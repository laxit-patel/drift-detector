# Next iteration — the Go question and learning from the wild

**Date:** 2026-07-30 · **Author:** Fable 5 (architect review #5) · **Branch:** `next/go-wild-learning`
**Status:** design/plan, not code. Recon findings below were fetched and verified this session.

---

## 0 · Executive summary

Two proposals were on the table: (1) rewrite Drift Detector from scratch in Go, and
(2) make it learn how vendor APIs are used "in the wild" from public wrappers, SDKs and
example repos so detection generalizes beyond one client's code.

**Verdict on (1): a from-scratch rewrite of the scan core is churn — don't.** Go shells
out to the ast-grep engine exactly like Python does today (there is still no Go binding;
verified again this session), so the rewrite buys no detection capability, no
performance, and no engine story — while re-rolling the dice on 505+ tests, each of which
pins a real shipped bug. **But the instinct behind the Go choice is right** for the part
of the system that doesn't exist yet: the wild-learning corpus miner, the multi-forge
fleet resolver, and delivery are cloud/platform surfaces where Go is genuinely the better
tool. **Recommendation: Go greenfield for the new platform layer (`drift-wild`,
`drift-fleet`), Python untouched for the proven scan core**, joined at the seams that
already exist (`drift.json`/`inventory.json` schemas + the YAML catalogs + the absorb
gate). A full port stays trigger-gated, same discipline CLAUDE.md applies to Rust.

**Verdict on (2): real, valuable, and mostly deterministic.** Recon confirms the wild is
rich exactly where our clients live (eBay, Amazon SP-API, Shopify) and — just as
important — confirms it is *barren* for the AU/NZ niche vendors, so wild-learning is a
complement to the catalog, never a replacement. The highest-value mining targets are not
even "learning": vendors publish machine-readable API models
(`amzn/selling-partner-api-models`, eBay OpenAPI contracts, Kogan's OpenAPI + `llms.txt`)
that can be parsed, and public SDK/wrapper repos can be **scanned with our own scanner**
to produce `sdk_profiles.yaml` — the knowledge that finally closes the SDK-mediated
blind spot (the `getCategoryFeatures` ceiling). Everything mined is a *hypothesis* that
enters through the existing absorb-gate discipline; nothing mined ever produces a
retirement date. **No AI is needed for phase 1–2. No SLM in CI, ever. No embeddings until
a demonstrated retrieval failure.** BM25 over the mined corpus (server-side, curator
tool) is the only "search" worth building, and only in phase 3.

---

## 1 · The rewrite verdict: Go, the engine, and what the real driver is

### 1.1 The engine facts (re-verified 2026-07-30)

CLAUDE.md's Rust-port section claims Rust is the only language that links the ast-grep
engine natively and that Go would shell out like Python does. That claim **still holds**:

- There is **no ast-grep Go binding** — the [ast-grep org](https://github.com/ast-grep)
  ships the Rust crates, a Python binding (`ast-grep-py`, measured *slower* than the
  subprocess: 144ms vs 74ms, because the CLI parallelizes in Rust), and a napi/Node route
  that puts PHP on a 0.0.x grammar. Nothing for Go.
- Go *can* link **tree-sitter** directly — official
  [tree-sitter/go-tree-sitter](https://github.com/tree-sitter/go-tree-sitter) bindings
  plus [tree-sitter-php Go bindings](https://pkg.go.dev/github.com/tree-sitter/tree-sitter-php/bindings/go)
  exist. But that is the *parser*, not the engine: we would be reimplementing ast-grep's
  pattern language (`$A->getHost() . $B`, metavariables, kinds) ourselves, and the absorb
  gate compiles idiom instances into exactly those patterns (`agent/lib/idioms.py:75-105`,
  `to_rules`). Reimplementing a pattern engine to avoid a subprocess is the definition of
  accidental scope. It also drags in cgo, which taxes the very thing Go was chosen for —
  painless static cross-compilation.

So a Go scanner has two honest options: **subprocess to the pinned ast-grep binary**
(what Python does today via `bin/drift-scan:154`, `AST_GREP_VERSION=0.44.1`, sha-pinned
in the container) — possibly `go:embed`-ing that binary for a one-file distribution — or
**cgo + tree-sitter + a bespoke matcher**. The first is architecture-identical to today.
The second is a multi-week engine project that buys nothing the subprocess doesn't.

### 1.2 So what would a Go rewrite of the *scanner* actually buy?

Run the candidate drivers honestly:

| Claimed driver | Reality |
|---|---|
| Performance | None. Scan time is already inside a Rust binary (CLAUDE.md: "no performance case"). Python is orchestration + joins over small JSON. |
| Single binary | Real but already solved to the degree anyone has asked: sha-pinned container (GHCR), `uvx` path banked. `go:embed` of ast-grep would be *nicer*, but no client has hit the trigger ("single no-network binary and uvx/PyInstaller won't do"). |
| Concurrency at fleet scale | The fleet is **3 repos** today. ast-grep parallelizes internally; the per-repo loop is I/O-bound on git clones. When the fleet is 300 repos, the bottleneck is the *resolver and forge APIs* — which is new code either way (TECH_DEBT.md, "Pluggable source-resolver drivers"). |
| Cloud/platform fit | Real — for services. The scan is a batch CLI in CI; Python is fine there and proven. The *new* long-running surfaces (corpus miner, fleet service) are where Go's deployment story pays. |
| Fresh start avoids old pitfalls | Backwards. The pitfalls are *encoded in the tests* — 505+ of them, each comment pinning a shipped bug (the version-less dedup key that silently suppressed retired findings, `agent/lib/endpoints.py:53-61`; the unstable-match-order determinism bug; the leading-slash path-literal invisibility, `classify_url.py:194-204`). A from-scratch rewrite doesn't avoid those pitfalls; it forfeits the regression suite that proves they stay fixed and re-ships some of them. CLAUDE.md's own port instructions say to carry the landmines *and the tests' prose* across. |

**The real driver, named:** the user's instinct — "this iteration leans cloud/platform
engineering" — is about the **new** system: mining public corpora on a server, resolving
multi-forge fleets, running scheduled enrichment, serving a curator UI/search. Those are
greenfield, concurrent, network-heavy, deploy-as-a-unit services. That is a *legitimate
Go project*. It just isn't a rewrite of `agent/lib/endpoints.py`.

### 1.3 Recommendation: split by maturity, not by fashion

- **Keep the Python scan core as-is** (`scan → audit → render → verify`, the absorb gate,
  the catalogs). ~6.3k prod + 5.7k test LOC of institutional memory, stdlib+PyYAML only,
  deterministic, shipped, and delivering. It is the *trust anchor*; rewriting the trust
  anchor first is how you lose the trust.
- **Write the new iteration's new code in Go**, as separate binaries with their own repo
  or `cmd/` tree:
  - `drift-wild` — the corpus miner + spec parser + SDK profiler (this document, §2–4).
  - `drift-fleet` (later) — the multi-forge resolver/driver model from TECH_DEBT.md, if
    and when a fleet actually spans forges.
- **The seam is data, and it already exists:** `drift.json` (schema'd), `inventory.json`,
  and the YAML catalogs under `agent/`. Go writes *staged proposals*; the Python absorb
  gate remains the only write path into the catalogs (`agent/absorb.py`). No RPC, no
  shared library, no FFI — a polyglot system joined by reviewed files in git is exactly
  the Tier-3 decision already on record ("learning happens between scans in git-versioned
  artifacts, never in mutable scan-time state").
- **A full port of the core stays trigger-gated**, mirroring CLAUDE.md's Rust gate:
  1. the pipeline modules go a full quarter without structural change, AND
  2. a client needs a single no-network binary that container/uvx can't satisfy, or the
     scanner is sold as a product.
  If those fire *and* the team still prefers Go over Rust (accepting that Go permanently
  forfeits the native-engine endgame — that's the real cost of parking Rust), the port
  path is the one already written: **harden `drift-eval` with a byte-diff mode FIRST**,
  port engine-adjacent modules behind the existing `run=` seam, renderers + `verify`
  last, and carry the landmine list (RE2 has no lookbehind — the `verify.py`
  `(?<!\\)\|` must be rewritten; Go map order; `SetEscapeHTML(false)`; float notation
  `1e+16` vs `10000000000000000` — `check_number_formats` exists because of exactly
  this).

**Blunt version:** "rewrite from scratch to avoid the precursor's pitfalls" is the one
justification that must be refused — the pitfalls listed in the brief (7-of-8 language
gap, multi-vendor idiom guard, access bottleneck, config-driven URLs) are **capability
gaps, not code-quality debts**. A rewrite in any language inherits all four on day one.
The wild-learning program below attacks the actual gaps; the rewrite would only delay it
by 4–8 weeks.

---

## 2 · Learning from the wild: what the recon actually found

Real reconnaissance, all URLs fetched/verified this session (two research passes:
eBay/Amazon; Shopify/AU-NZ/Walmart). Full findings condensed here because they *are* the
design constraints.

### 2.1 The wild is rich where our vendors are big…

**eBay**
- [timotheus/ebaysdk-python](https://github.com/timotheus/ebaysdk-python) — 854★, PyPI
  `ebaysdk`, **not archived but dormant** (last push 2023-05). Wraps Finding, Shopping,
  Merchandising, Trading — *two of its four APIs are decommissioned* (Finding + Shopping,
  2025-02-05) while the package still installs. URL idiom: config-driven domain with
  hardcoded defaults — `Config(domain='svcs.ebay.com')` + `set('uri',
  '/services/search/FindingService/v1')`.
- [hendt/ebay-api](https://github.com/hendt/ebay-api) — 206★, npm, active; covers both
  the dying traditional XML APIs *and* the RESTful Buy/Sell. Idiom: fixed base
  `https://api.ebay.com` with **dynamic subdomain switching** (`apix`/`apiz`).
- [davidtsadler/ebay-sdk-php](https://github.com/davidtsadler/ebay-sdk-php) — 354★,
  **archived 2021**; service-object idiom, no URL literals at call-sites.
- [ericblade/ebay-find-api](https://github.com/ericblade/ebay-find-api) — archived
  2025-12 with the banner *"THIS API IS NO LONGER AVAILABLE AT EBAY"*.
- Vendor machine-readable sources: OpenAPI contracts (OAS2+OAS3) for every RESTful API
  ([announcement](https://developer.ebay.com/updates/blog/ebays-openapi-3-0-contracts-now-available)),
  portal downloads (no monorepo); the traditional APIs are WSDL-era and *invisible* to
  OpenAPI tooling — which is precisely where the retirement risk concentrates. The
  deprecation RSS we already parse (`agent/lib/catalog_sources.py:19`) remains the
  structured retirement source.

**Amazon SP-API**
- [amzn/selling-partner-api-models](https://github.com/amzn/selling-partner-api-models)
  — official, 881★: **Swagger/OpenAPI JSON per API family and version**, diffable in
  git. This is the canonical machine-readable endpoint universe for the vendor our
  clients call 272 times.
- [saleweaver/python-amazon-sp-api](https://github.com/saleweaver/python-amazon-sp-api)
  — 667★, very active. Idiom: `BASE_URL = "https://sellingpartnerapi"` +
  `f"{BASE_URL}-na.amazon.com"` — **the full host never exists as one literal**. This is
  our concat-idiom wall, photographed in the wild.
- [jlevers/selling-partner-api](https://github.com/jlevers/selling-partner-api) — 436★,
  PHP, generated from Amazon's models; idiom: `Endpoint::NA` enum, hosts internal, zero
  URL literals downstream. [highsidelabs/laravel-spapi](https://github.com/highsidelabs/laravel-spapi)
  wraps *it* — second-order wrapping is normal.
- [amz-tools/amazon-sp-api](https://github.com/amz-tools/amazon-sp-api) — 262★, npm;
  idiom: `callAPI({operation: 'getMarketplaceParticipations', endpoint: 'sellers'})` —
  **operation-name dispatch, no URLs in client code at all**.
- [amazon-php/sp-api-sdk](https://github.com/amazon-php/sp-api-sdk) — 134★; "99% of
  code auto-generated from the SP-API models" — the wrapper *is* a projection of the
  spec.

**Shopify**
- [Shopify/shopify-app-js](https://github.com/Shopify/shopify-app-js) — official TS
  monorepo. `ApiVersion` enum (`January25 = '2025-01'` … `October26 = '2026-10'`), REST
  client validates paths against `^/admin/api/[^/]+/(.*)\.json$` — the same grammar as
  our `pathSignature` (`agent/vendors.yaml:19`).
- [Shopify/shopify-api-php](https://github.com/Shopify/shopify-api-php) — official PHP:
  `$path = "/admin/api/$apiVersion$path"`.
- [phpclassic/php-shopify](https://github.com/phpclassic/php-shopify) — 3.8M+ installs.
  **`public static $defaultApiVersion = '2025-01';`** — a wrapper-pinned default version
  is a drift vector all by itself: a client on an old package release silently pins a
  sunsetting API version, with no version string anywhere in the client's own code.
- [gnikyt/Basic-Shopify-API](https://github.com/gnikyt/Basic-Shopify-API) — version via
  `setVersion('2020-01')`, callers pass *unversioned* paths (`/admin/shop.json`).
- REST Admin is legacy since 2024-10, GraphQL-only for new public apps since 2025-04,
  first physical REST removals began 2025-10 ([shopify.dev](https://shopify.dev/docs/api/admin-rest)).
  No public OpenAPI for REST; the GraphQL schema is published per-version.

**Walmart (mid-tier control):** [highsidelabs/walmart-api-php](https://github.com/highsidelabs/walmart-api-php)
— OpenAPI-generated, host hardcoded (`https://marketplace.walmartapis.com`), version
baked into generated operation paths. Spec-diffing beats idiom-mining here.

### 2.2 …and genuinely barren where our vendors are niche

This is the finding that disciplines the whole design:

- **Trade Me:** the official wrapper is [deprecated by Trade Me itself](https://github.com/TradeMe/trade-me-api-wrapper);
  community remnants are stale hobby repos.
- **Kogan:** **zero** public wrappers — but the vendor publishes an OpenAPI spec *and an
  `llms.txt`* ([developers.kogan.com](https://developers.kogan.com/docs/getting-started)),
  the best-case machine-readable source shape.
- **Catch:** the marketplace itself **shut down 2025-04-30** (Wesfarmers ASX
  announcement). **MyDeal: closed 2025-09-30** (Woolworths). Zero open-source residue for
  either. An entire vendor dying is caught by the *sunset catalog*, not by idiom mining.
- **Marketplacer** (platform behind several AU marketplaces): official Node example has
  **0 stars**; single per-tenant GraphQL endpoint — no version in the URL at all.

**Consequences:**
1. Wild-learning is **vendor-weighted**: it will materially improve eBay/Amazon/Shopify
   detection and do *nothing* for MyDeal/TheMarket/Harvey Norman. The seller-portal
   access blocker (memory, 2026-07-29) stands; say so in the report rather than implying
   the wild covers everyone.
2. Where wilds are sparse, **vendor-published machine-readable sources** are the fallback
   (Kogan's OpenAPI, Marketplacer's GraphQL schema) — that's `catalog_sources.py`
   territory (freshness wiring), not corpus mining.
3. The recon *itself* validated the moat: three of the twelve repos examined are
   wrappers that outlived their API (ebaysdk-python, ebay-find-api, TradeMe's own). The
   wild is full of confidently-installable dead code — which is the product's pitch.

### 2.3 The four URL-shaping idioms of the wild (the detection taxonomy)

Across both recon passes, every wrapper falls into one of four shapes:

| # | Shape | Wild example | What catches it |
|---|---|---|---|
| A | Default-domain config string | ebaysdk-python `domain='svcs.ebay.com'` | Today's URL/host rules already fire |
| B | Concat/format region suffixing | `f"{BASE_URL}-na.amazon.com"` | Branch-1 concat idioms + `pathSignature`; needs per-language assembly rules |
| C | Operation-name dispatch, zero URLs | `callAPI({operation: ...})`, `Endpoint::NA` | **Nothing today** at the client call-site — needs SDK profiles (§3.2) |
| D | Fixed base + dynamic subdomain / per-tenant host | hendt `apix.ebay.com`, Marketplacer `{tenant}.marketplacer.com/graphql` | Host-fragment matching (`classify_url._matches`) partially; GraphQL needs operation-level evidence |

Shape C is the important one: it is the `getCategoryFeatures` deterministic ceiling
(memory, PM demo #2) and the `AccountService::API_VERSION` eval finding, *and* the recon
shows it is the dominant shape among modern generated SDKs. No amount of cleverer
call-site scanning fixes C — the version/endpoint knowledge physically lives in the
dependency, not the client code. That insight drives the central new mechanism:

---

## 3 · The design: wild knowledge as reviewed catalog data

Principle up front: **a mined pattern is a hypothesis, not truth.** Everything below is
shaped so a hypothesis becomes catalog data only through a deterministic gate, with
provenance, exactly as sunsets do today (`agent/absorb.py:47-81` refuses a date without
a source; the same posture, new knowledge kinds).

### 3.1 What gets mined — three tiers, by trust

**Tier S — vendor-published machine-readable specs** (highest trust, zero learning):
parse `amzn/selling-partner-api-models` (Swagger per family+version), eBay OpenAPI
contracts, Kogan OpenAPI, Walmart specs, Shopify's version calendar (already computed:
`agent/lib/version_lifecycle.py:35`). Output: the **endpoint universe** per vendor —
`(family path, version, operations)` — which mechanically grows Index A:
`pathSignature`s, `versionRegex`es, the `api_path_of` family anchors
(`classify_url.py:157-191`), and operation vocabularies for the operation axis
(`classify_url.py:146-154`). This is *parsing*, deterministic and replayable: pin the
spec repo SHA, commit the extraction, diff on refresh.

**Tier A — SDK profiling** (the crux, closes shape C): treat public wrappers as *scan
targets for our own scanner*. Scanning `saleweaver/python-amazon-sp-api` at a pinned SHA
attributes its internal endpoints (the wrapper's code *does* contain the hosts, paths and
versions the client's code lacks). Persist the result as **`sdk_profiles.yaml`**:

```yaml
- package: jlevers/selling-partner-api        # composer name
  registry: packagist
  versions: ">=5.0 <6.0"                       # lockfile-joinable range
  vendor: Amazon SP-API
  endpoints:                                   # what the wrapper itself calls
    - { apiPath: /orders/v0, operations: [getOrders, getOrderItems] }
    - { apiPath: /fba/inbound/v0 }
  minedFrom:                                   # provenance, non-negotiable
    repo: https://github.com/jlevers/selling-partner-api
    sha: <commit>
    scannedOn: "2026-07-30"
```

At client-scan time the join is: lockfile (`agent/lib/lockfile.py` already resolves exact
versions) → package@version → profile → the client is *exposed* to those endpoints.
Findings carry a new attribution class, `attribution: sdk-profile`, beside the existing
`observed`/`inferred` (`endpoints.py:72-76`) — and render as **"exposure via dependency
jlevers/selling-partner-api 5.x"**, never as a fabricated client `file:line`. The
evidence location is the dependency edge (the probe's EDGES join already computes edges;
this gives the edge *content*). "Cannot see ≠ clean" is preserved: an SDK-mediated call
stops being invisible and becomes an honestly-labeled, dependency-scoped fact.

**Tier B — idiom census** (community wrappers, lowest trust): run the assembly/idiom
rules across the curated corpus and *count* recurring URL-assembly shapes per language
(`sprintf`, f-string suffixing, Guzzle `base_uri`, `urljoin`, enum dispatch). Output:
**candidate idiom instances** for the existing closed families
(`idioms.py:23 FAMILIES = {url-assembly, url-append, operation-marker}`), and — where a
shape doesn't fit a family — a *documented proposal for a new family*, which stays a code
change + PR per the idioms.py docstring. Because each candidate is mined from a specific
vendor's wrapper, it arrives **vendor-scoped by construction** — which finally gives the
banked vendor-scoped-idioms enhancement its data source, instead of hand-authoring
scopes.

**Also mined, but only as *leads*:** archived-repo banners ("THIS API IS NO LONGER
AVAILABLE"), dormant wrappers of dead APIs, wrapper CHANGELOG migration notes. These feed
the **freshness Curator's work orders** (`agent/lib/freshness.py`, `/drift-refresh`) as
"go check the vendor's page" prompts. They are **never** admissible as dates — the gate
already refuses them, and the recon demonstrated why: the eBay/Amazon pass correctly
declined to record the MWS shutdown date because no dated Amazon source was fetched in
session. The discipline held even during recon; keep it that way.

### 3.2 How a mined hypothesis enters the catalog (gate extensions)

The absorb gate grows two checks, same shape as the existing three:

1. **Profile regeneration check** (for `sdk_profiles.yaml`): a staged profile must be
   *reproducible* — the gate re-scans the pinned `minedFrom.repo@sha` and requires the
   staged endpoints to be ⊆ the scanner's own attribution of that repo. A profile is
   literally a scan output, so the gate is "regenerate and diff" — fully mechanical, no
   trust in the miner. (Analogue of `measure_against_repo`'s claims check,
   `absorb.py:94-146`.)
2. **Corpus-pinned idiom check** (for wild-mined idioms): today's gate already requires
   claims to be met, no invented vendors, no unclaimed attributions, residue to shrink.
   Extend `evidence:` to require the *public* repo+SHA+file:line the idiom was mined
   from, and run the measure against a pinned corpus repo (the `eval/corpus.yaml`
   machinery — SHA-pinned, hard-fail on drift — is reused verbatim as
   `wild-corpus.yaml`).

Unchanged and load-bearing:
- **Never-invent-a-date is untouched.** Wild mining produces *detection* knowledge
  (Index A) and freshness *leads*. Retirement facts (Index B) still enter only from
  vendor sources through `check_sunsets`.
- **Attestations stay claims about the world** (`catalog_coverage.py`): an SDK profile
  gets its own `scannedOn` date and goes STALE on the same 90-day clock — a profile of a
  wrapper that has since shipped ten releases must decay visibly, not silently.
- **Provenance tiers render.** Every wild-derived record carries
  `vendor-published-spec | official-sdk | community-wrapper`, and the report shows it,
  so a reader can weigh a fact from Amazon's own models differently from one mined from
  a 29-star wrapper.

### 3.3 What wild-learning explicitly does NOT fix

Say it in the doc so nobody resells it internally as magic:
- **Access.** channelwiz's `tops/*` wrappers are private; no public corpus approximates
  them. The fix remains the fleet-membership ask (TECH_DEBT.md, vendor-scoped idioms
  entry: "fleet access beats teaching the scanner"). SDK profiles help only where
  in-house code wraps *public* packages — which the probe's EDGES output can now tell us.
- **Niche AU/NZ vendors.** §2.2. Portal-gated changelogs stay a human Curator lane.
- **Runtime egress.** The banked OTel/access-log signal (TECH_DEBT.md #1–2) is a
  different axis (dynamic vs static) and stays banked on its own trigger.

---

## 4 · Architecture: AI vs no-AI, CI vs server

### 4.1 The AI question, taken seriously

The user floated four architectures. Assessment:

| Option | Verdict | Why |
|---|---|---|
| **No AI — deterministic corpus mining** | **Build this. It is phases 1–2 entirely.** | Tier S is spec *parsing*. Tier A is *running our own scanner* on public repos. Tier B is *counting matches* of existing rule kinds. None of it needs a model; all of it is replayable, diffable, gate-checkable. The tool's identity — deterministic + honest — extends to the learning pipeline for free. |
| **Lucene / semantic search (+ maybe embeddings)** | **BM25 yes (phase 3, curator tool); embeddings no.** | The retrieval question is "given this residue sample / this vendor, what does the corpus know?" over a corpus of ~dozens of vendors, hundreds of endpoint families, tens of idioms. Entities are URLs, paths, and code shapes — **lexical overlap IS the signal**; there is no synonymy problem for `/ws/api.dll`. An embedded BM25 index ([bleve](https://github.com/blevesearch/bleve) in Go, or even SQLite FTS5) gives the Curator "search the wild" during freshness sessions at ~zero cost. A vector DB + embedding pipeline adds infra, non-determinism and a re-embedding lifecycle for no measurable recall win at this corpus size. Revisit only on a *demonstrated* retrieval failure ("BM25 couldn't find X that was in the corpus"). |
| **SLM runnable inside CI** | **No — twice over.** | (a) If it's in the scan path it violates principle 3 (zero-token, byte-identical) — the one property clients can verify. (b) If it's *outside* the scan path, "runs in CI" buys nothing: learning already happens between scans in git-versioned artifacts (the Tier-3 decision), where a *frontier* model in an offline Learn session is strictly more capable than any self-hostable SLM, and the absorb gate — not the model — is the safety property anyway. An SLM is the worst point on the curve: weaker than the Learn-loop model, more infra than no model. |
| **RAG pipeline + small AI** | **Not a system to build; a tool to hand the existing scout.** | The already-designed Tier-2 scout (residue-triggered, quarantined proposals, mechanical-verify-then-human-approve) simply gains a search tool over the mined corpus index when it eventually gets built (phase 4). That's "RAG" as ten lines of plumbing, not an architecture. If corpus-scale AI triage is ever needed (e.g., classifying 500 wrapper repos), it's an offline batch job — the Batches API runs at 50% price and none of it touches the scan path. |

**The honest one-liner:** the wild-learning corpus is *made of* code and specs —
artifacts that deterministic tools parse natively. AI earns a place only at the two
human-shaped edges (triaging ambiguous residue, reading prose changelogs), both of which
already have a designed home (Tier-2 scout; freshness Curator) with the gate between
them and the catalog. Anything more is over-engineering.

### 4.2 The CI/server line (drawn once, enforced by construction)

```
┌─ CI (deterministic, zero-token, reproducible) ────────────────────────┐
│ drift-scan run/verify · reads catalogs (baseline + overlay, git-      │
│ pinned) · reads sdk_profiles.yaml · byte-identical given same inputs  │
└──────────────────────────────▲────────────────────────────────────────┘
                               │ ONLY via reviewed, git-versioned YAML
                               │ (absorb gate → MR → human merge)
┌─ Server / offline (the LEARN loop, scheduled) ────────────────────────┐
│ drift-wild (Go): fetch spec repos + curated wrapper corpus (SHA-      │
│ pinned wild-corpus.yaml) · parse specs · SDK-profile scans · idiom    │
│ census · BM25 index build · freshness lead extraction                 │
│ output = STAGED proposals, never direct catalog writes               │
│ (later, phase 4: Tier-2 scout sessions consume the corpus here)       │
└───────────────────────────────────────────────────────────────────────┘
```

Rules that make the line real, not aspirational:
- The scan path gains **zero** new network calls and zero new dependencies; it only
  reads one more catalog file kind.
- `drift-wild` runs on the drift-ops cadence (weekly/monthly job or a small service —
  either is fine; start as a scheduled job, service-ify only when someone needs the
  search UI live).
- Corpus membership is **curated and pinned** (`wild-corpus.yaml`, per-vendor repo lists
  with SHAs — the recon above is its seed content). No GitHub-wide crawling: the corpus
  that matters is ~10–20 repos per major vendor, and pinning is what makes gate checks
  replayable.
- `verify` gains an invariant: any finding whose sunset joined through an `sdk-profile`
  attribution must render as dependency-scoped exposure (guard the honesty of the new
  evidence class the same way `check_owner_split` guards the owner split).

---

## 5 · What carries over vs. what's new (and which pitfalls are designed away)

**Carries over untouched (the moat):** the endpoint/attribution model with all four axes
— host→vendor, path→version, operation (`classify_url.operation_of`), API family
(`api_path_of`; Amazon retires per *(family, version)*, the catalog can express it);
KNOWN/UNKNOWN + CURRENT/STALE/UNAUDITED + residue-as-conscience; the absorb gate and
catalog-as-reviewed-data; attestations; the freshness loop; the eval harness (recall as
a hard gate); determinism (sorted walks, version-carrying dedup keys — the
`endpoints.py:53-61` lesson stays encoded in tests).

**New:** `sdk_profiles.yaml` + its gate check + the `sdk-profile` attribution class and
verify invariant; `wild-corpus.yaml`; the Tier-S spec extractors; `drift-wild` (Go);
provenance tiers in rendering; per-language egress rules *derived from* the corpus (next
paragraph).

**Pitfalls from the precursor → how this design answers each:**

| Pitfall | Answer |
|---|---|
| 7-of-8 languages have no egress rules | The corpus is the cure's raw material *and* its test set: the JS/TS/Python wrappers found in recon (hendt/ebay-api, saleweaver, amz-tools, shopify-app-js) exhibit exactly the sink/assembly shapes those rules must catch, and become the SHA-pinned eval corpora for the new languages. Phase 2 ships JS+Python egress rules validated against them — wild-learning's *first* deliverable is language coverage, not new vendors. |
| Idiom absorption only works in single-vendor repos | SDK profiles bypass the guard entirely for shape-C code (no idiom needed), and mined idioms arrive vendor-scoped by construction, giving the banked enhancement its safe form. The strict guard (`endpoints.py:125-149`) stays for unscoped idioms. |
| Version-less dedup key suppressed findings | Identity keys are contracts: any new record kind (profiles, corpus entries) defines its dedup key explicitly in the schema, with a paired regression test proven to fail on the collapsed-facts bug (principle 5). |
| config-driven-url / interpolated hosts | Shape B+D coverage grows via mined signatures (Tier S gives every vendor's path grammar, not just Shopify's); the residue conscience remains for what still escapes. Cheap add-on kept from TECH_DEBT: read `.env.example` for hosts. |
| Access is the real bottleneck | Not solved here, and the report should keep saying so (probe/EDGES + accept-with-reason). Wild-learning narrows what *access alone* can't see (public-SDK-mediated calls), nothing more. |
| Rewrite risk itself | §1 — the core is not rewritten; the 505-test regression suite keeps its jurisdiction. |

---

## 6 · Phased plan (prove it small, gate everything)

**Phase 0 — seams (≈1 week, Python only)**
- Schema for `sdk_profiles.yaml` + loader behind the catalog overlay; `sdk-profile`
  attribution class + verify invariant; `wild-corpus.yaml` format (clone of
  `eval/corpus.yaml` semantics). Exit: a *hand-written* profile for
  `jlevers/selling-partner-api` flows lockfile→profile→report on the real fleet, verify
  green, rendered as dependency-scoped exposure.

**Phase 1 — prove the mining (2–3 weeks, still zero AI; first Go code)**
- `drift-wild` v0 (Go): clone pinned corpus; run Tier-S extraction on
  `amzn/selling-partner-api-models` (families/versions/operations) and diff against
  `vendor_sunsets.yaml` scopes; run Tier-A profiling (invoke the existing Python scanner
  on wrapper repos) for jlevers + saleweaver + phpclassic/php-shopify; stage proposals;
  absorb-gate them (new regeneration check).
- **Success criteria (measurable):** (a) ebayapi's `getCategoryFeatures`-class
  SDK-mediated exposure appears as an `sdk-profile` finding instead of a silent miss;
  (b) the SP-API family list extracted from the spec repo reconciles with our catalog's
  `/fba/inbound/v0` vs `/finances/v0` scoping with zero hand-edits; (c) a Shopify client
  pinned to an old `phpclassic/php-shopify` release surfaces the wrapper's
  `$defaultApiVersion` exposure.

**Phase 2 — spend the corpus on the language gap (2–3 weeks)**
- JS/TS + Python egress rules (sinks + assembly), mined from and eval'd against the
  corpus wrappers; wire those repos in as new eval categories. This attacks open-item #1
  (7-of-8) with real-world fixtures instead of synthetic ones.

**Phase 3 — productize the loop (as needed)**
- Schedule `drift-wild` in drift-ops; profile-staleness surfacing; BM25 (bleve/FTS5)
  corpus search for the Curator; archived-repo/dormancy leads feeding `drift:freshness`
  work orders. Optionally begin `drift-fleet` (multi-forge drivers) *if* a real fleet
  spans forges by then — its own trigger, per TECH_DEBT.md.

**Phase 4 — gated cognition (unchanged design, new fuel)**
- Tier-2 scout sessions get corpus search; vendor-scoped idioms shipped only where
  profiles demonstrably don't cover a real repo's residue.

**Triggers to *stop* or re-scope (the CLAUDE.md discipline, applied to this program):**
- If Phase 1's success criteria don't hold on the real fleet — i.e., profiles don't
  convert real residue/blindness into honest findings — bank the program and write down
  why; don't proceed to Phase 3 infrastructure on faith.
- Full-Go-port question reopens only on the §1.3 triggers, quarterly.
- Embeddings/vector search only on a logged BM25 retrieval failure.
- SLM: no trigger exists; the design refuses it (§4.1).

Estimated total to end of Phase 2: **5–7 weeks** — comparable to the low end of the
rewrite estimate, but every week ships detection capability instead of re-shipping
existing behavior.

---

## 7 · Honest risks, and what I'd talk you out of

**Risks in what I *am* recommending:**
- **Profile staleness/version-skew:** a profile mined at wrapper v5.3 misstates v5.9.
  Mitigations: version-range keys joined against lockfile-exact versions, the 90-day
  STALE clock, and rendering the range on the finding. Residual risk is real; the
  finding text must say "exposure *as of* profile date".
- **Polyglot seam tax:** two languages means two toolchains in CI and a schema that must
  be versioned like an API (it already is — `drift-v1.schema.json` discipline extends to
  the new files). Accepted cost; cheaper than a rewrite.
- **Corpus curation is a standing chore:** someone owns `wild-corpus.yaml` like someone
  owns the sunset catalog. It's the Maintainer role's third stream (absorption,
  freshness, now corpus) — name it in the role docs or it rots.
- **Second-order wrappers** (laravel-spapi → jlevers) need transitive profile joins;
  Phase 1 should punt (profile the base package only) and record the punt.

**Don't build (talking you out of parts of the sketch):**
1. **The from-scratch Go rewrite of the scan core.** §1. It re-rolls 505 dice to win a
   subprocess we already have. If one day the port triggers fire, port module-by-module
   behind a byte-diff oracle — never "from scratch".
2. **An SLM in CI.** It sacrifices the product's one non-negotiable (deterministic,
   zero-token scan) for a capability the offline Learn loop already has in stronger form.
3. **Embeddings/vector infrastructure now.** Lexical corpus, lexical search. BM25
   embedded, later, as a curator convenience.
4. **A GitHub-wide crawler / "index the wild" ambitions.** The useful wild per vendor is
   10–20 curated, pinned repos (recon proves it — and proves the niche vendors have ~0).
   Curation is what keeps gate checks replayable; crawling is what poisons catalogs.
5. **LLM-as-detector or any scan-time model influence** — already refused in the Tier
   architecture; restated here because "learn from the wild" will tempt someone to wire
   the corpus into the scan directly. The corpus reaches the scan only as reviewed YAML.
6. **Rewriting to fix capability gaps.** The four precursor pitfalls are closed by new
   *knowledge kinds* and new *rules*, not by new *language*. Budget accordingly.

---

## 8 · Language re-assessment — the code-management POV (requested debate)

The user reframed: de-weight native-AST to one factor; the real concern is **managing a
rapidly-growing, complex codebase** — design patterns over duct tape, clean tests, no
runtime dep pile; Python "reads clanky and is dep-heavy"; Go compiles to a single fast
binary; Rust "may struggle on larger codebases"; Java/Kotlin on the table. Debate was
explicitly invited. Here it is, grounded in measurements taken today, not vibes.

### 8.1 Is the current Python "duct-taped and spread out"? Measured: no.

I re-audited the codebase specifically for this question:

- **79 modules, and the size histogram is healthy.** Median lib module is 100–250 LOC
  with one job each (`classify_url.py` 220, `endpoints.py` 213, `shapes.py` 237,
  `ops_config.py` 217). Two outliers only: `agent/cli.py` (1,041 — subcommand dispatch
  accreting) and `dashboard_render.py` (916 — inline templating). Those two are real
  refactor targets. Two modules out of 79 is not duct tape; it's a backlog item.
- **The discipline the user wants already exists, enforced by architecture not by
  language:** pure functions with injected I/O everywhere it matters (`now` is a
  parameter, never a clock; `absorb.measure_against_repo(scan=...)` injects the engine;
  `catalog_sources.py` parsers are text-in/facts-out against committed fixtures); hard
  data seams (`drift.json` is JSON-Schema'd; every catalog write goes through one gate);
  layering that holds under grep — `agent/lib/` imports stdlib + `yaml` and nothing else
  (verified: the only third-party import across the entire lib layer is PyYAML).
- **It is already typed where it counts:** 76 of 79 modules use
  `from __future__ import annotations`; 326 function signatures carry annotations.
  Turning on `mypy --strict` is an afternoon-to-days job, not a migration.
- **693 test functions in 84 files**, mirroring the module layout, each comment pinning
  a shipped bug. That suite *is* the code-management asset — it's what makes any future
  refactor (or port) safe.

**Assertion:** "clanky" is a reader's reaction to dynamic typing, not a property of this
codebase. This is unusually well-factored Python — better-factored than most Go services
I could name, because the discipline came from the contracts and gates, not the
compiler. A language does not give you architecture; this project already has one.

### 8.2 The rewrite is not the maintainability lever. Refactor-in-place is.

Head-to-head, honestly:

| | **Refactor Python in place** | **Rewrite in Go/Rust/Kotlin** |
|---|---|---|
| Gets static safety | `mypy --strict` in CI (near-free given 8.1), `import-linter` contract for the layer boundary, `ruff` | Yes, natively |
| Fixes the 2 real warts | Split `cli.py` into `agent/commands/*`; extract dashboard templates | Re-creates them in a new language (a 1,000-line `main.go` dispatch is just as easy to accrete) |
| Cost | **~1–2 weeks** | 4–8+ weeks (CLAUDE.md's own estimate) |
| Regression risk | ~zero — 693 tests keep jurisdiction the whole time | Re-derives every fixed bug; the tests must be *transliterated*, and their prose is the institutional memory |
| Ships detection capability meanwhile | Yes (wild-learning proceeds) | No — it *is* the schedule |

This is the classic never-rewrite-a-working-system trap, and the tell is the
justification: "better code management." **Rewrites don't pay code-management debt;
they transfer it** — you trade known, tested, documented complexity for unknown,
untested complexity plus a re-verification bill. Complexity in this system is managed by
the contracts (`drift-v1.schema.json`), the gate (`absorb.py`), the verify invariants,
and the test suite. All four are language-independent, and all four would have to be
rebuilt before a rewrite is even *safe*.

**Verdict on point 2, plainly: refactor Python, don't rewrite.** The refactor package —
mypy-strict gate, import-linter, split `cli.py`, extract templates — answers every named
symptom ("loose," "spread out," refactoring fear) at ~5% of the rewrite's cost.

### 8.3 The specific claims, pressure-tested against this project

- **"Python is dep-heavy at runtime" — false here, and measurably so.** Runtime is
  **stdlib + PyYAML, full stop** (`requirements-plugin.txt`: "PyYAML is the scanner's
  ONLY third-party Python import — dropping semgrep took the install from ~386 MB to
  ~90 MB"). `bin/drift-scan` self-bootstraps its venv; the container ships everything
  sha-pinned. The dep-pile experience being remembered is the *semgrep era* — a problem
  this project already identified and killed. What remains true: the host needs a Python
  interpreter. The container removes even that, and it shipped.
- **"Go: single binary, fast compiles at scale" — true properties, wrong ledger.**
  Single-binary distribution is a *banked trigger condition* (CLAUDE.md Rust gate #1),
  not a current requirement — no client has asked. And the binary isn't single anyway:
  the ast-grep engine rides along (subprocess or `go:embed`), so "one file" is a
  packaging nicety Python can also approximate (PyInstaller/uvx, banked). Compile speed:
  at this project's realistic ceiling (~10k prod LOC now; call it 30–50k in five years),
  *every* candidate language compiles in seconds. Optimizing language choice for
  compile-times-at-monorepo-scale is optimizing for a scale this project will not reach.
- **"Rust struggles on larger codebases" — not at any size this project will ever be.**
  Rust's compile-time and cognitive costs bite at hundreds of kLOC with heavy generics.
  A 10–50k LOC pipeline with exhaustive enums and one engine dependency is squarely in
  Rust's sweet spot — incremental builds in seconds. The *real* Rust costs for this team
  are hiring pool and iteration speed, and those are honest reasons to park it — but
  "struggles at scale" is not the reason, at this scale.

### 8.4 If a surface IS rewritten: the ranking, native-AST de-weighted

Baseline to beat: **Python-refactored** (mypy-strict, import-linter, split CLI). It wins
on cost and risk; it loses on compile-time refactoring safety and cold-start packaging.
The candidates, scored on the user's own lens (design/patterns, test tooling,
refactoring safety, readability at scale, build/distribution, ecosystem fit for *this*
domain, hireability):

1. **Go** — for the *new platform services* (`drift-wild`, `drift-fleet`). Boring on
   purpose: one formatter, `go test`/`go vet` built in, trivial CI, first-class
   single-binary deploys, excellent concurrency for forge-API fan-out. Honest downsides:
   verbosity and `if err != nil` boilerplate; **no sum types** — this domain is built on
   closed vocabularies (verdicts, idiom families, reason taxonomies) that Go renders as
   stringly-typed constants with linter discipline, exactly where Rust/Kotlin are
   stronger; the documented landmines (map order, `SetEscapeHTML`, RE2 no-lookbehind,
   float notation) all live in the *core's* renderer/verify territory — which is a
   reason to keep Go *out* of the core, not out of the platform layer.
2. **Rust** — if the *scan core* is ever ported. On the user's own criteria — strong
   types, refactoring safety, single deployable, long-term code management — Rust beats
   Go *for the core*: exhaustive `match` over the closed vocabularies is the single best
   type-system fit for this domain, and it happens to also link the engine natively
   (de-weighted, but it's a free tiebreaker, and it's why the banked plan says Rust).
   Downsides: smallest hiring pool, slowest iteration, borrow-checker tax on
   contributors. **Note the irony: the user's stated criteria argue for Rust more than
   for Go.** If "good code management sits right with Rust" — it does, at this scale.
3. **Kotlin** — pleasant language, good test story (JUnit/Kotest), sealed classes cover
   the closed-vocabulary need. But it **fails the user's own first filter**: the JVM is
   precisely a "runtime that must be present to run." GraalVM native-image escapes that
   at the cost of a gnarlier build than either Go or Rust. Domain ecosystem (tree-sitter
   /AST tooling) thin. Choose only if the team is already JVM-native — it isn't.
4. **Java** — everything Kotlin, minus expressiveness, plus boilerplate. No property
   this project needs that Kotlin/Go don't have. Not a contender.

### 8.5 Reconciliation — the code-management lens *reinforces* the split

The prior verdict (§1.3) was: Go greenfield for new surfaces, Python core untouched,
full port trigger-gated. The new lens strengthens it, because of where the *growth* is:

- The "rapidly-growing" part of the next iteration is the **platform layer** — miner,
  fleet, delivery, search. Build it in Go from day one and the growth the user worries
  about happens *in* the statically-typed, single-binary codebase they want. No rewrite
  needed to get there: it's greenfield.
- The **core is not rapidly growing** — pipeline-module stability is literally the
  banked port's trigger #3. A stable, gated, 693-test core is the best possible thing to
  leave alone. Give it the 1–2 week refactor package (mypy-strict, import-linter, split
  `cli.py`, extract dashboard templates) and the "clanky/loose" complaint is answered
  in-place.
- **If the port triggers ever fire, the core goes to Rust, not Go** — by the user's own
  criteria (8.4 #2), plus the byte-diff-eval-first path already written. Parking Rust
  today is right; *replacing* the Rust endgame with Go would be choosing the weaker
  fit for the core to match the platform layer's language. Uniformity is not a
  code-management virtue when the two halves have different shapes.

**Where I'm telling the user their instinct is wrong, explicitly:** (1) this codebase is
not duct-taped — measured, it's the opposite, and the two real warts are a two-week
refactor; (2) "dep-heavy at runtime" is false for this tool by construction (PyYAML
only, self-bootstrapping, containerized) — it's a memory of the semgrep era; (3) a
rewrite does not buy code management — the contracts, gate, and tests are the code
management, and a rewrite puts all three at risk; (4) Rust's large-codebase struggles
don't exist at this project's scale, and their own criteria (types, single binary,
refactoring safety) rank Rust *above* Go for the core. **Where their instinct is right:**
static types genuinely improve refactoring safety (adopt mypy-strict now, and build all
new code compiled); the new platform layer in Go is the correct call; and `cli.py`
deserved the callout even though nobody named it specifically.

---

## 9 · Greenfield language pick (clean slate, decisive)

Ground rules for this section, as requested: **no sunk cost** (pretend zero lines exist;
no deadline pressure) and **no native-AST factor** (the engine is a solved,
language-agnostic detail — it counts for and against nobody). One question: *for a
project of this nature, starting fresh today, Python, Go, or Rust?*

"This nature," restated as engineering requirements: deterministic byte-identical
output as a hard principle; a domain made of **closed vocabularies** (verdicts, idiom
families, attribution classes, reason taxonomies, owner streams — sum types, all of
them); heavy text/regex/URL/path parsing over catalog data; errors-as-facts (a silent
wrong answer is the worst possible outcome — worse than a crash); CLI/plugin
distribution growing a cloud/fleet layer; small team.

### 9.1 Head-to-head on the axes that matter here

| Axis (weighted for THIS project) | Python | Go | Rust |
|---|---|---|---|
| **Closed vocabularies / exhaustiveness** (highest weight — the domain IS sum types) | `Enum` + mypy-strict `Literal` gets *partial* exhaustiveness; unchecked at runtime boundaries | **No sum types.** Verdicts become string constants; a new variant compiles fine while half the renderers silently ignore it — the version-less-dedup-key *class* of bug, invited at the language level | **The type system is shaped like this domain.** `enum` + exhaustive `match`: add a fourth verdict and every render/verify site *fails to compile* until it answers |
| **Determinism footguns** | Dicts insertion-ordered since 3.7 (kind); float `repr` stable; `json` deterministic with `sort_keys` | Map iteration **deliberately randomized** (the classic footgun — bitten in this project's own probes); `SetEscapeHTML`; `%v` float notation | `HashMap` order is seeded/nondeterministic **but the fix is a visible type choice** (`BTreeMap`/`IndexMap`) reviewable in the signature; serde output deterministic by construction. (Greenfield note: the float-notation landmine mostly evaporates — it was a *cross-language byte-compat* problem with Python-emitted goldens; a clean slate only needs self-consistency) |
| **Regex/text semantics** | `re` has lookbehind; string ergonomics best-in-class | RE2: no lookbehind/backrefs | `regex` crate: same RE2-family limits (`fancy-regex` opt-in); iterator/pattern-match text processing strong, more ceremony than Python |
| **Error-handling model** ("never swallow silently") | Exceptions — easy to forget a handler; failures can propagate invisibly past the layer that should have recorded them | Errors as values, but **droppable**: `_ = err` and unchecked returns compile; linters, not the language, stand between you and a silent wrong answer | `Result` + `?` + `#[must_use]`: an unhandled failure is a compiler warning-or-error, and `thiserror` enums make failure taxonomies exhaustive too — the "cannot see ≠ clean" principle, expressed in types |
| **Test tooling** | pytest — excellent; fixtures/parametrize mature | `go test` built in; golden-file testing manual but easy | `cargo test` built in; `insta` snapshot testing is **purpose-built for byte-identical golden output**; `proptest` for determinism properties (same inputs ⇒ same bytes) |
| **Build & distribution** | Interpreter + venv or PyInstaller/container — workable, never elegant | Single static binary, trivial cross-compile — best-in-class | Single static binary (musl), cross-compile fine (cargo-zigbuild) — effectively ties Go |
| **Concurrency (fleet/platform layer)** | asyncio — serviceable, footgunny | Goroutines — best ergonomics of the three | tokio + rayon — mature (reqwest/axum for forge APIs); more ceremony than Go, fully adequate at this scale |
| **Iteration speed** | Fastest | Fast | **Slowest** — borrow checker + compile cycle; the honest cost |
| **Small-team maintainability / hireability** | Largest pool; discipline must come from convention | Large pool; language enforces uniformity but not correctness | Smallest pool; language enforces the most; code reads as its own spec |

Honest worst-downside per language, named: **Python** — no compiler-enforced
exhaustiveness and a packaging story you fight forever; the tool's guarantees live
entirely in tests and discipline. **Go** — the two things this project holds sacred
(closed vocabularies, deterministic output) are exactly where Go is weakest: no sum
types, and its most famous footguns (map randomization, escaping, float verbs) are
*determinism* footguns. **Rust** — you pay in iteration speed and hiring pool, every
week, forever.

### 9.2 The pick: **Rust.** One language, whole system.

With sunk cost and the engine both off the table, this stops being close. The decisive
question is: *what does the language enforce, versus what must the team enforce by
convention?* This project's entire identity is refusing trust-by-convention at the data
layer (the gate refuses unsourced dates; verify refuses unproven projections). Choosing
Go would reintroduce trust-by-convention at the *language* layer — stringly-typed
verdicts policed by linters, droppable errors policed by review, deterministic output
policed by remembering which footguns exist. Rust makes the compiler the absorb gate for
code: a new verdict variant, a new idiom family, a new attribution class *cannot ship*
half-handled. For a tool whose worst outcome is a silent wrong answer, that property
outweighs every week of borrow-checker tax — and the borrow-checker tax is at its
minimum here anyway, because the architecture is a pipeline of pure transforms over
owned data (no shared mutable state, no gnarly lifetimes; this is the easy 80% of Rust).
The stated premise "we have time" removes the one argument that historically beats
correctness-by-construction: deadline pressure.

And it's **one language, not a split**: the fleet/platform layer is I/O fan-out that
tokio handles trivially, and its data (profiles, proposals, provenance) benefits from
the same exhaustive types. A two-language split is justified *only* by sunk cost; on a
clean slate it's pure overhead. Go would be the pick if this were a big-team,
ship-fast, eventually-consistent network service — it is the correct boring choice for
that nature. This is not that nature. Python would be the pick only under "prototype to
find the design" — but the design is no longer unknown; the precursor found it.

For the record, the user's likely lean (Go, for the platform feel) is the wrong
greenfield call **for this domain**, and the reason is not taste: every principle in
CLAUDE.md maps to a type-system feature Rust has and Go deliberately omits. Weight the
axes any way you like; as long as "silent wrong answer is the worst outcome" stays the
top criterion, Go cannot finish first.

### 9.3 Greenfield vs. real world — the delta, stated plainly

- **Greenfield:** Rust, whole system, one language (§9.2).
- **Real world (sunk cost restored):** the delta is *only about the existing core.* The
  proven Python core + 693 tests are an asset no greenfield logic erases — keep it,
  refactor it (§8.2), port it to Rust only on the banked triggers, byte-diff-eval
  first. **But the new platform layer is greenfield in the real world too — so the
  greenfield logic applies to it directly.** This *revises* §1.3/§8.4: build
  `drift-wild` (and later `drift-fleet`) in **Rust, not Go**, converging the whole
  system on the language the banked core-port already names — a two-language *future*
  (Python now, Rust growing) instead of a three-language one (Python + Go + eventual
  Rust). Go remains the documented fallback on exactly one condition: the team decides
  hiring/onboarding for the platform layer outweighs type-enforced correctness there —
  a legitimate business call, but make it explicitly, not by defaulting to "platform
  feel."

---

## 10 · Analysis techniques — what we use, what we don't, and the capability ladder

Prompted by the question: *"grep, regex, AST, tree-sitting — are we using all, or one?
Doesn't code become AST only when it compiles? Could deeper static analysis crack cases
like this?"* — with the case being:

```php
$storeResponse = Http::withHeaders([
    'X-Shopify-Access-Token' => $accessToken,
])->withOptions(['verify' => false])->get("https://{$shop}/admin/api/2024-01/shop.json");
```

### 10.1 Inventory: the core is a two-stage hybrid — tree-sitter-AST *discovery*, regex *classification*

Not grep. Not compilation. Precisely:

**Stage 1 — FIND, on the AST.** The pinned ast-grep binary parses every source file
into a **tree-sitter AST** and matches rules by *node kind*:
- One broad rule per language matches any string-literal node whose text contains
  `https?://` (`agent/lib/vendor_rules.py:141`), over the empirically-verified container
  kinds per grammar (`AST_STRING_KINDS`, `vendor_rules.py:31-40` — PHP's
  `encapsed_string`, JS `template_string`, Go `interpreted_string_literal`, …; getting
  `encapsed_string` wrong once cost 9 real call-sites, hence "verified, do not guess").
- Plus per-vendor domain-literal rules, versioned path-literal rules
  (`vendor_rules.py:148-150`), egress-sink call patterns per language
  (`EGRESS_SINKS`, `vendor_rules.py:77-127` — `curl_exec($$$)`, `fetch($$$)`,
  `requests.$M($$$)`…), and the absorbed URL-assembly idioms compiled from YAML into
  ast-grep patterns like `$A->getHost() . $B` (`agent/lib/idioms.py:75-105`).
- Matching by node kind is what makes this **comment-safe by construction**
  (`vendor_rules.py:9`) — a URL in a comment is a different node kind. Grep can never
  give you that; this is exactly why the tool is AST-first at discovery.

**Stage 2 — CLASSIFY, with regex over the matched text.** Everything the AST stage
surfaces is then interpreted lexically in Python: extract URLs
(`classify_url.py:16`), host→vendor by registrable-domain suffix / boundary-aware
fragment (`classify_url.py:85-99`), URL→version (`:102-105`), path→API family anchored
on the version segment (`api_path_of`, `:157-191`), operation markers (`:146-154`),
host-independent path signatures (`:108-123`), all joined into endpoint records in
`agent/lib/endpoints.py:97-121`.

So: **AST answers "is this a string/call, and where"; regex answers "what is it".**
Each tool does the one job it's good at.

**Deliberately NOT used — and on record as deliberate:** no dataflow, no constant
propagation, no type inference, no call-graph, no symbolic execution. The 30 unresolved
`curl_exec` sinks in ebayapi are the standing exhibit: linking a sink to the endpoint it
calls needs dataflow, and the tool instead counts sinks as blindness only when nothing
was attributed (`shapes.verdict`) — "multi-hop/dataflow resolution is cognition
territory, not deterministic-rule territory" (open-items memory, #2). What the scanner
can't trace lands in **residue**, at file:line, as the honest remainder — that's the
design, not a gap in it.

### 10.2 Concept correction: ASTs come from *parsing*, not *compiling*

Kindly but plainly: code does **not** need to compile — or even be complete or correct —
to have an AST. tree-sitter builds the tree straight from source text, error-tolerantly
(it's an editor-tooling parser; it produces a tree for code with syntax errors in it).
That is what ast-grep already does on every scan today: no interpreter, no compiler, no
execution. What compilation *adds* on top of parsing is semantic analysis — name
resolution, type checking — and then codegen. "Predict what the code would do without
running it" is therefore not one thing but a **ladder** of increasingly expensive
semantic analyses on top of the AST we already have. Runtime values (`$shop`'s actual
contents) are a *third* axis that neither parsing nor compiling reaches — only execution
does (the banked OTel/access-log signal, TECH_DEBT.md #1–2).

### 10.3 The capability ladder, worked on the Shopify line

| Rung | What it resolves on the example | Cost | Worth it here? |
|---|---|---|---|
| **1 · AST-find + regex-classify** *(today)* | The interpolation `{$shop}` truncates URL extraction, so host→vendor is blind. **But the path IS resolved today** — the host-independent `pathSignature` `/admin/api/([0-9]{4}-[0-9]{2})/` (`agent/vendors.yaml:19`, matched at `classify_url.py:108-123`, wired at `endpoints.py:105-114`) names it Shopify + version `2024-01` → joined to the computed lifecycle (`version_lifecycle.py:35`) → **retired 2025-01-16, at file:line**. This exact case shipped this month and fired on channelwiz's two retired Shopify calls. | Already paid | **The standing lesson: a cheaper signal beat deeper analysis.** The host was never needed — the path grammar was vendor-unique. Wild-mining (Tier S) exists to find more such signatures. |
| **2 · Local constant propagation / intra-procedural dataflow** | Resolves `$shop` only if assigned a literal in the same function (`$shop = 'x.myshopify.com'; …`). In the real code it's a parameter/DB value — **still opaque**. Would genuinely help the split-literal shape (`$base = 'https://api.x.com'; … $base . $path`) — though the `url-append` idiom family (`idioms.py:44-48`) already covers the common assemble-then-append form without any dataflow. | Moderate: per-language scope/assignment semantics ×8 grammars; determinism survives | **Maybe, later, narrowly**: single-file, single-assignment constant folding only — and only if residue from a real fleet repo demonstrates the need (same trigger discipline as everything else). Not phase 1–2. |
| **3 · Inter-procedural dataflow / taint / call-graph** | The `getCategoryFeatures` class: version lives in `AccountService::API_VERSION`, threads through a config array into a `UriResolver` 3 files away. Dataflow *could* trace it… | High: symbol resolution per language, framework dynamism (Laravel facades — `Http::` in the example resolves via a service container, which static call-graphs handle badly), soundness/timeout tradeoffs | **No — §3's SDK profiling is the designed alternative.** Don't trace *into* the dependency at the client; **scan the dependency once, offline**, and join by lockfile. Same knowledge, deterministic, gate-checkable, paid once per package instead of per scan. |
| **4 · Type inference / type-aware analysis** | The TS intuition, honestly: types resolve **which** method/SDK is called (call resolution — `client.orders.get()` is SP-API's OrdersApi), which would sharpen SDK attribution. But `` `https://${shop}/…` `` has type `string`. **Types answer "what kind", never "which value"** — the host is a runtime value in every type system. So TS helps *some* (receiver/method identity), not the part that hurts (value of `shop`). And profiles (§3) already deliver the receiver-identity knowledge without embedding `tsc` in the scan. | High and per-language (tsc API for TS; PHP would need PHPStan-class machinery) | **Not in the scan path.** Possibly a *miner-side* tool later (typed call-resolution while building profiles from TS wrappers) — server-side, offline, gated. |
| **5 · Symbolic execution / abstract interpretation** | Could in principle enumerate the *set* of hosts `$shop` may hold. Path explosion, solver dependencies, timeouts; results are "possibly one of…" — which the report can't render as fact without weakening the evidence bar. | Very high | **Out of scope, full stop.** The tool's contract is facts-at-file:line + honest residue, not probable facts. |

### 10.4 What this means for the next iteration (and §9)

- **Stay at rung 1, and get better at it** — more Tier-S-mined path signatures,
  version grammars and operation vocabularies (§3.1) raise recall with zero new
  analysis machinery. The Shopify case is the proof: signature > dataflow.
- **Rung 3's problem is solved sideways, not climbed:** SDK profiling (§3) is
  explicitly the cheap substitute for inter-procedural dataflow — the endpoint
  knowledge physically lives in the dependency, so scan the dependency, don't build a
  taint engine. This was already the doc's central mechanism; the ladder shows *why*
  it's the right rung.
- **Rung 2 is the only climb worth banking:** bounded intra-file constant folding,
  trigger-gated on a real repo's residue proving the need. If built, it must stay
  deterministic (pure AST-local, no heuristics) and its attributions get their own
  evidence label, same as `inferred` and `sdk-profile`.
- **The §9 language pick doesn't change the ladder** — the engine is factored out
  either way. It changes the *ceiling*: if rung 2 is ever built, Rust is where the
  ecosystem cooperates (tree-sitter native, ast-grep's own crates, typed exhaustive
  node-kind handling); building per-language dataflow in Python would be the moment
  the "port trigger" argument writes itself.
- **Assertively:** cheap signals + honest residue beat a dataflow engine for this
  product. A dataflow engine would spend a quarter to convert *some* residue into
  findings while adding the first analysis stage whose failure modes are silent; the
  residue conscience only works because every stage below it is simple enough to trust.

---

## 11 · Mago: a native-PHP analysis engine — leverage it, but not where you'd think

The question: [Mago](https://github.com/carthage-software/mago) ("the oxidized PHP
toolchain") is Rust — can we leverage it to analyze our PHP projects? Two readings; the
load-bearing one is *Mago as the PHP engine inside our scanner*, in the Rust direction
§9 recommends. Researched live today.

### 11.1 What Mago actually is (verified 2026-07-30)

Not just a CLI — a **workspace of reusable Rust crates** with the CLI on top,
dual-licensed **MIT/Apache-2.0**, current release **v1.45.0**, actively shipped:

- [`mago-syntax`](https://crates.io/crates/mago-syntax) — hand-written PHP **lexer,
  parser, AST** ("correct, fast, memory-efficient"), no PHP runtime needed.
- [`mago-project`](https://crates.io/crates/mago-project) — parses a whole project,
  **resolves names**, collects semantic issues, merges module reflections into a
  unified project reflection. This is real semantic analysis, not just parsing.
- [`mago-codex`](https://crates.io/crates/mago-codex) — **PHP type-system
  representation** + comparison logic for static analysis;
  [`mago-type-syntax`](https://crates.io/crates/mago-type-syntax) parses docblock types.
- [`mago-analyzer`](https://crates.io/crates/mago-analyzer) — the static analyzer
  ("deep analysis … catch potential type errors"), plus linter/formatter crates and
  even [`mago-wasm`](https://crates.io/crates/mago-wasm).

Maturity, honestly: the toolchain is fast and real (sub-second on a 500-file Laravel
project in the [PHP toolchain benchmarks](https://carthage-software.github.io/php-toolchain-benchmarks/)),
but the *analyzer* is **not yet at PHPStan/Psalm parity** on type-level checks
(community assessments through 2026, incl. the project's own
[parity discussion #379](https://github.com/carthage-software/mago/discussions/379)),
and — like ast-grep's crates — **no published API-stability contract for library
consumers**: the crates exist to build the CLI and version in lockstep with it. Any
dependency would be pinned `=1.45.x` and treated bumps-as-re-verification, exactly the
posture CLAUDE.md already takes toward `ast-grep-*`.

### 11.2 Where Mago lands on the §10 ladder — for PHP only

- `mago-syntax` is **rung 1 with better ergonomics**: a PHP-native AST instead of a
  generic tree-sitter grammar. Notably, this **retires the one engine caveat CLAUDE.md
  recorded** (the napi route's "0.0.x PHP grammar" worry): in a Rust core, PHP — our
  dominant fleet language — would get a first-class, hand-written parser.
- `mago-project`'s name resolution + `mago-codex` reach into **rungs 2–3 for PHP**:
  resolving a class-constant reference (`AccountService::API_VERSION`) to its literal
  value is name resolution + constant evaluation — *static, deterministic, and exactly
  the shape of the eval-proven miss* ("version only in SDK code, 3 files of
  indirection"). This is the first tool surveyed that climbs past rung 1 without
  building our own dataflow.
- Against the two hard cases, though:
  - **(a) The interpolated-host Shopify line: moot.** `$shop` is a runtime value; no
    static analyzer — Mago, PHPStan, or a theorem prover — produces it. The shipped
    `pathSignature` already resolves that case (§10.3 rung 1). Mago adds nothing here.
  - **(b) The `getCategoryFeatures`-class case: Mago *could* help — but on the miner
    side, not the scan side.** That indirection lives in *wrapper* code, and §3's SDK
    profiling already scans wrappers offline. Where our rung-1 extraction can't follow
    a wrapper's constants into its URL assembly, a Mago-powered extractor could —
    improving **profile quality**, one package at a time, in the LEARN loop, behind
    the regeneration gate. SDK profiling remains the cheaper win; Mago makes the
    profiler smarter, it doesn't replace it.

### 11.3 The two-engine question — the crux, answered

Mago is **PHP-only**. Putting it in the scan path means two engines: a deep PHP engine
plus ast-grep for the other seven languages — two parsers, two match models, two rule
dialects (absorbed idioms compile to ast-grep patterns, `idioms.py:75-105`; a Mago path
would need its own matcher), and a consistency obligation between their outputs. The
fleet being PHP-heavy makes that tempting, and §10.4's own principle kills it anyway:
**the residue conscience works because every stage below it is simple enough to
trust.** A second engine in the deterministic scan path doubles the surface that has to
be simple, for gains (rung-2 constant resolution at client call-sites) that the residue
data has not yet shown we need — client-side misses are shape-C (SDK-mediated), which
profiles solve, and interpolated-host, which no static engine solves.

Determinism per se is not the blocker — Mago is a pure static analyzer, Rust, no
runtime, byte-stable given pinned versions. The footguns are lifecycle ones: unstable
crate API, and inference results that can legitimately change across versions — so
anything Mago-derived that reaches a catalog must carry the Mago version in its
provenance, and version bumps become re-verification events.

### 11.4 Verdict

**Leverage Mago — in the LEARN loop, not the scan path.**

1. **Now/Phase-3 (optional, trigger-gated):** a Mago-based *profile extractor* in
   `drift-wild` for PHP wrappers whose endpoint knowledge hides behind class
   constants/config indirection our rung-1 scan can't extract. Trigger: a real wrapper
   in the corpus whose profile is demonstrably incomplete (the regeneration check makes
   incompleteness visible). Output is staged YAML through the same gate; provenance
   records `mago@<version>`.
2. **If the Rust core is ever built (§9 triggers):** adopt `mago-syntax` as the PHP
   parser and keep tree-sitter/ast-grep semantics for the other seven — *inside one
   engine binary*, where "two parsers" is an implementation detail behind one match
   model, not two engines in the pipeline. This is also where the banked rung-2
   constant-folding would be built on `mago-project`'s name resolution rather than
   hand-rolled.
3. **The tangential reading — Mago as a linter ON client PHP repos** — is not our
   product, but it composes with banked idea #3 (the detectability linter,
   TECH_DEBT.md): a suggested-refactor MR could recommend the client adopt Mago/PHPStan
   themselves. Note it; don't build it.

**Effect on §9:** strengthens the Rust pick, materially. Mago is a second
domain-relevant, Rust-only ecosystem asset (after the ast-grep/tree-sitter crates) with
**no Go, Kotlin, or Python equivalent of comparable depth** — for the language our
fleet is actually written in. The greenfield argument gains a concrete exhibit: in
Rust, our dominant-language analysis ceiling is `mago-project`'s semantic layer; in Go
it's a generic grammar plus whatever we hand-roll.

**Effect on §10:** none on the recommendation, and that's the point — "stay at rung 1
in the scan path, enrich cheaply, solve rung 3 sideways via profiles" survives contact
with a genuinely good deep-PHP engine. Mago changes *how far the miner can climb*, not
where the scanner should stand.

---

## 12 · Reassessment: per-language engines under the real weighting (~90% PHP)

New fact placed into the equation by the user: **~90% of our integrations are PHP;
maybe 10% JS/Python, and that later-stage.** The challenge: §11 framed Mago as "a
second, co-equal engine that doubles the trust surface" — but under 90/10, a deep PHP
engine is the *primary* engine where almost all the value is, and the generic engine is
a thin fallback. Reassessed honestly below. **The verdict changes in architecture and
holds in sequencing.**

### 12.1 Concession one: "one generic engine" was never actually one engine

Looking at our own code kills the uniformity mystique: the ast-grep ruleset is
**already per-language dispatch**. Every rule is single-language
(`{base}@{language}`, `vendor_rules.py:135-138`), node kinds are per-grammar
(`AST_STRING_KINDS`, `:31-40`), egress sinks are hand-written per language
(`EGRESS_SINKS`, `:77-127`), and `rule_kinds_by_language()` (`:192-206`) exists
precisely because coverage differs by language. What is uniform is not the engine — it
is the **match-record IR** (`{path, line, text, kind}` consumed by
`endpoints.scan_endpoints`) and the shared classify→attribute→residue model downstream.
So the user's proposed architecture — dispatch by file language, deep lane for PHP,
generic lane for the rest, honest UNKNOWN for unrecognized — is not a departure from
the design. It *is* the design, with one lane upgraded.

### 12.2 Concession two: the seam dissolves most of §11.3's cost objection

§11.3 priced "two engines" as two parsers, two match models, two rule dialects, plus a
consistency obligation. Under the seam the user points at, that was overweighted:

- If a Mago lane emits the **same IR kinds** (`url`, `path-literal`, `sink`,
  `path-assembly`, `operation-marker` — plus one new kind, `resolved-literal`, for
  const-evaluated values, carrying its own evidence label), then classification,
  attribution, dedup, residue, verdicts, rendering, and verify are all **shared and
  unchanged**. The trust surface is the IR contract, not 2× the pipeline.
- Cross-engine inconsistency risk inverts into a **strength**: run *both* lanes over
  PHP in CI and diff their rung-1 outputs (literal-finding must agree). Differential
  testing between two independent parsers is a stronger silent-blindness guard than
  either alone — the `encapsed_string` bug (9 lost call-sites) would have been caught
  by exactly this.
- What §11.3 got right and survives: **rule authoring stays double** for anything
  expressed as engine patterns (absorbed idioms compile to ast-grep patterns,
  `idioms.py:75-105`; the Mago lane needs equivalent matchers, and the absorb gate's
  measure-against-repo must run per-lane), and a second pinned engine version enters
  the determinism/provenance story. Real, bounded, and worth it *for the 90% language*
  — not for eight.

### 12.3 Concession three: asymmetric depth is what the honesty model was built for

"Cannot see ≠ clean" already expresses per-language asymmetry today: PHP had
sinks/assembly rules while seven languages returned `UNKNOWN/no-egress-signal`
(`shapes.py`, `signalCoverage`), and the verdict machinery renders exactly that. PHP at
rung 2 while JS/Python sit at rung 1 is not a principle violation — it is the same
asymmetry, pointed the other way, with each language's residue stating what its lane
could not resolve. §11 should not have implied depth-uniformity was itself a principle;
the principle is that depth differences must be *visible*, and the machinery for that
already exists.

### 12.4 What does NOT change — the couplings, stated plainly

1. **"Mago in the PHP scan path" ≈ "build the §9 Rust core."** Mago's value is
   crate-level (AST + `mago-project` name resolution feeding our matcher directly).
   Bolting it onto today's Python means shelling out to a CLI that has no
   custom-pattern scan mode — you'd get Mago's lint findings, not our rules over
   Mago's AST. There is no cheap Python+Mago integration; this rides the Rust-core
   decision, full stop.
2. **The empirical question is untouched by the weighting.** 90% PHP raises the
   *stakes* of client-side rung-2 wins, not their *frequency*. The evidence so far
   points the other way: amazonspapi's 272 call-sites fell to rung-1 + concat idioms;
   channelwiz's misses were interpolated-host (runtime — no engine helps) and
   wrapper-dependency edges (profiles); the one proven const-indirection case
   (`AccountService::API_VERSION`) lives in *SDK* code, which the miner scans anyway.
   **What would settle it:** residue/eval evidence from the fleet — a PHP repo where
   rung-1 + idioms + SDK profiles still leave versioned egress unattributed *and*
   inspection shows client-side constant indirection. The Mago-powered profile
   extractor (§11.4 item 1) generates exactly this evidence as a side effect: it
   quantifies how much const-indirection exists per package and where.
3. **Mago maturity/API-stability caveats (§11.1) stand** — pin exact, bumps are
   re-verification events, `mago@<version>` in provenance.

### 12.5 Revised verdict

- **Architecture (changed):** the target design for the Rust core (§9) is now
  explicitly **engine lanes behind one IR** — Mago lane as the *primary* PHP front-end
  (rung 2: name resolution + const-eval, emitting `resolved-literal` with provenance),
  tree-sitter lane for the other languages, unknown-language → honest UNKNOWN, one
  shared classify→attribute→residue pipeline, differential rung-1 testing between
  lanes on PHP. §11.3's "two co-equal engines" framing is withdrawn; under 90/10, PHP
  depth is where the product's recall lives, and the seam keeps it inside "simple
  enough to trust" because the trusted thing is the IR contract plus shared
  downstream, not two pipelines.
- **Sequencing (held):** entry into the scan path is still gated, because the gate was
  never about weighting — it's about evidence and coupling. Triggers, explicitly:
  (a) the §9 Rust core is being built (coupling #1 — no Python+Mago bolt-on), AND
  (b) fleet residue demonstrates client-side const-indirection misses that rung-1 +
  idioms + profiles don't cover (coupling #2). Until both fire: Mago enters the LEARN
  loop now (miner-side profile extraction), which both delivers value immediately and
  produces the evidence to fire or retire trigger (b).
- **Net effect on §9:** strengthened again. "Engine lanes with Mago primary for the
  dominant language" is only buildable in Rust — which now makes the Rust core the
  place where *both* the greenfield correctness argument (§9.2) and the deep-PHP
  recall argument converge.

---

## Appendix A — recon index (all verified this session)

eBay: timotheus/ebaysdk-python (854★, dormant, 2 of 4 wrapped APIs dead) ·
hendt/ebay-api (206★, active, subdomain idiom) · davidtsadler/ebay-sdk-php (archived
2021) · matecsaj/ebay_rest (active) · ericblade/ebay-find-api (archived w/ "API no
longer available" banner) · eBay OpenAPI contracts (portal) · eBay deprecation RSS
(already wired).
Amazon: amzn/selling-partner-api-models (official specs, diffable) ·
amzn/selling-partner-api-sdk (official generated SDKs) · jlevers/selling-partner-api
(436★, Endpoint enum) · saleweaver/python-amazon-sp-api (667★, f-string host concat) ·
amz-tools/amazon-sp-api (262★, operation dispatch) · amazon-php/sp-api-sdk (spec-
generated) · highsidelabs/laravel-spapi (second-order wrapper).
Shopify: Shopify/shopify-app-js (ApiVersion enum, path regex) · Shopify/shopify-api-php
(`"/admin/api/$apiVersion$path"`) · Shopify/shopify_python_api · phpclassic/php-shopify
(3.8M installs, pinned `$defaultApiVersion`) · gnikyt/Basic-Shopify-API.
AU/NZ: TradeMe/trade-me-api-wrapper (officially deprecated) · Kogan (no wrappers;
vendor OpenAPI + llms.txt) · Catch (marketplace shut down 2025-04-30) · MyDeal (closed
2025-09-30) · Marketplacer seller-integration-nodejs (0★, per-tenant GraphQL).
Walmart: highsidelabs/walmart-api-php (OpenAPI-generated, hardcoded host).
Engine: no ast-grep Go binding (github.com/ast-grep) · official
tree-sitter/go-tree-sitter + tree-sitter-php Go bindings exist (cgo).
