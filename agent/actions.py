"""Action router: the single seam for side effects. Only config-named actions can fire (QUIET default)."""
from __future__ import annotations


def run_actions(ctx: dict, *, registry: dict) -> list:
    enabled = list(ctx["config"].delivery.actions)
    results = []
    for name in enabled:
        fn = registry.get(name)
        if fn is None:
            results.append({"name": name, "ok": False, "error": "no such action"})
            continue
        try:
            results.append(fn(ctx))
        except Exception as exc:
            results.append({"name": name, "ok": False, "error": str(exc)})
    return results


def commit_report_action(ctx: dict) -> dict:
    commit_id = ctx["commit"](ctx)     # injected callable does the GitLab commit
    return {"name": "commit-report", "ok": True, "commit": commit_id}


def chat_alert_action(ctx: dict) -> dict:
    ok = ctx["chat"](ctx)              # injected callable posts to Chat
    return {"name": "chat-alert", "ok": bool(ok)}
