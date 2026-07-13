# Layer 1 Completion (Change-Monitor Plan 08) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete announced-change (Layer 1) coverage for the seller-portal marketplaces — wire the already-built `html-changelog` adapter into ingest and point the production config at the best real sources (SP-API official changelog RSS + Walmart release-notes HTML).

**Architecture:** The `html-changelog` adapter (`agent/lib/feeds/html_changelog.py`) already fetches a page, hashes it, skips re-processing when unchanged, and structures changed pages via an injected LLM seam — but it returns `(entries, page_hash)` and needs the last page hash passed in, a contract the ingest loop doesn't yet support. This plan teaches `agent/kb_ingest.py` to thread that page hash through the KB watermark for hash-based adapters (an explicit `HASH_ADAPTERS` set), un-gates `html-changelog` in config, and updates `deploy/config.yaml` to the validated marketplace sources. `rss`/`endoflife` adapters are untouched.

**Tech Stack:** Python 3.12 (project `.venv` — `source .venv/bin/activate`; system python is 3.10, do NOT use it). Tests: `python -m pytest -q`. No network, no LLM, no subprocess in tests — all external seams are injected fakes.

## Global Constraints

- **TDD**: write the failing test first, watch it fail, then implement. Frequent commits.
- **Injected seams / no I/O in tests**: `html-changelog` takes injected `fetch_text` and `structure_fn`; `ingest_feed` takes an injected `get` (adapter registry). Tests never hit the network, the `claude` CLI, or wall-clock.
- **Deterministic-shell + one-LLM-stage**: the LLM is confined to `html-changelog`'s `structure_fn` seam. The ingest loop stays deterministic.
- **techKey MUST match `agent/patterns.yaml`** so a repo's marketplace usage joins to the change: SP-API = `api:amazon-sp-api`, Walmart = `api:walmart-marketplace`, Shopify = `api:shopify`.
- **Fail-soft**: a feed that errors (page down, structurer unavailable) becomes a per-feed coverage gap (`IngestResult.status="error"`), never crashes the run. This is existing `ingest_feed` behavior and must be preserved.
- **eBay is deferred** (bot-blocked — 403 even with a browser UA). Do NOT add an eBay feed in this plan.

---

## File Structure

- **Modify** `agent/kb_ingest.py` — teach the ingest loop to thread the page hash for hash-based adapters; import `html_changelog` so it self-registers. (Task 1)
- **Modify** `agent/config.py` — remove `html-changelog` from `NOT_YET_WIRED` so it is accepted as a feed. (Task 1)
- **Modify** `tests/test_kb_ingest.py` — add page-hash-threading + config-acceptance + registration tests. (Task 1)
- **Modify** `deploy/config.yaml` — SP-API official changelog RSS (replaces the interim GitHub-commits feed) + add Walmart `html-changelog` feed; document the live-`structure_fn` follow-up. (Task 2)
- **Create** `tests/test_deploy_config.py` — assert the production config loads and carries the expected marketplace feeds. (Task 2)

Reference (read-only, do not modify): `agent/lib/feeds/html_changelog.py` (the adapter — signature `fetch(spec, *, fetch_text=_http_get, structure_fn=_llm_structure, prior_hash="") -> (list[ChangeEntry], str)`), `agent/lib/kb_store.py` (`read_watermark`/`write_watermark`/`append_entries`), `agent/lib/models.py` (`ChangeEntry`, `FeedSpec`, `IngestResult`), `agent/patterns.yaml` (marketplace techKeys).

---

## Task 1: Thread page-hash through ingest + un-gate `html-changelog`

**Files:**
- Modify: `agent/kb_ingest.py`
- Modify: `agent/config.py:15-24` (the `NOT_YET_WIRED` dict)
- Test: `tests/test_kb_ingest.py`

**Interfaces:**
- Consumes:
  - `kb_store.read_watermark(root, techKey) -> dict` and `kb_store.write_watermark(root, techKey, data: dict) -> None` (watermark is a plain dict persisted per techKey).
  - `kb_store.append_entries(root, techKey, entries) -> list[ChangeEntry]` (idempotent by `ChangeEntry.id`; returns only newly-written entries).
  - Hash-based adapter contract: `adapter(spec, prior_hash="") -> (list[ChangeEntry], str)`. It returns `([], prior_hash)` when the page is unchanged (its hash equals `prior_hash`), else `(entries, new_hash)`.
  - Plain adapter contract (`rss`/`endoflife`): `adapter(spec) -> list[ChangeEntry]`.
- Produces:
  - `HASH_ADAPTERS: set[str]` = `{"html-changelog"}` in `agent/kb_ingest.py` — the set of adapters that use the page-hash calling convention. Later marketplaces reuse this.
  - Unchanged public signatures `ingest_feed(spec, kb_root, now, *, get=get_adapter) -> IngestResult` and `ingest_all(feeds, kb_root, now, *, get=get_adapter) -> list[IngestResult]`.
  - The KB watermark for a hash-based feed gains a `"pageHash"` key.

- [ ] **Step 1: Write the failing tests**

Add these to `tests/test_kb_ingest.py` (it already defines `_fake_get`, and imports `ChangeEntry`, `FeedSpec`, `kb_store`, `kb_ingest`):

```python
def _hash_spec():
    return FeedSpec(techKey="api:walmart-marketplace", label="Walmart Marketplace",
                    category="integration", adapter="html-changelog",
                    url="http://x/whatsnew", tier=1)


def test_hash_adapter_threads_page_hash_and_skips_unchanged(tmp_path):
    # Fake html-changelog: records the prior_hash it was handed; returns ([], "H1")
    # when told the page is unchanged (prior_hash == "H1"), else one entry + "H1".
    seen = {}

    def fake(spec, prior_hash=""):
        seen["prior"] = prior_hash
        if prior_hash == "H1":
            return [], "H1"                              # unchanged page -> nothing new
        return ([ChangeEntry(techKey=spec.techKey, date="2026-07-03", changeType="breaking",
                             title="Item spec v5", summary="", sourceUrl=spec.url, sourceTier=1)],
                "H1")

    get = _fake_get({"html-changelog": fake})

    # First run: no prior hash -> structures, appends, stores pageHash "H1".
    r1 = kb_ingest.ingest_feed(_hash_spec(), str(tmp_path), now="2026-07-05", get=get)
    assert r1.status == "ok" and len(r1.new_entries) == 1
    assert seen["prior"] == ""                           # nothing threaded in on the first run
    wm = kb_store.read_watermark(str(tmp_path), "api:walmart-marketplace")
    assert wm["pageHash"] == "H1" and wm["lastRun"] == "2026-07-05"

    # Second run: stored "H1" threaded back in -> page unchanged -> no new entries.
    r2 = kb_ingest.ingest_feed(_hash_spec(), str(tmp_path), now="2026-07-12", get=get)
    assert seen["prior"] == "H1"                          # stored hash was passed to the adapter
    assert r2.new_entries == []
    assert kb_store.read_watermark(str(tmp_path), "api:walmart-marketplace")["pageHash"] == "H1"


def test_plain_adapter_unaffected_by_hash_wiring(tmp_path):
    # rss/endoflife-style adapter: called as adapter(spec), returns a plain list, no pageHash.
    get = _fake_get({"rss": lambda spec, **kw: [_entry("A")]})
    spec = FeedSpec(techKey="api:shopify", label="Shopify", category="integration",
                    adapter="rss", url="http://x", tier=1)
    res = kb_ingest.ingest_feed(spec, str(tmp_path), now="2026-07-05", get=get)
    assert res.status == "ok" and len(res.new_entries) == 1
    assert "pageHash" not in kb_store.read_watermark(str(tmp_path), "api:shopify")


def test_config_accepts_html_changelog_feed(tmp_path):
    from agent.config import load_config
    p = tmp_path / "c.yaml"
    p.write_text(
        "kb: { root: kb/ }\n"
        "feeds:\n"
        "  - { techKey: api:walmart-marketplace, label: Walmart, category: integration,"
        " adapter: html-changelog, url: http://x, tier: 1 }\n"
    )
    cfg = load_config(str(p))
    assert cfg.feeds[0].adapter == "html-changelog"


def test_html_changelog_registered_after_importing_ingest():
    from agent.lib.feeds import get_adapter, html_changelog
    assert get_adapter("html-changelog") is html_changelog.fetch
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_kb_ingest.py -q`
Expected: the four new tests FAIL — `test_hash_adapter_...` because `ingest_feed` unpacks a `list` (calls `adapter(spec)`, gets `(entries, hash)` back only if it passed `prior_hash`, which it doesn't) → `TypeError`/assertion; `test_config_accepts_html_changelog_feed` FAILS with `ConfigError: ... not yet wired`; `test_html_changelog_registered_after_importing_ingest` FAILS with `KeyError` (adapter not imported/registered by `kb_ingest`). `test_plain_adapter_unaffected_by_hash_wiring` should already pass.

- [ ] **Step 3: Un-gate `html-changelog` in `agent/config.py`**

Replace the `NOT_YET_WIRED` dict (currently lines 15-24) with only the `registry` entry — `html-changelog` is now wired:

```python
# Adapters kept in ALLOWED_ADAPTERS but rejected as feeds with a specific reason
# (so config load explains WHY instead of "unknown adapter").
NOT_YET_WIRED = {
    "registry": (
        "adapter 'registry' is not a feed adapter — registry deprecation checks run via "
        "the `registry-scan` command (see docs), not as a feed"
    ),
}
```

- [ ] **Step 4: Wire the page-hash threading in `agent/kb_ingest.py`**

Replace the entire file contents with:

```python
# agent/kb_ingest.py
"""Ingest orchestration: run each feed's adapter, append to KB, advance watermarks."""
from __future__ import annotations

from dataclasses import replace

from agent.lib.models import FeedSpec, IngestResult
from agent.lib import kb_store
from agent.lib.feeds import get_adapter
# Import built-in adapters so they self-register on import of this module:
from agent.lib.feeds import rss, endoflife, html_changelog  # noqa: F401

# Adapters that fetch a whole page and skip re-processing when it is unchanged.
# They accept prior_hash=<last page hash> and return (entries, page_hash);
# plain adapters (rss/endoflife) are called as adapter(spec) and return a list.
HASH_ADAPTERS = {"html-changelog"}


def ingest_feed(spec: FeedSpec, kb_root: str, now: str, *, get=get_adapter) -> IngestResult:
    try:
        adapter = get(spec.adapter)
        wm = kb_store.read_watermark(kb_root, spec.techKey)
        if spec.adapter in HASH_ADAPTERS:
            raw, page_hash = adapter(spec, prior_hash=wm.get("pageHash", ""))
        else:
            raw, page_hash = adapter(spec), None
        stamped = [replace(e, ingestedAt=now) for e in raw]
        written = kb_store.append_entries(kb_root, spec.techKey, stamped)
        if page_hash is not None or raw:            # advance watermark on any run that fetched
            if page_hash is not None:
                wm["pageHash"] = page_hash
            latest = max((e.date for e in raw if e.date), default="")
            if latest:
                wm["lastIngestedDate"] = max(wm.get("lastIngestedDate", ""), latest)
            wm["lastRun"] = now
            kb_store.write_watermark(kb_root, spec.techKey, wm)
        return IngestResult(techKey=spec.techKey, adapter=spec.adapter,
                            new_entries=written, status="ok")
    except Exception as exc:  # feed down / parse error -> coverage gap, never crash the run
        return IngestResult(techKey=spec.techKey, adapter=spec.adapter,
                            new_entries=[], status="error", error=str(exc))


def ingest_all(feeds: list[FeedSpec], kb_root: str, now: str, *, get=get_adapter) -> list[IngestResult]:
    return [ingest_feed(spec, kb_root, now, get=get) for spec in feeds]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_kb_ingest.py -q`
Expected: PASS (all tests in the file, including the four new ones).

Then run the full suite to confirm no regression (esp. existing `test_kb_ingest.py` and `test_config*` / `test_html_changelog.py`):
Run: `source .venv/bin/activate && python -m pytest -q`
Expected: PASS — previous count (204) + 4 new = 208 passed.

- [ ] **Step 6: Commit**

```bash
git add agent/kb_ingest.py agent/config.py tests/test_kb_ingest.py
git commit -m "feat(ingest): wire html-changelog adapter (page-hash threading)"
```

---

## Task 2: Point production config at real marketplace sources (SP-API RSS + Walmart)

**Files:**
- Modify: `deploy/config.yaml` (the `feeds:` block)
- Test: `tests/test_deploy_config.py` (create)

**Interfaces:**
- Consumes: `agent.config.load_config(path) -> Config` with `Config.feeds: list[FeedSpec]`; the now-wired `html-changelog` adapter (Task 1); techKeys from `agent/patterns.yaml` (`api:amazon-sp-api`, `api:walmart-marketplace`, `api:shopify`).
- Produces: a production `deploy/config.yaml` whose feeds cover SP-API (official changelog RSS, replacing the interim GitHub-commits feed), Shopify (RSS, unchanged), and Walmart (`html-changelog`). No eBay (deferred).

- [ ] **Step 1: Write the failing test**

Create `tests/test_deploy_config.py`:

```python
"""Guards the shipped production config: it must load and carry the marketplace feeds."""
from agent.config import load_config


def test_deploy_config_loads_and_has_marketplace_feeds():
    cfg = load_config("deploy/config.yaml")
    by_tk = {f.techKey: f for f in cfg.feeds}

    # SP-API: official changelog RSS (not the interim GitHub-commits feed)
    sp = by_tk["api:amazon-sp-api"]
    assert sp.adapter == "rss"
    assert sp.url == "https://developer-docs.amazon.com/sp-api/changelog.rss"

    # Walmart: wired via the html-changelog adapter (Task 1)
    wm = by_tk["api:walmart-marketplace"]
    assert wm.adapter == "html-changelog"

    # Shopify: still the official Atom feed
    assert by_tk["api:shopify"].adapter == "rss"

    # eBay is deferred — must NOT be present
    assert "api:ebay" not in by_tk
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_deploy_config.py -q`
Expected: FAIL — `KeyError: 'api:walmart-marketplace'` (no Walmart feed yet) and the SP-API URL assertion fails (currently the GitHub-commits feed URL).

- [ ] **Step 3: Update the `feeds:` block in `deploy/config.yaml`**

Replace the existing `feeds:` block (the comment line plus the SP-API/Shopify/Twilio/runtime entries) with:

```yaml
# Marketplace change signals (Layer 1 — announced changes). techKey MUST match
# agent/patterns.yaml so a repo's usage joins to the change.
#   - SP-API: Amazon's official changelog RSS (prose release posts).
#   - Walmart: What's New / release-notes HTML via the html-changelog adapter. This
#     adapter structures the page with an LLM seam (structure_fn); in an environment
#     without that seam wired (no `claude` CLI / ANTHROPIC_API_KEY) it fetches +
#     hashes the page but structures no entries — a fail-soft coverage gap, not a
#     crash. Wiring the live structure_fn is a documented follow-up.
#   - eBay is deferred: it is bot-blocked (403 even with a browser UA) and needs a
#     headless-render or authenticated-download fetch path.
feeds:
  - { techKey: api:amazon-sp-api,       label: Amazon SP-API,       category: integration, adapter: rss,            url: https://developer-docs.amazon.com/sp-api/changelog.rss, tier: 1 }
  - { techKey: api:shopify,             label: Shopify Admin API,   category: integration, adapter: rss,            url: https://shopify.dev/changelog/feed.xml, tier: 1 }
  - { techKey: api:walmart-marketplace, label: Walmart Marketplace, category: integration, adapter: html-changelog, url: https://developer.walmart.com/us-marketplace/page/whats-new, tier: 1 }
  - { techKey: api:twilio,              label: Twilio,              category: integration, adapter: rss,            url: https://www.twilio.com/en-us/changelog.feed.xml, tier: 1 }
  - { techKey: runtime:php,     label: PHP,     category: runtime,   adapter: endoflife, url: php,     tier: 1 }
  - { techKey: runtime:node,    label: Node.js, category: runtime,   adapter: endoflife, url: nodejs,  tier: 1 }
  - { techKey: runtime:python,  label: Python,  category: runtime,   adapter: endoflife, url: python,  tier: 1 }
  - { techKey: runtime:laravel, label: Laravel, category: framework, adapter: endoflife, url: laravel, tier: 1 }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_deploy_config.py -q`
Expected: PASS.

Then the full suite:
Run: `source .venv/bin/activate && python -m pytest -q`
Expected: PASS — 208 + 1 new = 209 passed.

- [ ] **Step 5: Commit**

```bash
git add deploy/config.yaml tests/test_deploy_config.py
git commit -m "feat(feeds): SP-API official changelog RSS + Walmart html-changelog feed"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-07-13-contract-break-detection-design.md` → "Implementation sequencing … Plan A"):
- "replace the interim SP-API GitHub-commits feed with the official changelog RSS" → Task 2, Step 3 ✓
- "wire the `html-changelog` adapter into ingest … thread its `(entries, page_hash)` return through `kb_ingest`" → Task 1, Step 4 (the `HASH_ADAPTERS` branch + `pageHash` watermark) ✓
- "add the Walmart … feed via `html-changelog`" → Task 2, Step 3 ✓
- "Shopify RSS already wired (no change)" → retained verbatim in Task 2's feeds block ✓
- "eBay deferred" → Global Constraints + Task 2 asserts `api:ebay` absent ✓
- "config.py deliberately REJECTS adapter 'html-changelog' … remove the html-changelog gate" → Task 1, Step 3 ✓
- "tests must inject a fake … no network in tests" → all Task 1 tests use `_fake_get` fakes; Task 2 only loads config; no I/O ✓
- "live structure_fn wiring can be a documented follow-up" → documented in the `deploy/config.yaml` comment (Task 2, Step 3) ✓

**Placeholder scan:** No TBD/TODO. Every code step shows complete, runnable code. The one prose note ("fix the typo") is an explicit instruction, not a placeholder.

**Type consistency:** `ingest_feed`/`ingest_all` signatures unchanged. `HASH_ADAPTERS` is a `set[str]`. Hash-adapter return `(list[ChangeEntry], str)` matches `html_changelog.fetch`'s real return. Watermark stays a `dict` with a new `"pageHash": str` key. `FeedSpec(techKey, label, category, adapter, url, tier)` field names match `agent/lib/models.py`. techKeys (`api:amazon-sp-api`, `api:walmart-marketplace`, `api:shopify`) match `agent/patterns.yaml`.

**Note for the executor:** `deploy/config.yaml` also declares `source.type: github` with an `owner` placeholder — `load_config("deploy/config.yaml")` in Task 2's test succeeds because the placeholder is a non-empty string. Do not blank it out.
