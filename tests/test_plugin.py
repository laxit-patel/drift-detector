"""Guards the Claude Code plugin structure: valid manifest, command + skill present and
referencing the real CLI subcommand they drive, and a self-bootstrapping runner."""
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


def test_catalog_defaults_are_package_relative():
    # loaders must resolve their catalog regardless of the caller's cwd
    from agent.lib.vendors import _DEFAULT_VENDORS
    from agent.lib.frameworks import _DEFAULT_FRAMEWORKS
    assert Path(_DEFAULT_VENDORS).is_absolute() and Path(_DEFAULT_VENDORS).exists()
    assert Path(_DEFAULT_FRAMEWORKS).is_absolute() and Path(_DEFAULT_FRAMEWORKS).exists()


def test_skill_present_with_frontmatter():
    skill = (_ROOT / "skills" / "drift-detector" / "SKILL.md").read_text()
    assert skill.startswith("---") and "name: drift-detector" in skill
    assert "inventory.json" in skill                                # documents the queryable IR


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
