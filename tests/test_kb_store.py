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

def test_append_dedupes_within_single_batch(tmp_path):
    root = str(tmp_path)
    dup = _entry("Same")
    written = kb_store.append_entries(root, "api:shopify", [dup, _entry("Same"), _entry("Other")])
    assert len(written) == 2      # one "Same" + "Other"
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

def test_append_load_roundtrips_unicode_line_separators(tmp_path):
    # U+2028 (LINE SEPARATOR) inside a field is written literally by json.dumps(ensure_ascii=False)
    # (it is not a JSON-required-escape control char) and must NOT split the JSONL record on read.
    root = str(tmp_path)
    tricky = ChangeEntry(techKey="api:shopify", date="2026-07-03", changeType="additive",
                         title="Bulk Operations endpoint", summary="line sep",
                         sourceUrl="https://x", sourceTier=1)
    kb_store.append_entries(root, "api:shopify", [tricky])
    loaded = kb_store.load_entries(root, "api:shopify")
    assert len(loaded) == 1
    assert loaded[0] == tricky
