"""Google Chat delivery — build a cardsV2 message from an audit and POST it to an incoming webhook.

Deterministic, stdlib HTTP (injected). A failed post is reported (False), never raised, so a
scheduled run still completes and refreshes the local reports.
"""
from __future__ import annotations

from collections import Counter

from agent.lib.actions import build_actions
from agent.lib.http_util import default_http


def build_chat_card(audit: dict, now: str, *, folder: str | None = None) -> dict:
    c = audit.get("counts", {})
    delta = audit.get("delta")
    actions = audit.get("actions")
    if actions is None:
        actions = build_actions([f for f in audit.get("findings", []) if not f.get("suppressed")])
    urgent = [a for a in actions if a["status"] == "DEPRECATED"]

    dep = Counter(a["repo"] for a in urgent)
    worst = "<br>".join(f"• <b>{repo}</b> — {n}" for repo, n in dep.most_common(5)) or "—"
    top = "<br>".join(
        f"• {a['ref']} {a['current_version']} → {a['fix_version'] or a['recommendation']}"
        f" ({a['finding_count']})" for a in urgent[:5]) or "—"

    sections = []
    if delta is not None:
        new_actions = build_actions(delta.get("new", []))
        change = (f"🆕 <b>{len(new_actions)} new</b> · ✅ {len(delta.get('resolved', []))} resolved"
                  f" · ⏳ {len(delta.get('persisting', []))} still open")
        section_new = "<br>".join(f"• {a['ref']} in {a['repo']}" for a in new_actions[:5]) or "—"
        sections.append({"header": "Since last scan", "widgets": [
            {"textParagraph": {"text": change}},
            {"textParagraph": {"text": "<b>New:</b><br>" + section_new}}]})
    sections += [
        {"header": "Worst repos", "widgets": [{"textParagraph": {"text": worst}}]},
        {"header": "Top fixes", "widgets": [{"textParagraph": {"text": top}}]},
    ]
    if folder:
        sections.append({"widgets": [{"textParagraph": {"text": f"Full report in <code>{folder}/.drift-detector/AUDIT.md</code>"}}]})

    return {"cardsV2": [{
        "cardId": "drift-audit",
        "card": {
            "header": {
                "title": f"Drift Audit — {now}",
                "subtitle": f"🔴 {len(urgent)} fixes needed · "
                            f"🟠 {len(actions) - len(urgent)} review · "
                            f"{c.get('reposAffected', 0)} repos",
            },
            "sections": sections,
        },
    }]}


def post_chat(webhook_url: str, card: dict, *, http=default_http) -> bool:
    if not webhook_url:
        return False
    try:
        http(webhook_url, method="POST", body=card)
        return True
    except Exception:
        return False
