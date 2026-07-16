from agent.lib.chat import build_chat_card, post_chat


_AUDIT = {
    "generated": "2026-07-15",
    "counts": {"DEPRECATED": 106, "REVIEW": 113, "reposAffected": 32},
    "findings": [
        {"repo": "Wav2Lip", "status": "DEPRECATED", "ref": "python/torch", "version": "==1.1.0",
         "recommendation": "upgrade to >= 2.0"},
        {"repo": "Wav2Lip", "status": "DEPRECATED", "ref": "python/opencv-python", "version": "==4.1.0",
         "recommendation": "upgrade to >= 4.8"},
        {"repo": "ifolio", "status": "DEPRECATED", "ref": "php", "version": "^7.4",
         "recommendation": "upgrade to 8.5.8"},
    ],
}


def test_build_card_shape_and_counts():
    card = build_chat_card(_AUDIT, "2026-07-15", folder="/home/x/Projects")
    header = card["cardsV2"][0]["card"]["header"]
    assert "Drift Audit — 2026-07-15" == header["title"]
    # subtitle now counts ACTIONS (computed from findings), not the stale audit["counts"] fields:
    # 3 findings -> 3 actions, all DEPRECATED.
    assert "3 fixes needed" in header["subtitle"] and "0 review" in header["subtitle"]
    body = str(card)
    assert "Wav2Lip" in body and "torch" in body           # worst repo + a top fix present
    assert "/home/x/Projects/.drift-detector/AUDIT.md" in body


def test_post_chat_ok_and_failure_non_fatal():
    sent = {}

    def ok_http(url, *, method="GET", body=None, timeout=20):
        sent["url"] = url
        sent["body"] = body
        return {}

    assert post_chat("https://chat.googleapis.com/hook", {"cardsV2": []}, http=ok_http) is True
    assert sent["url"].endswith("/hook") and sent["body"] == {"cardsV2": []}

    def boom(*a, **k):
        raise ConnectionError("no network")

    assert post_chat("https://chat.googleapis.com/hook", {}, http=boom) is False   # never raises
    assert post_chat("", {}, http=ok_http) is False                                # empty webhook


def test_card_reports_actions_not_raw_findings():
    from agent.lib.actions import build_actions
    findings = [{"repo": "r", "ref": "python/torch", "kind": "cve", "version": "1.1.0",
                 "fixed": "2.8.0", "severity": "CRITICAL", "status": "DEPRECATED",
                 "first_seen": "2026-07-15", "detail": "d",
                 "recommendation": "upgrade to >= 2.8.0",
                 "source_url": "https://osv.dev/x", "tier": 1} for _ in range(30)]
    audit = {"findings": findings, "actions": build_actions(findings),
             "counts": {"reposAffected": 1}, "coverage": {}}
    card = build_chat_card(audit, "2026-07-15")
    sub = card["cardsV2"][0]["card"]["header"]["subtitle"]
    assert "1 fixes needed" in sub          # ONE action, not 30 findings
    body = str(card)
    assert "1.1.0 → 2.8.0" in body
    assert "(30)" in body                   # ...and it says how many advisories it clears
