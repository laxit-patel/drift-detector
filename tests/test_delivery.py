"""Issue + draft-MR delivery. The planner is pure (payload + what's already on GitLab -> a
create/update/close plan), so idempotency is unit-testable without a network."""
from agent.lib import delivery


def _cve(repo="web", ref="composer/aws/aws-sdk-php"):
    return {"repo": repo, "ref": ref, "kind": "cve", "unit": None, "owner": "devops",
            "status": "DEPRECATED", "date": None, "recommendation": "upgrade to >= 3.283",
            "command": "composer require aws/aws-sdk-php:^3.283", "worst": "HIGH",
            "files": [{"loc": "composer.json:1", "href": "https://git.x/web/-/blob/a/composer.json#L1"}],
            "sources": ["https://osv.dev/x"]}


def _sunset(repo="ebayapi", unit="GetCategories"):
    return {"repo": repo, "ref": "eBay", "kind": "sunset", "unit": unit, "owner": "developer",
            "status": "DEPRECATED", "date": "2025-01-01", "recommendation": "migrate to Taxonomy API",
            "files": [{"loc": "src/Ebay.php:9", "href": "https://git.x/g/ebayapi/-/blob/a/src/Ebay.php#L9"}],
            "sources": ["https://developer.ebay.com/x"]}


_META = {"web": {"project": "root/web"}, "ebayapi": {"project": "g/ebayapi"}}


def _payload(actions):
    return {"actions": actions}


# --------------------------------------------------------------- identity + parsing
def test_action_fingerprint_is_version_independent():
    a1 = {"repo": "r", "kind": "cve", "ref": "npm/x", "unit": None}
    a2 = dict(a1)                                    # a version bump doesn't change the ref/unit
    assert delivery.action_fingerprint(a1) == delivery.action_fingerprint(a2)
    b = {"repo": "r", "kind": "sunset", "ref": "eBay", "unit": "GetItem"}
    assert delivery.action_fingerprint(a1) != delivery.action_fingerprint(b)


def test_project_path_from_remote():
    assert delivery.project_path("https://git.x/group/repo.git") == "group/repo"
    assert delivery.project_path("https://git.x/a/b/c") == "a/b/c"
    assert delivery.project_path("not-a-url") is None


# --------------------------------------------------------------- the plan (pure)
def test_new_findings_create_an_issue_and_a_draft_mr():
    plan = delivery.build_plan(_payload([_cve(), _sunset()]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    assert [i["op"] for i in plan["issues"]] == ["create"]
    assert plan["issues"][0]["project"] == "root/drift-detector"
    assert [m["op"] for m in plan["mrs"]] == ["create"]
    assert plan["mrs"][0]["project"] == "g/ebayapi"
    assert plan["mrs"][0]["title"].startswith("Draft:")          # a DRAFT mr
    assert delivery.MIGRATIONS_PATH in plan["mrs"][0]["file_path"]


def test_existing_issue_with_same_body_is_skipped_not_duplicated():
    a = _cve()
    body = delivery.issue_body(a, "root/web")            # the planner displays by project path
    fp = delivery.action_fingerprint(a)
    existing = {"issues": [{"iid": 7, "state": "opened", "description": body,
                            "title": delivery.issue_title(a)}], "mrs": {}}
    plan = delivery.build_plan(_payload([a]), _META, existing, "root/drift-detector")
    assert plan["issues"][0]["op"] == "skip" and plan["issues"][0]["iid"] == 7


def test_crlf_only_difference_skips_not_updates():
    """SHIPPED BUG: a live re-run reported '2 updated' for unchanged issues — GitLab returns
    the description with CRLF, so the raw compare always looked changed and rewrote the issue
    (noise) every run. Normalised compare must treat CRLF/trailing-space as identical → skip."""
    a = _cve()
    body = delivery.issue_body(a, "root/web")
    gitlab_returned = body.replace("\n", "\r\n") + "   \r\n"   # CRLF + trailing whitespace
    existing = {"issues": [{"iid": 7, "state": "opened", "description": gitlab_returned,
                            "title": delivery.issue_title(a)}], "mrs": {}}
    plan = delivery.build_plan(_payload([a]), _META, existing, "root/drift-detector")
    assert plan["issues"][0]["op"] == "skip"


def test_changed_finding_updates_the_same_issue():
    a = _cve()
    stale = {"issues": [{"iid": 7, "state": "opened", "description": delivery.marker(
        delivery.action_fingerprint(a)) + "\nOLD BODY", "title": "old"}], "mrs": {}}
    plan = delivery.build_plan(_payload([a]), _META, stale, "root/drift-detector")
    assert plan["issues"][0]["op"] == "update" and plan["issues"][0]["iid"] == 7


def test_closed_issue_for_a_still_present_finding_is_reopened():
    a = _cve()
    existing = {"issues": [{"iid": 7, "state": "closed", "description": delivery.marker(
        delivery.action_fingerprint(a)), "title": "t"}], "mrs": {}}
    plan = delivery.build_plan(_payload([a]), _META, existing, "root/drift-detector")
    assert plan["issues"][0]["op"] == "update" and plan["issues"][0]["reopen"] is True


def test_resolved_finding_closes_its_issue():
    # an issue we filed whose fingerprint is no longer in the findings -> close
    ghost = {"issues": [{"iid": 9, "state": "opened",
                         "description": delivery.marker("deadbeefdeadbeef"), "title": "gone"}],
             "mrs": {}}
    plan = delivery.build_plan(_payload([_cve()]), _META, ghost, "root/drift-detector")
    ops = {i["op"] for i in plan["issues"]}
    assert "close" in ops
    assert next(i for i in plan["issues"] if i["op"] == "close")["iid"] == 9


def test_dev_as_issues_files_the_developer_stream_as_issues_not_mrs():
    """The Reporter-friendly fallback: developer findings become one issue per repo in the
    devops project, and no MRs are attempted."""
    plan = delivery.build_plan(_payload([_cve(), _sunset()]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector",
                               dev_as_issues=True)
    assert plan["mrs"] == []                                  # no MRs attempted
    titles = [i["title"] for i in plan["issues"]]
    assert any("API migrations for g/ebayapi" in t for t in titles)   # one per repo
    assert all(i["project"] == "root/drift-detector" for i in plan["issues"])
    # idempotent: the per-repo issue carries the repo marker
    dev_issue = next(i for i in plan["issues"] if "migrations" in i["title"])
    assert delivery.repo_fingerprint("g/ebayapi", "developer") in dev_issue["body"]   # keyed on project path


def test_issue_and_mr_bodies_link_back_to_the_run_and_report():
    """Provenance ('what stemmed it'): every issue/MR footer links the scan run + report."""
    links = {"run": "https://gh/run/1", "report": "https://git.x/root/ops"}
    ib = delivery.issue_body(_cve(), "root/web", links)
    assert "[scan run](https://gh/run/1)" in ib and "[full report](https://git.x/root/ops)" in ib
    mr = delivery.mr_description("g/ebayapi", [_sunset()], links)
    assert "[scan run](https://gh/run/1)" in mr and "Draft, filed by Drift Detector" in mr


def test_developer_finding_with_no_known_project_is_unroutable_not_silent():
    plan = delivery.build_plan(_payload([_sunset(repo="mystery")]), {},  # no repo_meta
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    assert plan["mrs"][0]["op"] == "unroutable" and plan["mrs"][0]["repo"] == "mystery"


def test_existing_mr_on_the_drift_branch_updates_not_duplicates():
    existing = {"issues": [], "mrs": {"g/ebayapi": [
        {"iid": 4, "source_branch": delivery.MR_BRANCH, "state": "opened"}]}}
    plan = delivery.build_plan(_payload([_sunset()]), _META, existing, "root/drift-detector")
    assert plan["mrs"][0]["op"] == "update" and plan["mrs"][0]["iid"] == 4


def test_issue_and_mr_bodies_carry_a_discovery_marker():
    a = _cve()
    assert delivery.action_fingerprint(a) in "".join(delivery.markers_in(delivery.issue_body(a)))
    md = delivery.migrations_md("ebayapi", [_sunset()])
    assert delivery.repo_fingerprint("ebayapi", "developer") in "".join(delivery.markers_in(md))


# --------------------------------------------------------------- execute (fake GitLab)
class _FakeGL:
    def __init__(self, default="main"):
        self.calls = []
        self._default = default
        self._branches = set()
        self._files = {}

    def project(self, p):
        return {"default_branch": self._default}

    def create_issue(self, p, **k):
        self.calls.append(("create_issue", p, k["title"]))

    def update_issue(self, p, iid, **k):
        self.calls.append(("update_issue", p, iid, k.get("state_event")))

    def branch(self, p, b):
        return {"name": b} if (p, b) in self._branches else None

    def create_branch(self, p, b, ref):
        self._branches.add((p, b))
        self.calls.append(("create_branch", p, b, ref))

    def get_file(self, p, path, ref):
        return self._files.get((p, path, ref))

    def set_file(self, p, path, *, branch, content, message, exists):
        self._files[(p, path, branch)] = content
        self.calls.append(("set_file", p, path, exists))

    def create_mr(self, p, **k):
        self.calls.append(("create_mr", p, k["title"], k["source_branch"]))

    def update_mr(self, p, iid, **k):
        self.calls.append(("update_mr", p, iid))


def test_execute_creates_issue_branch_file_and_draft_mr():
    plan = delivery.build_plan(_payload([_cve(), _sunset()]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    gl = _FakeGL()
    done = delivery.execute_plan(gl, plan)
    kinds = [c[0] for c in gl.calls]
    assert "create_issue" in kinds
    assert kinds.count("create_branch") == 1 and kinds.count("set_file") == 1
    mr = next(c for c in gl.calls if c[0] == "create_mr")
    assert mr[1] == "g/ebayapi" and mr[2].startswith("Draft:") and mr[3] == delivery.MR_BRANCH
    assert done["created"] == 2                       # one issue + one MR


def test_cli_dry_run_produces_a_plan_and_writes_nothing(tmp_path, monkeypatch, capsys):
    import json
    from agent import cli
    from agent.lib import gitlab_api
    (tmp_path / "drift.json").write_text(json.dumps(
        _payload([_cve(repo="web"), _sunset(repo="ebayapi")])))
    (tmp_path / "inventory.json").write_text(json.dumps({"repos": [
        {"path": "web", "remote_url": "https://git.x/root/web"},
        {"path": "ebayapi", "remote_url": "https://git.x/g/ebayapi"}]}))

    class FakeGL:                                      # nothing filed yet
        def __init__(self, *a, **k): pass
        def list_issues(self, *a, **k): return []
        def list_mrs(self, *a, **k): return []
    monkeypatch.setattr(gitlab_api, "GitLab", FakeGL)
    rc = cli.main(["deliver", "--state", str(tmp_path), "--gitlab-host", "git.x",
                   "--devops-project", "root/drift-detector", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "create" in out and "root/drift-detector" in out and "Draft" in out
    assert "dry run" in out


def test_cli_reads_host_project_and_mode_from_config(tmp_path, monkeypatch, capsys):
    import json
    from agent import cli
    from agent.lib import gitlab_api
    (tmp_path / "drift.json").write_text(json.dumps(_payload([_sunset(repo="ebayapi")])))
    (tmp_path / "inventory.json").write_text(json.dumps({"repos": [
        {"path": "ebayapi", "remote_url": "https://git.x/g/ebayapi"}]}))
    (tmp_path / "drift.yml").write_text(
        "fleet: [https://git.x/g/ebayapi]\n"
        "delivery:\n  mode: dry-run\n  devops_project: root/ops\n  dev_as_issues: true\n")

    class FakeGL:
        def __init__(self, host, *a, **k): FakeGL.host = host
        def list_issues(self, *a, **k): return []
        def list_mrs(self, *a, **k): return []
    monkeypatch.setattr(gitlab_api, "GitLab", FakeGL)
    rc = cli.main(["deliver", "--config", str(tmp_path / "drift.yml"),
                   "--state", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert FakeGL.host == "git.x"                    # host derived from the fleet in config
    assert "delivery mode: dry-run" in out and "dry run" in out
    assert "root/ops" in out                         # devops_project from config
    assert "draft MRs: nothing" in out               # dev_as_issues from config -> issue, no MR


def test_cli_config_mode_off_skips_delivery(tmp_path, capsys):
    import json
    from agent import cli
    (tmp_path / "drift.json").write_text(json.dumps(_payload([])))
    (tmp_path / "inventory.json").write_text(json.dumps({"repos": []}))
    (tmp_path / "drift.yml").write_text(
        "fleet: [https://git.x/g/a]\ndelivery:\n  mode: off\n  devops_project: root/ops\n")
    rc = cli.main(["deliver", "--config", str(tmp_path / "drift.yml"), "--state", str(tmp_path)])
    assert rc == 0 and "off — skipping" in capsys.readouterr().out


# --------------------------------------------------------------- shape stream (absorption flags)
def _shape(repo, verdict="UNKNOWN", reasons=("config-driven-url",), fp="deadbeef00000000"):
    return {"repo": repo, "verdict": verdict, "reasons": list(reasons),
            "attributed": 3, "unattributedPaths": 5, "unresolvedSinks": 2,
            "languages": {"php": 40}, "residueFingerprint": fp}


def _pl_shapes(shapes, samples=None):
    return {"actions": [], "shapes": shapes, "residueSamples": samples or []}


def test_shape_stream_is_off_by_default():
    plan = delivery.build_plan(_pl_shapes([_shape("svc")]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    assert plan["issues"] == []                              # no flag unless the stream is on


def test_shape_stream_flags_each_unknown_repo_at_the_maintainer():
    shapes = [_shape("svc-a"), _shape("svc-b"), _shape("svc-c", verdict="KNOWN")]
    plan = delivery.build_plan(_pl_shapes(shapes), _META, {"issues": [], "mrs": {}},
                               "root/drift-detector", shape_stream=True)
    creates = [i for i in plan["issues"] if i["op"] == "create"]
    assert len(creates) == 2                                 # only the two UNKNOWN
    assert all(o["project"] == "root/drift-detector" for o in creates)   # aimed at us
    assert all(o.get("stream") == "shape" for o in creates)
    assert "absorption needed" in creates[0]["title"]


def test_shape_issue_body_carries_blindspots_fingerprint_and_bootstrap():
    samples = [{"repo": "svc", "loc": "src/A.php:12", "sample": "/v2/orders"}]
    plan = delivery.build_plan(_pl_shapes([_shape("svc")], samples), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector", shape_stream=True)
    body = plan["issues"][0]["body"]
    assert "deadbeef00000000" in body and "src/A.php:12" in body and "config-driven-url" in body
    assert "drift-absorb" in body and "DRIFT_OPS_DIR" in body     # the absorb bootstrap


def test_shape_flag_is_idempotent():
    sh = _shape("svc")
    first = delivery.build_plan(_pl_shapes([sh]), _META, {"issues": [], "mrs": {}},
                                "root/drift-detector", shape_stream=True)["issues"][0]
    existing = {"issues": [{"iid": 9, "state": "opened",
                            "description": first["body"], "title": first["title"]}], "mrs": {}}
    again = delivery.build_plan(_pl_shapes([sh]), _META, existing,
                                "root/drift-detector", shape_stream=True)
    assert again["issues"][0]["op"] == "skip"               # unchanged shape -> no rewrite


def test_shape_flag_closes_itself_when_the_repo_goes_known():
    fp = delivery.shape_fingerprint("svc")
    existing = {"issues": [{"iid": 9, "state": "opened", "description": delivery.marker(fp),
                            "title": "[drift] absorption needed: svc"}], "mrs": {}}
    plan = delivery.build_plan(_pl_shapes([_shape("svc", verdict="KNOWN")]), _META, existing,
                               "root/drift-detector", shape_stream=True)
    closes = [i for i in plan["issues"] if i["op"] == "close"]
    assert len(closes) == 1 and closes[0]["iid"] == 9       # KNOWN now -> flag closes


def test_shape_fingerprint_is_repo_keyed_and_distinct():
    assert delivery.shape_fingerprint("svc") == delivery.shape_fingerprint("svc")
    assert delivery.shape_fingerprint("svc") != delivery.repo_fingerprint("svc")


# ------------------------------------------------- freshness stream (catalog work-order)
def _cat(vendor, verdict="UNAUDITED", sites=4, checked=None):
    return {"vendor": vendor, "verdict": verdict, "callSites": sites, "checked": checked}


def _pl_catalog(records):
    return {"actions": [], "catalog": records, "generated": "2026-07-29"}


def test_freshness_stream_is_off_by_default():
    plan = delivery.build_plan(_pl_catalog([_cat("MyDeal")]), _META,
                               {"issues": [], "mrs": {}}, "root/drift-detector")
    assert plan["issues"] == []                       # no work-order unless the stream is on


def test_freshness_stream_files_one_work_order_for_the_due_vendors():
    """WIRING GAP (found in review): drift:freshness had a label and an execute_plan branch
    but NO producer — build_plan never set stream='freshness', so the maintainer's due-list
    lived only in a CLI nobody was required to run. With the stream on, the due vendors are
    filed as ONE maintainer work-order issue (the work-order is one queue, not one issue per
    vendor), auto-lane vendors (catalog-check re-fetches those) and CURRENT vendors excluded."""
    records = [_cat("MyDeal"),                          # portal-gated -> due
               _cat("Kogan", verdict="STALE", checked="2026-03-01"),
               _cat("Stripe", verdict="CURRENT", checked="2026-07-20"),   # fresh -> not due
               _cat("eBay", verdict="STALE")]           # auto lane -> catalog-check's job
    plan = delivery.build_plan(_pl_catalog(records), _META, {"issues": [], "mrs": {}},
                               "root/drift-detector", freshness_stream=True)
    creates = [i for i in plan["issues"] if i["op"] == "create"]
    assert len(creates) == 1                            # ONE work-order, not one per vendor
    op = creates[0]
    assert op.get("stream") == "freshness" and op["project"] == "root/drift-detector"
    assert "catalog freshness" in op["title"] and "2 vendor(s)" in op["title"]
    assert delivery.marker(delivery.freshness_fingerprint()) in op["body"]
    assert "MyDeal" in op["body"] and "Kogan" in op["body"]
    assert "Stripe" not in op["body"] and "eBay" not in op["body"]


def test_freshness_work_order_is_idempotent():
    records = [_cat("MyDeal")]
    first = delivery.build_plan(_pl_catalog(records), _META, {"issues": [], "mrs": {}},
                                "root/drift-detector", freshness_stream=True)["issues"][0]
    existing = {"issues": [{"iid": 7, "state": "opened",
                            "description": first["body"], "title": first["title"]}], "mrs": {}}
    again = delivery.build_plan(_pl_catalog(records), _META, existing,
                                "root/drift-detector", freshness_stream=True)
    assert again["issues"][0]["op"] == "skip"           # unchanged due-list -> no rewrite


def test_freshness_work_order_closes_itself_when_nothing_is_due():
    fp = delivery.freshness_fingerprint()
    existing = {"issues": [{"iid": 7, "state": "opened", "description": delivery.marker(fp),
                            "title": "[drift] catalog freshness: 1 vendor(s) due a re-check"}],
                "mrs": {}}
    plan = delivery.build_plan(_pl_catalog([_cat("MyDeal", verdict="CURRENT",
                                                 checked="2026-07-29")]), _META, existing,
                               "root/drift-detector", freshness_stream=True)
    closes = [i for i in plan["issues"] if i["op"] == "close"]
    assert len(closes) == 1 and closes[0]["iid"] == 7   # all CURRENT -> work-order closes


def test_maintainer_streams_carry_the_shared_audience_tag():
    """Absorption (shape) and freshness both go to the maintainer, so both carry drift:maintainer
    AND their own stream tag; the DevOps finding stream stays separate."""
    from agent.lib.delivery import _issue_labels
    assert _issue_labels("shape") == "drift-detector,drift:maintainer,drift:shape"
    assert _issue_labels("freshness") == "drift-detector,drift:maintainer,drift:freshness"
    assert _issue_labels(None) == "drift-detector,drift:devops"        # DevOps default, no maintainer tag


# --------------------------------------------------------------- pure helpers (new)
def test_resolve_owner_prefers_owner_then_maintainer_then_fallback():
    members = [{"id": 6, "username": "bo", "access_level": 40},   # Maintainer
               {"id": 5, "username": "ann", "access_level": 50}]  # Owner
    assert delivery.resolve_owner(members, 99) == 5                        # Owner (50) wins
    assert delivery.resolve_owner([{"id": 6, "access_level": 40}], 99) == 6   # Maintainer (40)
    assert delivery.resolve_owner([{"id": 7, "access_level": 30}], 99) == 99  # Developer -> fallback
    assert delivery.resolve_owner([], None) is None                       # nothing -> unassigned


def test_resolve_owner_is_deterministic_across_equal_access():
    members = [{"id": 8, "access_level": 50}, {"id": 3, "access_level": 50}]
    assert delivery.resolve_owner(members, None) == 3                      # lowest id among equal Owners


def test_repo_fingerprint_namespaced_by_stream_and_backcompat():
    assert delivery.repo_fingerprint("g/r") == delivery.repo_fingerprint("g/r", "")   # back-compat
    assert delivery.repo_fingerprint("g/r", "devops") != delivery.repo_fingerprint("g/r", "developer")


def test_devops_repo_body_bundles_actions_with_marker():
    acts = [{"kind": "eol", "ref": "php", "status": "DEPRECATED", "recommendation": "upgrade php"},
            {"kind": "cve", "ref": "guzzle", "status": "DEPRECATED"}]
    body = delivery.devops_repo_body("g/r", acts)
    assert "php" in body and "guzzle" in body
    assert delivery.marker(delivery.repo_fingerprint("g/r", "devops")) in body                  # idempotency marker present
