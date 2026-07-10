"""Read-only GitLab REST v4 client. All HTTP goes through an injected `request`
callable so it is fully testable without the network. GET-only by construction."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.parse import quote


class GitLabError(Exception):
    pass


class GitLabUnreachable(GitLabError):
    pass


class GitLabAuthError(GitLabError):
    pass


class GitLabForbidden(GitLabError):
    def __init__(self, resource: str):
        super().__init__(f"forbidden: {resource}")
        self.resource = resource


MAX_PAGES = 1000


@dataclass
class HttpResponse:
    status: int
    headers: dict
    body_text: str

    def json(self):
        return json.loads(self.body_text or "null")


def _default_request(method, url, headers, params, timeout, body=None):  # pragma: no cover - thin HTTP shim
    import requests
    resp = requests.request(method, url, headers=headers, params=params, json=body, timeout=timeout)
    return HttpResponse(status=resp.status_code, headers=dict(resp.headers), body_text=resp.text)


class GitLabClient:
    def __init__(self, base_url: str, token: str, *, request=_default_request, timeout: int = 30):
        self._base = base_url.rstrip("/") + "/api/v4"
        self._token = token
        self._request = request
        self._timeout = timeout

    def _do_get(self, url: str, headers: dict, params: dict | None) -> HttpResponse:
        """Single guarded transport call: any OS/network error -> GitLabUnreachable.

        Builtin ConnectionError/TimeoutError AND requests.exceptions.* (which
        subclass OSError) are both caught here, so the client stays
        transport-agnostic and never needs to import `requests` itself.
        """
        try:
            return self._request("GET", url, headers, params or {}, self._timeout)
        except OSError as exc:
            raise GitLabUnreachable(str(exc)) from exc

    def get(self, path: str, params: dict | None = None, *, allow_404: bool = False) -> HttpResponse:
        url = self._base + path
        headers = {"PRIVATE-TOKEN": self._token, "User-Agent": "change-monitor/1.0"}
        resp = self._do_get(url, headers, params)

        if resp.status == 429:
            try:
                wait = float(resp.headers.get("Retry-After", "1"))
            except ValueError:
                wait = 1.0
            time.sleep(wait)
            resp = self._do_get(url, headers, params)
            if resp.status == 429:
                raise GitLabUnreachable("rate limited (429) after retry")

        if resp.status == 401:
            raise GitLabAuthError(f"401 on {path}")
        if resp.status == 403:
            raise GitLabForbidden(path)
        if resp.status == 404 and allow_404:
            return resp
        if resp.status >= 400:
            raise GitLabError(f"{resp.status} on {path}")
        return resp

    def get_paginated(self, path: str, params: dict | None = None) -> list:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        out: list = []
        page = 1
        while page <= MAX_PAGES:
            params["page"] = page
            resp = self.get(path, params)
            batch = resp.json() or []
            out.extend(batch)
            nxt = resp.headers.get("X-Next-Page", "")
            if not nxt:
                break
            page = int(nxt)
        return out

    def list_candidate_projects(self, since_iso: str) -> list:
        return self.get_paginated("/projects", {
            "last_activity_after": since_iso,
            "archived": "false",
            "simple": "true",
            "order_by": "last_activity_at",
        })

    def has_commit_since(self, project_id: int, since_iso: str, ref: str | None = None) -> "str | None":
        params = {"all": "true", "per_page": 1, "since": since_iso}
        if ref:
            params["ref_name"] = ref
        commits = self.get(f"/projects/{project_id}/repository/commits", params).json() or []
        return commits[0]["committed_date"] if commits else None

    def get_tree(self, project_id: int, ref: str) -> list:
        items = self.get_paginated(
            f"/projects/{project_id}/repository/tree",
            {"recursive": "true", "ref": ref},
        )
        return [it["path"] for it in items if it.get("type") == "blob"]

    def get_raw_file(self, project_id: int, path: str, ref: str) -> "str | None":
        enc = quote(path, safe="")
        resp = self.get(
            f"/projects/{project_id}/repository/files/{enc}/raw",
            {"ref": ref}, allow_404=True,
        )
        return resp.body_text if resp.status == 200 else None

    def search_blobs(self, project_id: int, query: str) -> list:
        return self.get_paginated(
            f"/projects/{project_id}/search",
            {"scope": "blobs", "search": query},
        )

    def _post(self, path: str, body: dict) -> HttpResponse:
        url = self._base + path
        headers = {"PRIVATE-TOKEN": self._token, "User-Agent": "change-monitor/1.0",
                   "Content-Type": "application/json"}
        try:
            resp = self._request("POST", url, headers, {}, self._timeout, body=body)
        except OSError as exc:
            raise GitLabUnreachable(str(exc)) from exc
        if resp.status == 401:
            raise GitLabAuthError(f"401 on {path}")
        if resp.status == 403:
            raise GitLabForbidden(path)
        if resp.status >= 400:
            raise GitLabError(f"{resp.status} on {path}")
        return resp

    def create_commit(self, project_id: int, branch: str, message: str, actions: list) -> dict:
        body = {"branch": branch, "commit_message": message, "actions": actions}
        return self._post(f"/projects/{project_id}/repository/commits", body).json()

    def file_exists(self, project_id: int, path: str, ref: str) -> bool:
        return self.get_raw_file(project_id, path, ref) is not None
