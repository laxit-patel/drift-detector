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
    assert e.id.startswith("api:amazon-sp-api|2026-07-03|orders-api-buyerinfo-now-optional|")
    # deterministic: same inputs -> same id
    e2 = ChangeEntry(techKey="api:amazon-sp-api", date="2026-07-03", changeType="breaking",
                     title="Orders API: BuyerInfo now optional", summary="different summary",
                     sourceUrl="https://z", sourceTier=1)
    assert e.id == e2.id

def test_id_distinguishes_long_titles_sharing_60char_prefix():
    prefix = "Orders API deprecation notice for the BuyerInfo field in version "
    a = ChangeEntry(techKey="api:sp", date="2026-07-03", changeType="breaking",
                    title=prefix + "2024", summary="", sourceUrl="https://x", sourceTier=1)
    b = ChangeEntry(techKey="api:sp", date="2026-07-03", changeType="breaking",
                    title=prefix + "2025", summary="", sourceUrl="https://x", sourceTier=1)
    assert a.id != b.id   # distinct despite identical 60-char slug prefix

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
