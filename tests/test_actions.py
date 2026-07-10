from agent import actions

class _Cfg:
    class delivery:
        actions = ["chat-alert"]     # commit-report NOT enabled

def test_only_configured_actions_run():
    ran = []
    reg = {"chat-alert": lambda ctx: ran.append("chat") or {"name": "chat-alert", "ok": True},
           "commit-report": lambda ctx: ran.append("commit") or {"name": "commit-report", "ok": True}}
    res = actions.run_actions({"config": _Cfg}, registry=reg)
    assert ran == ["chat"]                       # commit-report absent from config -> did not fire
    assert res == [{"name": "chat-alert", "ok": True}]

def test_action_exception_is_captured():
    def boom(ctx): raise RuntimeError("x")
    class C:
        class delivery: actions = ["chat-alert"]
    res = actions.run_actions({"config": C}, registry={"chat-alert": boom})
    assert res[0]["ok"] is False and "x" in res[0]["error"]
