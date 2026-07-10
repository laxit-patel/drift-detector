"""Load and validate config.yaml into typed objects. Fail loud on bad config."""
from __future__ import annotations

from dataclasses import dataclass
import yaml

from agent.lib.models import FeedSpec

ALLOWED_ADAPTERS = {"rss", "endoflife", "github-releases", "registry", "html-changelog"}
ALLOWED_CATEGORIES = {"integration", "framework", "library", "runtime"}
_REQUIRED = ("techKey", "label", "category", "adapter", "url", "tier")


class ConfigError(ValueError):
    pass


@dataclass
class GitLabConfig:
    base_url: str
    token_env: str
    expected_namespaces: list[str]


@dataclass
class ScanConfig:
    active_window_days: int = 90
    always_include: list[str] = None
    allow: list[str] = None
    deny: list[str] = None
    branch_overrides: dict = None
    max_repos: int = 50

    def __post_init__(self):
        self.always_include = self.always_include or []
        self.allow = self.allow or []
        self.deny = self.deny or []
        self.branch_overrides = self.branch_overrides or {}


@dataclass
class DeliveryConfig:
    reports_project: str
    reports_branch: str = "main"
    report_token_env: str = "REPORTS_TOKEN"
    chat_webhook_env: str = "GCHAT_WEBHOOK_URL"
    health_ping_env: str = "HEALTHCHECK_URL"
    actions: list = None
    review_horizon_months: int = 6
    urgent_deadline_days: int = 90

    def __post_init__(self):
        self.actions = self.actions or []


@dataclass
class Config:
    kb_root: str
    feeds: list[FeedSpec]
    raw: dict
    gitlab: "GitLabConfig | None" = None
    scan: "ScanConfig" = None
    delivery: "DeliveryConfig | None" = None


def _feed_from(d: dict) -> FeedSpec:
    for k in _REQUIRED:
        if d.get(k) in (None, ""):
            raise ConfigError(f"feed {d.get('techKey', '?')}: missing required field '{k}'")
    if d["adapter"] not in ALLOWED_ADAPTERS:
        raise ConfigError(f"feed {d['techKey']}: unknown adapter '{d['adapter']}'")
    if d["category"] not in ALLOWED_CATEGORIES:
        raise ConfigError(f"feed {d['techKey']}: unknown category '{d['category']}'")
    return FeedSpec(
        techKey=d["techKey"], label=d["label"], category=d["category"],
        adapter=d["adapter"], url=str(d["url"]), tier=int(d["tier"]),
        warn=d.get("warn", ""), upgradeGuide=d.get("upgradeGuide", ""),
    )


def _gitlab_from(raw: dict) -> "GitLabConfig | None":
    g = raw.get("gitlab")
    if not g:
        return None
    for k in ("baseUrl", "tokenEnv"):
        if not g.get(k):
            raise ConfigError(f"gitlab section: missing required field '{k}'")
    return GitLabConfig(
        base_url=str(g["baseUrl"]).rstrip("/"),
        token_env=g["tokenEnv"],
        expected_namespaces=list(g.get("expectedNamespaces") or []),
    )


def _scan_from(raw: dict) -> "ScanConfig":
    s = raw.get("scan") or {}
    return ScanConfig(
        active_window_days=int(s.get("activeWindowDays", 90)),
        always_include=list(s.get("alwaysInclude") or []),
        allow=list(s.get("allow") or []),
        deny=list(s.get("deny") or []),
        branch_overrides=dict(s.get("branchOverrides") or {}),
        max_repos=int(s.get("maxRepos", 50)),
    )


def _delivery_from(raw: dict) -> "DeliveryConfig | None":
    d = raw.get("delivery")
    if not d:
        return None
    if not d.get("reportsProject"):
        raise ConfigError("delivery section: missing required field 'reportsProject'")
    return DeliveryConfig(
        reports_project=d["reportsProject"], reports_branch=d.get("reportsBranch", "main"),
        report_token_env=d.get("reportTokenEnv", "REPORTS_TOKEN"),
        chat_webhook_env=d.get("chatWebhookEnv", "GCHAT_WEBHOOK_URL"),
        health_ping_env=d.get("healthPingEnv", "HEALTHCHECK_URL"),
        actions=list(d.get("actions") or []),
        review_horizon_months=int(d.get("reviewHorizonMonths", 6)),
        urgent_deadline_days=int(d.get("urgentDeadlineDays", 90)),
    )


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    feeds_raw = raw.get("feeds") or []
    if not feeds_raw:
        raise ConfigError("config must declare at least one feed")
    feeds = [_feed_from(f) for f in feeds_raw]
    kb_root = (raw.get("kb") or {}).get("root", "kb/")
    return Config(
        kb_root=kb_root,
        feeds=feeds,
        raw=raw,
        gitlab=_gitlab_from(raw),
        scan=_scan_from(raw),
        delivery=_delivery_from(raw),
    )
