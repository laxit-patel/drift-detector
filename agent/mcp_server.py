"""Read-only MCP server over the Drift Detector artifacts + live checks.

Exposes the (unit-tested) `agent.lib.facade` functions as MCP tools so any host — Claude Code,
Claude Desktop, Cursor, Copilot agents — can ask "what integrations do we use / is this dep
safe" on demand. The killer tool is `check_dependency`: an assistant about to add a package
checks it FIRST, so drift is prevented rather than detected. Point it at a scan's state dir via
`--state <folder>/.drift-detector` (or the DRIFT_STATE env var).
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from agent.lib import facade

_STATE = os.environ.get("DRIFT_STATE", ".")
mcp = FastMCP("drift-detector")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@mcp.tool()
def list_repos() -> list:
    """List scanned repos with the third-party APIs, runtimes, and package counts each uses."""
    inv, _ = facade.load_state(_STATE)
    return facade.list_repos(inv)


@mcp.tool()
def query_integrations(vendor: str = "", repo: str = "") -> list:
    """Which repos call a third-party API (by vendor), or what a repo calls — with file:line call-sites."""
    inv, _ = facade.load_state(_STATE)
    return facade.query_integrations(inv, vendor or None, repo or None)


@mcp.tool()
def get_findings(repo: str = "", status: str = "") -> list:
    """Audit findings (CVE / end-of-life / vendor API sunset), optionally filtered by repo or status (DEPRECATED|REVIEW)."""
    _, audit = facade.load_state(_STATE)
    return facade.get_findings(audit, repo or None, status or None)


@mcp.tool()
def check_dependency(ecosystem: str, name: str, version: str) -> dict:
    """BEFORE adding or upgrading a dependency, check that exact version for known vulnerabilities (live OSV.dev).
    ecosystem is one of: npm, composer, python. Returns whether it is vulnerable + a recommended version."""
    return facade.check_dependency(ecosystem, name, version)


@mcp.tool()
def check_runtime(product: str, version: str) -> dict:
    """Check whether a runtime/framework version is end-of-life (live endoflife.date).
    product examples: node, php, python, laravel/framework, nextjs."""
    return facade.check_runtime(product, version, _today())


def main() -> None:
    global _STATE
    ap = argparse.ArgumentParser(prog="drift-mcp")
    ap.add_argument("--state", default=os.environ.get("DRIFT_STATE", "."),
                    help="the scan's .drift-detector state dir (holds inventory.json / audit.json)")
    _STATE = ap.parse_args().state
    mcp.run()          # stdio transport, blocking


if __name__ == "__main__":
    main()
