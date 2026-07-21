"""CLI for the Drift Detector.

Builds the code-level third-party integration inventory (the IR /
inventory.json), audits it, and renders the single report surface
(dashboard.html). Driven by the bundled `bin/drift-scan` runner.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from agent import inventory_scan as inventory_scan_mod
from agent.lib import scan_util


def _cmd_inventory_scan(args) -> int:
    progress = None
    if getattr(args, "progress", False):
        print("drift-detector · deterministic static-analysis (local · 0 LLM tokens)",
              file=sys.stderr, flush=True)

        def progress(msg):
            print(f"⚙ {msg}", file=sys.stderr, flush=True)

    t0 = time.perf_counter()
    try:
        out = inventory_scan_mod.scan_folder(args.root, args.state, args.now, progress=progress)
    except RuntimeError as exc:
        print(f"inventory-scan failed: {exc}", file=sys.stderr)
        return 2
    dt = time.perf_counter() - t0
    with open(args.out_json, "w", encoding="utf-8") as fh:
        json.dump(out["doc"], fh, ensure_ascii=False, indent=2, sort_keys=True)
    d = out["doc"]
    print(f"✓ {len(d['repos'])} repos · {len(d.get('unique_apis', []))} APIs · "
          f"{len(d.get('unique_packages', []))} packages · "
          f"{len(d['coverage']['reposErrored'])} errors · {dt:.1f}s")
    return 0


def _cmd_audit(args) -> int:
    from agent.audit import audit_inventory
    from agent.lib.dashboard_render import render_dashboard

    with open(args.in_json, encoding="utf-8") as fh:
        doc = json.load(fh)
    http = None
    if getattr(args, "offline", False):
        def http(*a, **k):
            raise ConnectionError("offline")
    if getattr(args, "progress", False):
        print("drift-detector audit · OSV.dev + endoflife.date (deterministic · 0 LLM tokens)",
              file=sys.stderr, flush=True)

    audit = audit_inventory(doc, args.now, http=http) if http else audit_inventory(doc, args.now)
    from agent.lib.findings_state import apply_lifecycle
    apply_lifecycle(audit, os.path.dirname(os.path.abspath(args.in_json)), args.now)

    if getattr(args, "out_json", None):
        with open(args.out_json, "w", encoding="utf-8") as fh:
            json.dump(audit, fh, ensure_ascii=False, indent=2, sort_keys=True)
    if getattr(args, "out_html", None):
        with open(args.out_html, "w", encoding="utf-8") as fh:
            fh.write(render_dashboard(doc, audit, args.now))
    c = audit["counts"]
    print(f"✓ audit: 🔴 {c.get('DEPRECATED', 0)} action-required · 🟠 {c.get('REVIEW', 0)} review · "
          f"across {c.get('reposAffected', 0)} repos")
    return 0


def _cmd_run(args) -> int:
    from agent.run import run_pipeline
    progress = None
    if getattr(args, "progress", False):
        print("drift-detector · scan → audit → deliver (deterministic · 0 LLM tokens)",
              file=sys.stderr, flush=True)

        def progress(msg):
            print(f"⚙ {msg}", file=sys.stderr, flush=True)
    try:
        out = run_pipeline(args.root, args.state, args.now,
                           pull=getattr(args, "pull", False), progress=progress)
    except RuntimeError as exc:
        print(f"run failed: {exc}", file=sys.stderr)
        return 2
    # Nothing scanned is NEVER a clean bill. A URL, a typo, or a plain non-git folder
    # otherwise printed a green checkmark over zero repos — the failure the PM hit and
    # the exact "cannot see == clean" collapse this tool exists to refuse.
    if out.get("scope", {}).get("reposScanned", 0) == 0:
        print("✗ scanned 0 repositories — this is NOT a clean result.", file=sys.stderr)
        for u in (out.get("rootsUnscannable") or []):
            print(f"    {u['reason']}", file=sys.stderr)
        print("  Nothing was audited. Point at a git checkout (or a folder containing one).",
              file=sys.stderr)
        return 4                           # 'found nothing to scan' is 'couldn't verify'

    # A root that failed to resolve is surfaced even when OTHERS scanned fine — a typo'd
    # or unreachable root buried in a good run must not disappear.
    for u in (out.get("rootsUnscannable") or []):
        print(f"⚠ skipped: {u['reason']}", file=sys.stderr)

    c = out["auditCounts"]
    print(f"✓ scan+audit: 🔴 {c.get('DEPRECATED', 0)} action-required · 🟠 {c.get('REVIEW', 0)} review")
    if getattr(args, "fail_on_deprecated", False):
        cov = out.get("coverage", {})
        if cov.get("osvErrors") or cov.get("eolErrors"):
            print("✗ gate: audit sources (OSV/endoflife) were unreachable — cannot certify clean "
                  "(exit 4). Re-run with network access.", file=sys.stderr)
            return 4                       # 'couldn't check' is NOT 'clean'
        if c.get("DEPRECATED", 0) > 0:
            print(f"✗ gate: {c['DEPRECATED']} DEPRECATED finding(s) (excluding muted) — failing (exit 3)",
                  file=sys.stderr)
            return 3
    return 0


def _cmd_schedule(args) -> int:
    from pathlib import Path
    from agent.lib import schedule as sched
    plugin_root = str(Path(__file__).resolve().parent.parent)
    try:
        line = sched.install_cron(args.root, args.state, args.at, plugin_root=plugin_root,
                                  pull=getattr(args, "pull", False))
    except Exception as exc:      # missing/failed crontab -> actionable message, not a traceback
        print(f"schedule failed: {exc}\n  Is 'crontab' installed and the cron service running?",
              file=sys.stderr)
        return 2
    print("installed cron:\n  " + line)
    return 0


def _cmd_unschedule(args) -> int:
    from agent.lib import schedule as sched
    try:
        removed = sched.remove_cron(args.state)
    except Exception as exc:
        print(f"unschedule failed: {exc}", file=sys.stderr)
        return 2
    print("removed schedule" if removed else "no schedule found")
    return 0


def _cmd_catalog_refresh(args) -> int:
    """Reconcile a vendor's published API specs against our sunset catalog.

    Reports, never writes. Exit 0 clean, 3 when the vendor contradicts itself (our
    catalog dates a family the vendor still publishes unflagged) — that is not an error
    in our data, it is a disagreement a human has to resolve, and it should be loud
    rather than buried in output nobody reads.
    """
    from agent import catalog_refresh
    try:
        result = catalog_refresh.refresh(args.vendor)
    except KeyError as exc:
        print(f"catalog-refresh: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"catalog-refresh: could not reach the vendor's specs ({exc}). "
              f"Nothing was concluded — an unreachable source is not a clean one.",
              file=sys.stderr)
        return 4
    print(catalog_refresh.render(result))
    return 3 if result["specUnflagged"] else 0


def _cmd_verify(args) -> int:
    """Check a produced report against itself: do the tiles agree with the tables, does
    the page carry the data the JSON claims, is every row distinguishable?

    Exists so "the dashboard is correct" stops being a claim anyone makes by looking at
    it. Two bugs shipped in one day because rendered HTML cannot be verified by reading
    the source — a tile said `Sunsets 1` over twelve findings, then twelve rows rendered
    with the same label. Both are mechanically detectable from the payload, and this is
    where that happens. Exit 0 clean, 3 violations, 4 nothing to verify.
    """
    import json as _json
    from agent.lib import verify as _verify

    state = args.state
    try:
        def _slurp(name):
            with open(os.path.join(state, name), encoding="utf-8") as fh:
                return fh.read()
        payload = _json.loads(_slurp("dashboard.json"))
        audit = _json.loads(_slurp("audit.json"))
        html = _slurp("dashboard.html")
    except OSError as exc:
        print(f"drift verify: nothing to verify — {exc}", file=sys.stderr)
        return 4

    violations = _verify.verify_payload(payload, audit.get("findings", []))
    try:
        _verify.check_blob_matches_payload(html, _json.dumps(payload))
    except _verify.Violation as v:
        violations.append(v)

    if violations:
        print(f"✗ {len(violations)} invariant(s) violated:")
        for v in violations:
            print(f"  [{v.check}] {v.detail}")
        return 3
    n = payload.get("counts", {})
    print(f"✓ report is self-consistent — {n.get('sunsets', 0)} sunsets, "
          f"{n.get('eol', 0)} eol, {n.get('private', 0)} private, "
          f"tiles match their tables, page matches dashboard.json")
    return 0


def _cmd_preflight(args) -> int:
    from agent.lib.repo_discovery import discover_repos
    from agent.lib import private_sources
    repos = discover_repos([args.root])
    print(f"scan-readiness · {args.root}")
    print(f"  repos discovered: {len(repos)}")
    flagged, n_pkg, n_src = [], 0, 0
    for abs_path, name in repos:
        ps = private_sources.detect(abs_path)
        if ps["packages"] or ps["repositories"]:
            flagged.append((name, ps))
            n_pkg += len(ps["packages"])
            n_src += len(ps["repositories"])
    if flagged:
        print(f"  ⚠ {len(flagged)} repo(s) declare private package sources needing access "
              f"({n_pkg} git/file deps · {n_src} private composer repos):")
        for name, ps in flagged[:20]:
            bits = [p["pkg"] for p in ps["packages"]] + ps["repositories"]
            print(f"    - {name}: {', '.join(bits[:6])}" + (" …" if len(bits) > 6 else ""))
        print("  → these need source access; clone them locally and add them as a --root to scan them.")
    else:
        print("  ✓ no private package sources detected — full source coverage.")
    return 0


def _cmd_recommend(args) -> int:
    """Suggest a scan profile per repo — for when the user can't decide which mode to run.

    Uses the shape verdicts from a previous scan when one exists (precise), and falls
    back to a language census when it doesn't (no engine needed, still honest).
    """
    import json
    from agent.lib.repo_discovery import discover_repos
    from agent.lib.vendors import load_vendors
    from agent.lib.vendor_rules import rule_kinds_by_language
    from agent.lib import shapes

    kinds = rule_kinds_by_language(load_vendors())
    prior = {}
    state = getattr(args, "state", None) or os.path.join(args.root, ".drift-detector")
    try:
        with open(os.path.join(state, "inventory.json"), encoding="utf-8") as fh:
            prior = {s["repo"]: s for s in (json.load(fh).get("coverage") or {}).get("shapes", [])}
    except (OSError, ValueError):
        pass

    repos = discover_repos([args.root])
    matched = sum(1 for _, name in repos if name in prior)
    print(f"scan profiles · {args.root}")
    if matched:
        print(f"  {len(repos)} repo(s); {matched} with shape verdicts from a previous scan"
              + (f", {len(repos) - matched} from a language census" if matched < len(repos) else ""))
    else:
        print(f"  {len(repos)} repo(s); language census only "
              "(no matching prior scan — repo identities depend on the --root used)")
    print()
    tally = {}
    for abs_path, name in repos:
        sh = prior.get(name)
        if sh:
            profile, why = shapes.recommend_profile(sh)
            langs = ",".join(sh.get("languages", {}))
            extra = f"{sh['verdict']}"
        else:
            counts, unmodeled = shapes.census(abs_path)
            profile, why = shapes.recommend_from_census(counts, kinds, unmodeled)
            langs = ",".join(shapes.meaningful_languages(counts)) or "-"
            extra = "unscanned"
        tally[profile] = tally.get(profile, 0) + 1
        print(f"  {name:<28} {profile:<7} [{extra}] {langs}")
        print(f"      {why}")
    print("\n  " + " · ".join(f"{n} {p}" for p, n in sorted(tally.items())))
    if tally.get(shapes.MANUAL) or tally.get(shapes.HYBRID):
        print("  → repos not on `auto` need an agent pass; the tool says exactly what it missed.")
    return 0


def _cmd_absorb(args) -> int:
    """Gate a staged proposal into the tool. Deterministic, zero tokens.

    An agent may PROPOSE (idiom instances, sunset entries); nothing is trusted
    because an agent said it. This re-scans the repo with the staged specs and
    refuses anything that cannot show its work.
    """
    import tempfile
    from agent import absorb
    from agent.lib import idioms as idioms_mod, shapes
    from agent.lib.vendors import load_vendors
    from agent.lib.vendor_rules import write_ruleset
    from agent.lib.engine import run_scan
    from agent.lib.endpoints import scan_endpoints

    staged_idioms = absorb._load(os.path.join(args.staged, "idioms.yaml"))
    staged_sunsets = absorb._load(os.path.join(args.staged, "sunsets.yaml"))
    claims = absorb._load(os.path.join(args.staged, "claims.yaml")) or []

    problems = absorb.check_idioms(staged_idioms) + absorb.check_sunsets(staged_sunsets)
    if problems:
        print("✗ absorb rejected — the proposal is malformed:", file=sys.stderr)
        for p in problems:
            print(f"    {p}", file=sys.stderr)
        return 3

    vendors = load_vendors()
    engine = scan_util.resolve_engine()

    def scan(extra_idioms):
        insts = idioms_mod.load_idioms() + list(extra_idioms or [])
        with tempfile.TemporaryDirectory() as td:
            rules = os.path.join(td, "rules.yaml")
            write_ruleset(vendors, rules, idiom_instances=insts)
            res = run_scan(args.repo, rules, engine=engine)
        return scan_endpoints(res["matches"], args.repo, vendors)

    problems = absorb.verify_against_repo(args.repo, staged_idioms, claims, scan=scan)
    if problems:
        print("✗ absorb rejected — the proposal did not hold up against the repo:", file=sys.stderr)
        for p in problems:
            print(f"    {p}", file=sys.stderr)
        return 3

    added = absorb.promote(args.staged, idioms_path=idioms_mod._DEFAULT,
                           sunsets_path=os.path.join(os.path.dirname(idioms_mod._DEFAULT),
                                                     "vendor_sunsets.yaml"))
    print(f"✓ absorbed: {added['idioms']} idiom(s), {added['sunsets']} sunset(s) — "
          "verified against the repo, promoted to the catalogs")
    if args.state:
        after = scan(staged_idioms)
        fp = shapes.residue_fingerprint(after["residue"])
        shapes.attest(args.state, args.repo_name or os.path.basename(args.repo.rstrip("/")),
                      fp, resolved_by="absorb", date=args.now or "",
                      note=f"{added['idioms']} idiom(s) absorbed")
        print(f"  attestation written for residue {fp}")
    return 0


def _cmd_mute(args) -> int:
    from agent.lib.findings_state import add_to_baseline, remove_from_baseline
    if args.remove:
        remove_from_baseline(args.state, args.fingerprint)
        print(f"unmuted {args.fingerprint}")
    else:
        add_to_baseline(args.state, args.fingerprint)
        print(f"muted {args.fingerprint} (excluded from action counts until unmuted)")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="drift-detector")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run")           # scan -> audit -> deliver, deterministic (cron entrypoint)
    pr.add_argument("--root", action="append", required=True)
    pr.add_argument("--state", required=True)
    pr.add_argument("--now", required=True)
    pr.add_argument("--pull", action="store_true")
    pr.add_argument("--progress", action="store_true")
    pr.add_argument("--fail-on-deprecated", action="store_true",
                    help="exit 3 if any un-muted DEPRECATED finding (CI gate)")
    pr.set_defaults(func=_cmd_run)

    psc = sub.add_parser("schedule")
    psc.add_argument("--root", required=True)
    psc.add_argument("--state", required=True)
    psc.add_argument("--at", default="0 7 * * 0")
    psc.add_argument("--pull", action="store_true")
    psc.set_defaults(func=_cmd_schedule)

    pu = sub.add_parser("unschedule")
    pu.add_argument("--state", required=True)
    pu.set_defaults(func=_cmd_unschedule)

    pmu = sub.add_parser("mute")
    pmu.add_argument("--state", required=True)
    pmu.add_argument("--fingerprint", required=True)
    pmu.add_argument("--remove", action="store_true")
    pmu.set_defaults(func=_cmd_mute)

    pab = sub.add_parser("absorb")        # gate a staged agent proposal into the tool
    pab.add_argument("--staged", required=True)
    pab.add_argument("--repo", required=True)
    pab.add_argument("--repo-name")
    pab.add_argument("--state")
    pab.add_argument("--now")
    pab.set_defaults(func=_cmd_absorb)

    prc = sub.add_parser("recommend")     # which scan profile should this folder run?
    prc.add_argument("--root", required=True)
    prc.add_argument("--state")
    prc.set_defaults(func=_cmd_recommend)

    ppf = sub.add_parser("preflight")
    ppf.add_argument("--root", required=True)
    ppf.set_defaults(func=_cmd_preflight)

    pcr = sub.add_parser("catalog-refresh")   # vendor specs vs our curated catalog
    pcr.add_argument("--vendor", required=True)
    pcr.set_defaults(func=_cmd_catalog_refresh)

    pv = sub.add_parser("verify")         # do the report's numbers agree with its data?
    pv.add_argument("--state", required=True)
    pv.set_defaults(func=_cmd_verify)

    pa = sub.add_parser("audit")
    pa.add_argument("--in", dest="in_json", required=True)
    pa.add_argument("--now", required=True)
    pa.add_argument("--out-json")
    pa.add_argument("--out-html")
    pa.add_argument("--offline", action="store_true")
    pa.add_argument("--progress", action="store_true")
    pa.set_defaults(func=_cmd_audit)

    pis = sub.add_parser("inventory-scan")
    pis.add_argument("--root", action="append", required=True,
                     help="folder to scan for git repos (recursive); repeat for multiple roots")
    for a in ("--state", "--out-json", "--now"):
        pis.add_argument(a, required=True)
    pis.add_argument("--progress", action="store_true",
                     help="emit an informative per-phase log to stderr")
    pis.set_defaults(func=_cmd_inventory_scan)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
