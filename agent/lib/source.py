"""Factory selecting a SourceProvider (gitlab | local | github) from config. The provider is any
object implementing list_candidate_projects/has_commit_since/get_tree/get_raw_file/search_blobs."""
from __future__ import annotations

import os
import subprocess

from agent.lib.gitlab_read import GitLabClient
from agent.lib.github_provider import GitHubProvider
from agent.lib.local_provider import LocalProvider


class SourceError(Exception):
    pass


def _gh_token() -> str:  # pragma: no cover - shells out to the user's gh login
    try:
        p = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def make_provider(config, *, env=None):
    env = os.environ if env is None else env
    src = config.source
    if src is None:
        raise SourceError("config has no `source` (build it via load_config)")
    if src.type == "local":
        return LocalProvider(src.local_root)
    if src.type == "github":
        token = env.get(src.github_token_env) or _gh_token()
        if not token:
            raise SourceError(f"no GitHub token: set {src.github_token_env} or run `gh auth login`")
        return GitHubProvider(src.github_owner, token)
    # gitlab
    if config.gitlab is None:
        raise SourceError("source.type=gitlab but no `gitlab` config section")
    token = env.get(config.gitlab.token_env)
    if not token:
        raise SourceError(f"env var {config.gitlab.token_env} is not set")
    return GitLabClient(config.gitlab.base_url, token)
