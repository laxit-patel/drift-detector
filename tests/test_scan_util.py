import pytest
from agent.lib.scan_util import git_meta, resolve_engine


def test_git_meta_from_injected_run():
    calls = []

    def fake(args):
        calls.append(args)
        return {"rev-parse HEAD": "abc123",
                "rev-parse --abbrev-ref HEAD": "main",
                "log -1 --format=%cI": "2026-07-10T00:00:00Z"}[" ".join(args[2:])]

    meta = git_meta("/repo", run=fake)
    assert meta == {"head_sha": "abc123", "ref": "main",
                    "last_activity_at": "2026-07-10T00:00:00Z", "ref_is_default": True}
    assert calls[0][:2] == ["-C", "/repo"]                      # git -C <repo> ...


def test_git_meta_empty_when_no_git():
    meta = git_meta("/repo", run=lambda args: "")
    assert meta["head_sha"] == "" and meta["ref"] == ""


def test_resolve_engine_raises_when_absent(monkeypatch):
    import agent.lib.scan_util as su
    monkeypatch.setattr(su.shutil, "which", lambda name: None)
    monkeypatch.setattr(su.os.path, "exists", lambda p: False)
    with pytest.raises(RuntimeError, match="engine"):
        resolve_engine()


def test_resolve_engine_finds_on_path(monkeypatch):
    import agent.lib.scan_util as su
    monkeypatch.setattr(su.shutil, "which", lambda name: "/usr/bin/semgrep" if name == "semgrep" else None)
    assert resolve_engine() == "/usr/bin/semgrep"
