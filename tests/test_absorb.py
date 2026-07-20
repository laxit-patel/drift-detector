import pytest
import yaml

from agent import absorb


# --- check 1: a date nobody sourced is not admissible ---------------------------

def test_sunset_without_a_source_url_is_rejected():
    bad = [{"vendor": "eBay", "operation": "GetX", "retires": "2026-01-01"}]
    problems = absorb.check_sunsets(bad)
    assert any("no source URL" in p for p in problems)


def test_sunset_with_an_unparseable_date_is_rejected():
    bad = [{"vendor": "eBay", "operation": "GetX", "retires": "sometime in 2026",
            "source": "https://developer.ebay.com/x"}]
    assert any("YYYY-MM-DD" in p for p in absorb.check_sunsets(bad))


def test_a_properly_sourced_and_dated_sunset_passes():
    ok = [{"vendor": "eBay", "operation": "GetCategories", "retires": "2026-04-15",
           "source": "https://developer.ebay.com/develop/get-started/api-deprecation-status"}]
    assert absorb.check_sunsets(ok) == []


def test_sunset_without_a_scope_is_rejected():
    bad = [{"vendor": "eBay", "retires": "2026-04-15", "source": "https://x/y"}]
    assert any("needs a scope" in p for p in absorb.check_sunsets(bad))


# --- check 2/3: the idiom must deliver its claims and invent nothing -------------

_EP = lambda vendor, files: {"vendor": vendor, "files": files}


def _scanner(before, after):
    return lambda insts: after if insts else before


def test_idiom_that_does_not_attribute_its_claimed_call_sites_is_rejected():
    scan = _scanner(
        before={"endpoints": [], "residue": {"pathLiterals": [{"loc": "a.php:3"}]}},
        after={"endpoints": [], "residue": {"pathLiterals": [{"loc": "a.php:3"}]}})
    problems = absorb.verify_against_repo("/repo", [{"id": "x"}], ["a.php:3"], scan=scan)
    assert any("still unattributed" in p for p in problems)


def test_idiom_that_invents_a_new_vendor_is_rejected():
    """The cardinal rule: no false endpoints. Closing a gap by inventing calls
    elsewhere is worse than the gap."""
    scan = _scanner(
        before={"endpoints": [_EP("eBay", ["a.php:3"])], "residue": {"pathLiterals": []}},
        after={"endpoints": [_EP("eBay", ["a.php:3"]), _EP("Stripe", ["z.php:9"])],
               "residue": {"pathLiterals": []}})
    problems = absorb.verify_against_repo("/repo", [{"id": "x"}], ["a.php:3"], scan=scan)
    assert any("not previously present" in p and "Stripe" in p for p in problems)


def test_idiom_that_grows_residue_is_rejected():
    scan = _scanner(
        before={"endpoints": [_EP("eBay", ["a.php:3"])],
                "residue": {"pathLiterals": [{"loc": "b.php:1"}]}},
        after={"endpoints": [_EP("eBay", ["a.php:3"])],
               "residue": {"pathLiterals": [{"loc": "b.php:1"}, {"loc": "c.php:2"}]}})
    assert any("residue grew" in p for p in
               absorb.verify_against_repo("/repo", [{"id": "x"}], ["a.php:3"], scan=scan))


def test_a_good_idiom_passes_all_three_checks():
    scan = _scanner(
        before={"endpoints": [_EP("eBay", ["a.php:3"])],
                "residue": {"pathLiterals": [{"loc": "b.php:1"}]}},
        after={"endpoints": [_EP("eBay", ["a.php:3", "b.php:1"])],
               "residue": {"pathLiterals": []}})          # gap closed, nothing invented
    assert absorb.verify_against_repo("/repo", [{"id": "x"}], ["b.php:1"], scan=scan) == []


def test_malformed_idiom_instances_are_rejected_before_any_scan():
    assert absorb.check_idioms([{"id": "x", "family": "telepathy", "evidence": "a:1"}])
    assert absorb.check_idioms([{"id": "x", "family": "url-assembly"}])      # no evidence/base
    assert absorb.check_idioms([{"id": "ok", "family": "url-assembly",
                                 "base": "$A->x()", "evidence": "r f.php:1"}]) == []


def test_promote_appends_staged_specs(tmp_path):
    staged = tmp_path / "staged"; staged.mkdir()
    (staged / "idioms.yaml").write_text(yaml.safe_dump(
        [{"id": "new-one", "family": "url-assembly", "base": "$A->baseUrl",
          "evidence": "repo f.php:1"}]))
    idioms_f = tmp_path / "idioms.yaml"; idioms_f.write_text("- id: existing\n")
    sunsets_f = tmp_path / "sunsets.yaml"; sunsets_f.write_text("- vendor: x\n")
    added = absorb.promote(str(staged), idioms_path=str(idioms_f), sunsets_path=str(sunsets_f))
    assert added["idioms"] == 1 and added["sunsets"] == 0
    assert "new-one" in idioms_f.read_text() and "existing" in idioms_f.read_text()
