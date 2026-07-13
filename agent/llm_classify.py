# agent/llm_classify.py
"""Claude classify stage: re-judge needsReview entries. LLM decides changeType + evidence only;
severity is re-derived deterministically. The subprocess call is behind an injected seam."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace

from agent.classify_rules import map_severity


def reclassify(findings: list, now: str, *, classify_fn, review_horizon_months: int = 6):
    todo = [f for f in findings if f.needsReview]
    if not todo:
        return list(findings), []
    items = [{"id": f.id, "techKey": f.techKey, "title": f.tech,
              "summary": f.evidence or "", "versionInUse": f.versionInUse} for f in todo]
    verdicts = {v["id"]: v for v in (classify_fn(items) or [])}

    out, unresolved = [], []
    for f in findings:
        if not f.needsReview:
            out.append(f)
            continue
        v = verdicts.get(f.id)
        if not v:
            unresolved.append(f.id)
            out.append(f)
            continue
        ctype = v.get("changeType", f.changeType)
        deadline = f.deadlineDate
        severity, _ = map_severity(ctype, deadline, now, review_horizon_months)
        out.append(replace(f, changeType=ctype, severity=severity, needsReview=False,
                           evidence=v.get("evidence", f.evidence),
                           businessRiskNote=v.get("businessRiskNote", "")))
    return out, unresolved


def claude_classify_fn(items: list, *, model="<pinned>", schema_path="agent/classify.schema.json"):  # pragma: no cover
    """Production seam: shell out to the claude CLI, env scrubbed of secrets. Not unit-tested live."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("GITLAB_READ_TOKEN", "REPORTS_TOKEN", "GCHAT_WEBHOOK_URL")}
    prompt = ("Classify each change entry's changeType (breaking|security|deprecation|behavioral|additive) "
              "for the used technology, quote verbatim evidence, and write a one-line business-risk note. "
              "Return JSON list of {id, changeType, evidence, businessRiskNote}. Items:\n" + json.dumps(items))
    proc = subprocess.run(
        ["claude", "--bare", "-p", prompt, "--output-format", "json",
         "--json-schema", f"@{schema_path}", "--permission-mode", "dontAsk",
         "--max-budget-usd", "15", "--no-session-persistence", "--model", model],
        capture_output=True, text=True, env=env, timeout=1800,
    )
    if proc.returncode != 0:
        return []
    return json.loads(proc.stdout or "[]")
