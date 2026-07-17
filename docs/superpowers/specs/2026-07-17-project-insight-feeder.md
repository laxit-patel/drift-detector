# Project Insight — Branch 1: The Deterministic Feeder

**Date:** 2026-07-17
**Status:** approved for planning
**Branch:** `insight` (off master 7dde93c, Spec A + B merged)
**Strategy:** Fable 5 architecture memo (fourth review) — the tiered "deterministic feeds, AI scouts" design. This spec is **Tier 1 only** (the feeder). The AI scout (Tier 2) and the versioned facts store (Tier 3) are later branches.

## Problem

The scanner matches string literals that carry a **host** (a full `https://…` URL, or a vendor host-token like `sellingpartnerapi`). A real fleet repo (`chetan/amazonspapi`, a hand-rolled PHP Amazon SP-API client) assembles its entire API surface — 262 calls across 47 `src/Api/*.php` classes — as:

```php
$resource_path = '/orders/2026-01-01/orders';       // path literal, carries the API version
$url = $this->config->getHost() . $resource_path;    // host injected from config at runtime
```

The scanner detected **3 of 262**. The path literal has no host, so no rule matched. Worse, the "endpoints may undercount" honesty signal we shipped in Spec B fires only when a repo declares a **third-party SDK package** in composer.json — this is a hand-rolled client with 0 SDK packages, so it slipped through **both** detection and the honesty net and looked clean. A PM caught the miss in a demo; the tool did not.

The lesson (Fable): this is not a determinism failure. It is (a) a **rule-library gap** — one un-taught assembly idiom — and (b) an **honesty-net bug** — the undercount signal watched the wrong thing. Trust is preserved by *disclosed uncertainty*, not maximal recall. A repo with 262 endpoint-shaped literals should never look clean.

## The two-layer design (why generality differs by layer)

Detection has two layers with **opposite** generality goals:

1. **Attribution** (code → a named endpoint) **must be precise**, so it is **idiom-by-idiom**. Each URL-assembly shape (`getHost() . $path`, `sprintf`, Guzzle `base_uri`, `urljoin`, template strings, route tables) is a separate rule. A loose rule invents false endpoints — the one thing an audit can never do. Attribution grows one idiom at a time; proposing the next idiom is the (later) AI scout's job.
2. **The conscience** (detecting that we are **blind** somewhere) **should be as general as possible**. It does not need to understand the assembly — it only needs evidence that an outbound call exists that we could not attribute. That evidence is vendor- and largely idiom-agnostic.

This spec builds a **general conscience** + the **first precise idiom** (concat), proving the residue→attribution loop end to end.

## Goals

- A **residue detector** (the conscience): per-repo, deterministic, vendor/idiom-agnostic, surfacing what the scan could not attribute, as a first-class coverage grade. Supersedes the Spec B SDK-package undercount signal.
- The **concat idiom rule**: deterministically attribute the `getHost() . $path` shape to the repo's classified vendor, closing the `amazonspapi` wall (262/262) — and proven non-vendor-specific by catching a second vendor in the fixture.
- A committed **synthetic eval fixture** regression-locking both.
- Deterministic, hermetic, zero-LLM-token throughout. The dashboard stays a self-contained `file://` document.

## Non-goals (explicitly out of scope for this branch)

- **The AI scout (Tier 2)** — no LLM anywhere in this branch.
- **The versioned facts store / `repo_profiles.yaml` (Tier 3)** — later branch.
- **Attribution idioms beyond concat** — `sprintf`, Guzzle `base_uri`, `urljoin`, template strings, route tables. The scout proposes these later; adding them now would overfit before the loop exists.
- **JS/TS/Python egress sinks** — the conscience's sink signal is **PHP-first** (the fleet's language and the wall we hit). Other languages are a follow-up.
- **Multi-hop / cross-file resolution** — remains cognition territory (Fable's standing line). The concat rule is single-hop, class/file-local only.
- **A Go rewrite** — adopt interface discipline later; no rewrite of working Python here.
- **Sourcing new vendor sunset dates** — unchanged; the SP-API `v0` retirement stays a curator decision, not part of this branch.

## Component 1 — The conscience (residue detector)

**Two deterministic signals, both PHP-first.**

**1a. Unattributed path-literals.** An opengrep rule emits `kind: path-literal` matches for string literals shaped like an API resource path: **leading `/`** and containing a **version segment** — `/vN/` (e.g. `/v0/`, `/v1/`) or a date `/YYYY-MM-DD/` (e.g. `/2026-01-01/`). Rationale for "versioned only" (a deliberate precision-first call): version-bearing paths are exactly the deprecation-relevant ones and have a very low false-positive rate; unversioned resource paths can be added later if residue analysis shows misses. A path-literal that Component 2 (or any future idiom) attributes to an endpoint is **not** residue; one that stays unattributed **is**.

**1b. Unresolved egress sinks.** An opengrep rule emits `kind: sink` matches for PHP network-egress call-sites: `curl_exec`, `curl_setopt(..., CURLOPT_URL, ...)`, Guzzle (`->request(`, `->get(`/`->post(` on a client, `new \GuzzleHttp\Client`), and `file_get_contents(`/`fopen(` whose argument is an `http` URL or a variable. A sink whose URL resolves to an attributed endpoint is **not** residue; a sink with no resolvable URL **is** (the fully-dynamic case with no path literal).

**Rollup + grade.** In `agent/inventory_scan.py` `_rollup_coverage`, add `coverage.residue`:
```
coverage["residue"] = {
    "pathLiterals":   [{repo, sample, loc}, …],   # unattributed path-shaped literals
    "sinks":          [{repo, kind, loc}, …],      # unresolved egress sinks
    "byRepo":         [{repo, attributed, unattributedPaths, unresolvedSinks, grade}, …],
}
```
Per-repo **coverage grade**, deterministic thresholds (final numbers pinned in the plan; the shape):
- **HIGH** — no residue (every path-literal attributed, every sink resolved).
- **PARTIAL** — some residue but a majority of endpoint-evidence attributed.
- **LOW** — most endpoint-evidence unattributed (e.g. `amazonspapi`: 262 literals, 0 attributed).

**Relationship to Spec B.** The residue grade becomes the **primary** honesty signal. `coverage.sdkMediated` (Spec B) is retained as data and folded in as *one contributor* to residue (an SDK-mediated repo is another unresolved-egress case), but it is no longer the headline "undercount" claim. `coverage.privateSources` (Spec B) is unchanged — a distinct, valid signal.

**Surfacing.** The dashboard Coverage section leads with the per-repo grade and residue samples; INVENTORY.md per-repo section shows the grade + a `⚠ N endpoint-shaped literals / M egress sinks unattributed` line (replacing the SDK-only ⚠ line).

## Component 2 — The concat idiom rule (first precise attribution)

**Detection.** An opengrep rule emits `kind: path` matches for the assembly idiom `$U = $C->getHost() . $P`, resolving `$P` to its string literal via semgrep constant-propagation. **Fallback** (if propagation proves unreliable across the corpus): a class/file-local two-pass — collect the `$resource_path = '/…'` literals and the `getHost() . $var` assemblies within the same file/class and join them. The rule is **single-hop, file/class-local** — no cross-file or multi-hop resolution.

**Attribution (the no-false-endpoints guard).** `agent/lib/endpoints.py` `build_endpoints` gains a `path` branch. A `path` match carries a resolved path but **no host**. Attribute the vendor from the repo's **already-classified endpoints**, under a strict unambiguity rule:
- If the repo has **exactly one distinct classified vendor** (one `techKey` across all classified endpoints — SP-API in `amazonspapi`), attribute the path to that vendor: emit an endpoint with that `techKey`/`vendor`, `version` extracted from the path (reuse `classify_url.version_of`'s path-segment regex), `domain` = that vendor's host, `files` = the call-site `file:line`.
- If the repo has **two or more** distinct classified vendors, or **none**, the path stays **residue** (Component 1) — never a guessed attribution. (Multi-vendor path attribution is deferred; guessing which vendor a host-less path belongs to would manufacture false endpoints. It can be revisited later, e.g. via a per-file dominant-vendor heuristic, only if real fleet data shows single-vendor attribution leaves too much residue.)

**Downstream.** Attributed path-endpoints are ordinary endpoints in `inventory.json` (techKey, version, call-sites) and flow into the existing sunset join — so a future SP-API sunset entry would light all 262 at their precise `file:line`.

**Acceptance:** 262/262 on `amazonspapi` (verified via the local private clone during the plan's controller step); and the fixture's non-Amazon concat client attributed correctly (proves idiom, not vendor).

## Component 3 — Eval fixture (regression-lock)

A committed **synthetic, public-safe** PHP fixture (the real `chetan/amazonspapi` is a private GitLab repo and cannot enter the public corpus). Because the attribution guard is strict per-repo (exactly one classified vendor), the fixture is **two separate repos** so the idiom can be proven across vendors without tripping the multi-vendor guard:

- **Repo A (vendor #1, e.g. SP-API-shaped host):**
  1. A `getHost() . $resource_path` client on a **versioned** path (e.g. `/orders/2026-01-01/orders`), the repo's host classified as vendor #1 → **attributed** endpoint, version extracted.
  2. A raw `curl_exec` with a dynamic (variable) URL → **sink residue** (no resolvable URL).
  3. A bare versioned path literal with no assembly the rule understands → **path-literal residue**.
  → Repo A grade: **PARTIAL/LOW** (has attributed endpoints *and* residue).
- **Repo B (vendor #2, a different classified host):** the **same** `getHost() . $path` idiom → attributed to **vendor #2** (proves the rule is idiom-shaped, not amazon-tight). → grade **HIGH** (all attributed).

Assertions: Repo A's concat call and Repo B's concat call each appear as attributed endpoints with the correct (distinct) vendor + version; Repo A's sink and bare-path cases appear in `coverage.residue` and hold its grade below HIGH; Repo B grades HIGH; determinism (same input → byte-identical inventory + dashboard).

## Data flow

```
opengrep rules (NEW): path-literal | sink | path      (+ existing url | endpoint)
   → repo_scan records matches
   → endpoints.build_endpoints:
        kind=path      → attribute via repo's single dominant classified host (else residue)
        kind=path-literal, kind=sink → residue candidates
   → inventory_scan._rollup_coverage:
        coverage.residue {pathLiterals, sinks, byRepo[grade]}   (NEW, supersedes sdkMediated headline)
   → dashboard Coverage section + INVENTORY.md   (grade-led)
   → attributed path-endpoints flow into the existing sunset join
```

No `audit.py` change. `coverage.residue` and the `path` endpoint kind are additive; existing artifacts (SARIF/BOM/AUDIT.md) read other fields and are unaffected.

## Testing

- **`tests/test_classify_url.py`** (extend): the path-version regex extracts `2026-01-01` / `v0` from a bare path.
- **`tests/test_endpoints.py`** (extend): a `path` match with a single dominant classified host → attributed endpoint (vendor + version + loc); with multiple vendors or none → NOT attributed (becomes residue); dedup with an existing URL/host endpoint at the same loc.
- **`tests/test_inventory_scan.py`** (extend): `coverage.residue` shape; the grade thresholds (HIGH/PARTIAL/LOW) over hand-built repos; a repo with all paths attributed → HIGH; `amazonspapi`-like fixture → LOW.
- **`tests/test_inventory_render.py`** / **`tests/test_dashboard_render.py`** (extend): the grade + residue samples render (grade-led Coverage section); XSS on residue samples (scan-derived strings via esc/escA); the old SDK-only ⚠ line is replaced by the grade line.
- **Eval:** the synthetic fixture (Component 3) scored deterministically; `bin/drift-eval run ebay` still **5/5** (additive; must not perturb recall).
- No network in any unit test.

## Success criteria

Re-scanning `amazonspapi` yields all 262 SP-API endpoints at their `file:line` with versions, attributed via the concat rule; the fixture's second-vendor client is attributed to *that* vendor; a repo with unresolvable calls shows a residue grade below HIGH with samples; the dashboard Coverage section leads with the grade; `drift-eval run ebay` stays 5/5; same input → byte-identical inventory + dashboard. The deterministic layer never claims completeness — residue is a first-class output that will later trigger the AI scout.
