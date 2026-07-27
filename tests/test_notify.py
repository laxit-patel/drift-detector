"""Google Chat push — a compact summary + report link. Pure message + injected POST."""
from agent.lib import notify


_PAYLOAD = {"generated": "2026-07-27", "counts": {
    "fixes": 18, "reposAffected": 2, "reposScanned": 2, "pastDue": 18,
    "byOwner": {"devops": {"fixes": 0, "review": 0}, "developer": {"fixes": 18, "review": 2}}}}


def test_message_summarises_the_scan():
    m = notify.chat_message(_PAYLOAD, report_url="https://git.x/root/ops",
                            run_url="https://gh/run/1")
    assert "Drift Detector" in m and "2026-07-27" in m
    assert "18 to fix" in m and "2 to review" in m and "2/2 repo(s)" in m
    assert "18 already past-due" in m
    assert "<https://git.x/root/ops|full report>" in m         # Google Chat link syntax
    assert "<https://gh/run/1|scan run>" in m


def test_post_sends_text_to_the_webhook():
    sent = {}

    def http(url, *, method="GET", body=None, timeout=20):
        sent.update(url=url, method=method, body=body)
        return {}
    notify.post("https://chat.example/hook", "hello", http=http)
    assert sent["url"] == "https://chat.example/hook" and sent["method"] == "POST"
    assert sent["body"] == {"text": "hello"}


def test_cli_no_webhook_is_a_noop(tmp_path, monkeypatch, capsys):
    import json
    from agent import cli
    (tmp_path / "drift.json").write_text(json.dumps(_PAYLOAD))
    monkeypatch.delenv("DRIFT_CHAT_WEBHOOK", raising=False)
    rc = cli.main(["notify", "--state", str(tmp_path)])
    assert rc == 0 and "skipping" in capsys.readouterr().out


def test_cli_posts_when_webhook_given(tmp_path, monkeypatch, capsys):
    import json
    from agent import cli
    from agent.lib import notify as n
    (tmp_path / "drift.json").write_text(json.dumps(_PAYLOAD))
    posted = {}
    monkeypatch.setattr(n, "post", lambda w, t, **k: posted.update(webhook=w, text=t))
    rc = cli.main(["notify", "--state", str(tmp_path), "--webhook", "https://chat/hook",
                   "--report-url", "https://git.x/root/ops"])
    assert rc == 0 and posted["webhook"] == "https://chat/hook"
    assert "18 to fix" in posted["text"] and "sent" in capsys.readouterr().out
