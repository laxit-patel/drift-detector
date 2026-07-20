from agent.lib.classify_url import path_literal_of, version_of


def test_path_literal_of_extracts_versioned_path():
    assert path_literal_of("$resource_path = '/orders/2026-01-01/orders';") == "/orders/2026-01-01/orders"
    assert path_literal_of('$p = "/catalog/v0/items";') == "/catalog/v0/items"
    # no version segment -> not a candidate
    assert path_literal_of("$p = '/local/file/path';") == ""
    # a full URL is not a path literal (handled elsewhere)
    assert path_literal_of("$u = 'https://api.x.com/v1/foo';") == ""
    # version extraction on a bare path reuses version_of
    assert version_of("/orders/2026-01-01/orders", None) == "2026-01-01"
    assert version_of("/catalog/v0/items", None) == "v0"


def test_operation_of_reads_the_api_operation_name():
    from agent.lib.classify_url import operation_of
    # eBay Trading: the XML request root names the operation
    assert operation_of("$b = '<?xml version=\"1.0\"?><GetCategoryFeaturesRequest xmlns=\"urn:ebay\">'") \
        == "GetCategoryFeatures"
    assert operation_of('<AddDisputeRequest xmlns="urn:ebay:apis:eBLBaseComponents">') == "AddDispute"
    # the call-name argument form (becomes the X-EBAY-API-CALL-NAME header)
    assert operation_of('$session = $this->getEbaySession("GetCategories", $credentials);') == "GetCategories"
    assert operation_of("'X-EBAY-API-CALL-NAME: ' . $verb") == ""      # a variable is not a name
    # never guesses
    assert operation_of("$x = 'just a string';") == ""
    assert operation_of("<div>Request</div>") == ""                    # lowercase tag, not an operation
