"""A scan that discovers nothing must never read as a clean bill.

The PM pointed the tool at a local folder of Amazon SP-API code and got a green
checkmark with zero findings — because the folder had no .git, discover_repos returned
[], and the pipeline reported "0 action-required" at exit 0. "Cannot see" rendered
identically to "clean", which is the one collapse this whole project exists to refuse.
"""
import os

import pytest

from agent.lib.repo_discovery import diagnose_root


def test_url_is_diagnosed_as_a_url_not_silently_dropped():
    r = diagnose_root("https://git.topsdemo.in/chetan/amazonspapi")
    assert r and "URL" in r


def test_ssh_remote_is_diagnosed():
    assert "URL" in diagnose_root("git@github.com:owner/repo.git")


def test_nonexistent_path_is_diagnosed():
    assert "does not exist" in diagnose_root("/no/such/path/xyz")


def test_a_plain_source_folder_is_diagnosed_not_scanned(tmp_path):
    (tmp_path / "OrdersApi.php").write_text('<?php $u="https://x/orders/v0/o";')
    r = diagnose_root(str(tmp_path))
    assert r and "no .git" in r and "git init" in r


def test_a_real_git_repo_is_not_flagged(tmp_path):
    (tmp_path / "a.php").write_text("<?php")
    os.system(f"cd {tmp_path} && git init -q && git add -A && "
              f"git -c user.email=x@x -c user.name=x commit -qm x")
    assert diagnose_root(str(tmp_path)) is None


def test_zero_repos_scanned_exits_4_not_0(tmp_path):
    """The end-to-end guarantee: a run that scans nothing returns 'couldn't verify',
    never success."""
    from agent.cli import main
    src = tmp_path / "src"
    src.mkdir()
    (src / "OrdersApi.php").write_text('<?php $u="https://sellingpartnerapi-na.amazon.com/orders/v0/o";')
    state = tmp_path / "state"
    rc = main(["run", "--root", str(src), "--state", str(state), "--now", "2026-07-21"])
    assert rc == 4, "a scan of zero repos must exit 4 (couldn't verify), not 0 (clean)"
