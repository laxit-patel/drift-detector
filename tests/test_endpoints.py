from agent.lib.vendors import Vendor
from agent.lib.endpoints import build_endpoints, scan_endpoints


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


def test_same_resource_groups_and_counts(tmp_path):
    """Two call-sites to the SAME resource group into one endpoint. (Same-vendor,
    same-version, DIFFERENT resources now split — a front-loaded version like Stripe's
    /v1/a vs /v1/b names distinct API families, the same granularity Amazon already has,
    and the granularity per-sub-API sunset scoping needs.)"""
    _write(tmp_path, "a.php", '"https://api.stripe.com/v1/charges";\n')
    _write(tmp_path, "b.php", '"https://api.stripe.com/v1/charges";\n')
    eps = build_endpoints([_url("a.php", 1), _url("b.php", 1)], str(tmp_path), [_STRIPE])
    assert len(eps) == 1 and eps[0]["file_count"] == 2 and set(eps[0]["files"]) == {"a.php:1", "b.php:1"}


def test_different_resources_under_one_version_split(tmp_path):
    """The Walmart-shaped case: /v3/insights/refunds and /v3/feeds are distinct APIs on
    separate lifecycles, so they must NOT collapse into one /v3 record."""
    _write(tmp_path, "a.php", '"https://api.stripe.com/v1/charges";\n')
    _write(tmp_path, "b.php", '"https://api.stripe.com/v1/refunds";\n')
    eps = build_endpoints([_url("a.php", 1), _url("b.php", 1)], str(tmp_path), [_STRIPE])
    assert len(eps) == 2
    assert {e["apiPath"] for e in eps} == {"/v1/charges", "/v1/refunds"}


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


def test_no_phantom_vendor_from_substring_collision(tmp_path):
    # 'ups.com' (UPS) must NOT match inside 'startups.com'; 'slack.com' not inside 'myslack.com'
    _write(tmp_path, "s.php", '"https://startups.com/x"; $h = "myslack.com";\n')
    vendors = [Vendor("UPS", "api:ups", ("ups.com",), r'/(v\d+)'),
               Vendor("Slack", "api:slack", ("slack.com",), r'/(v\d+)')]
    matches = [{"kind": "url", "path": "s.php", "line": 1},
               {"kind": "endpoint", "techKey": "api:ups", "path": "s.php", "line": 1},
               {"kind": "endpoint", "techKey": "api:slack", "path": "s.php", "line": 1}]
    eps = build_endpoints(matches, str(tmp_path), vendors)
    assert not any(e["vendor"] in ("UPS", "Slack") for e in eps)     # no phantom known integrations
    assert [e["vendor"] for e in eps] == ["Unknown"]                 # startups.com surfaces as Unknown


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


def test_path_literal_attributed_when_single_vendor_and_assembly_present(tmp_path):
    _write(tmp_path, "Configuration.php", "$host = 'https://sellingpartnerapi-na.amazon.com';\n")
    _write(tmp_path, "OrdersApi.php",
           "$resource_path = '/orders/2026-01-01/orders';\n"
           "$url = $this->config->getHost() . $resource_path;\n")
    matches = [
        {"kind": "url", "path": "Configuration.php", "line": 1},              # classifies SP-API host
        {"kind": "path-literal", "path": "OrdersApi.php", "line": 1},
        {"kind": "path-assembly", "path": "OrdersApi.php", "line": 2},
    ]
    out = scan_endpoints(matches, str(tmp_path), [_SP, _STRIPE])
    eps = out["endpoints"]
    # the SP-API host endpoint + the attributed path endpoint
    orders = [e for e in eps if e.get("version") == "2026-01-01"]
    assert orders and orders[0]["techKey"] == "api:amazon-sp-api"
    assert "OrdersApi.php:1" in orders[0]["files"]
    assert out["residue"]["pathLiterals"] == []                              # it was attributed, not residue


def test_path_literal_is_residue_when_two_vendors(tmp_path):
    _write(tmp_path, "cfg.php",
           "$a = 'https://sellingpartnerapi-na.amazon.com'; $b = 'https://api.stripe.com';\n")
    _write(tmp_path, "Api.php",
           "$resource_path = '/orders/2026-01-01/orders';\n"
           "$url = $this->config->getHost() . $resource_path;\n")
    matches = [
        {"kind": "url", "path": "cfg.php", "line": 1},                        # line has BOTH hosts -> 2 vendors
        {"kind": "path-literal", "path": "Api.php", "line": 1},
        {"kind": "path-assembly", "path": "Api.php", "line": 2},
    ]
    out = scan_endpoints(matches, str(tmp_path), [_SP, _STRIPE])
    assert not any(e.get("version") == "2026-01-01" for e in out["endpoints"])   # NOT attributed (ambiguous)
    assert out["residue"]["pathLiterals"] == [{"sample": "/orders/2026-01-01/orders", "loc": "Api.php:1"}]


def test_path_literal_is_residue_when_no_assembly_in_file(tmp_path):
    _write(tmp_path, "Configuration.php", "$host = 'https://sellingpartnerapi-na.amazon.com';\n")
    _write(tmp_path, "OrdersApi.php",
           "$resource_path = '/orders/2026-01-01/orders';\n"
           "$url = $this->config->getHost() . $resource_path;\n")
    _write(tmp_path, "Const.php", "$VERSIONED = '/feeds/2021-06-30/documents';\n")
    matches = [
        {"kind": "url", "path": "Configuration.php", "line": 1},
        {"kind": "path-literal", "path": "OrdersApi.php", "line": 1},
        {"kind": "path-assembly", "path": "OrdersApi.php", "line": 2},   # assembly here, NOT in Const.php
        {"kind": "path-literal", "path": "Const.php", "line": 1},        # no assembly in this file
    ]
    out = scan_endpoints(matches, str(tmp_path), [_SP])
    # OrdersApi.php literal attributed (its file has the assembly); Const.php literal is residue
    assert any(e.get("version") == "2026-01-01" for e in out["endpoints"])
    assert out["residue"]["pathLiterals"] == [{"sample": "/feeds/2021-06-30/documents", "loc": "Const.php:1"}]


def test_sinks_are_reported_as_residue(tmp_path):
    matches = [{"kind": "sink", "path": "Client.php", "line": 7}]
    out = scan_endpoints(matches, str(tmp_path), [_SP])
    assert out["residue"]["sinks"] == [{"kind": "egress", "loc": "Client.php:7"}]


def test_build_endpoints_still_returns_a_list(tmp_path):
    _write(tmp_path, "x.php", "$u = 'https://api.stripe.com/v1/charges';\n")
    matches = [{"kind": "url", "path": "x.php", "line": 1}]
    eps = build_endpoints(matches, str(tmp_path), [_STRIPE])
    assert isinstance(eps, list) and eps[0]["techKey"] == "api:stripe"


# --- the operation axis: one host, many operations, independent lifecycles ------

def _op_match(path, line, text):
    return {"kind": "operation-marker", "path": path, "line": line, "text": text}


def test_operation_marker_attributed_to_the_single_classified_vendor(tmp_path):
    _write(tmp_path, "cfg.php", "$h = 'https://api.ebay.com';\n")
    _write(tmp_path, "Cat.php", "$x = '<GetCategoryFeaturesRequest xmlns=\"urn:ebay\">';\n")
    _EBAY = Vendor("eBay", "api:ebay", ("ebay.com",), r"/(v[0-9]+)")
    matches = [{"kind": "url", "path": "cfg.php", "line": 1},
               _op_match("Cat.php", 1, "'<GetCategoryFeaturesRequest xmlns=\"urn:ebay\">'")]
    out = scan_endpoints(matches, str(tmp_path), [_EBAY])
    ops = {e["operation"]: e for e in out["endpoints"] if e.get("operation")}
    assert "GetCategoryFeatures" in ops
    assert ops["GetCategoryFeatures"]["techKey"] == "api:ebay"
    assert "Cat.php:1" in ops["GetCategoryFeatures"]["files"]


def test_operation_marker_not_attributed_when_two_vendors(tmp_path):
    _write(tmp_path, "cfg.php", "$a='https://api.ebay.com'; $b='https://api.stripe.com';\n")
    _write(tmp_path, "Cat.php", "$x = '<GetCategoryFeaturesRequest>';\n")
    _EBAY = Vendor("eBay", "api:ebay", ("ebay.com",), r"/(v[0-9]+)")
    matches = [{"kind": "url", "path": "cfg.php", "line": 1},
               _op_match("Cat.php", 1, "'<GetCategoryFeaturesRequest>'")]
    out = scan_endpoints(matches, str(tmp_path), [_EBAY, _STRIPE])
    assert not any(e.get("operation") for e in out["endpoints"])   # ambiguous -> never guess


def test_operation_read_from_multiline_literal_text(tmp_path):
    """The XML root often sits on line 2+ of the literal; the match's start line
    alone would miss it, so the full matched text is searched."""
    _write(tmp_path, "cfg.php", "$h = 'https://api.ebay.com';\n")
    _write(tmp_path, "Cancel.php", "$body = '<?xml version=\"1.0\"?>\n    <AddDisputeRequest xmlns=\"x\">';\n")
    _EBAY = Vendor("eBay", "api:ebay", ("ebay.com",), r"/(v[0-9]+)")
    matches = [{"kind": "url", "path": "cfg.php", "line": 1},
               _op_match("Cancel.php", 1, "'<?xml version=\"1.0\"?>\n    <AddDisputeRequest xmlns=\"x\">'")]
    out = scan_endpoints(matches, str(tmp_path), [_EBAY])
    assert any(e.get("operation") == "AddDispute" for e in out["endpoints"])


def test_operations_on_one_host_stay_separate_records(tmp_path):
    _write(tmp_path, "cfg.php", "$h = 'https://api.ebay.com';\n")
    _write(tmp_path, "A.php", "x\n")
    _EBAY = Vendor("eBay", "api:ebay", ("ebay.com",), r"/(v[0-9]+)")
    matches = [{"kind": "url", "path": "cfg.php", "line": 1},
               _op_match("A.php", 1, "'<GetCategoriesRequest>'"),
               _op_match("A.php", 1, "'<GetItemRequest>'")]
    out = scan_endpoints(matches, str(tmp_path), [_EBAY])
    ops = {e["operation"] for e in out["endpoints"] if e.get("operation")}
    assert ops == {"GetCategories", "GetItem"}      # same host+version, distinct lifecycles
