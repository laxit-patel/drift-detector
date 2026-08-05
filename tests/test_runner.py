"""Guards the standalone runner (`bin/drift-scan`) and the intake doctrine
(`docs/drift-absorb.md`) — the Claude-plugin scaffolding was stripped; the tool
stands on its own now, but the runner's engine pin + subcommand dispatch and the
absorb gate's guardrails are still load-bearing."""
import os
import stat
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_runner_present_and_executable():
    runner = _ROOT / "bin" / "drift-scan"
    assert runner.exists()
    assert os.stat(runner).st_mode & stat.S_IXUSR                # executable bit set
    body = runner.read_text()
    assert "agent.cli inventory-scan" in body                   # drives the real CLI
    assert "requirements-plugin.txt" in body                    # installs the lean runtime deps
    assert (_ROOT / "requirements-plugin.txt").exists()


def test_runner_has_doctor_with_actionable_hint():
    body = (_ROOT / "bin" / "drift-scan").read_text()
    assert '"${1:-}" = "doctor"' in body                        # doctor health-check mode
    assert "astral.sh/uv/install.sh" in body                    # exact uv install remediation


def test_runner_dispatches_every_subcommand():
    runner = (_ROOT / "bin" / "drift-scan").read_text()
    case_line = next(l for l in runner.splitlines() if l.strip().startswith("audit|run|"))
    for sub in ("audit", "run", "deliver", "schedule", "unschedule", "mute", "preflight", "absorb", "verify"):
        assert sub in case_line                                  # runner dispatches every subcommand
    assert "gitlab-sync" not in case_line                        # connector stripped on hybrid (see master)
    from agent import cli
    assert all(hasattr(cli, n) for n in ("_cmd_audit", "_cmd_run", "_cmd_schedule", "_cmd_unschedule"))


def test_referenced_cli_subcommand_exists():
    # the runner defaults to `python -m agent.cli inventory-scan`; ensure that handler exists
    from agent import cli
    assert hasattr(cli, "_cmd_inventory_scan")


def test_catalog_defaults_are_package_relative():
    # loaders must resolve their catalog regardless of the caller's cwd (the runner never chdirs)
    from agent.lib.vendors import _DEFAULT_VENDORS
    from agent.lib.frameworks import _DEFAULT_FRAMEWORKS
    assert Path(_DEFAULT_VENDORS).is_absolute() and Path(_DEFAULT_VENDORS).exists()
    assert Path(_DEFAULT_FRAMEWORKS).is_absolute() and Path(_DEFAULT_FRAMEWORKS).exists()


def test_absorb_doctrine_present_and_states_its_guardrails():
    """The absorb gate's procedure — moved from a plugin command to `docs/` doctrine — is the
    contract that keeps agent output out of the catalogs unreviewed. Its guardrails are
    load-bearing, not decoration (each pins a real way the intake has been burned)."""
    doc = (_ROOT / "docs" / "drift-absorb.md")
    assert doc.exists(), "the intake doctrine must survive the plugin strip"
    cmd = doc.read_text()
    # it drives the real CLI, not an invented flow
    assert "drift-scan" in cmd and "absorb --staged" in cmd and "recommend" in cmd
    assert "absorb --check" in cmd                              # the iteration instrument (measure without committing)
    # the guardrails that exist because they were violated for real
    assert "did not open" in cmd.lower() or "did not fetch" in cmd.lower()
    assert "source" in cmd.lower() and "staged" in cmd.lower()
    assert "Never edit" in cmd and "vendor_sunsets.yaml" in cmd  # never a direct write to the catalogs
    # the overlay hand-off must be wired (absorb must NOT write installed catalogs)
    assert "DRIFT_CATALOG_DIR" in cmd and "DRIFT_OPS_DIR" in cmd
    assert "mr create" in cmd or "merge request" in cmd.lower()  # handed back to drift-ops


def test_no_plugin_scaffolding_remains():
    # the Claude-plugin surface was intentionally stripped (it moves to a separate future repo)
    assert not (_ROOT / ".claude-plugin").exists()
    assert not (_ROOT / "commands").exists()
    assert not (_ROOT / "skills").exists()
