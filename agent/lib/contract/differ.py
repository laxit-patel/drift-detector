"""Deterministic semantic diff of two NormalizedSpecs into classified ContractChanges.
No LLM: the verdict (BREAKING/ADDITIVE/AMBIGUOUS) is decided by structural rules alone."""
from __future__ import annotations

from agent.lib.contract.models import NormalizedSpec, Operation, ContractChange


def diff(prev: NormalizedSpec, curr: NormalizedSpec) -> list:
    changes: list = []
    prev_ops, curr_ops = prev.operations, curr.operations
    for key in prev_ops.keys() - curr_ops.keys():
        changes.append(ContractChange(opKey=key, kind="operation", verdict="BREAKING",
                                      before=key, after="", detail=f"operation removed: {key}"))
    for key in curr_ops.keys() - prev_ops.keys():
        changes.append(ContractChange(opKey=key, kind="operation", verdict="ADDITIVE",
                                      before="", after=key, detail=f"operation added: {key}"))
    for key in prev_ops.keys() & curr_ops.keys():
        changes += _diff_op(key, prev_ops[key], curr_ops[key])
    return changes


def _diff_op(key: str, pop: Operation, cop: Operation) -> list:
    ch: list = []

    # --- response fields ---
    pf = {f.path: f for f in pop.responseFields}
    cf = {f.path: f for f in cop.responseFields}
    for path in pf.keys() - cf.keys():
        ch.append(ContractChange(key, "response_field", "BREAKING",
                                 before=path, after="", detail=f"response field removed: {path}"))
    for path in cf.keys() - pf.keys():
        ch.append(ContractChange(key, "response_field", "ADDITIVE",
                                 before="", after=path, detail=f"response field added: {path}"))
    for path in pf.keys() & cf.keys():
        a, b = pf[path], cf[path]
        if a.type != b.type:
            ch.append(ContractChange(key, "response_field", "AMBIGUOUS",
                                     before=f"{path}:{a.type}", after=f"{path}:{b.type}",
                                     detail=f"response field type changed: {path}"))
        elif not a.nullable and b.nullable:
            ch.append(ContractChange(key, "response_field", "AMBIGUOUS",
                                     before=f"{path}:non-null", after=f"{path}:nullable",
                                     detail=f"response field became nullable: {path}"))

    # --- request params ---
    pp = {p.name: p for p in pop.requestParams}
    cp = {p.name: p for p in cop.requestParams}
    for name in pp.keys() - cp.keys():
        ch.append(ContractChange(key, "request_param", "BREAKING",
                                 before=name, after="", detail=f"request param removed: {name}"))
    for name in cp.keys() - pp.keys():
        required = cp[name].required
        ch.append(ContractChange(key, "request_param", "BREAKING" if required else "ADDITIVE",
                                 before="", after=name,
                                 detail=f"request param added ({'required' if required else 'optional'}): {name}"))
    for name in pp.keys() & cp.keys():
        a, b = pp[name], cp[name]
        if not a.required and b.required:
            ch.append(ContractChange(key, "request_param", "BREAKING",
                                     before=f"{name}:optional", after=f"{name}:required",
                                     detail=f"request param became required: {name}"))
        elif a.required and not b.required:
            ch.append(ContractChange(key, "request_param", "ADDITIVE",
                                     before=f"{name}:required", after=f"{name}:optional",
                                     detail=f"request param became optional: {name}"))
        elif a.type != b.type:
            ch.append(ContractChange(key, "request_param", "AMBIGUOUS",
                                     before=f"{name}:{a.type}", after=f"{name}:{b.type}",
                                     detail=f"request param type changed: {name}"))

    # --- enums ---
    for path in set(pop.enums) & set(cop.enums):     # only fields enum-typed on BOTH sides;
                                                     # enum-typed field add/remove is the response-field loop's job
        pv, cv = set(pop.enums.get(path, [])), set(cop.enums.get(path, []))
        before, after = ",".join(sorted(pv)), ",".join(sorted(cv))
        if pv - cv:
            ch.append(ContractChange(key, "enum", "BREAKING", before=before, after=after,
                                     detail=f"enum value(s) removed at {path}: {sorted(pv - cv)}"))
        if cv - pv:
            ch.append(ContractChange(key, "enum", "ADDITIVE", before=before, after=after,
                                     detail=f"enum value(s) added at {path}: {sorted(cv - pv)}"))
    return ch
