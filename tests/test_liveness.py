from agent import liveness

def test_ping_true_on_2xx_never_raises():
    assert liveness.ping_healthcheck("https://hc", get=lambda u: 200) is True
    assert liveness.ping_healthcheck("https://hc", get=lambda u: 500) is False
    def boom(u): raise ConnectionError("x")
    assert liveness.ping_healthcheck("https://hc", get=boom) is False

def test_check_report_fresh():
    assert liveness.check_report_fresh("2026-07-12", "2026-07-13") is True       # 1 day old
    assert liveness.check_report_fresh("2026-07-01", "2026-07-13") is False      # 12 days old
    assert liveness.check_report_fresh("", "2026-07-13") is False                # never ran
