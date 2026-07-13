"""Out-of-band dead-man's switch: heartbeat ping on success + a freshness check for a Monday cron."""
from __future__ import annotations

from datetime import date


def _default_get(url):  # pragma: no cover
    import requests
    return requests.get(url, timeout=15).status_code


def ping_healthcheck(url: str, *, get=_default_get) -> bool:
    try:
        return 200 <= int(get(url)) < 300
    except Exception:
        return False


def check_report_fresh(last_report_date: str, now: str, *, max_age_days: int = 8) -> bool:
    if not last_report_date:
        return False
    try:
        return (date.fromisoformat(now) - date.fromisoformat(last_report_date)).days <= max_age_days
    except ValueError:
        return False
