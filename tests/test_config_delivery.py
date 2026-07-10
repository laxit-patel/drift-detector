import textwrap
from agent.config import load_config

def test_delivery_parsed(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        kb: { root: kb/ }
        delivery:
          reportsProject: tools/reports
          reportsBranch: main
          reportTokenEnv: REPORTS_TOKEN
          chatWebhookEnv: GCHAT_WEBHOOK_URL
          healthPingEnv: HEALTHCHECK_URL
          actions: [commit-report, chat-alert]
          reviewHorizonMonths: 6
          urgentDeadlineDays: 90
        feeds:
          - { techKey: runtime:php, label: PHP, category: runtime, adapter: endoflife, url: php, tier: 1 }
    """))
    cfg = load_config(str(p))
    assert cfg.delivery.reports_project == "tools/reports"
    assert cfg.delivery.actions == ["commit-report", "chat-alert"]
    assert cfg.delivery.review_horizon_months == 6
