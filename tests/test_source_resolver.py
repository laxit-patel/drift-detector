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


# ------------------------------------------------- the private-URL auth path (security)
def test_token_is_passed_to_git_but_never_written_to_argv_or_disk(tmp_path, monkeypatch):
    """The claim behind 'clone reuses machine auth, token never persisted': a GITLAB_TOKEN
    must reach git via a credential helper that READS the env var at run time, so the
    secret value never appears in the process argv (visible in `ps`) nor in .git/config.
    """
    import subprocess as _sp
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["env_has_token"] = "DRIFT_CLONE_TOKEN" in (kw.get("env") or {})
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    monkeypatch.setattr(_sp, "run", fake_run)
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-SECRETVALUE123")
    ok, _ = sr._default_clone("https://git.topsdemo.in/chetan/amazonspapi.git",
                              str(tmp_path / "dest"))
    assert ok
    argv = " ".join(captured["cmd"])
    # the credential helper is wired, referencing the ENV VAR, not the literal secret
    assert "credential.helper" in argv
    assert "DRIFT_CLONE_TOKEN" in argv          # the env var name is referenced
    assert "glpat-SECRETVALUE123" not in argv   # the SECRET itself is never in argv
    assert captured["env_has_token"]            # it travels in the environment instead


def test_no_token_means_plain_clone_reusing_machine_auth(tmp_path, monkeypatch):
    """With no token in the env, the tool adds no credential args at all — git uses the
    machine's own helper / SSH keys, exactly 'reuse machine auth'."""
    import subprocess as _sp
    captured = {}
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("DRIFT_GIT_TOKEN", raising=False)

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    monkeypatch.setattr(_sp, "run", fake_run)
    sr._default_clone("https://x/y.git", str(tmp_path / "d"))
    assert "credential.helper" not in " ".join(captured["cmd"])


def test_clone_via_https_does_not_persist_a_token_in_git_config(tmp_path):
    """End-to-end on a real (file://) clone with a token set: the stored remote URL must
    be tokenless. file:// ignores the token, but the non-persistence property is the same
    code path and is what a leaked-secret audit would check."""
    import os
    _make_repo(tmp_path / "origin")
    dest = tmp_path / "dest"
    os.environ["GITLAB_TOKEN"] = "glpat-SHOULDNOTPERSIST"
    try:
        ok, _ = sr._default_clone(f"file://{tmp_path/'origin'}", str(dest))
    finally:
        del os.environ["GITLAB_TOKEN"]
    assert ok
    cfg = (dest / ".git" / "config").read_text()
    assert "glpat-SHOULDNOTPERSIST" not in cfg, "a token must never be written to .git/config"
