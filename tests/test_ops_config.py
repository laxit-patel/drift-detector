"""drift.yml — the one operational config. Malformed config is an ERROR, never guessed."""
import pytest

from agent.lib import ops_config


def _write(tmp_path, text):
    p = tmp_path / "drift.yml"
    p.write_text(text)
    return str(p)


_GOOD = """
version: 1
fleet:
  - https://git.x/g/a
  - https://git.x/g/b
delivery:
  mode: live
  dev_as_issues: true
  devops_project: root/ops
"""


def test_valid_config_loads_and_derives_the_host(tmp_path):
    cfg = ops_config.load(_write(tmp_path, _GOOD))
    assert cfg["fleet"] == ["https://git.x/g/a", "https://git.x/g/b"]
    assert cfg["host"] == "git.x"                              # derived from the fleet URLs
    assert cfg["delivery"] == {"mode": "live", "dev_as_issues": True,
                               "devops_project": "root/ops"}


def test_delivery_defaults_when_omitted(tmp_path):
    cfg = ops_config.load(_write(tmp_path, "fleet: [https://git.x/g/a]\n"))
    assert cfg["delivery"] == {"mode": "dry-run", "dev_as_issues": False, "devops_project": None}


def test_empty_fleet_is_an_error(tmp_path):
    with pytest.raises(ops_config.ConfigError):
        ops_config.load(_write(tmp_path, "fleet: []\n"))


def test_non_https_fleet_entry_is_an_error(tmp_path):
    with pytest.raises(ops_config.ConfigError):
        ops_config.load(_write(tmp_path, "fleet: [git@git.x:g/a.git]\n"))


def test_mixed_hosts_are_rejected(tmp_path):
    with pytest.raises(ops_config.ConfigError):
        ops_config.load(_write(tmp_path, "fleet:\n  - https://a.x/g/a\n  - https://b.x/g/b\n"))


def test_unknown_top_key_is_an_error_not_ignored(tmp_path):
    # a typo must not silently disable something
    with pytest.raises(ops_config.ConfigError):
        ops_config.load(_write(tmp_path, "fleet: [https://git.x/g/a]\ndelivry: {}\n"))


def test_bad_delivery_mode_is_rejected(tmp_path):
    with pytest.raises(ops_config.ConfigError):
        ops_config.load(_write(tmp_path,
                               "fleet: [https://git.x/g/a]\ndelivery:\n  mode: yolo\n"))


def test_unknown_delivery_key_is_an_error(tmp_path):
    with pytest.raises(ops_config.ConfigError):
        ops_config.load(_write(tmp_path,
                               "fleet: [https://git.x/g/a]\ndelivery:\n  drymode: true\n"))
