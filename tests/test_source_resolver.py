"""Ingestion: a checkout, a plain folder, or a URL all resolve to scannable projects."""
import os
import subprocess

import pytest

from agent.lib import source_resolver as sr


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _make_repo(path, filename="OrdersApi.php"):
    path.mkdir(parents=True, exist_ok=True)
    (path / filename).write_text('<?php $u="https://sellingpartnerapi-na.amazon.com/orders/v0/o";')
    _git(path, "init", "-q")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "x")


# --------------------------------------------------------------------- url classification
@pytest.mark.parametrize("u", ["https://git.topsdemo.in/chetan/amazonspapi",
                               "http://x/y", "git@github.com:o/r.git", "ssh://g/r",
                               "git://h/r"])
def test_urls_are_recognised(u):
    assert sr.is_url(u)


@pytest.mark.parametrize("p", ["/home/x/repo", "./rel", "../up", "C:/x", "repo"])
def test_local_paths_are_not_urls(p):
    assert not sr.is_url(p)


def test_slug_is_stable_and_disambiguates_shared_basenames():
    a = sr.slug("https://git.topsdemo.in/chetan/amazonspapi")
    b = sr.slug("https://github.com/other/amazonspapi")
    assert a == sr.slug("https://git.topsdemo.in/chetan/amazonspapi")   # stable
    assert a != b and "amazonspapi" in a                                # disambiguated
    assert "/" not in a and ":" not in a                                # fs-safe


# --------------------------------------------------------------------- the three shapes
def test_local_git_checkout(tmp_path):
    _make_repo(tmp_path / "repo")
    out = sr.resolve_sources([str(tmp_path / "repo")], str(tmp_path / "state"))
    assert not out["errors"]
    assert len(out["projects"]) == 1
    assert out["projects"][0][2] == "local-git"


def test_a_plain_folder_is_scanned_as_one_project(tmp_path):
    """The zip case: real code, no .git. Resolves to a project, kind local-plain."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "OrdersApi.php").write_text('<?php $u="https://x/orders/v0/o";')
    out = sr.resolve_sources([str(plain)], str(tmp_path / "state"))
    assert not out["errors"]
    assert len(out["projects"]) == 1
    assert out["projects"][0][2] == "local-plain"


def test_a_url_is_cloned_then_scanned(tmp_path):
    """Exercises the REAL clone path via a file:// URL — no network, same code."""
    _make_repo(tmp_path / "origin")
    url = f"file://{tmp_path / 'origin'}"
    state = tmp_path / "state"
    out = sr.resolve_sources([url], str(state))
    assert not out["errors"], out["errors"]
    assert len(out["projects"]) == 1
    abs_dir, ident, kind = out["projects"][0]
    assert kind == "remote"
    assert (state / "sources").as_posix() in abs_dir      # cloned under state/sources
    assert (state / "sources").exists()


def test_a_second_resolve_updates_the_existing_clone_not_re_clones(tmp_path):
    _make_repo(tmp_path / "origin")
    url = f"file://{tmp_path / 'origin'}"
    state = str(tmp_path / "state")
    first = sr.resolve_sources([url], state)["projects"][0][0]
    second = sr.resolve_sources([url], state)               # must not error on existing dir
    assert second["projects"][0][0] == first
    assert not second["errors"]


# --------------------------------------------------------------------- errors, never silent
def test_a_failing_clone_is_an_error_not_a_silent_drop(tmp_path):
    out = sr.resolve_sources(["https://no.such.host.invalid/x/y.git"], str(tmp_path / "s"),
                             clone=lambda url, dest: (False, "host not found"))
    assert out["projects"] == []
    assert out["errors"] and "could not clone" in out["errors"][0]["reason"]


def test_a_nonexistent_local_path_is_an_error(tmp_path):
    out = sr.resolve_sources([str(tmp_path / "nope")], str(tmp_path / "s"))
    assert out["projects"] == []
    assert out["errors"]


def test_an_empty_folder_with_no_code_is_an_error_not_a_project(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    out = sr.resolve_sources([str(empty)], str(tmp_path / "s"))
    assert out["projects"] == []
    assert out["errors"]


def test_one_or_many_mixed(tmp_path):
    _make_repo(tmp_path / "gitrepo")
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.py").write_text("import requests; requests.get('https://x/v1/y')")
    out = sr.resolve_sources([str(tmp_path / "gitrepo"), str(plain)], str(tmp_path / "s"))
    assert not out["errors"]
    kinds = sorted(k for _, _, k in out["projects"])
    assert kinds == ["local-git", "local-plain"]
