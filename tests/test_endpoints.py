from agent.lib.vendors import Vendor
from agent.lib.endpoints import build_endpoints


def _write(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


_SP = Vendor("Amazon SP-API", "api:amazon-sp-api", ("sellingpartnerapi",),
             r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})')
_STRIPE = Vendor("Stripe", "api:stripe", ("stripe.com",), r'/(v\d+)')
_VENDORS = [_SP, _STRIPE]


def _url(path, line):
    return {"kind": "url", "path": path, "line": line}


def test_aggregates_endpoints_with_version_and_filelines(tmp_path):
    _write(tmp_path, "a.php", 'x\n$u = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders";\n')
    _write(tmp_path, "b.php", '$v = "https://api.stripe.com/v1/charges";\n')
    eps = build_endpoints([_url("a.php", 2), _url("b.php", 1)], str(tmp_path), _VENDORS)
    by = {(e["techKey"], e["version"]): e for e in eps}
    sp = by[("api:amazon-sp-api", "v0")]
    assert sp["domain"] == "sellingpartnerapi-na.amazon.com" and sp["files"] == ["a.php:2"]
    assert sp["vendor"] == "Amazon SP-API" and "sellingpartnerapi" in sp["example"]
    assert by[("api:stripe", "v1")]["domain"] == "api.stripe.com"


def test_registrable_suffix_catches_subdomain_variants(tmp_path):
    # the whole point of #1: ebay.com must catch api.sandbox.ebay.com (the old allowlist missed it)
    _write(tmp_path, "c.php", '"https://api.sandbox.ebay.com/ws/api.dll";\n')
    ebay = Vendor("eBay", "api:ebay", ("ebay.com",), r'/(v\d+)')
    eps = build_endpoints([_url("c.php", 1)], str(tmp_path), [ebay])
    assert eps[0]["vendor"] == "eBay" and eps[0]["domain"] == "api.sandbox.ebay.com"


def test_uncatalogued_url_is_unknown_external(tmp_path):
    _write(tmp_path, "d.php", '"https://api.feedonomics.com/v2/import";\n')
    eps = build_endpoints([_url("d.php", 1)], str(tmp_path), _VENDORS)
    assert len(eps) == 1 and eps[0]["vendor"] == "Unknown" and eps[0]["classified"] is False
    assert eps[0]["domain"] == "api.feedonomics.com" and eps[0]["version"] == "v2"


def test_boilerplate_hosts_ignored(tmp_path):
    _write(tmp_path, "e.php", '"http://www.w3.org/2001/XMLSchema"; "https://fonts.googleapis.com/css";\n')
    assert build_endpoints([_url("e.php", 1)], str(tmp_path), _VENDORS) == []


def test_known_vendor_kept_even_if_its_registrable_is_on_ignore_list(tmp_path):
    # facebook.com is ignored (marketing links) but graph.facebook.com is a real known API
    _write(tmp_path, "g.php", '"https://graph.facebook.com/v19.0/me"; "https://www.facebook.com/share";\n')
    meta = Vendor("Meta Graph API", "api:meta-graph", ("graph.facebook.com",), r'/(v[0-9.]+)')
    eps = build_endpoints([_url("g.php", 1)], str(tmp_path), [meta])
    assert len(eps) == 1 and eps[0]["vendor"] == "Meta Graph API"    # graph.* kept, www.* ignored


def test_same_vendor_version_groups_and_counts(tmp_path):
    _write(tmp_path, "a.php", '"https://api.stripe.com/v1/a";\n')
    _write(tmp_path, "b.php", '"https://api.stripe.com/v1/b";\n')
    eps = build_endpoints([_url("a.php", 1), _url("b.php", 1)], str(tmp_path), [_STRIPE])
    assert len(eps) == 1 and eps[0]["file_count"] == 2 and set(eps[0]["files"]) == {"a.php:1", "b.php:1"}


def test_no_version_when_url_has_none(tmp_path):
    _write(tmp_path, "a.php", '"https://api.stripe.com/charges";\n')
    assert build_endpoints([_url("a.php", 1)], str(tmp_path), [_STRIPE])[0]["version"] is None


def test_non_url_matches_ignored(tmp_path):
    assert build_endpoints([{"kind": "sdk", "path": "a.php", "line": 1}], str(tmp_path), _VENDORS) == []


def test_host_only_known_reference_caught_via_endpoint_rule(tmp_path):
    # a config with NO url scheme — 'api.mailgun.net' as a bare host literal (the old allowlist
    # caught this; the broad URL rule alone would miss it, so the per-vendor rule recovers it)
    _write(tmp_path, "services.php", "'mailgun' => ['domain' => 'api.mailgun.net'],\n")
    mg = Vendor("Mailgun", "api:mailgun", ("mailgun.net",), r'/(v\d+)')
    eps = build_endpoints([{"kind": "endpoint", "techKey": "api:mailgun", "path": "services.php", "line": 1}],
                          str(tmp_path), [mg])
    assert len(eps) == 1 and eps[0]["vendor"] == "Mailgun" and eps[0]["files"] == ["services.php:1"]


def test_url_and_vendor_rule_on_same_line_deduped(tmp_path):
    # a real Mailgun URL fires BOTH the url-literal and the mailgun rule at the same spot -> one record
    _write(tmp_path, "m.php", '"https://api.mailgun.net/v3/send";\n')
    mg = Vendor("Mailgun", "api:mailgun", ("mailgun.net",), r'/(v\d+)')
    matches = [{"kind": "url", "path": "m.php", "line": 1},
               {"kind": "endpoint", "techKey": "api:mailgun", "path": "m.php", "line": 1}]
    eps = build_endpoints(matches, str(tmp_path), [mg])
    assert len(eps) == 1 and eps[0]["file_count"] == 1     # not double-counted


def test_most_specific_domain_wins(tmp_path):
    _write(tmp_path, "m.php", '"https://maps.googleapis.com/maps/api/geocode/json";\n')
    vendors = [Vendor("Google APIs", "api:google", ("googleapis.com",), r'/(v\d+)'),
               Vendor("Google Maps", "api:google-maps", ("maps.googleapis.com",), r'/(v\d+)')]
    eps = build_endpoints([_url("m.php", 1)], str(tmp_path), vendors)
    assert len(eps) == 1 and eps[0]["techKey"] == "api:google-maps"     # longest matching domain wins


def test_two_urls_on_one_line_both_extracted(tmp_path):
    _write(tmp_path, "m.php",
           '$u = ["https://api.stripe.com/v1/a","https://sellingpartnerapi-na.amazon.com/orders/v0/b"];\n')
    eps = build_endpoints([_url("m.php", 1)], str(tmp_path), _VENDORS)   # one line -> both URLs classified
    by = {e["techKey"]: e for e in eps}
    assert set(by) == {"api:stripe", "api:amazon-sp-api"}
    assert by["api:stripe"]["version"] == "v1" and by["api:amazon-sp-api"]["version"] == "v0"


def test_endpoint_files_are_repo_relative(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "req.php").write_text('"https://api.stripe.com/v1/x";\n')
    eps = build_endpoints([_url(str(tmp_path / "lib" / "req.php"), 1)], str(tmp_path), [_STRIPE])
    assert eps[0]["files"] == ["lib/req.php:1"] and eps[0]["version"] == "v1"
