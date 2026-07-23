"""The GitHub Actions scan pipeline: ephemeral compute on GitHub, private data on GitLab.
Static guards on the workflow file (the run happens on GitHub, but the properties that would
silently break it — engine drift, a leaked token, a missing reachability gate — are in the
file)."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WF_PATH = ROOT / ".github" / "workflows" / "scan.yml"
WF_TEXT = WF_PATH.read_text()


def test_workflow_is_valid_yaml():
    yaml.safe_load(WF_TEXT)          # must parse (note: YAML 1.1 turns the `on:` key into True)


def test_runs_scheduled_and_on_demand():
    assert "workflow_dispatch" in WF_TEXT and "schedule" in WF_TEXT


def test_engine_pinned_sha_verified_and_matches_the_runner():
    v = re.search(r"AST_GREP_VERSION:\s*\"([0-9.]+)\"", WF_TEXT).group(1)
    assert re.search(r'AST_GREP_SHA256:\s*"[0-9a-f]{64}"', WF_TEXT)
    assert "sha256sum -c" in WF_TEXT and "releases/latest" not in WF_TEXT
    runner = re.search(r"DRIFT_AST_GREP_VERSION:-([0-9.]+)",
                       (ROOT / "bin" / "drift-scan").read_text()).group(1)
    assert v == runner


def test_checks_reachability_before_scanning():
    """GitHub runners are on the public internet; the first step must prove it can reach the
    private GitLab (and that the token works) with a clear error, not fail cryptically mid-run."""
    assert "/api/v4/version" in WF_TEXT
    assert WF_TEXT.index("/api/v4/version") < WF_TEXT.index("agent.cli run")


def test_scans_then_verifies_then_persists():
    assert "agent.cli run" in WF_TEXT and "agent.cli verify" in WF_TEXT
    assert WF_TEXT.index("agent.cli run") < WF_TEXT.index("agent.cli verify")
    assert "git push origin" in WF_TEXT          # state pushed back to drift-ops


def test_overlay_is_wired_from_drift_ops():
    assert "DRIFT_CATALOG_DIR:" in WF_TEXT and "drift-ops/catalog" in WF_TEXT
    assert "drift-ops/config/fleet.yaml" in WF_TEXT


def test_token_comes_from_a_secret_never_a_literal():
    assert "secrets.GITLAB_TOKEN" in WF_TEXT
    assert not re.search(r"glpat-[A-Za-z0-9_-]{15,}", WF_TEXT)


def test_only_reads_this_repo_writes_go_to_gitlab():
    wf = yaml.safe_load(WF_TEXT)
    assert wf["permissions"]["contents"] == "read"      # no write-back to the GitHub repo
