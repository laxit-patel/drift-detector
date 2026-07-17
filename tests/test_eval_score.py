"""The pure scoring core: (corpus entries, inventory doc, audit doc) -> scorecard.
No git/network/scanner — hand-built dicts only."""
from agent.eval.score import score


def _entry(repo="o/ebay-sdk-php", vendor="eBay", sdk_keywords=None, sunset_host=None,
           known_gaps=None, holdout=False, category="ebay"):
    exp = {"vendor": vendor}
    if sdk_keywords is not None:
        exp["sdk_keywords"] = sdk_keywords
    if sunset_host:
        exp["sunset_host"] = sunset_host
    return {"repo": repo, "category": category, "expect": exp,
            "known_gaps": known_gaps or [], "holdout": holdout}


def _repo(name, endpoints=(), sdks=()):
    return {"path": name, "endpoints": list(endpoints), "sdks": list(sdks)}


def _inv(repos, errored=()):
    return {"repos": list(repos),
            "coverage": {"reposErrored": [{"repo": r, "reason": "boom"} for r in errored]}}


def _ep(vendor="eBay", classified=True, version="v1", domain="api.ebay.com"):
    return {"vendor": vendor, "classified": classified, "version": version, "domain": domain}


def _audit(findings=()):
    return {"findings": list(findings)}


def test_recall_via_classified_endpoint():
    sc = score([_entry()], _inv([_repo("ebay-sdk-php", endpoints=[_ep()])]), _audit())
    r = sc["repos"][0]
    assert r["detected"] is True and r["via"] == "endpoint"
    assert sc["gate"]["passed"] is True


def test_recall_via_sdk_keyword():
    inv = _inv([_repo("ebay-sdk-php", sdks=[{"eco": "composer", "pkg": "dts/ebay-sdk-php"}])])
    sc = score([_entry(sdk_keywords=["ebay"])], inv, _audit())
    r = sc["repos"][0]
    assert r["detected"] is True and r["via"] == "sdk"


def test_sdk_keyword_defaults_to_category():
    inv = _inv([_repo("ebay-sdk-php", sdks=[{"eco": "composer", "pkg": "acme/ebay-things"}])])
    sc = score([_entry(sdk_keywords=None)], inv, _audit())    # no sdk_keywords -> [category]="ebay"
    assert sc["repos"][0]["detected"] is True and sc["repos"][0]["via"] == "sdk"


def test_endpoint_takes_precedence_when_both_fire():
    inv = _inv([_repo("ebay-sdk-php", endpoints=[_ep()],
                      sdks=[{"eco": "composer", "pkg": "dts/ebay-sdk-php"}])])
    sc = score([_entry(sdk_keywords=["ebay"])], inv, _audit())
    assert sc["repos"][0]["via"] == "endpoint"


def test_miss_when_neither_and_gate_fails_unattributed():
    inv = _inv([_repo("ebay-sdk-php", endpoints=[_ep(vendor="Unknown", classified=False)])])
    sc = score([_entry()], inv, _audit())
    r = sc["repos"][0]
    assert r["detected"] is False and r["via"] is None
    assert r["miss_mode"] == "unattributed"
    assert sc["gate"]["passed"] is False and "ebay-sdk-php" in str(sc["gate"]["failures"])


def test_gate_passes_when_miss_is_a_declared_known_gap():
    inv = _inv([_repo("ebay-sdk-php")])                       # nothing detected
    sc = score([_entry(known_gaps=["sdk-only-no-callsite"])], inv, _audit())
    r = sc["repos"][0]
    assert r["detected"] is False and r["miss_mode"] == "sdk-only-no-callsite"
    assert sc["gate"]["passed"] is True
    assert sc["summary"]["recall"]["known_miss"] == 1


def test_noise_counts_only_unknown_endpoints():
    inv = _inv([_repo("r", endpoints=[_ep(), _ep(vendor="Unknown", classified=False),
                                      _ep(vendor="Unknown", classified=False)])])
    sc = score([_entry(repo="o/r")], inv, _audit())
    assert sc["repos"][0]["noise"] == 2
    assert sc["summary"]["noise"]["max"] == 2


def test_version_rate_over_classified_and_zero_is_none():
    inv = _inv([_repo("r", endpoints=[_ep(version="v1"), _ep(version=None)])])
    sc = score([_entry(repo="o/r")], inv, _audit())
    assert sc["repos"][0]["version_rate"] == 0.5
    inv2 = _inv([_repo("r2", endpoints=[_ep(vendor="Unknown", classified=False)])])
    sc2 = score([_entry(repo="o/r2")], inv2, _audit())
    assert sc2["repos"][0]["version_rate"] is None            # no classified endpoints, no div-by-zero


def test_sunset_hit_matches_host():
    a = _audit([{"kind": "sunset", "domain": "svcs.ebay.com"}])
    sc = score([_entry(sunset_host="svcs.ebay.com")],
               _inv([_repo("ebay-sdk-php", endpoints=[_ep()])]), a)
    r = sc["repos"][0]
    assert r["sunset_expected"] is True and r["sunset_hit"] is True
    assert sc["summary"]["sunset_match"] == {"expected": 1, "hit": 1}


def test_sunset_miss_on_different_host_and_absent_when_unset():
    a = _audit([{"kind": "sunset", "domain": "open.api.ebay.com"}])
    sc = score([_entry(sunset_host="svcs.ebay.com")],
               _inv([_repo("ebay-sdk-php", endpoints=[_ep()])]), a)
    assert sc["repos"][0]["sunset_hit"] is False
    sc2 = score([_entry()], _inv([_repo("ebay-sdk-php", endpoints=[_ep()])]), _audit())
    assert sc2["repos"][0]["sunset_expected"] is False and sc2["repos"][0]["sunset_hit"] is None


def test_errored_repo_reported_not_crashing():
    sc = score([_entry(repo="o/broken")], _inv([], errored=["broken"]), _audit())
    r = sc["repos"][0]
    assert r["errored"] is True and r["detected"] is False
    assert sc["summary"]["errored"] == 1


def test_deterministic():
    entries = [_entry(repo="o/a"), _entry(repo="o/b")]
    inv = _inv([_repo("a", endpoints=[_ep()]), _repo("b", endpoints=[_ep()])])
    assert score(entries, inv, _audit()) == score(entries, inv, _audit())
