import re

from agent.lib import gitlab
from agent import gitlab_sync

_A = {"id": 1, "path_with_namespace": "grp/a", "http_url_to_repo": "https://gl/grp/a.git",
      "default_branch": "main", "last_activity_at": "2026-07-01T00:00:00Z", "archived": False}
_OLD = {"id": 2, "path_with_namespace": "grp/old", "http_url_to_repo": "https://gl/grp/old.git",
        "default_branch": "main", "last_activity_at": "2020-01-01T00:00:00Z", "archived": False}
_ARCH = {"id": 3, "path_with_namespace": "grp/arch", "http_url_to_repo": "https://gl/grp/arch.git",
         "last_activity_at": "2026-07-01T00:00:00Z", "archived": True}
_B = {"id": 4, "path_with_namespace": "grp/b", "http_url_to_repo": "https://gl/grp/b.git",
      "last_activity_at": "2026-07-10T00:00:00Z", "archived": False}


def _page_of(url):
    # NB: anchor on [?&] — a bare `page=` also matches inside `per_page=`
    return int(re.search(r"[?&]page=(\d+)", url).group(1))


def _paged_get(url, token):
    """Two FULL pages of 2 then empty — exercises pagination (used with per_page=2)."""
    assert token == "glpat-XXX"
    return {1: [_A, _OLD], 2: [_ARCH, _B]}.get(_page_of(url), [])


def _all_get(url, token):
    """One short page — what the real API returns when total < per_page."""
    assert token == "glpat-XXX"
    return [_A, _OLD, _ARCH, _B] if _page_of(url) == 1 else []


def test_list_projects_paginates_and_drops_archived():
    projs = gitlab.list_projects("https://gl", "glpat-XXX", per_page=2, get=_paged_get)
    assert [p["path"] for p in projs] == ["grp/a", "grp/old", "grp/b"]      # grp/arch dropped


def test_list_projects_group_vs_membership_urls():
    seen = []

    def spy(url, token):
        seen.append(url)
        return []
    gitlab.list_projects("https://gl/", "glpat-XXX", group="team/sub", get=spy)
    assert "/api/v4/groups/team%2Fsub/projects" in seen[0] and "include_subgroups=true" in seen[0]
    seen.clear()
    gitlab.list_projects("https://gl", "glpat-XXX", get=spy)
    assert "/api/v4/projects?membership=true" in seen[0]


def test_sync_clones_and_strips_token_from_config(tmp_path):
    calls = []
    out = gitlab_sync.sync("https://gl", "glpat-XXX", str(tmp_path), get=_all_get,
                           git=lambda args, cwd=None: calls.append(list(args)))
    assert set(out["synced"]) == {"grp/a", "grp/old", "grp/b"}
    joined = " ".join(" ".join(a) for a in calls)
    assert "clone --depth 1 https://oauth2:glpat-XXX@gl/grp/a.git" in joined   # token used transiently
    # each clone is followed by remote set-url back to the PLAIN url -> no token left in .git/config
    assert "remote set-url origin https://gl/grp/a.git" in joined
    assert "glpat-XXX" not in " ".join(calls[-1])


def test_sync_active_days_filter():
    out = gitlab_sync.sync("https://gl", "glpat-XXX", "/tmp/x", active_days=90, now="2026-07-15",
                           get=_all_get, git=lambda a, cwd=None: None)
    assert set(out["synced"]) == {"grp/a", "grp/b"}          # grp/old (2020) filtered out


def test_sync_best_effort_on_clone_failure():
    def flaky_git(args, cwd=None):
        if args and args[0] == "clone" and "grp/a" in " ".join(args):
            raise RuntimeError("boom")

    out = gitlab_sync.sync("https://gl", "glpat-XXX", "/tmp/x", get=_all_get, git=flaky_git)
    assert out["failed"][0]["repo"] == "grp/a"              # one failure doesn't abort the sync
    assert "grp/b" in out["synced"] and "grp/old" in out["synced"]


def test_cli_requires_env_token(monkeypatch, capsys):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    from agent import cli
    rc = cli.main(["gitlab-sync", "--base-url", "https://gl", "--dest", "/tmp/x"])
    assert rc == 2 and "GITLAB_TOKEN" in capsys.readouterr().err          # token is env-only, never a flag
