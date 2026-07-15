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
    assert "106 action-required" in header["subtitle"] and "113 review" in header["subtitle"]
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
