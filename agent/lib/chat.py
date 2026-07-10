"""Google Chat webhook client (plain-text v1). All HTTP injected for testability."""
from __future__ import annotations


def _default_post(url, json):
    import requests
    return requests.post(url, json=json, timeout=30).status_code


def build_summary_text(doc: dict, report_url: str, max_items: int = 10) -> str:
    c = doc["counts"]
    d = doc["delta"]
    action = [f for f in doc.get("findings", []) if f["severity"] == "ACTION"][:max_items]
    lines = [f"*Change Monitor — {doc['runDate']}*",
             f"🔴 {c['action']} ACTION · 🟡 {c['review']} REVIEW · 👀 {c['watchlist']} watch",
             f"🆕 {len(d.get('new',[]))} new · ✅ {len(d.get('resolved',[]))} resolved · ⏳ {len(d.get('ongoing',[]))} ongoing"]
    if action:
        lines.append("")
        lines.append("*Business-logic risk:*")
        for f in action:
            ver = f" {f['versionInUse']}" if f.get("versionInUse") else ""
            lines.append(f"• {f['repo']} — {f['tech']}{ver}: {f['evidence']} ({f['changeType']})")
    lines.append("")
    lines.append(f"<{report_url}|Full report>")
    return "\n".join(lines)


def build_failure_text(stage: str, error: str, now: str, last_good: str) -> str:
    return (f"⚠️ *Change Monitor scan FAILED* — {now}\n"
            f"Reason: {stage}: {error}\nNo report was generated. Last good report: {last_good}.")


def post_chat(webhook_url: str, text: str, *, post=_default_post) -> bool:
    try:
        return 200 <= int(post(webhook_url, {"text": text})) < 300
    except Exception:
        return False
