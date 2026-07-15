from agent.lib import schedule


class FakeCrontab:
    """In-memory stand-in for the crontab command."""
    def __init__(self, initial=""):
        self.content = initial

    def __call__(self, action, content=None):
        if action == "read":
            return self.content
        self.content = content or ""
        return ""


def test_install_writes_wrapper_and_one_marked_line(tmp_path):
    state = tmp_path / "state"
    ct = FakeCrontab(initial="0 0 * * * echo existing\n")
    line = schedule.install_cron(str(tmp_path / "repos"), str(state), "0 7 * * 0",
                                 plugin_root="/plug", chat_webhook="https://hook",
                                 path_env="/usr/bin:/home/u/.local/bin", crontab_run=ct)
    # wrapper script (values are shlex-quoted; safe strings render unquoted)
    wrapper = state / "cron-run.sh"
    body = wrapper.read_text()
    assert "/plug/bin/drift-scan" in body and "run --root" in body
    assert "--chat-webhook" in body and "https://hook" in body
    assert "export PATH=" in body and "/usr/bin:/home/u/.local/bin" in body
    assert wrapper.stat().st_mode & 0o100                       # executable
    # crontab: existing line preserved + one marked line added
    assert "echo existing" in ct.content
    assert ct.content.count("# drift-detector:") == 1
    assert line in ct.content and line.startswith("0 7 * * 0")
    # config persisted
    cfg = schedule.load_config(str(state))
    assert cfg["schedule"] == "0 7 * * 0" and cfg["connectors"]["chat"]["webhookUrl"] == "https://hook"


def test_reinstall_is_idempotent(tmp_path):
    state = str(tmp_path / "state")
    ct = FakeCrontab()
    schedule.install_cron(str(tmp_path / "r"), state, "0 7 * * 0", plugin_root="/p", crontab_run=ct)
    schedule.install_cron(str(tmp_path / "r"), state, "30 6 * * 1", plugin_root="/p", crontab_run=ct)
    assert ct.content.count("# drift-detector:") == 1           # replaced, not duplicated
    assert "30 6 * * 1" in ct.content and "0 7 * * 0" not in ct.content


def test_unschedule_removes_only_this_folders_line(tmp_path):
    state_a = str(tmp_path / "a")
    state_b = str(tmp_path / "b")
    ct = FakeCrontab(initial="0 0 * * * keep-me\n")
    schedule.install_cron(str(tmp_path / "ra"), state_a, "0 7 * * 0", plugin_root="/p", crontab_run=ct)
    schedule.install_cron(str(tmp_path / "rb"), state_b, "0 8 * * 0", plugin_root="/p", crontab_run=ct)
    assert ct.content.count("# drift-detector:") == 2

    removed = schedule.remove_cron(state_a, crontab_run=ct)
    assert removed is True
    assert ct.content.count("# drift-detector:") == 1           # only b's line remains
    assert "keep-me" in ct.content                              # unrelated line untouched
    assert schedule.remove_cron(state_a, crontab_run=ct) is False   # already gone


def test_install_aborts_on_ambiguous_crontab_read_failure(tmp_path):
    # a read failure that is NOT "no crontab" must abort, never overwrite the real crontab
    import subprocess as sp
    from agent.lib import schedule as sched

    def read_boom(cmd, capture_output=True, text=True, **kw):
        if cmd[:2] == ["crontab", "-l"]:
            return sp.CompletedProcess(cmd, 1, stdout="", stderr="crontab: permission denied")
        raise AssertionError("must not reach the write step")

    import pytest
    monkey = pytest.MonkeyPatch()
    monkey.setattr(sched.subprocess, "run", read_boom)
    try:
        with pytest.raises(RuntimeError, match="overwriting"):
            sched.install_cron(str(tmp_path / "r"), str(tmp_path / "s"), "0 7 * * 0", plugin_root="/p")
    finally:
        monkey.undo()


def test_shlex_quotes_path_with_spaces(tmp_path):
    import os
    import shlex
    ct = FakeCrontab()
    state = tmp_path / "sp ace"
    schedule.install_cron(str(tmp_path / "re po"), str(state), "0 7 * * 0",
                          plugin_root="/p", crontab_run=ct)
    body = (state / "cron-run.sh").read_text()
    # the space-containing root is safely quoted (no bare `--root .../re po` that cron would split)
    assert shlex.quote(os.path.abspath(str(tmp_path / "re po"))) in body
