from pathlib import Path

import yaml

from agent import cli

_ROOT = Path(__file__).resolve().parent.parent


def _run_args(tmp_path, *extra):
    return ["run", "--root", str(tmp_path), "--state", str(tmp_path / "s"),
            "--now", "2026-07-15", *extra]


def test_fail_on_deprecated_exit_code(monkeypatch, tmp_path):
    import agent.run as run_mod

    def counts(dep, rev=0):
        return lambda *a, **k: {"scope": {}, "auditCounts": {"DEPRECATED": dep, "REVIEW": rev}, "delivered": []}

    monkeypatch.setattr(run_mod, "run_pipeline", counts(2))
    assert cli.main(_run_args(tmp_path, "--fail-on-deprecated")) == 3      # gate trips

    monkeypatch.setattr(run_mod, "run_pipeline", counts(0, 3))
    assert cli.main(_run_args(tmp_path, "--fail-on-deprecated")) == 0      # only REVIEW -> passes

    monkeypatch.setattr(run_mod, "run_pipeline", counts(5))
    assert cli.main(_run_args(tmp_path)) == 0                              # no flag -> never fails


def test_composite_action_valid():
    action = yaml.safe_load((_ROOT / "action.yml").read_text())
    assert action["runs"]["using"] == "composite"
    for inp in ("path", "fail-on-deprecated", "upload-sarif", "chat-webhook"):
        assert inp in action["inputs"]
    body = (_ROOT / "action.yml").read_text()
    assert "bin/drift-scan" in body and "run \\" in body                  # runs the deterministic pipeline
    assert "codeql-action/upload-sarif" in body                           # -> Security tab / PR alerts


def test_reference_workflow_shape():
    text = (_ROOT / "examples" / "drift-ci.yml").read_text()
    assert "security-events: write" in text                              # needed for upload-sarif
    assert "schedule:" in text and "pull_request:" in text               # both modes
    assert "laxit-patel/drift-detector@" in text                         # references the action
