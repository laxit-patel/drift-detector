"""Native GitHub SourceProvider: scan repos via the GitHub REST API, no cloning.
Implements the same five read methods as GitLabClient/LocalProvider. HTTP is injected."""
from __future__ import annotations

import re

from agent.lib.gitlab_read import HttpResponse

_API = "https://api.github.com"
_LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


class GitHubError(Exception):
    pass


class GitHubUnreachable(GitHubError):
    pass


class GitHubAuthError(GitHubError):
    pass


def _default_request(method, url, headers, params, timeout):  # pragma: no cover - real HTTP
    import requests
    resp = requests.request(method, url, headers=headers, params=params, timeout=timeout)
    return HttpResponse(status=resp.status_code, headers=dict(resp.headers), body_text=resp.text)


class GitHubProvider:
    def __init__(self, owner, token, *, request=_default_request, timeout=30):
        self.owner = owner
        self._token = token
        self._request = request
        self._timeout = timeout
        self._by_id = {}                 # id -> full_name, populated by list_candidate_projects

    def _headers(self, accept=None):
        return {"Authorization": f"Bearer {self._token}",
                "Accept": accept or "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "change-monitor/1.0"}

    def _get(self, path, params=None, *, allow_404=False, accept=None) -> HttpResponse:
        url = path if path.startswith("http") else _API + path
        try:
            resp = self._request("GET", url, self._headers(accept), params or {}, self._timeout)
        except (ConnectionError, TimeoutError) as exc:
            raise GitHubUnreachable(str(exc)) from exc
        if resp.status == 401:
            raise GitHubAuthError(f"401 on {path}")
        if resp.status == 404 and allow_404:
            return resp
        if resp.status >= 400:
            rem = resp.headers.get("X-RateLimit-Remaining", "?")
            raise GitHubError(f"{resp.status} on {path} (rate-limit-remaining={rem})")
        return resp

    def _get_paginated(self, path, params=None) -> list:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        out, url = [], path
        while url:
            resp = self._get(url, params if url == path else None)
            out.extend(resp.json() or [])
            m = _LINK_NEXT.search(resp.headers.get("Link", ""))
            url = m.group(1) if m else None
        return out
