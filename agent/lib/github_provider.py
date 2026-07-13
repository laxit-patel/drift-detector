"""Native GitHub SourceProvider: scan repos via the GitHub REST API, no cloning.
Implements the same five read methods as GitLabClient/LocalProvider. HTTP is injected."""
from __future__ import annotations

import re

from agent.lib.gitlab_read import HttpResponse

_API = "https://api.github.com"
_LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')
_MAX_PAGES = 1000


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
        except OSError as exc:
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
        pages = 0
        while url and pages < _MAX_PAGES:
            resp = self._get(url, params if url == path else None)
            out.extend(resp.json() or [])
            m = _LINK_NEXT.search(resp.headers.get("Link", ""))
            url = m.group(1) if m else None
            pages += 1
        return out

    def _full_name(self, project_id):
        return self._by_id[project_id]

    def list_candidate_projects(self, since_iso: str) -> list:
        repos = self._get_paginated("/user/repos", {"affiliation": "owner", "sort": "pushed"})
        out = []
        prefix = f"{self.owner}/"
        for r in repos:
            if r.get("archived") or not r.get("full_name", "").startswith(prefix):
                continue
            self._by_id[r["id"]] = r["full_name"]
            out.append({"id": r["id"], "path_with_namespace": r["full_name"],
                        "default_branch": r.get("default_branch") or "main",
                        "last_activity_at": r.get("pushed_at", "")})
        return out

    def has_commit_since(self, project_id, since_iso, ref=None) -> "str | None":
        params = {"per_page": 1, "since": since_iso}
        if ref:
            params["sha"] = ref
        commits = self._get(f"/repos/{self._full_name(project_id)}/commits", params).json() or []
        if not commits:
            return None
        return commits[0].get("commit", {}).get("committer", {}).get("date")
