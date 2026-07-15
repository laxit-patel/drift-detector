"""Classify a discovered URL against the vendor catalog (discover-then-classify).

The scan now finds ALL http(s) URL literals; this decides what each one is:
- a KNOWN vendor (registrable-domain suffix match, e.g. `ebay.com` matches `api.sandbox.ebay.com`;
  or a distinctive host fragment like `sellingpartnerapi` for regional Amazon SP-API hosts),
- boilerplate to IGNORE (schemas, w3.org, localhost, fonts, analytics — not integrations),
- otherwise an UNKNOWN external endpoint (surfaced so the catalog is never the ceiling).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from agent.lib.vendors import DEFAULT_VERSION_REGEX

_URL_RE = re.compile(r"""https?://[^\s"'`<>)\]}]+""", re.IGNORECASE)

# hosts (by registrable suffix) that are never third-party API integrations
_IGNORE = {
    "w3.org", "xmlsoap.org", "schema.org", "json-schema.org", "purl.org", "apache.org",
    "example.com", "example.org", "example.net", "localhost", "test.com",
    "fonts.googleapis.com", "fonts.gstatic.com", "gravatar.com", "placeholder.com",
    "googletagmanager.com", "google-analytics.com", "gstatic.com", "jsdelivr.net",
    "unpkg.com", "cloudflare.com", "cdnjs.cloudflare.com", "bootstrapcdn.com",
    "ns.adobe.com", "sentry.io", "gmpg.org", "wordpress.org", "adobe.com",
}


def extract_urls(text: str) -> list:
    return _URL_RE.findall(text or "")


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_ignored(host: str) -> bool:
    if not host or "." not in host or host.replace(".", "").isdigit():   # empty / bare / raw IP
        return True
    return any(host == s or host.endswith("." + s) for s in _IGNORE)


def _matches(host: str, domain: str) -> bool:
    d = domain.lower()
    if "." in d:
        return host == d or host.endswith("." + d)      # registrable-domain suffix
    return d in host                                     # distinctive fragment (e.g. sellingpartnerapi)


def classify_host(host: str, vendors: list):
    """Return the best-matching Vendor (most specific domain wins) or None."""
    best, best_len = None, -1
    for v in vendors:
        for d in v.domains:
            if _matches(host, d) and len(d) > best_len:
                best, best_len = v, len(d)
    return best


def version_of(url: str, vendor) -> str | None:
    regex = vendor.version_regex if vendor else DEFAULT_VERSION_REGEX
    m = re.search(regex, url)
    return m.group(1) if m else None
