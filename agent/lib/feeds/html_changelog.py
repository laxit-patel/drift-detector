"""html-changelog adapter: structure a changelog page via an injected LLM seam, only when it changed."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

import requests

from agent.lib.models import ChangeEntry, FeedSpec
from agent.lib.feeds import register


def _http_get(url: str) -> str:
    r = requests.get(url, timeout=30, headers={"User-Agent": "change-monitor/1.0"})
    r.raise_for_status()
    return r.text


def _llm_structure(text: str, spec: FeedSpec):  # pragma: no cover
    env = {k: v for k, v in os.environ.items()
           if k not in ("GITLAB_READ_TOKEN", "REPORTS_TOKEN", "GCHAT_WEBHOOK_URL")}
    prompt = (f"Extract change entries from this {spec.label} changelog page as JSON list of "
              "{date(YYYY-MM-DD), changeType, title, summary, evidence(verbatim quote)}. Page:\n" + text[:20000])
    proc = subprocess.run(["claude", "--bare", "-p", prompt, "--output-format", "json",
                           "--permission-mode", "dontAsk", "--max-budget-usd", "10", "--no-session-persistence"],
                          capture_output=True, text=True, env=env, timeout=900)
    return json.loads(proc.stdout or "[]") if proc.returncode == 0 else []


@register("html-changelog")
def fetch(spec: FeedSpec, *, fetch_text=_http_get, structure_fn=_llm_structure, prior_hash: str = ""):
    text = fetch_text(spec.url)
    page_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if page_hash == prior_hash:
        return [], page_hash
    entries = []
    for item in structure_fn(text, spec) or []:
        entries.append(ChangeEntry(
            techKey=spec.techKey, date=item.get("date", ""),
            changeType=item.get("changeType", "additive"),
            title=item.get("title", ""), summary=item.get("summary", ""),
            sourceUrl=spec.url, sourceTier=spec.tier,
            evidence=item.get("evidence", ""), feedAdapter="html-changelog",
        ))
    return entries, page_hash
