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
    # schemas / specs / xml namespaces
    "w3.org", "xmlsoap.org", "schema.org", "json-schema.org", "purl.org", "apache.org",
    "example.com", "example.org", "example.net", "localhost", "test.com", "gmpg.org",
    # asset / font / image CDNs + placeholders
    "fonts.googleapis.com", "fonts.gstatic.com", "gstatic.com", "jsdelivr.net", "unpkg.com",
    "cloudflare.com", "cdnjs.cloudflare.com", "bootstrapcdn.com", "fonts.bunny.net",
    "gravatar.com", "placeholder.com", "placehold.co", "picsum.photos", "via.placeholder.com",
    # analytics / tag managers
    "googletagmanager.com", "google-analytics.com", "ns.adobe.com",
    # developer docs / package registries / code hosting (repo & doc links, not API calls)
    "github.com", "gitlab.com", "bitbucket.org", "laravel.com", "laracasts.com", "symfony.com",
    "php.net", "npmjs.com", "packagist.org", "wordpress.org", "readthedocs.io", "mozilla.org",
    "getcomposer.org", "nodejs.org", "python.org", "jquery.com", "getbootstrap.com",
    # search / social / video (marketing links, not integrations)
    "google.com", "bing.com", "youtube.com", "youtu.be", "vimeo.com", "facebook.com",
    "twitter.com", "linkedin.com", "instagram.com",
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


def domain_in_line(line: str, domains) -> str:
    for d in domains:
        if d in line:
            return d
    return ""


def segment_at(line: str, token: str) -> str:
    """The literal token containing `token` (up to the next quote/space/backtick) — so version/example
    for a host-only reference aren't contaminated by neighbouring text on the line."""
    idx = line.find(token)
    if idx < 0:
        return token
    return re.split(r"""["'\s`]""", line[idx:], 1)[0]
