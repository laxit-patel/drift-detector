"""Factory selecting a SourceProvider (gitlab | local) from config. The provider is any object
implementing list_candidate_projects/has_commit_since/get_tree/get_raw_file/search_blobs."""
from __future__ import annotations

import os

from agent.lib.gitlab_read import GitLabClient
from agent.lib.local_provider import LocalProvider


class SourceError(Exception):
    pass


def make_provider(config, *, env=None):
    env = os.environ if env is None else env
    src = config.source
    if src is None:
        raise SourceError("config has no `source` (build it via load_config)")
    if src.type == "local":
        return LocalProvider(src.local_root)
    # gitlab
    if config.gitlab is None:
        raise SourceError("source.type=gitlab but no `gitlab` config section")
    token = env.get(config.gitlab.token_env)
    if not token:
        raise SourceError(f"env var {config.gitlab.token_env} is not set")
    return GitLabClient(config.gitlab.base_url, token)
