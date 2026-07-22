"""The owner split: which team fixes a finding/action. Pure function, exhaustive over kinds."""
from agent.lib.owners import owner, DEVOPS, DEVELOPER


def test_package_cve_is_devops():
    assert owner({"kind": "cve", "ref": "composer/aws/aws-sdk-php"}) == DEVOPS


def test_runtime_eol_is_devops():
    assert owner({"kind": "eol", "ref": "php", "refKind": "runtime"}) == DEVOPS


def test_framework_eol_is_developer():
    # a Laravel/Django major is application-code migration, not a platform bump
    assert owner({"kind": "eol", "ref": "laravel", "refKind": "framework"}) == DEVELOPER


def test_vendor_sunset_is_developer():
    assert owner({"kind": "sunset", "ref": "eBay"}) == DEVELOPER


def test_eol_without_refkind_defaults_to_developer_not_devops():
    # defensive: a missing refKind must never silently route a runtime to DevOps
    assert owner({"kind": "eol", "ref": "php"}) == DEVELOPER


def test_owner_is_always_one_of_the_two_streams():
    for rec in ({"kind": "cve"}, {"kind": "eol", "refKind": "runtime"},
                {"kind": "eol", "refKind": "framework"}, {"kind": "sunset"}, {"kind": None}):
        assert owner(rec) in (DEVOPS, DEVELOPER)
