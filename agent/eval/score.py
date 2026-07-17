"""The pure scoring core. (corpus entries, inventory doc, audit doc) -> scorecard dict.

No git, no network, no scanner, no filesystem — it takes already-produced dicts, so it is
fully deterministic and unit-testable. The recall GATE is the only pass/fail; noise,
version-rate and sunset-match are informational.
"""
from __future__ import annotations

import os
import statistics


def _basename(repo_or_path: str) -> str:
    return os.path.basename(str(repo_or_path).rstrip("/"))


def _match_repo(entry, inventory):
    want = _basename(entry["repo"])
    for r in inventory.get("repos", []):
        if _basename(r.get("path", "")) == want:
            return r
    return None


def _errored_names(inventory) -> set:
    cov = inventory.get("coverage") or {}
    return {_basename(x.get("repo", "")) for x in (cov.get("reposErrored") or [])}


def _detect(entry, repo) -> tuple:
    """Returns (detected, via). Endpoint match wins over sdk when both fire."""
    vendor = entry["expect"]["vendor"]
    for e in repo.get("endpoints", []):
        if e.get("classified") and e.get("vendor") == vendor:
            return True, "endpoint"
    keywords = [k.lower() for k in (entry["expect"].get("sdk_keywords") or [entry["category"]])]
    for s in repo.get("sdks", []):
        pkg = str(s.get("pkg", "")).lower()
        if any(k in pkg for k in keywords):
            return True, "sdk"
    return False, None


def _sunsets(audit) -> set:
    return {f.get("domain") for f in audit.get("findings", []) if f.get("kind") == "sunset"}


def score(entries: list, inventory: dict, audit: dict) -> dict:
    fired_sunsets = _sunsets(audit)
    errored = _errored_names(inventory)
    rows, noises, classified_total, versioned_total = [], [], 0, 0
    sunset_expected = sunset_hit = 0

    for entry in entries:
        name = _basename(entry["repo"])
        repo = _match_repo(entry, inventory)
        is_errored = repo is None or name in errored
        if repo is None:
            repo = {"endpoints": [], "sdks": []}

        detected, via = (False, None) if is_errored else _detect(entry, repo)

        eps = repo.get("endpoints", [])
        noise = sum(1 for e in eps if e.get("vendor") == "Unknown")
        classified = [e for e in eps if e.get("classified")]
        classified_total += len(classified)
        versioned_total += sum(1 for e in classified if e.get("version") is not None)
        version_rate = (sum(1 for e in classified if e.get("version") is not None) / len(classified)
                        if classified else None)

        host = entry["expect"].get("sunset_host")
        s_exp = host is not None
        s_hit = (host in fired_sunsets) if s_exp else None
        if s_exp:
            sunset_expected += 1
            sunset_hit += 1 if s_hit else 0

        known = entry.get("known_gaps") or []
        if detected:
            miss_mode = None
        elif known:
            miss_mode = known[0]           # attributed to the first declared gap
        else:
            miss_mode = "unattributed"

        rows.append({"repo": entry["repo"], "detected": detected, "via": via,
                     "miss_mode": miss_mode, "noise": noise, "version_rate": version_rate,
                     "sunset_expected": s_exp, "sunset_hit": s_hit, "errored": is_errored,
                     "holdout": bool(entry.get("holdout"))})
        noises.append(noise)

    failures = [r["repo"] for r in rows if not r["detected"] and r["miss_mode"] == "unattributed"]
    passed = [r for r in rows if r["detected"]]
    summary = {
        "recall": {
            "passed": len(passed), "total": len(rows),
            "endpoint": sum(1 for r in rows if r["via"] == "endpoint"),
            "sdk_only": sum(1 for r in rows if r["via"] == "sdk"),
            "known_miss": sum(1 for r in rows if not r["detected"]
                              and r["miss_mode"] not in (None, "unattributed")),
            "holdout": sum(1 for r in rows if r["holdout"]),
        },
        "noise": {"median": int(statistics.median(noises)) if noises else 0,
                  "max": max(noises) if noises else 0},
        "version_rate": (versioned_total / classified_total) if classified_total else None,
        "sunset_match": {"expected": sunset_expected, "hit": sunset_hit},
        "errored": sum(1 for r in rows if r["errored"]),
    }
    return {"category": entries[0]["category"] if entries else None,
            "repos": rows, "summary": summary,
            "gate": {"passed": not failures, "failures": failures}}
