from agent.lib.vendors import Vendor
from agent.lib.endpoints import build_endpoints


def _write(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


_VENDORS = [Vendor("Amazon SP-API", "api:amazon-sp-api", ("sellingpartnerapi",),
                   r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})'),
            Vendor("Stripe", "api:stripe", ("api.stripe.com",), r'/(v\d+)')]


def test_aggregates_endpoints_with_version_and_filelines(tmp_path):
    _write(tmp_path, "a.php", 'x\n$u = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders";\n')
    _write(tmp_path, "b.php", '$v = "https://api.stripe.com/v1/charges";\n')
    matches = [
        {"kind": "endpoint", "techKey": "api:amazon-sp-api", "vendor": "Amazon SP-API",
         "path": "a.php", "line": 2},
        {"kind": "endpoint", "techKey": "api:stripe", "vendor": "Stripe", "path": "b.php", "line": 1},
    ]
    eps = build_endpoints(matches, str(tmp_path), _VENDORS)
    by_key = {(e["techKey"], e["version"]): e for e in eps}
    sp = by_key[("api:amazon-sp-api", "v0")]
    assert sp["domain"] == "sellingpartnerapi" and sp["files"] == ["a.php:2"] and sp["file_count"] == 1
    assert "sellingpartnerapi" in sp["example"]
    assert by_key[("api:stripe", "v1")]["domain"] == "api.stripe.com"


def test_same_vendor_version_groups_and_counts(tmp_path):
    _write(tmp_path, "a.php", '"https://api.stripe.com/v1/a";\n')
    _write(tmp_path, "b.php", '"https://api.stripe.com/v1/b";\n')
    matches = [{"kind": "endpoint", "techKey": "api:stripe", "vendor": "Stripe", "path": p, "line": 1}
               for p in ("a.php", "b.php")]
    eps = build_endpoints(matches, str(tmp_path),
                          [Vendor("Stripe", "api:stripe", ("api.stripe.com",), r'/(v\d+)')])
    assert len(eps) == 1 and eps[0]["file_count"] == 2 and set(eps[0]["files"]) == {"a.php:1", "b.php:1"}


def test_no_version_when_url_has_none(tmp_path):
    _write(tmp_path, "a.php", '"https://api.stripe.com/charges";\n')
    eps = build_endpoints([{"kind": "endpoint", "techKey": "api:stripe", "vendor": "Stripe",
                            "path": "a.php", "line": 1}], str(tmp_path),
                          [Vendor("Stripe", "api:stripe", ("api.stripe.com",), r'/(v\d+)')])
    assert eps[0]["version"] is None


def test_non_endpoint_matches_ignored(tmp_path):
    eps = build_endpoints([{"kind": "sdk", "techKey": "api:stripe", "vendor": "Stripe",
                            "path": "a.php", "line": 1}], str(tmp_path), _VENDORS)
    assert eps == []


def test_nested_domain_attributes_to_most_specific_vendor(tmp_path):
    _write(tmp_path, "m.php", '"https://maps.googleapis.com/maps/api/geocode/json";\n')
    vendors = [Vendor("Google APIs", "api:google", ("googleapis.com",), r'/(v\d+)'),
               Vendor("Google Maps", "api:google-maps", ("maps.googleapis.com",), r'/(v\d+)')]
    # both rules fire at the same location:
    matches = [{"kind":"endpoint","techKey":"api:google","vendor":"Google APIs","path":"m.php","line":1},
               {"kind":"endpoint","techKey":"api:google-maps","vendor":"Google Maps","path":"m.php","line":1}]
    eps = build_endpoints(matches, str(tmp_path), vendors)
    assert len(eps) == 1 and eps[0]["techKey"] == "api:google-maps"   # most-specific wins, no double-count


def test_two_unrelated_vendors_on_same_line_both_kept(tmp_path):
    _write(tmp_path, "m.php",
           '$u = ["https://api.stripe.com/v1/a","https://sellingpartnerapi.com/orders/v0/b"];\n')
    vendors = [Vendor("Stripe","api:stripe",("api.stripe.com",),r'/(v\d+)'),
               Vendor("Amazon SP-API","api:amazon-sp-api",("sellingpartnerapi",),
                      r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})')]
    matches=[{"kind":"endpoint","techKey":"api:stripe","vendor":"Stripe","path":"m.php","line":1},
             {"kind":"endpoint","techKey":"api:amazon-sp-api","vendor":"Amazon SP-API","path":"m.php","line":1}]
    eps = build_endpoints(matches, str(tmp_path), vendors)
    by = {e["techKey"]: e for e in eps}
    assert set(by) == {"api:stripe","api:amazon-sp-api"}   # unrelated domains on one line -> BOTH kept
    assert by["api:stripe"]["version"] == "v1"          # each version from its OWN url, not the neighbor's
    assert by["api:amazon-sp-api"]["version"] == "v0"
    assert "stripe" in by["api:stripe"]["example"] and "sellingpartner" in by["api:amazon-sp-api"]["example"]


def test_endpoint_files_are_repo_relative(tmp_path):
    # the engine returns ABSOLUTE paths when scanning an absolute dir; files[] must be repo-relative
    from agent.lib.vendors import Vendor
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "req.php").write_text('"https://api.stripe.com/v1/x";\n')
    abs_path = str(tmp_path / "lib" / "req.php")
    v = [Vendor("Stripe", "api:stripe", ("api.stripe.com",), r'/(v\d+)')]
    eps = build_endpoints([{"kind": "endpoint", "techKey": "api:stripe", "vendor": "Stripe",
                            "path": abs_path, "line": 1}], str(tmp_path), v)
    assert eps[0]["files"] == ["lib/req.php:1"]          # relative, not the absolute /tmp/... path
    assert eps[0]["version"] == "v1"                      # still reads the line + extracts version
