from agent.classify_rules import days_until, map_severity, candidate_to_finding

def test_days_until():
    assert days_until("2026-07-20", "2026-07-10") == 10
    assert days_until("2026-07-01", "2026-07-10") == -9
    assert days_until("", "2026-07-10") is None

def test_map_severity_rules():
    assert map_severity("breaking", "", "2026-07-10") == ("ACTION", False)
    assert map_severity("security", "", "2026-07-10") == ("ACTION", False)
    assert map_severity("eol", "2020-01-01", "2026-07-10") == ("ACTION", False)      # passed
    assert map_severity("eol", "2026-09-01", "2026-07-10") == ("REVIEW", False)      # ~2 months
    assert map_severity("eol", "2030-01-01", "2026-07-10") == ("OK", False)          # far future
    assert map_severity("deprecation", "", "2026-07-10") == ("REVIEW", False)
    assert map_severity("behavioral", "", "2026-07-10") == ("REVIEW", False)
    assert map_severity("additive", "", "2026-07-10") == ("OK", True)                # needs LLM judgement

def test_candidate_to_finding_eol():
    cand = {"repo": "c/a", "projectId": 42, "techKey": "runtime:php", "category": "runtime",
            "versionInUse": "8.0", "changeEntry": {
                "id": "runtime:php|2020-01-01|php-8-0-eol", "changeType": "eol", "date": "2020-01-01",
                "sourceUrl": "https://eol", "sourceTier": 1, "evidence": "PHP 8.0 EOL"}}
    f = candidate_to_finding(cand, "2026-07-10")
    assert f.severity == "ACTION" and f.findingType == "lifecycle"
    assert f.urgencyDays < 0 and f.deadlineDate == "2020-01-01"
    assert f.changeEntryId in f.id and f.id.startswith("42|runtime:php|")
    assert f.sourceUrl == "https://eol" and f.evidence == "PHP 8.0 EOL"

def test_candidate_to_finding_additive_needs_review():
    cand = {"repo": "c/a", "projectId": 1, "techKey": "api:shopify", "category": "integration",
            "versionInUse": "", "changeEntry": {
                "id": "shopify|2026-07-01|x", "changeType": "additive", "date": "2026-07-01",
                "sourceUrl": "https://s", "sourceTier": 1, "evidence": "some change"}}
    f = candidate_to_finding(cand, "2026-07-10")
    assert f.severity == "OK" and f.needsReview is True and f.findingType == "drift"
    assert f.changeEntryId == "shopify|2026-07-01|x"
