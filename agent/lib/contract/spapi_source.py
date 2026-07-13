"""Fetch the Amazon SP-API OpenAPI/Swagger model files from amzn/selling-partner-api-models.
The published models are Swagger 2.0 and contain literal control characters, so parsing uses
strict=False. HTTP is injected; a file that won't parse is skipped as a coverage gap."""
from __future__ import annotations

import json

_REPO = "amzn/selling-partner-api-models"
_API = "https://api.github.com"


def _default_fetch_tree():  # pragma: no cover - real GitHub HTTP
    import requests
    url = f"{_API}/repos/{_REPO}/git/trees/main?recursive=1"
    r = requests.get(url, timeout=30, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "change-monitor/1.0"})
    r.raise_for_status()
    return [b["path"] for b in r.json().get("tree", []) if b.get("type") == "blob"]


def _default_fetch_raw(path):  # pragma: no cover - real GitHub HTTP
    import requests
    url = f"{_API}/repos/{_REPO}/contents/{path}"
    r = requests.get(url, timeout=30, headers={"Accept": "application/vnd.github.raw",
                                               "User-Agent": "change-monitor/1.0"})
    r.raise_for_status()
    return r.text


def _api_name(path: str) -> str:
    # "models/orders-api-model/ordersV0.json" -> "orders-api-model/ordersV0"
    return path[len("models/"):].rsplit(".json", 1)[0]


def fetch_spapi_models(*, fetch_tree=_default_fetch_tree, fetch_raw=_default_fetch_raw):
    """Returns (models: dict[api_name -> parsed doc], skipped: list[path])."""
    models: dict = {}
    skipped: list = []
    for path in fetch_tree():
        if not (path.startswith("models/") and path.endswith(".json")):
            continue
        try:
            models[_api_name(path)] = json.loads(fetch_raw(path), strict=False)
        except (ValueError, OSError):
            skipped.append(path)
    return models, skipped
