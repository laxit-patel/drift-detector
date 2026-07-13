from agent.contract_findings import changes_to_findings, carry_forward


def _scoped(verdict="BREAKING", used=True, repo="repoA", opKey="GET /orders",
            detail="response field removed: payload.AmazonOrderId", marketplace="sp-api",
            api="orders-api-model/ordersV0"):
    return {"marketplace": marketplace, "api": api, "opKey": opKey, "kind": "response_field",
            "verdict": verdict, "before": "payload.AmazonOrderId", "after": "",
            "detail": detail, "techKey": "api:amazon-sp-api", "repo": repo, "used": used}


def test_breaking_used_is_action():
    f = changes_to_findings([_scoped()], {"repoA": 7}, "2026-07-13")[0]
    assert f.severity == "ACTION" and f.watchlist is False
    assert f.findingType == "contract-drift" and f.techKey == "api:amazon-sp-api"
    assert f.projectId == 7 and f.changeType == "breaking" and "AmazonOrderId" in f.evidence
    assert f.sourceUrl.endswith("models/orders-api-model/ordersV0.json")


def test_ambiguous_used_is_review_and_additive_is_ok():
    review = changes_to_findings([_scoped(verdict="AMBIGUOUS")], {"repoA": 1}, "2026-07-13")[0]
    additive = changes_to_findings([_scoped(verdict="ADDITIVE")], {"repoA": 1}, "2026-07-13")[0]
    assert review.severity == "REVIEW" and additive.severity == "OK"


def test_breaking_unused_is_watchlist():
    f = changes_to_findings([_scoped(used=False, repo="")], {}, "2026-07-13")[0]
    assert f.watchlist is True and f.severity == "OK"


def test_same_change_two_repos_get_distinct_ids():
    rows = [_scoped(repo="repoA"), _scoped(repo="repoB")]
    fs = changes_to_findings(rows, {"repoA": 1, "repoB": 2}, "2026-07-13")
    assert fs[0].id != fs[1].id                                  # projectId distinguishes them


def test_carry_forward_persists_prior_contract_findings():
    prev_finding = changes_to_findings([_scoped()], {"repoA": 7}, "2026-07-01")[0]
    prev_doc = {"findings": [prev_finding.to_dict()], "watchlist": []}
    # This run detected nothing new (one-shot change already fired last week)
    carried = carry_forward([], prev_doc, "2026-07-13")
    assert len(carried) == 1 and carried[0].id == prev_finding.id  # persisted, not dropped


def test_carry_forward_ignores_non_contract_findings_and_dedups():
    prev_finding = changes_to_findings([_scoped()], {"repoA": 7}, "2026-07-01")[0]
    prev_doc = {"findings": [prev_finding.to_dict(),
                             {"id": "x", "findingType": "lifecycle", "severity": "ACTION",
                              "repo": "r", "techKey": "runtime:php", "tech": "php",
                              "projectId": 0, "category": "runtime", "changeType": "deprecation",
                              "sourceUrl": "", "sourceTier": 1}],
                "watchlist": []}
    fresh = changes_to_findings([_scoped(detail="response field removed: payload.OrderStatus")],
                                {"repoA": 7}, "2026-07-13")
    carried = carry_forward(fresh, prev_doc, "2026-07-13")
    ids = {f.id for f in carried}
    assert prev_finding.id in ids and fresh[0].id in ids         # both contract findings kept
    assert all(f.findingType == "contract-drift" for f in carried)  # lifecycle finding NOT carried
