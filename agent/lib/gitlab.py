"""Read-only GitLab API client — enumerate the projects a token can see, to clone + scan them.

Deterministic, no LLM. The token is passed in (never stored here) and sent as the PRIVATE-TOKEN
header. Pagination follows ?page until a short page.
"""
from __future__ import annotations

import json
import urllib.request
from urllib.parse import quote

_API = "/api/v4"


def _default_get(url: str, token: str) -> list:
    req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
    with urllib.request.urlopen(req, timeout=30) as r:      # noqa: S310 (fixed https GitLab host)
        return json.loads(r.read().decode())


def list_projects(base_url: str, token: str, *, group: str | None = None,
                  per_page: int = 100, get=_default_get) -> list:
    base = base_url.rstrip("/")
    if group:
        url = (f"{base}{_API}/groups/{quote(group, safe='')}/projects"
               f"?include_subgroups=true&archived=false&per_page={per_page}")
    else:
        url = f"{base}{_API}/projects?membership=true&archived=false&per_page={per_page}"

    out, page = [], 1
    while True:
        data = get(f"{url}&page={page}", token)
        if not data:
            break
        for p in data:
            out.append({
                "id": p.get("id"),
                "path": p.get("path_with_namespace"),
                "url": p.get("http_url_to_repo"),
                "default_branch": p.get("default_branch"),
                "last_activity_at": p.get("last_activity_at"),
                "archived": p.get("archived", False),
            })
        if len(data) < per_page:
            break
        page += 1
    return [p for p in out if not p.get("archived") and p.get("url") and p.get("path")]
