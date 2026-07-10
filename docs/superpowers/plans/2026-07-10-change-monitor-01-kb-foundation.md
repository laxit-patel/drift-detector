# Change Monitor — Plan 01: KB Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Change Knowledge Base foundation — data models, config + feed registry, an append-only KB store, two deterministic feed adapters (RSS + endoflife), ingest orchestration, and the drift engine — so the agent can ingest real changelog feeds and compute week-over-week drift, with zero GitLab or LLM dependency.

**Architecture:** Pure-Python, file-based pipeline. Feeds are fetched by pluggable adapter functions that normalise items into append-only `ChangeEntry` records stored as JSONL under `kb/<techKey>/`. A deterministic drift engine selects entries newer than a caller-supplied watermark. All I/O (HTTP, clock) is injected so every unit is testable with fixtures — no network in tests.

**Tech Stack:** Python 3.11+, pytest, PyYAML, feedparser (RSS/Atom), requests, python-dateutil.

## Global Constraints

- Python **3.11+** (uses `list[X]` / `X | None` builtins, `dataclasses`).
- **No network and no wall-clock in unit tests.** Adapters take an injected `fetch_text`/`fetch_json`; ingest takes an injected `now` (ISO date string). Tests must never hit the internet.
- The KB is **append-only**: ingest never deletes or rewrites past entries. Idempotency is by `ChangeEntry.id` de-duplication.
- Package root is `agent/` (importable from repo root). Tests live in `tests/`. `pytest.ini` sets `pythonpath = .` so no install step is needed.
- Every finding/entry that will later be reported must carry a `sourceUrl` + `sourceTier`; models enforce these as required fields now.
- `changeType` at *ingest* is conservative (`additive` for generic feed items, `deprecation` for endoflife EOL rows). Real severity/breaking judgement is Plan 03's classifier — do **not** try to infer it here.
- Commit after every task (steps below). Conventional-commit messages.

**This is Plan 01 of 3** (02 = GitLab inventory + remaining adapters; 03 = classify → report → deliver). Keep module boundaries clean so 02/03 bolt on without edits here.

---

### Task 1: Project scaffolding + data models

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `agent/__init__.py`, `agent/lib/__init__.py`, `agent/lib/models.py`
- Test: `tests/__init__.py`, `tests/test_models.py`

**Interfaces:**
- Produces: `agent.lib.models.slugify(text: str) -> str`; `techkey_to_dir(techKey: str) -> str`; frozen dataclass `ChangeEntry(techKey, date, changeType, title, summary, sourceUrl, sourceTier, evidence="", affectedArea="", breaking=False, ingestedAt="", feedAdapter="", id="")` with auto-computed `id` and `to_dict()/from_dict()`; frozen dataclass `FeedSpec(techKey, label, category, adapter, url, tier, warn="", upgradeGuide="")`; dataclass `IngestResult(techKey, adapter, new_entries: list, status: str, error: str | None = None)`; constant `CHANGE_TYPES`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from agent.lib.models import (
    slugify, techkey_to_dir, ChangeEntry, FeedSpec, IngestResult, CHANGE_TYPES,
)

def test_slugify_lowercases_and_dashes():
    assert slugify("BuyerInfo now Optional!") == "buyerinfo-now-optional"

def test_slugify_truncates_and_never_empty():
    assert slugify("x" * 200).__len__() <= 60
    assert slugify("!!!") == "entry"

def test_techkey_to_dir_is_filesystem_safe():
    assert techkey_to_dir("api:amazon-sp-api") == "api_amazon-sp-api"
    assert techkey_to_dir("lib:npm/aws-sdk") == "lib_npm_aws-sdk"

def test_change_entry_autocomputes_id():
    e = ChangeEntry(
        techKey="api:amazon-sp-api", date="2026-07-03", changeType="breaking",
        title="Orders API: BuyerInfo now optional", summary="null-check required",
        sourceUrl="https://x/y", sourceTier=1,
    )
    assert e.id == "api:amazon-sp-api|2026-07-03|orders-api-buyerinfo-now-optional"

def test_change_entry_roundtrips_through_dict():
    e = ChangeEntry(
        techKey="runtime:php", date="2025-11-21", changeType="deprecation",
        title="PHP 8.1 EOL", summary="", sourceUrl="https://eol", sourceTier=1,
    )
    assert ChangeEntry.from_dict(e.to_dict()) == e

def test_change_types_constant():
    assert CHANGE_TYPES == {"breaking", "deprecation", "behavioral", "security", "additive"}

def test_ingest_result_defaults():
    r = IngestResult(techKey="api:shopify", adapter="rss", new_entries=[], status="ok")
    assert r.error is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent'`

- [ ] **Step 3: Write scaffolding + minimal implementation**

```
# requirements.txt
pytest>=7.4
PyYAML>=6.0
feedparser>=6.0
requests>=2.31
python-dateutil>=2.9
```

```ini
# pytest.ini
[pytest]
pythonpath = .
testpaths = tests
```

```python
# agent/__init__.py
```
```python
# agent/lib/__init__.py
```
```python
# tests/__init__.py
```

```python
# agent/lib/models.py
"""Core data models for the change-monitoring agent. Pure data, no I/O."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field

CHANGE_TYPES = {"breaking", "deprecation", "behavioral", "security", "additive"}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "entry"


def techkey_to_dir(techKey: str) -> str:
    """Filesystem-safe directory name for a techKey (e.g. 'api:amazon-sp-api')."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", techKey)


@dataclass(frozen=True)
class ChangeEntry:
    techKey: str
    date: str            # ISO 'YYYY-MM-DD'
    changeType: str
    title: str
    summary: str
    sourceUrl: str
    sourceTier: int
    evidence: str = ""
    affectedArea: str = ""
    breaking: bool = False
    ingestedAt: str = ""
    feedAdapter: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(
                self, "id", f"{self.techKey}|{self.date}|{slugify(self.title)}"
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ChangeEntry":
        return cls(**d)


@dataclass(frozen=True)
class FeedSpec:
    techKey: str
    label: str
    category: str        # integration | framework | library | runtime
    adapter: str         # rss | endoflife | github-releases | registry | html-changelog
    url: str
    tier: int
    warn: str = ""
    upgradeGuide: str = ""


@dataclass
class IngestResult:
    techKey: str
    adapter: str
    new_entries: list      # list[ChangeEntry]
    status: str            # "ok" | "error"
    error: str | None = None
```

- [ ] **Step 4: Install deps + run test to verify it passes**

Run: `pip install -r requirements.txt && pytest tests/test_models.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add requirements.txt pytest.ini agent/ tests/
git commit -m "feat(kb): data models (ChangeEntry, FeedSpec, IngestResult) + scaffolding"
```

---

### Task 2: Config loader + feed-registry validation

**Files:**
- Create: `agent/config.py`, `config.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `FeedSpec` from Task 1.
- Produces: dataclass `Config(kb_root: str, feeds: list[FeedSpec], raw: dict)`; `load_config(path: str) -> Config` (raises `ConfigError` on any invalid/missing field or unknown adapter).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import textwrap
import pytest
from agent.config import load_config, ConfigError

def _write(tmp_path, body):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)

VALID = """
    kb: { root: kb/ }
    feeds:
      - { techKey: api:shopify, label: Shopify, category: integration, adapter: rss, url: https://shopify.dev/changelog/feed.xml, tier: 1 }
      - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }
"""

def test_load_valid_config(tmp_path):
    cfg = load_config(_write(tmp_path, VALID))
    assert cfg.kb_root == "kb/"
    assert len(cfg.feeds) == 2
    assert cfg.feeds[0].techKey == "api:shopify"
    assert cfg.feeds[1].adapter == "endoflife"

def test_unknown_adapter_rejected(tmp_path):
    body = VALID.replace("adapter: rss", "adapter: telepathy")
    with pytest.raises(ConfigError, match="unknown adapter"):
        load_config(_write(tmp_path, body))

def test_missing_required_field_rejected(tmp_path):
    body = """
        kb: { root: kb/ }
        feeds:
          - { techKey: api:shopify, label: Shopify, category: integration, adapter: rss, tier: 1 }
    """
    with pytest.raises(ConfigError, match="url"):
        load_config(_write(tmp_path, body))

def test_no_feeds_rejected(tmp_path):
    with pytest.raises(ConfigError, match="at least one feed"):
        load_config(_write(tmp_path, "kb: { root: kb/ }\nfeeds: []\n"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/config.py
"""Load and validate config.yaml into typed objects. Fail loud on bad config."""
from __future__ import annotations

from dataclasses import dataclass
import yaml

from agent.lib.models import FeedSpec

ALLOWED_ADAPTERS = {"rss", "endoflife", "github-releases", "registry", "html-changelog"}
ALLOWED_CATEGORIES = {"integration", "framework", "library", "runtime"}
_REQUIRED = ("techKey", "label", "category", "adapter", "url", "tier")


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    kb_root: str
    feeds: list[FeedSpec]
    raw: dict


def _feed_from(d: dict) -> FeedSpec:
    for k in _REQUIRED:
        if d.get(k) in (None, ""):
            raise ConfigError(f"feed {d.get('techKey', '?')}: missing required field '{k}'")
    if d["adapter"] not in ALLOWED_ADAPTERS:
        raise ConfigError(f"feed {d['techKey']}: unknown adapter '{d['adapter']}'")
    if d["category"] not in ALLOWED_CATEGORIES:
        raise ConfigError(f"feed {d['techKey']}: unknown category '{d['category']}'")
    return FeedSpec(
        techKey=d["techKey"], label=d["label"], category=d["category"],
        adapter=d["adapter"], url=str(d["url"]), tier=int(d["tier"]),
        warn=d.get("warn", ""), upgradeGuide=d.get("upgradeGuide", ""),
    )


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    feeds_raw = raw.get("feeds") or []
    if not feeds_raw:
        raise ConfigError("config must declare at least one feed")
    feeds = [_feed_from(f) for f in feeds_raw]
    kb_root = (raw.get("kb") or {}).get("root", "kb/")
    return Config(kb_root=kb_root, feeds=feeds, raw=raw)
```

```yaml
# config.yaml  (seed — a runnable subset for Plan 01; full registry lands in Plan 02/03)
kb:
  root: kb/
feeds:
  - { techKey: api:shopify, label: Shopify Admin API, category: integration, adapter: rss, url: https://shopify.dev/changelog/feed.xml, tier: 1 }
  - { techKey: api:twilio,  label: Twilio, category: integration, adapter: rss, url: https://www.twilio.com/en-us/changelog.feed.xml, tier: 1 }
  - { techKey: runtime:node,   label: Node.js, category: runtime, adapter: endoflife, url: nodejs, tier: 1 }
  - { techKey: runtime:php,    label: PHP,     category: runtime, adapter: endoflife, url: php,    tier: 1 }
  - { techKey: runtime:python, label: Python,  category: runtime, adapter: endoflife, url: python, tier: 1 }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/config.py config.yaml tests/test_config.py
git commit -m "feat(kb): config loader with feed-registry validation + seed config.yaml"
```

---

### Task 3: Append-only KB store (JSONL + dedupe + watermark)

**Files:**
- Create: `agent/lib/kb_store.py`
- Test: `tests/test_kb_store.py`

**Interfaces:**
- Consumes: `ChangeEntry`, `techkey_to_dir` from Task 1.
- Produces:
  - `changes_path(root, techKey) -> pathlib.Path`
  - `load_entries(root, techKey) -> list[ChangeEntry]`
  - `append_entries(root, techKey, entries: list[ChangeEntry]) -> list[ChangeEntry]` (returns only the *newly written* entries after de-duping by `id`; append-only)
  - `read_watermark(root, techKey) -> dict`
  - `write_watermark(root, techKey, data: dict) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kb_store.py
from agent.lib.models import ChangeEntry
from agent.lib import kb_store

def _entry(title, date="2026-07-03", tk="api:shopify"):
    return ChangeEntry(techKey=tk, date=date, changeType="additive", title=title,
                       summary="", sourceUrl="https://x", sourceTier=1)

def test_append_then_load_roundtrip(tmp_path):
    root = str(tmp_path)
    written = kb_store.append_entries(root, "api:shopify", [_entry("A"), _entry("B")])
    assert len(written) == 2
    loaded = kb_store.load_entries(root, "api:shopify")
    assert {e.title for e in loaded} == {"A", "B"}

def test_append_is_idempotent_by_id(tmp_path):
    root = str(tmp_path)
    kb_store.append_entries(root, "api:shopify", [_entry("A")])
    written2 = kb_store.append_entries(root, "api:shopify", [_entry("A"), _entry("C")])
    assert [e.title for e in written2] == ["C"]        # "A" already present, skipped
    assert len(kb_store.load_entries(root, "api:shopify")) == 2

def test_load_missing_returns_empty(tmp_path):
    assert kb_store.load_entries(str(tmp_path), "api:nope") == []

def test_watermark_roundtrip(tmp_path):
    root = str(tmp_path)
    assert kb_store.read_watermark(root, "api:shopify") == {}
    kb_store.write_watermark(root, "api:shopify", {"lastIngestedDate": "2026-07-05"})
    assert kb_store.read_watermark(root, "api:shopify")["lastIngestedDate"] == "2026-07-05"

def test_path_is_filesystem_safe(tmp_path):
    p = kb_store.changes_path(str(tmp_path), "lib:npm/aws-sdk")
    assert "lib_npm_aws-sdk" in str(p)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kb_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.kb_store'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/kb_store.py
"""Append-only JSONL knowledge-base store. Idempotent by ChangeEntry.id."""
from __future__ import annotations

import json
from pathlib import Path

from agent.lib.models import ChangeEntry, techkey_to_dir


def _dir(root: str, techKey: str) -> Path:
    return Path(root) / techkey_to_dir(techKey)


def changes_path(root: str, techKey: str) -> Path:
    return _dir(root, techKey) / "changes.jsonl"


def _watermark_path(root: str, techKey: str) -> Path:
    return _dir(root, techKey) / "watermark.json"


def load_entries(root: str, techKey: str) -> list[ChangeEntry]:
    p = changes_path(root, techKey)
    if not p.exists():
        return []
    out: list[ChangeEntry] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(ChangeEntry.from_dict(json.loads(line)))
    return out


def append_entries(root: str, techKey: str, entries: list[ChangeEntry]) -> list[ChangeEntry]:
    existing_ids = {e.id for e in load_entries(root, techKey)}
    fresh = [e for e in entries if e.id not in existing_ids]
    if not fresh:
        return []
    p = changes_path(root, techKey)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for e in fresh:
            fh.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
    return fresh


def read_watermark(root: str, techKey: str) -> dict:
    p = _watermark_path(root, techKey)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def write_watermark(root: str, techKey: str, data: dict) -> None:
    p = _watermark_path(root, techKey)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_kb_store.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/kb_store.py tests/test_kb_store.py
git commit -m "feat(kb): append-only JSONL store with id-dedupe and watermarks"
```

---

### Task 4: Feed adapter registry

**Files:**
- Create: `agent/lib/feeds/__init__.py`
- Test: `tests/test_feed_registry.py`

**Interfaces:**
- Produces: decorator `register(name: str)` that registers a callable `fetch(spec: FeedSpec, **kw) -> list[ChangeEntry]`; `get_adapter(name: str) -> callable` (raises `KeyError` if absent); `adapter_names() -> set[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_feed_registry.py
import pytest
from agent.lib import feeds

def test_register_and_get():
    @feeds.register("dummy-test")
    def fetch(spec, **kw):
        return []
    assert feeds.get_adapter("dummy-test") is fetch
    assert "dummy-test" in feeds.adapter_names()

def test_get_unknown_raises():
    with pytest.raises(KeyError, match="no feed adapter"):
        feeds.get_adapter("does-not-exist")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_feed_registry.py -v`
Expected: FAIL — `AttributeError: module 'agent.lib.feeds' has no attribute 'register'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/lib/feeds/__init__.py
"""Feed adapter registry. Adapters are functions: fetch(spec, **kw) -> list[ChangeEntry]."""
from __future__ import annotations

_ADAPTERS: dict = {}


def register(name: str):
    def deco(fn):
        _ADAPTERS[name] = fn
        return fn
    return deco


def get_adapter(name: str):
    if name not in _ADAPTERS:
        raise KeyError(f"no feed adapter registered for '{name}'")
    return _ADAPTERS[name]


def adapter_names() -> set:
    return set(_ADAPTERS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_feed_registry.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/lib/feeds/__init__.py tests/test_feed_registry.py
git commit -m "feat(kb): feed adapter registry"
```

---

### Task 5: RSS/Atom feed adapter

**Files:**
- Create: `agent/lib/feeds/rss.py`, `tests/fixtures/shopify_changelog.xml`
- Test: `tests/test_rss_adapter.py`

**Interfaces:**
- Consumes: `register` (Task 4), `ChangeEntry`, `FeedSpec`.
- Produces: registered adapter `"rss"` — `fetch(spec, *, fetch_text=<http>) -> list[ChangeEntry]`. Injectable `fetch_text(url) -> str` so tests pass fixture XML. Each item → `ChangeEntry(changeType="additive", feedAdapter="rss")` with a normalised `YYYY-MM-DD` date and HTML-stripped summary.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rss_adapter.py
from pathlib import Path
from agent.lib.models import FeedSpec
from agent.lib.feeds import rss, get_adapter

FIX = Path(__file__).parent / "fixtures" / "shopify_changelog.xml"

def _spec():
    return FeedSpec(techKey="api:shopify", label="Shopify", category="integration",
                    adapter="rss", url="https://shopify.dev/changelog/feed.xml", tier=1)

def test_rss_parses_items():
    xml = FIX.read_text()
    entries = rss.fetch(_spec(), fetch_text=lambda url: xml)
    assert len(entries) == 2
    first = entries[0]
    assert first.title == "New Bulk Operations endpoint"
    assert first.date == "2026-07-01"
    assert first.techKey == "api:shopify"
    assert first.changeType == "additive"
    assert first.feedAdapter == "rss"
    assert first.sourceUrl == "https://shopify.dev/changelog/bulk-ops"
    assert "<" not in first.summary            # HTML stripped

def test_rss_is_registered():
    assert get_adapter("rss") is rss.fetch
```

- [ ] **Step 2: Create the fixture**

```xml
<!-- tests/fixtures/shopify_changelog.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Shopify Changelog</title>
  <item>
    <title>New Bulk Operations endpoint</title>
    <link>https://shopify.dev/changelog/bulk-ops</link>
    <description><![CDATA[<p>Adds a <b>bulkOperations</b> endpoint.</p>]]></description>
    <pubDate>Wed, 01 Jul 2026 10:00:00 +0000</pubDate>
    <guid>https://shopify.dev/changelog/bulk-ops</guid>
  </item>
  <item>
    <title>REST Admin deprecation notice</title>
    <link>https://shopify.dev/changelog/rest-deprecation</link>
    <description>REST Admin API winding down in favour of GraphQL.</description>
    <pubDate>Mon, 22 Jun 2026 09:00:00 +0000</pubDate>
    <guid>https://shopify.dev/changelog/rest-deprecation</guid>
  </item>
</channel></rss>
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_rss_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.feeds.rss'`

- [ ] **Step 4: Write minimal implementation**

```python
# agent/lib/feeds/rss.py
"""RSS/Atom adapter. Normalises feed items into additive ChangeEntry records."""
from __future__ import annotations

import re
import time

import feedparser
import requests

from agent.lib.models import ChangeEntry, FeedSpec
from agent.lib.feeds import register

_TAG = re.compile(r"<[^>]+>")


def _http_get(url: str) -> str:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "change-monitor/1.0"})
    resp.raise_for_status()
    return resp.text


def _to_date(entry) -> str:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    return time.strftime("%Y-%m-%d", st) if st else ""


def _clean(text: str) -> str:
    return _TAG.sub("", text or "").strip()


@register("rss")
def fetch(spec: FeedSpec, *, fetch_text=_http_get) -> list[ChangeEntry]:
    parsed = feedparser.parse(fetch_text(spec.url))
    out: list[ChangeEntry] = []
    for e in parsed.entries:
        out.append(ChangeEntry(
            techKey=spec.techKey,
            date=_to_date(e),
            changeType="additive",
            title=e.get("title", "").strip(),
            summary=_clean(e.get("summary", "")),
            sourceUrl=e.get("link", spec.url),
            sourceTier=spec.tier,
            feedAdapter="rss",
        ))
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_rss_adapter.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add agent/lib/feeds/rss.py tests/test_rss_adapter.py tests/fixtures/shopify_changelog.xml
git commit -m "feat(kb): RSS/Atom feed adapter"
```

---

### Task 6: endoflife.date adapter

**Files:**
- Create: `agent/lib/feeds/endoflife.py`, `tests/fixtures/endoflife_php.json`
- Test: `tests/test_endoflife_adapter.py`

**Interfaces:**
- Consumes: `register`, `ChangeEntry`, `FeedSpec`.
- Produces: registered adapter `"endoflife"` — `fetch(spec, *, fetch_json=<http>) -> list[ChangeEntry]`. `spec.url` is the endoflife product slug (e.g. `php`). Emits one `ChangeEntry(changeType="deprecation", feedAdapter="endoflife")` per cycle whose `eol` is a real date string, with `date = eol` and `affectedArea = "cycle <cycle>"`. Boolean `eol` (true/false) cycles are skipped (no concrete date to report).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_endoflife_adapter.py
import json
from pathlib import Path
from agent.lib.models import FeedSpec
from agent.lib.feeds import endoflife, get_adapter

FIX = json.loads((Path(__file__).parent / "fixtures" / "endoflife_php.json").read_text())

def _spec():
    return FeedSpec(techKey="runtime:php", label="PHP", category="runtime",
                    adapter="endoflife", url="php", tier=1)

def test_endoflife_emits_entry_per_dated_cycle():
    entries = endoflife.fetch(_spec(), fetch_json=lambda url: FIX)
    # fixture has cycles 8.3 (eol date), 8.2 (eol date), 8.1 (eol bool true -> skipped)
    dates = sorted(e.date for e in entries)
    assert dates == ["2025-12-08", "2026-12-31"]
    e = next(e for e in entries if e.date == "2025-12-08")
    assert e.changeType == "deprecation"
    assert e.techKey == "runtime:php"
    assert "8.2" in e.title
    assert e.sourceUrl == "https://endoflife.date/php"

def test_endoflife_registered():
    assert get_adapter("endoflife") is endoflife.fetch
```

- [ ] **Step 2: Create the fixture**

```json
// tests/fixtures/endoflife_php.json
[
  {"cycle": "8.3", "eol": "2026-12-31", "latest": "8.3.10"},
  {"cycle": "8.2", "eol": "2025-12-08", "latest": "8.2.22"},
  {"cycle": "8.1", "eol": true, "latest": "8.1.29"}
]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_endoflife_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.feeds.endoflife'`

- [ ] **Step 4: Write minimal implementation**

```python
# agent/lib/feeds/endoflife.py
"""endoflife.date adapter. Emits a lifecycle ChangeEntry per cycle with a concrete EOL date."""
from __future__ import annotations

import requests

from agent.lib.models import ChangeEntry, FeedSpec
from agent.lib.feeds import register


def _http_json(url: str):
    resp = requests.get(url, timeout=30, headers={"User-Agent": "change-monitor/1.0"})
    resp.raise_for_status()
    return resp.json()


@register("endoflife")
def fetch(spec: FeedSpec, *, fetch_json=_http_json) -> list[ChangeEntry]:
    product = spec.url.strip("/")
    data = fetch_json(f"https://endoflife.date/api/{product}.json")
    human_url = f"https://endoflife.date/{product}"
    out: list[ChangeEntry] = []
    for row in data:
        eol = row.get("eol")
        if not isinstance(eol, str):        # bool eol has no concrete date to report
            continue
        cycle = row.get("cycle", "?")
        out.append(ChangeEntry(
            techKey=spec.techKey,
            date=eol,
            changeType="deprecation",
            title=f"{spec.label} {cycle} end-of-life",
            summary=f"{spec.label} {cycle} reaches end-of-life on {eol}.",
            sourceUrl=human_url,
            sourceTier=spec.tier,
            affectedArea=f"cycle {cycle}",
            feedAdapter="endoflife",
        ))
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_endoflife_adapter.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add agent/lib/feeds/endoflife.py tests/test_endoflife_adapter.py tests/fixtures/endoflife_php.json
git commit -m "feat(kb): endoflife.date lifecycle adapter"
```

---

### Task 7: KB ingest orchestration

**Files:**
- Create: `agent/kb_ingest.py`
- Test: `tests/test_kb_ingest.py`

**Interfaces:**
- Consumes: `Config`/`FeedSpec` (Task 2), `get_adapter` (Task 4), `kb_store` (Task 3), `ChangeEntry`/`IngestResult` (Task 1).
- Produces:
  - `ingest_feed(spec, kb_root, now, *, get=get_adapter) -> IngestResult` — dispatches the adapter, stamps `ingestedAt=now` on each entry, appends (dedupe), advances the watermark to the max entry date seen, and returns an `IngestResult`. Any adapter exception → `IngestResult(status="error", error=str(exc))` (never raises).
  - `ingest_all(feeds, kb_root, now, *, get=get_adapter) -> list[IngestResult]`.
- Importing this module imports the built-in adapters so they self-register.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kb_ingest.py
from dataclasses import replace
from agent.lib.models import ChangeEntry, FeedSpec
from agent.lib import kb_store
from agent import kb_ingest

def _spec(adapter="fake-ok"):
    return FeedSpec(techKey="api:shopify", label="Shopify", category="integration",
                    adapter=adapter, url="http://x", tier=1)

def _entry(title):
    return ChangeEntry(techKey="api:shopify", date="2026-07-03", changeType="additive",
                       title=title, summary="", sourceUrl="https://x", sourceTier=1)

def _fake_get(mapping):
    return lambda name: mapping[name]

def test_ingest_feed_appends_and_stamps_now(tmp_path):
    get = _fake_get({"fake-ok": lambda spec, **kw: [_entry("A"), _entry("B")]})
    res = kb_ingest.ingest_feed(_spec(), str(tmp_path), now="2026-07-05", get=get)
    assert res.status == "ok"
    assert len(res.new_entries) == 2
    stored = kb_store.load_entries(str(tmp_path), "api:shopify")
    assert all(e.ingestedAt == "2026-07-05" for e in stored)
    assert kb_store.read_watermark(str(tmp_path), "api:shopify")["lastIngestedDate"] == "2026-07-03"

def test_ingest_feed_is_idempotent(tmp_path):
    get = _fake_get({"fake-ok": lambda spec, **kw: [_entry("A")]})
    kb_ingest.ingest_feed(_spec(), str(tmp_path), now="2026-07-05", get=get)
    res2 = kb_ingest.ingest_feed(_spec(), str(tmp_path), now="2026-07-12", get=get)
    assert res2.new_entries == []          # already present
    assert len(kb_store.load_entries(str(tmp_path), "api:shopify")) == 1

def test_ingest_feed_captures_adapter_error(tmp_path):
    def boom(spec, **kw):
        raise RuntimeError("feed down")
    get = _fake_get({"fake-boom": boom})
    res = kb_ingest.ingest_feed(_spec("fake-boom"), str(tmp_path), now="2026-07-05", get=get)
    assert res.status == "error"
    assert "feed down" in res.error

def test_ingest_all_runs_each_feed(tmp_path):
    get = _fake_get({"fake-ok": lambda spec, **kw: [_entry("A")]})
    feeds = [_spec(), replace(_spec(), techKey="api:twilio")]
    results = kb_ingest.ingest_all(feeds, str(tmp_path), now="2026-07-05", get=get)
    assert [r.status for r in results] == ["ok", "ok"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kb_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.kb_ingest'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/kb_ingest.py
"""Ingest orchestration: run each feed's adapter, append to KB, advance watermarks."""
from __future__ import annotations

from dataclasses import replace

from agent.lib.models import FeedSpec, IngestResult
from agent.lib import kb_store
from agent.lib.feeds import get_adapter
# Import built-in adapters so they self-register on import of this module:
from agent.lib.feeds import rss, endoflife  # noqa: F401


def ingest_feed(spec: FeedSpec, kb_root: str, now: str, *, get=get_adapter) -> IngestResult:
    try:
        adapter = get(spec.adapter)
        raw = adapter(spec)
        stamped = [replace(e, ingestedAt=now) for e in raw]
        written = kb_store.append_entries(kb_root, spec.techKey, stamped)
        if raw:
            latest = max(e.date for e in raw if e.date) if any(e.date for e in raw) else ""
            wm = kb_store.read_watermark(kb_root, spec.techKey)
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

Note: `ChangeEntry` is frozen; `replace(e, ingestedAt=now)` recomputes nothing else (id already set) — the `id` field is preserved because it is non-empty, so `__post_init__` leaves it. Verified by Task 1's roundtrip test semantics.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_kb_ingest.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/kb_ingest.py tests/test_kb_ingest.py
git commit -m "feat(kb): ingest orchestration with per-feed error capture + watermarks"
```

---

### Task 8: Drift engine

**Files:**
- Create: `agent/drift.py`
- Test: `tests/test_drift.py`

**Interfaces:**
- Consumes: `kb_store.load_entries` (Task 3), `ChangeEntry` (Task 1).
- Produces:
  - `select_drift(entries: list[ChangeEntry], since_date: str | None) -> list[ChangeEntry]` — pure: entries with `date > since_date` (all entries if `since_date` is falsy), sorted by `date`.
  - `drift_for_tech(kb_root, techKey, since_date) -> list[ChangeEntry]` — loads from KB and applies `select_drift`.
  - `compute_drift(kb_root, techKeys: list[str], watermarks: dict[str, str]) -> list[dict]` — returns `[{"techKey": tk, "entries": [ChangeEntry, ...]}]`, omitting techs with no drift.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drift.py
from agent.lib.models import ChangeEntry
from agent.lib import kb_store
from agent import drift

def _e(title, date, tk="api:shopify"):
    return ChangeEntry(techKey=tk, date=date, changeType="additive", title=title,
                       summary="", sourceUrl="https://x", sourceTier=1)

def test_select_drift_filters_by_since():
    entries = [_e("old", "2026-06-01"), _e("edge", "2026-07-01"), _e("new", "2026-07-08")]
    got = drift.select_drift(entries, "2026-07-01")
    assert [e.title for e in got] == ["new"]          # strictly newer than watermark

def test_select_drift_none_returns_all_sorted():
    entries = [_e("b", "2026-07-08"), _e("a", "2026-07-01")]
    assert [e.title for e in drift.select_drift(entries, None)] == ["a", "b"]

def test_drift_for_tech_reads_kb(tmp_path):
    root = str(tmp_path)
    kb_store.append_entries(root, "api:shopify", [_e("old", "2026-06-01"), _e("new", "2026-07-08")])
    got = drift.drift_for_tech(root, "api:shopify", "2026-07-01")
    assert [e.title for e in got] == ["new"]

def test_compute_drift_omits_empty(tmp_path):
    root = str(tmp_path)
    kb_store.append_entries(root, "api:shopify", [_e("new", "2026-07-08")])
    kb_store.append_entries(root, "api:twilio", [_e("stale", "2026-01-01", tk="api:twilio")])
    out = drift.compute_drift(root, ["api:shopify", "api:twilio"],
                              {"api:shopify": "2026-07-01", "api:twilio": "2026-06-01"})
    assert len(out) == 1
    assert out[0]["techKey"] == "api:shopify"
    assert [e.title for e in out[0]["entries"]] == ["new"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_drift.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.drift'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/drift.py
"""Drift engine: select KB change entries newer than a caller-supplied watermark."""
from __future__ import annotations

from agent.lib.models import ChangeEntry
from agent.lib import kb_store


def select_drift(entries: list[ChangeEntry], since_date: str | None) -> list[ChangeEntry]:
    picked = [e for e in entries if (not since_date or (e.date and e.date > since_date))]
    return sorted(picked, key=lambda e: e.date)


def drift_for_tech(kb_root: str, techKey: str, since_date: str | None) -> list[ChangeEntry]:
    return select_drift(kb_store.load_entries(kb_root, techKey), since_date)


def compute_drift(kb_root: str, techKeys: list[str], watermarks: dict) -> list[dict]:
    out: list[dict] = []
    for tk in techKeys:
        entries = drift_for_tech(kb_root, tk, watermarks.get(tk))
        if entries:
            out.append({"techKey": tk, "entries": entries})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_drift.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/drift.py tests/test_drift.py
git commit -m "feat(kb): drift engine (watermark-based new-entry selection)"
```

---

### Task 9: CLI runner + smoke test + README

**Files:**
- Create: `agent/cli.py`, `docs/change-monitor-plan01-README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_config` (Task 2), `ingest_all` (Task 7), `compute_drift` (Task 8), `kb_store.read_watermark` (Task 3).
- Produces: `main(argv: list[str]) -> int` with two subcommands: `ingest --config <path> --now <YYYY-MM-DD>` and `drift --config <path> --since <YYYY-MM-DD>`. Prints a human summary; returns 0 on success, 1 if any feed errored during `ingest`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import textwrap
from pathlib import Path
from agent import cli

def _cfg(tmp_path):
    root = tmp_path / "kb"
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(f"""
        kb: {{ root: {root} }}
        feeds:
          - {{ techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }}
    """))
    return str(p)

def test_cli_ingest_then_drift(tmp_path, monkeypatch, capsys):
    # Stub the endoflife adapter's HTTP so the smoke test never hits the network.
    from agent.lib.feeds import endoflife
    monkeypatch.setattr(endoflife, "_http_json",
                        lambda url: [{"cycle": "8.2", "eol": "2025-12-08"}])
    # Re-register fetch bound to the patched default? Simpler: patch module-level default via kw.
    cfg = _cfg(tmp_path)

    # Ingest
    rc = cli.main(["ingest", "--config", cfg, "--now", "2026-07-05",
                   "--_test_eol", '[{"cycle":"8.2","eol":"2025-12-08"}]'])
    assert rc == 0
    out = capsys.readouterr().out
    assert "runtime:php" in out and "1 new" in out

    # Drift since before the EOL date -> the entry shows
    rc = cli.main(["drift", "--config", cfg, "--since", "2025-01-01"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "PHP 8.2 end-of-life" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/cli.py
"""CLI for Plan 01: `ingest` populates the KB from feeds; `drift` reports new entries.

The `--_test_eol` flag is a hidden hook so the smoke test can inject endoflife JSON
without patching HTTP; production runs never pass it.
"""
from __future__ import annotations

import argparse
import json
import sys

from agent.config import load_config
from agent import kb_ingest, drift
from agent.lib import kb_store
from agent.lib.feeds import endoflife


def _cmd_ingest(args) -> int:
    cfg = load_config(args.config)
    if args._test_eol:
        payload = json.loads(args._test_eol)
        # Wrap the endoflife adapter so its HTTP is bypassed for the smoke test.
        orig = endoflife.fetch
        def patched(spec, **kw):
            return orig(spec, fetch_json=lambda url: payload)
        get = lambda name: patched if name == "endoflife" else __import__(
            "agent.lib.feeds", fromlist=["get_adapter"]).get_adapter(name)
        results = kb_ingest.ingest_all(cfg.feeds, cfg.kb_root, args.now, get=get)
    else:
        results = kb_ingest.ingest_all(cfg.feeds, cfg.kb_root, args.now)
    errored = 0
    for r in results:
        if r.status == "ok":
            print(f"  {r.techKey}: {len(r.new_entries)} new ({r.adapter})")
        else:
            errored += 1
            print(f"  {r.techKey}: ERROR — {r.error}")
    print(f"Ingest complete: {len(results)} feeds, {errored} errored.")
    return 1 if errored else 0


def _cmd_drift(args) -> int:
    cfg = load_config(args.config)
    tks = [f.techKey for f in cfg.feeds]
    wms = {tk: args.since for tk in tks}
    groups = drift.compute_drift(cfg.kb_root, tks, wms)
    if not groups:
        print("No drift since watermark.")
        return 0
    for g in groups:
        print(f"\n{g['techKey']}:")
        for e in g["entries"]:
            print(f"  [{e.date}] {e.title}  <{e.sourceUrl}>")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="change-monitor")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest")
    pi.add_argument("--config", required=True)
    pi.add_argument("--now", required=True)
    pi.add_argument("--_test_eol", default="")
    pi.set_defaults(func=_cmd_ingest)

    pd = sub.add_parser("drift")
    pd.add_argument("--config", required=True)
    pd.add_argument("--since", default="")
    pd.set_defaults(func=_cmd_drift)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

```markdown
<!-- docs/change-monitor-plan01-README.md -->
# Change Monitor — Plan 01 (KB Foundation)

Deterministic Change Knowledge Base: ingest changelog feeds → append-only JSONL → drift.

## Run
```bash
pip install -r requirements.txt
python -m agent.cli ingest --config config.yaml --now 2026-07-12
python -m agent.cli drift  --config config.yaml --since 2026-07-05
```
Ingest is idempotent (dedupe by entry id) and append-only. Feeds that fail are
reported as errors (exit 1) but never crash the run. No GitLab or LLM needed here.

## What's next
- Plan 02: GitLab discovery + inventory + `github-releases`/`registry`/`html-changelog` adapters.
- Plan 03: Claude classify stage + trust gate, delta, report, Chat, `run.sh`, dead-man's switch.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full suite + a real smoke (network) run**

Run: `pytest -q`
Expected: all green.

Optional live smoke (hits the network — not part of CI):
`python -m agent.cli ingest --config config.yaml --now 2026-07-12 && python -m agent.cli drift --config config.yaml --since 2020-01-01`
Expected: real Shopify/Twilio/endoflife entries land under `kb/`, drift lists them.

- [ ] **Step 6: Commit**

```bash
git add agent/cli.py tests/test_cli.py docs/change-monitor-plan01-README.md
git commit -m "feat(kb): CLI ingest/drift commands + Plan 01 README"
```

---

## Self-Review

**Spec coverage (Plan 01 slice of the v2 spec):**
- §3.2 Config loader → Task 2 ✓
- §3.3 KB ingest + feed adapters (rss, endoflife subset) → Tasks 4–7 ✓ (github-releases/registry/html-changelog deferred to Plan 02, stated up front)
- §3.7 Drift engine → Task 8 ✓
- §5.1 Change Entry schema → Task 1 ✓
- §5.3 Feed registry (seed subset) → Task 2 `config.yaml` ✓
- §13 "feed down → coverage gap, never silent" → Task 7 error capture ✓
- §13 "KB append-only / duplicate dedupe" → Task 3 ✓
- Deferred (correctly, per decomposition): GitLab (§3.4–3.6), classify/trust-gate (§3.8/§4), delta findings/watermark-in-findings.json (§3.10/§7), report/Chat/actions/run.sh (§3.11–3.13/§8/§9/§11). The Plan-01 drift engine takes the watermark as a parameter precisely so Plan 03 can supply the reported-watermark from `findings.json` without changing this module.

**Placeholder scan:** none — every step has complete, runnable code. The `--_test_eol` hook is real, documented code (a deliberate test seam), not a placeholder.

**Type consistency:** `ChangeEntry`/`FeedSpec`/`IngestResult` field names are identical across Tasks 1, 3, 5, 6, 7, 8. `fetch(spec, *, fetch_text/fetch_json=...)` adapter signature is consistent (Tasks 5–6) and dispatched uniformly in Task 7. `select_drift(entries, since_date)` / `compute_drift(kb_root, techKeys, watermarks)` names match between Task 8 and their Task 9 callers. `load_config → Config(kb_root, feeds, raw)` consistent between Tasks 2 and 9.

**Known limitation (documented, not a gap):** RSS date parsing depends on `published_parsed`; feeds lacking dates yield `date=""` and are treated as pre-watermark by `select_drift` (won't spuriously alert). Fine for Plan 01; Plan 02's `html-changelog` adapter handles dateless sources via the LLM structurer.
