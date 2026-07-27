"""Post a one-line scan summary to a Google Chat space (or any webhook accepting `{text}`).

The push layer: the reports + issues/MRs are pull (you go look); this pings a channel so the
team knows a scan ran and what it found, with a link to the full report. Opt-in — no webhook,
no-op. `http` is injected so it's testable without network. The webhook URL is a secret,
read from the environment, never committed.
"""
from __future__ import annotations

from agent.lib.http_util import default_http


def chat_message(payload: dict, *, report_url: str | None = None,
                 run_url: str | None = None) -> str:
    """A compact Google-Chat-formatted summary of a scan (pure function of the payload)."""
    c = payload.get("counts", {})
    bo = c.get("byOwner", {})
    review = sum((bo.get(o) or {}).get("review", 0) for o in ("devops", "developer"))
    when = payload.get("generated", "")
    head = f"*Drift Detector* — scan {when}".rstrip()
    body = (f"🔴 {c.get('fixes', 0)} to fix · 🟠 {review} to review "
            f"across {c.get('reposAffected', 0)}/{c.get('reposScanned', 0)} repo(s)")
    if c.get("pastDue"):
        body += f" · ⏰ {c['pastDue']} already past-due"
    lines = [head, body]
    if report_url:
        lines.append(f"📄 <{report_url}|full report>"
                     + (f" · <{run_url}|scan run>" if run_url else ""))
    return "\n".join(lines)


def post(webhook: str, text: str, *, http=None) -> None:
    """POST the message to the webhook. Google Chat takes `{"text": ...}`."""
    (http or default_http)(webhook, method="POST", body={"text": text})
