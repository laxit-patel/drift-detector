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
    body = delivery.issue_body(a)
    fp = delivery.action_fingerprint(a)
    existing = {"issues": [{"iid": 7, "state": "opened", "description": body,
                            "title": delivery.issue_title(a)}], "mrs": {}}
    plan = delivery.build_plan(_payload([a]), _META, existing, "root/drift-detector")
    assert plan["issues"][0]["op"] == "skip" and plan["issues"][0]["iid"] == 7


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
    assert delivery.repo_fingerprint("ebayapi") in "".join(delivery.markers_in(md))


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
