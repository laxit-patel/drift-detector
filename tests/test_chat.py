# tests/test_chat.py
from agent.lib import chat

DOC = {"runDate": "2026-07-12", "counts": {"action": 2, "review": 5, "ok": 10, "watchlist": 3},
       "delta": {"new": ["a", "b"], "resolved": [], "ongoing": ["c"]},
       "findings": [{"severity": "ACTION", "repo": "c/a", "tech": "sp-api", "evidence": "BuyerInfo optional",
                     "changeType": "breaking", "versionInUse": "", "sourceUrl": "https://s"}]}

def test_summary_text_has_counts_urgent_and_link():
    t = chat.build_summary_text(DOC, "https://reports/x")
    assert "2026-07-12" in t and "2 " in t
    assert "BuyerInfo optional" in t
    assert "https://reports/x" in t

def test_failure_text():
    t = chat.build_failure_text("classify", "boom", "2026-07-12T07:00", "2026-07-05")
    assert "FAILED" in t and "classify" in t and "2026-07-05" in t

def test_post_chat_true_on_2xx():
    calls = []
    ok = chat.post_chat("https://hook", "hi", post=lambda url, json: (calls.append((url, json)) or 200))
    assert ok is True and calls[0][1] == {"text": "hi"}

def test_post_chat_false_on_error_never_raises():
    assert chat.post_chat("https://hook", "hi", post=lambda url, json: 500) is False
    def boom(url, json): raise ConnectionError("down")
    assert chat.post_chat("https://hook", "hi", post=boom) is False
