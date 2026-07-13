"""Pipeline orchestrator: candidates -> classify (rule + LLM) -> validate -> delta -> report -> deliver."""
from __future__ import annotations

from agent import candidates as candidates_mod
from agent import classify_rules, llm_classify, validator
from agent import delta as delta_mod
from agent import report as report_mod
from agent import actions as actions_mod


def run_pipeline(*, inventory, active, kb_root, prev_doc, config, now,
                 classify_fn, fetched_urls, review_horizon_months=6):
    repo_ids = {r["path_with_namespace"]: r["id"] for r in active.get("active", [])}
    cands = candidates_mod.build_candidates(inventory, kb_root, repo_ids=repo_ids)
    findings = [classify_rules.candidate_to_finding(c, now, review_horizon_months=review_horizon_months)
                for c in cands]
    findings, unresolved = llm_classify.reclassify(findings, now, classify_fn=classify_fn,
                                                   review_horizon_months=review_horizon_months)
    kept, rejected = validator.validate_findings(findings, set(fetched_urls or set()), now)
    delta, stamped = delta_mod.compute_delta(kept, prev_doc, now)

    coverage = dict(inventory.get("coverage", {}))
    gaps = [{"id": r["id"], "reason": r["reason"]} for r in rejected]
    gaps += [{"id": i, "reason": "LLM classify unresolved"} for i in unresolved]
    if gaps:
        coverage["classifyGaps"] = gaps

    doc = report_mod.assemble_findings_doc(stamped, delta, coverage, {}, now)
    return {"doc": doc, "report_md": report_mod.render_report(doc)}


def deliver(doc, report_md, config, *, commit, chat) -> list:
    registry = {
        "commit-report": lambda ctx: {"name": "commit-report", "ok": True, "commit": commit(ctx)},
        "chat-alert": lambda ctx: {"name": "chat-alert", "ok": bool(chat(ctx))},
    }
    ctx = {"doc": doc, "report_md": report_md, "config": config, "commit": commit, "chat": chat}
    return actions_mod.run_actions(ctx, registry=registry)
