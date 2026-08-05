"""Guard: the public tool tree must never carry the internal GitLab host or client repo names.

The tool is published for adoption; its source is a shop window. A client's private repo map —
namespaces, repo names, `file:line` — must never ship in it. This generalizes the one-file check
already in the codebase (`test_github_scan_workflow`'s `assert "topsdemo" not in WF_TEXT`) to the
WHOLE tracked tree, so a future PR can't reintroduce a leak.

Principle 5 (prove a guard against its bug): this was written to FAIL on a tree carrying 30+ such
identifiers, then the tree was sanitized until it passed. It stays as the invariant that keeps it
clean — client-scoped catalog data lives in the private drift-ops overlay, public examples cite
public repos.
"""
import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# the internal GitLab host + the client namespaces/usernames that must never appear publicly.
# (The company's own identity — Tops Infosolutions / TOPSinfo — is fine; it publishes the tool.)
_DENY = re.compile(
    r"topsdemo"                                   # the internal GitLab host
    r"|akshit\.tops|shubhTops|shubhtops|channelwiz"   # client namespaces (both casings)
    r"|\b(?:chetan|rushikesh|jilesh|hiral)/"      # client usernames as a path segment
    r"|gitlab-fleet"                              # the internal fleet-clone directory name
    # NB: a leaked live token (glpat-…) is guarded separately — the redaction tests
    # (test_source_resolver, test_scan_util) prove tokens are stripped before write, and they
    # legitimately use fake glpat- fixtures, so banning the prefix here would only fight them.
)

# this file names the patterns by necessity; binary assets can't be grepped (removed, not scrubbed)
_ALLOW = {"tests/test_no_internal_identifiers.py"}
_BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"}


def _tracked_text_files():
    out = subprocess.run(["git", "ls-files"], cwd=_ROOT, capture_output=True, text=True).stdout
    for rel in out.splitlines():
        if rel in _ALLOW or Path(rel).suffix.lower() in _BINARY:
            continue
        yield rel, _ROOT / rel


def test_no_internal_or_client_identifiers_in_the_public_tree():
    hits = []
    for rel, p in _tracked_text_files():
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if _DENY.search(line):
                hits.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not hits, (f"{len(hits)} internal/client identifier(s) in the public tree "
                      f"(move client-scoped data to the drift-ops overlay; cite public repos in "
                      f"examples):\n" + "\n".join(hits))
