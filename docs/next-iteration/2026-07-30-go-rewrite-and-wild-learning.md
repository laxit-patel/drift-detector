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
