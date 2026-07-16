"""AUDIT.md renders ACTIONS, ranked. The first thing on the page must be the worst thing."""
from agent.lib.actions import build_actions
from agent.lib.audit_render import render_audit_md


def _cve(repo, ref, severity="HIGH", status="DEPRECATED", fixed="1.16.0", version="0.21.1"):
    return {"repo": repo, "ref": ref, "kind": "cve", "version": version, "fixed": fixed,
            "severity": severity, "status": status, "first_seen": "2026-07-15",
            "detail": "summary text", "recommendation": f"upgrade to >= {fixed}",
            "source_url": "https://osv.dev/x", "tier": 1}


def _audit(findings, **kw):
    actions = build_actions(findings)
    return {"generated": "2026-07-15", "findings": findings, "actions": actions,
            "counts": {"DEPRECATED": sum(1 for f in findings if f["status"] == "DEPRECATED"),
                       "REVIEW": sum(1 for f in findings if f["status"] == "REVIEW"),
                       "reposAffected": len({f["repo"] for f in findings})},
            "coverage": {"notes": []}, **kw}


def test_the_worst_action_is_first_not_the_alphabetically_first_repo():
    # THE REGRESSION TEST. The old renderer did `urgent[:15]` with no sort, so an
    # alphabetically-early repo buried a CRITICAL RCE under "...and 104 more".
    findings = [_cve("aaa/first-alphabetically", "npm/lodash", severity="HIGH")]
    findings += [_cve("zzz/heygen/Wav2Lip", "python/torch", severity="CRITICAL",
                      fixed="2.8.0", version="1.1.0") for _ in range(30)]
    md = render_audit_md(_audit(findings))
    first = md.index("zzz/heygen/Wav2Lip")
    second = md.index("aaa/first-alphabetically")
    assert first < second


def test_do_this_first_shows_the_command():
    md = render_audit_md(_audit([_cve("r", "python/torch", severity="CRITICAL",
                                      fixed="2.8.0", version="1.1.0")]))
    assert "## Do this first" in md
    assert "pip install 'torch>=2.8.0'" in md


def test_thirty_findings_render_as_one_action_saying_thirty():
    findings = [_cve("r", "python/torch", severity="CRITICAL", fixed="2.8.0") for _ in range(30)]
    md = render_audit_md(_audit(findings))
    assert "Fixes 30 advisories" in md
    queue_rows = [l for l in md.splitlines() if l.startswith("| 1 |")]
    assert len(queue_rows) == 1                # exactly one numbered row in the fix queue...
    assert "| 2 |" not in md                   # ...and no second one. 30 findings, 1 job.


def test_truncation_is_announced_never_silent():
    findings = [_cve(f"repo{i:02d}", "npm/x") for i in range(14)]
    md = render_audit_md(_audit(findings))
    assert "10 shown of 14" in md              # "Do this first" caps at 10 and SAYS so
    for i in range(14):
        assert f"repo{i:02d}" in md            # ...but the full queue drops nothing


def test_review_only_actions_are_not_in_the_fix_queue():
    md = render_audit_md(_audit([_cve("r", "npm/x", severity="LOW", status="REVIEW")]))
    assert "## Fix queue" not in md            # nothing action-required -> no queue section
    assert "npm/x" in md                       # ...but it still appears under "By repo"


def test_action_without_a_fix_shows_prose_not_a_broken_command():
    # OSV knows the vuln but no fixed version exists yet (13 such findings in the real run)
    unfixed = _cve("r", "npm/x", fixed=None)
    unfixed["recommendation"] = "review advisory"
    md = render_audit_md(_audit([unfixed]))
    assert "review advisory" in md
    assert "npm install" not in md          # never a command without a version to install
    assert "None" not in md                 # and never a half-formed string


def test_sunset_action_renders_its_call_sites():
    sunset = {"repo": "r", "ref": "eBay", "kind": "sunset", "version": "v1",
              "severity": "SUNSET", "status": "DEPRECATED", "first_seen": "2026-07-15",
              "detail": "eBay v1 retires 2026-09-30", "date": "2026-09-30",
              "source_url": "https://developer.ebay.com/x", "tier": 1,
              "recommendation": "migrate to Sell API before 2026-09-30",
              "files": ["src/Ebay/x.php:11"]}
    md = render_audit_md(_audit([sunset]))
    assert "eBay" in md
    assert "migrate to Sell API before 2026-09-30" in md
    assert "src/Ebay/x.php:11" in md           # the file:line payload is the point


def test_coverage_note_admits_the_transitive_gap():
    md = render_audit_md(_audit([_cve("r", "npm/x")]))
    assert "Only manifest-declared (direct) dependencies are audited" in md


def test_delta_counts_new_actions_not_new_findings():
    # 5 new advisories against one package = ONE new job to do. The delta line must say so,
    # or the weekly "what changed" number keeps overstating the work.
    findings = [_cve("r", "npm/axios") for _ in range(5)]
    md = render_audit_md(_audit(findings, delta={"new": findings, "resolved": [],
                                                 "persisting": [], "mutedCount": 0}))
    assert "🆕 1 new" in md
    assert "## 🆕 New since last scan" in md
    new_bullets = [l for l in md.splitlines() if l.startswith("- ") and "npm/axios" in l]
    assert len(new_bullets) == 1               # one bullet, not five


def test_empty_audit_renders_cleanly():
    md = render_audit_md({"generated": "2026-07-15", "findings": [], "actions": [],
                          "counts": {}, "coverage": {}})
    assert "_No open deprecation or vulnerability findings._" in md


def test_render_is_deterministic():
    a = _audit([_cve("b", "npm/z"), _cve("a", "npm/y", severity="CRITICAL")])
    assert render_audit_md(a) == render_audit_md(a)
