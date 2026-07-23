"""The drift-ops deployment scaffold. Static guards on the shipped template — the CI itself
runs on GitLab, but the properties that would silently break a deployment (a push-triggered
commit loop, an unpinned image, a leaked token) are checkable from the files."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent / "deploy" / "drift-ops"
CI = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text())
CI_TEXT = (ROOT / ".gitlab-ci.yml").read_text()


def test_pipeline_never_runs_on_push():
    """The persist job pushes a commit back; running on push would loop forever. The
    workflow must allow only schedule + manual and end in `when: never`."""
    rules = CI["workflow"]["rules"]
    assert any(r.get("if", "").endswith('"schedule"') for r in rules)
    assert rules[-1] == {"when": "never"}


def test_state_commit_cannot_trigger_a_pipeline():
    assert "[skip ci]" in CI_TEXT                       # belt-and-braces against the loop


def test_runs_on_a_stock_public_image_no_registry_needed():
    assert CI["default"]["image"] == "python:3.12-slim"


def test_engine_is_pinned_sha_verified_and_matches_the_runner():
    """Container-free: the engine is fetched at run time, so determinism rides on the version
    pin + sha256 check (no 'latest' fallback), and the pin must match the plugin runner."""
    v = CI["variables"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(v["AST_GREP_VERSION"]))
    assert re.fullmatch(r"[0-9a-f]{64}", str(v["AST_GREP_SHA256"]))
    assert "sha256sum -c" in CI_TEXT and "releases/latest" not in CI_TEXT
    runner = re.search(r"DRIFT_AST_GREP_VERSION:-([0-9.]+)",
                       (Path(__file__).resolve().parent.parent / "bin" / "drift-scan").read_text())
    assert str(v["AST_GREP_VERSION"]) == runner.group(1)   # no drift across the two


def test_overlay_and_serialisation_are_configured():
    assert CI["variables"]["DRIFT_CATALOG_DIR"] == "catalog"
    assert CI["scan"]["resource_group"]                 # no two runs race on the state push


def test_every_script_line_is_a_string():
    """GitLab rejects a script item that parses as anything but a string. A ': ' in a
    command (e.g. a commit message) turns the line into a YAML mapping unless it's quoted —
    which is exactly the config error that failed the first pipeline."""
    for job in ("scan", "persist"):
        for i, item in enumerate(CI[job]["script"]):
            assert isinstance(item, str), f"{job}:script[{i}] is {type(item).__name__}: {item!r}"


def test_scan_verifies_before_persisting():
    script = " ".join(CI["scan"]["script"])
    assert "agent.cli run" in script and "agent.cli verify" in script
    assert CI["persist"]["needs"] == ["scan"]           # persist only after a green scan


def test_scanner_is_on_the_pythonpath():
    assert "scanner" in CI["variables"]["PYTHONPATH"]   # the bundled agent/ package


def test_fleet_config_is_a_nonempty_root_list():
    fleet = yaml.safe_load((ROOT / "config" / "fleet.yaml").read_text())
    assert isinstance(fleet.get("roots"), list) and fleet["roots"]
    assert all(r.startswith("https://") for r in fleet["roots"])


def test_clones_and_cache_are_gitignored_but_reports_are_not():
    ign = (ROOT / ".gitignore").read_text()
    assert "state/sources/" in ign and "state/repos_v" in ign
    assert "drift.json" not in ign                      # reports ARE committed


def test_no_token_is_committed_in_the_scaffold():
    """No real PAT ever lands in the template — auth is a masked CI variable at run time."""
    for p in ROOT.rglob("*"):
        if p.is_file():
            assert not re.search(r"glpat-[A-Za-z0-9_-]{15,}", p.read_text(errors="ignore"))
