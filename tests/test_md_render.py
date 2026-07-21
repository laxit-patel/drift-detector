"""The Markdown view is agent-readable AND pipe-safe — the two properties that make it
trustworthy where HTML was not."""
from agent.lib import md_render as md


def _payload(**over):
    base = {
        "generated": "2026-07-21",
        "counts": {"fixes": 6, "sunsets": 8, "eol": 0, "critical": 0, "unaudited": 0,
                   "reposAffected": 1, "reposScanned": 1},
        "actions": [
            {"kind": "sunset", "ref": "Amazon SP-API", "unit": "/fba/inbound/v0",
             "status": "DEPRECATED", "date": "2025-01-21", "finding_count": 6,
             "files": [{"loc": "src/Api/FbaShipment.php:25"}]},
            {"kind": "sunset", "ref": "Amazon SP-API", "unit": "/orders/v0",
             "status": "REVIEW", "date": "2027-03-27", "finding_count": 6,
             "files": [{"loc": "src/Api/OrdersApi.php:38"}]},
        ],
        "coverageGrades": [{"repo": "amazonspapi", "grade": "HIGH", "attributed": 46,
                            "unattributedPaths": 0, "unresolvedSinks": 7}],
        "catalog": [{"vendor": "Amazon SP-API", "verdict": "CURRENT", "callSites": 272,
                     "catalogEntries": 8, "checked": "2026-07-20"}],
        "coverageNotes": ["Vendor API sunsets: curated catalog."],
    }
    base.update(over)
    return base


def test_headline_names_the_past_due_alarm():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "1 of 2 retiring API surface(s) are already past" in out


def test_operation_appears_in_a_row_not_a_bare_vendor():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "Amazon SP-API /fba/inbound/v0" in out
    assert "Amazon SP-API /orders/v0" in out


def test_every_finding_has_its_own_date_column():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "2025-01-21" in out and "2027-03-27" in out


def test_pipe_in_a_cell_is_escaped_not_column_breaking():
    """The bug class: an unescaped | silently truncates a GitHub table row. A version
    constraint like `~5.6.0|7.0.2` must not add phantom columns."""
    p = _payload(actions=[{"kind": "cve", "ref": "composer/acme/x", "unit": None,
                           "status": "DEPRECATED", "date": None, "fix_version": "~5.6.0|7.0.2",
                           "finding_count": 1, "files": [{"loc": "composer.json:1"}]}],
                 counts={"fixes": 1, "sunsets": 0, "eol": 0, "critical": 0, "unaudited": 0,
                         "reposAffected": 1, "reposScanned": 1})
    out = md.render_markdown(p, "2026-07-21")
    # the raw pipe must be backslash-escaped so the cell stays one column
    assert "~5.6.0\\|7.0.2" in out
    assert "~5.6.0|7.0.2" not in out.replace("\\|", "")   # no unescaped pipe survived


def test_coverage_verdicts_render():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert "CURRENT" in out and "HIGH" in out
    assert "have we checked the retirement list?" in out


def test_clean_repo_says_no_action_required_not_a_false_alarm():
    p = _payload(actions=[], counts={"fixes": 0, "sunsets": 0, "eol": 0, "critical": 0,
                                     "unaudited": 0, "reposAffected": 0, "reposScanned": 2})
    out = md.render_markdown(p, "2026-07-21")
    assert "No action-required findings across 2 repo(s)" in out


def test_deterministic():
    assert md.render_markdown(_payload(), "2026-07-21") == md.render_markdown(_payload(), "2026-07-21")


def test_front_matter_self_identifies_the_source():
    out = md.render_markdown(_payload(), "2026-07-21")
    assert out.startswith("---\n")
    assert "schemaVersion: drift/v1" in out
    assert "generatedFrom: drift.json" in out


# ------------------------------------------------- the parity check (the trust mechanism)
def test_parity_holds_on_the_real_render():
    from agent.lib.verify import check_md_matches_payload
    out = md.render_markdown(_payload(), "2026-07-21")
    check_md_matches_payload(out, _payload())          # must not raise


def test_parity_catches_a_summary_number_that_drifts():
    """If the Markdown's summary disagrees with the payload counts, it must fail —
    this is bug #1's class (a tile/number contradicting the data) in the MD."""
    import pytest
    from agent.lib.verify import check_md_matches_payload, Violation
    out = md.render_markdown(_payload(), "2026-07-21")
    tampered = out.replace("| Vendor API sunsets | 8 |", "| Vendor API sunsets | 1 |")
    with pytest.raises(Violation) as e:
        check_md_matches_payload(tampered, _payload())
    assert e.value.check == "md-summary-parity"


def test_parity_catches_an_unescaped_pipe_truncation():
    """A raw | injected into a cell adds a phantom column — the exact GitHub
    silent-truncation bug — and must fail column integrity."""
    import pytest
    from agent.lib.verify import check_md_matches_payload, Violation
    out = md.render_markdown(_payload(), "2026-07-21")
    # forge a broken row: an unescaped pipe inside the first findings cell
    broken = out.replace("| Amazon SP-API \\| /fba", "| Amazon SP-API | /fba", 1) \
        if "\\|" in out else out.replace("/fba/inbound/v0", "/fba|inbound/v0", 1)
    with pytest.raises(Violation):
        check_md_matches_payload(broken, _payload())


def test_parity_catches_two_identical_findings_rows():
    import pytest
    from agent.lib.verify import check_md_matches_payload, Violation
    # two sunset actions with the SAME label + date + everything = indistinguishable rows
    dup = {"kind": "sunset", "ref": "eBay", "unit": None, "status": "DEPRECATED",
           "date": "2022-04-30", "finding_count": 1, "files": [{"loc": "a.php:1"}]}
    p = _payload(actions=[dict(dup), dict(dup)],
                 counts={"fixes": 2, "sunsets": 2, "eol": 0, "critical": 0, "unaudited": 0,
                         "reposAffected": 1, "reposScanned": 1})
    out = md.render_markdown(p, "2026-07-21")
    with pytest.raises(Violation) as e:
        check_md_matches_payload(out, p)
    assert e.value.check == "md-row-identity"
