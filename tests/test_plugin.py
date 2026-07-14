"""Guards the Claude Code plugin structure: valid manifest, command + skill present and
referencing the real CLI subcommand they drive."""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_plugin_manifest_valid():
    manifest = json.loads((_ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "integration-inventory"
    assert manifest["description"] and manifest["version"]


def test_command_present_with_frontmatter_and_references_cli():
    cmd = (_ROOT / "commands" / "integration-inventory.md").read_text()
    assert cmd.startswith("---") and "description:" in cmd and "argument-hint:" in cmd
    assert "inventory-scan" in cmd and "$ARGUMENTS" in cmd          # drives the real CLI over the arg


def test_skill_present_with_frontmatter():
    skill = (_ROOT / "skills" / "integration-inventory" / "SKILL.md").read_text()
    assert skill.startswith("---") and "name: integration-inventory" in skill
    assert "inventory.json" in skill                                # documents the queryable IR


def test_referenced_cli_subcommand_exists():
    # the plugin drives `python -m agent.cli inventory-scan`; ensure that subcommand handler exists
    from agent import cli
    assert hasattr(cli, "_cmd_inventory_scan")
