"""Assemble a contract-drift findings doc + markdown report from scan output, reusing the
shared delta + report machinery. Persistence (carry_forward) keeps one-shot changes ONGOING."""
from __future__ import annotations

from agent.contract_scope import scope_changes
from agent.contract_findings import changes_to_findings, carry_forward
from agent.delta import compute_delta
from agent.report import assemble_findings_doc, render_report


def build_contract_report(changes: list, inventory: dict, active: dict, prev_doc: dict, now: str) -> dict:
    repo_ids = {r["path_with_namespace"]: r["id"] for r in active.get("active", [])}
    scoped = scope_changes(changes, inventory)
    new_findings = changes_to_findings(scoped, repo_ids, now)
    current = carry_forward(new_findings, prev_doc, now)        # persist one-shot changes
    delta, stamped = compute_delta(current, prev_doc, now)
    coverage = {"contractApisChanged": len({c.get("api", "") for c in changes})}
    watermarks = prev_doc.get("reportedWatermarks", {})
    doc = assemble_findings_doc(stamped, delta, coverage, watermarks, now)
    return {"doc": doc, "report_md": render_report(doc)}
