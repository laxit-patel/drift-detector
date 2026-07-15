"""Google Chat delivery — build a cardsV2 message from an audit and POST it to an incoming webhook.

Deterministic, stdlib HTTP (injected). A failed post is reported (False), never raised, so a
scheduled run still completes and refreshes the local reports.
"""
from __future__ import annotations

from collections import Counter

from agent.lib.http_util import default_http


def build_chat_card(audit: dict, now: str, *, folder: str | None = None) -> dict:
    c = audit.get("counts", {})
    delta = audit.get("delta")
    findings = [f for f in audit.get("findings", []) if not f.get("suppressed")]
    dep = Counter(f["repo"] for f in findings if f.get("status") == "DEPRECATED")
    worst = "<br>".join(f"• <b>{repo}</b> — {n}" for repo, n in dep.most_common(5)) or "—"
    fixes = [f for f in findings if f.get("status") == "DEPRECATED" and f.get("recommendation")]
    top = "<br>".join(f"• {f['ref']} {f['version']} → {f['recommendation']}" for f in fixes[:5]) or "—"

    sections = []
    if delta is not None:
        newf, res = delta.get("new", []), delta.get("resolved", [])
        change = (f"🆕 <b>{len(newf)} new</b> · ✅ {len(res)} resolved · ⏳ {len(delta.get('persisting', []))} still open")
        section_new = "<br>".join(f"• {f['ref']} {f['version']} in {f['repo']}" for f in newf[:5]) or "—"
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
                "subtitle": f"🔴 {c.get('DEPRECATED', 0)} action-required · "
                            f"🟠 {c.get('REVIEW', 0)} review · {c.get('reposAffected', 0)} repos",
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
