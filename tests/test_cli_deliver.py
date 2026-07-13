import json, textwrap
from agent import cli

class FakeClient:
    def __init__(self): self.commits = []
    def get_raw_file(self, pid, path, ref): return None      # all files new -> create
    def create_commit(self, pid, branch, message, actions):
        self.commits.append((pid, [a["file_path"] for a in actions])); return {"id": "c1"}

def _cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        kb: { root: kb/ }
        gitlab: { baseUrl: https://gl.test, tokenEnv: GITLAB_READ_TOKEN }
        delivery:
          reportsProject: tools/reports
          reportsBranch: main
          reportTokenEnv: REPORTS_TOKEN
          chatWebhookEnv: GCHAT_WEBHOOK_URL
          actions: [commit-report, chat-alert]
        feeds:
          - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }
    """))
    return str(p)

def test_deliver_commits_and_posts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REPORTS_TOKEN", "wtok")
    monkeypatch.setenv("GCHAT_WEBHOOK_URL", "https://hook")
    findings = tmp_path / "f.json"; findings.write_text(json.dumps(
        {"runDate": "2026-07-13", "counts": {"action": 1, "review": 0, "ok": 0, "watchlist": 0},
         "delta": {"new": [], "resolved": [], "ongoing": []}, "findings": []}))
    report = tmp_path / "r.md"; report.write_text("# report")
    fake = FakeClient(); posted = []
    rc = cli.main(["deliver", "--config", _cfg(tmp_path), "--findings", str(findings),
                   "--report", str(report), "--report-url", "https://reports/x", "--now", "2026-07-13"],
                  client=fake, post=lambda url, json: posted.append((url, json)) or 200)
    assert rc == 0
    assert fake.commits and "state/findings.json" in fake.commits[0][1]     # committed report+findings
    assert posted and posted[0][0] == "https://hook"                         # chat posted

def test_deliver_fails_loud_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("REPORTS_TOKEN", raising=False)
    findings = tmp_path / "f.json"; findings.write_text("{}")
    report = tmp_path / "r.md"; report.write_text("x")
    rc = cli.main(["deliver", "--config", _cfg(tmp_path), "--findings", str(findings),
                   "--report", str(report), "--report-url", "u", "--now", "2026-07-13"], client=None)
    assert rc == 2
