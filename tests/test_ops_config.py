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
                               "devops_project": "root/ops", "shape_stream": False}


def test_delivery_defaults_when_omitted(tmp_path):
    # default developer target is `issues` (Reporter-friendly) — MRs need Developer access the
    # deployment may not have, so the safe default routes developer findings to issues too.
    cfg = ops_config.load(_write(tmp_path, "fleet: [https://git.x/g/a]\n"))
    assert cfg["delivery"] == {"mode": "dry-run", "dev_as_issues": True,
                               "devops_project": None, "shape_stream": False}


def test_shape_stream_opt_in(tmp_path):
    cfg = ops_config.load(_write(tmp_path,
        "fleet: [https://git.x/g/a]\ndelivery:\n  shape_stream: true\n"))
    assert cfg["delivery"]["shape_stream"] is True
    # orthogonal to the v1/v2 forms — combining with either is NOT a mix error
    cfg2 = ops_config.load(_write(tmp_path,
        "fleet: [https://git.x/g/a]\ndelivery:\n  shape_stream: true\n  developer: {target: mrs}\n"))
    assert cfg2["delivery"]["shape_stream"] is True and cfg2["delivery"]["dev_as_issues"] is False


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


# --- v2: auth env-var NAMES, notify, per-stream developer target -----------------

def test_auth_defaults_to_one_token_when_omitted(tmp_path):
    """Schema-ready for split tokens, but a config that says nothing keeps working on a single
    GITLAB_TOKEN — the auth block holds env-var NAMES (never secrets), all defaulting to it."""
    cfg = ops_config.load(_write(tmp_path, "fleet: [https://git.x/g/a]\n"))
    assert cfg["auth"] == {"clone": "GITLAB_TOKEN", "persist": "GITLAB_TOKEN",
                           "deliver": "GITLAB_TOKEN"}


def test_auth_names_are_taken_and_missing_ones_fall_back(tmp_path):
    cfg = ops_config.load(_write(tmp_path,
        "fleet: [https://git.x/g/a]\nauth:\n  deliver: DELIVER_PAT\n"))
    assert cfg["auth"] == {"clone": "GITLAB_TOKEN", "persist": "GITLAB_TOKEN",
                           "deliver": "DELIVER_PAT"}


def test_auth_must_hold_names_not_secrets(tmp_path):
    # a value that looks like a real token is almost certainly a mistake — refuse it
    with pytest.raises(ops_config.ConfigError):
        ops_config.load(_write(tmp_path,
            "fleet: [https://git.x/g/a]\nauth:\n  deliver: glpat-abcdefghij0123456789\n"))


def test_unknown_auth_key_is_an_error(tmp_path):
    with pytest.raises(ops_config.ConfigError):
        ops_config.load(_write(tmp_path,
            "fleet: [https://git.x/g/a]\nauth:\n  push: X\n"))


def test_notify_gchat_is_an_env_name_and_defaults_off(tmp_path):
    cfg = ops_config.load(_write(tmp_path, "fleet: [https://git.x/g/a]\n"))
    assert cfg["notify"] == {"gchat": None}
    cfg2 = ops_config.load(_write(tmp_path,
        "fleet: [https://git.x/g/a]\nnotify:\n  gchat: GCHAT_WEBHOOK\n"))
    assert cfg2["notify"] == {"gchat": "GCHAT_WEBHOOK"}


def test_unknown_notify_key_is_an_error(tmp_path):
    with pytest.raises(ops_config.ConfigError):
        ops_config.load(_write(tmp_path,
            "fleet: [https://git.x/g/a]\nnotify:\n  slack: X\n"))


def test_developer_target_mrs_maps_to_dev_as_issues_false(tmp_path):
    cfg = ops_config.load(_write(tmp_path,
        "fleet: [https://git.x/g/a]\ndelivery:\n  developer: {target: mrs}\n"))
    assert cfg["delivery"]["dev_as_issues"] is False


def test_developer_target_issues_maps_to_dev_as_issues_true(tmp_path):
    cfg = ops_config.load(_write(tmp_path,
        "fleet: [https://git.x/g/a]\ndelivery:\n  developer: {target: issues}\n"))
    assert cfg["delivery"]["dev_as_issues"] is True


def test_devops_project_can_be_set_via_the_stream_block(tmp_path):
    cfg = ops_config.load(_write(tmp_path,
        "fleet: [https://git.x/g/a]\ndelivery:\n  devops: {project: root/ops}\n"))
    assert cfg["delivery"]["devops_project"] == "root/ops"


def test_bad_developer_target_is_rejected(tmp_path):
    with pytest.raises(ops_config.ConfigError):
        ops_config.load(_write(tmp_path,
            "fleet: [https://git.x/g/a]\ndelivery:\n  developer: {target: carrier-pigeon}\n"))


def test_mixing_v1_and_v2_delivery_forms_is_rejected(tmp_path):
    # dev_as_issues (v1) and developer: (v2) say the same thing two ways — ambiguous, refuse it
    with pytest.raises(ops_config.ConfigError):
        ops_config.load(_write(tmp_path,
            "fleet: [https://git.x/g/a]\ndelivery:\n"
            "  dev_as_issues: true\n  developer: {target: mrs}\n"))


def test_probe_accept_defaults_empty(tmp_path):
    cfg = ops_config.load(_write(tmp_path, "fleet: [https://git.x/g/a]\n"))
    assert cfg["probe"] == {"accept": []}


def test_probe_accept_parses_gap_and_reason(tmp_path):
    cfg = ops_config.load(_write(tmp_path,
        "fleet: [https://git.x/g/a]\nprobe:\n  accept:\n"
        "    - {gap: 'repo:ebayapinew', reason: 'decommissioned next sprint'}\n"))
    assert cfg["probe"]["accept"] == [{"gap": "repo:ebayapinew",
                                       "reason": "decommissioned next sprint"}]


def test_probe_accept_without_reason_is_refused(tmp_path):
    # a blind spot may be accepted, never SILENTLY — mirrors never-invent-a-date
    try:
        ops_config.load(_write(tmp_path,
            "fleet: [https://git.x/g/a]\nprobe:\n  accept:\n    - {gap: 'repo:x'}\n"))
        assert False, "expected ConfigError for a reasonless acceptance"
    except ops_config.ConfigError as exc:
        assert "reason" in str(exc)
