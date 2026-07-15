"""Guards the Claude Code plugin structure: valid manifest, the slash command
referencing the real CLI subcommand it drives, and a self-bootstrapping runner."""
import json
import os
import stat
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_plugin_manifest_valid():
    manifest = json.loads((_ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "drift-detector"
    assert manifest["description"] and manifest["version"]


def test_command_present_with_frontmatter_and_references_runner():
    cmd = (_ROOT / "commands" / "drift-detector.md").read_text()
    assert cmd.startswith("---") and "description:" in cmd and "argument-hint:" in cmd
    assert "drift-scan" in cmd and "$ARGUMENTS" in cmd          # drives the bundled runner over the arg


def test_bootstrap_runner_present_and_executable():
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


def test_mcp_server_launcher_and_tools():
    runner = _ROOT / "bin" / "drift-mcp"
    assert runner.exists() and os.stat(runner).st_mode & stat.S_IXUSR
    body = runner.read_text()
    assert "agent.mcp_server" in body and "requirements-mcp.txt" in body    # self-bootstraps + runs the server
    assert "mcp>=" in (_ROOT / "requirements-mcp.txt").read_text()
    server = (_ROOT / "agent" / "mcp_server.py").read_text()
    assert "FastMCP" in server
    for tool in ("list_repos", "query_integrations", "get_findings", "check_dependency", "check_runtime"):
        assert f"def {tool}" in server                                      # the 5 facade tools


def test_runner_and_command_support_audit_run_schedule():
    runner = (_ROOT / "bin" / "drift-scan").read_text()
    case_line = next(l for l in runner.splitlines() if l.strip().startswith("audit|run|"))
    for sub in ("audit", "run", "schedule", "unschedule", "mute", "preflight", "gitlab-sync"):
        assert sub in case_line                                  # runner dispatches every subcommand
    cmd = (_ROOT / "commands" / "drift-detector.md").read_text()
    assert "audit" in cmd and "bom.json" in cmd and "findings.sarif" in cmd
    assert "schedule" in cmd and "cron" in cmd.lower()          # agent offers autonomy
    from agent import cli
    assert all(hasattr(cli, n) for n in ("_cmd_audit", "_cmd_run", "_cmd_schedule", "_cmd_unschedule"))


def test_catalog_defaults_are_package_relative():
    # loaders must resolve their catalog regardless of the caller's cwd
    from agent.lib.vendors import _DEFAULT_VENDORS
    from agent.lib.frameworks import _DEFAULT_FRAMEWORKS
    assert Path(_DEFAULT_VENDORS).is_absolute() and Path(_DEFAULT_VENDORS).exists()
    assert Path(_DEFAULT_FRAMEWORKS).is_absolute() and Path(_DEFAULT_FRAMEWORKS).exists()


def test_command_asks_when_no_folder_and_documents_ir():
    cmd = (_ROOT / "commands" / "drift-detector.md").read_text()
    assert "No folder given" in cmd                                 # guards the empty-argument case
    assert "inventory.json" in cmd                                  # documents the queryable IR (folded in from the old skill)


def test_no_skill_dir():
    # single entry point: the slash command only, no skill (which showed as a duplicate)
    assert not (_ROOT / "skills").exists()


def test_referenced_cli_subcommand_exists():
    # the plugin drives `python -m agent.cli inventory-scan`; ensure that subcommand handler exists
    from agent import cli
    assert hasattr(cli, "_cmd_inventory_scan")


def test_marketplace_manifest_valid_and_matches_plugin():
    mp = json.loads((_ROOT / ".claude-plugin" / "marketplace.json").read_text())
    pj = json.loads((_ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert mp["name"] and mp["owner"]["name"]                    # required marketplace fields
    entry = next(p for p in mp["plugins"] if p["name"] == pj["name"])
    assert entry["source"] == "./"                              # plugin IS this repo root
