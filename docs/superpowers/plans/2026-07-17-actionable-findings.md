# Spec A — Actionable Findings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make findings act-on-able — precise per-API citation links, and file:line call-sites that render on their own line as clickable GitHub/GitLab permalinks (or a copy button locally), with no credential ever reaching the shared dashboard.

**Architecture:** The scanner captures a credential-stripped `remote_url` per repo (`scan_util`). The dashboard projection (Python, tested) builds blob permalinks pinned to `head_sha`; the inline JS is a dumb renderer. Citations are catalog curation plus a lint. The eval harness is the regression net for the scanner-capture change.

**Tech Stack:** Python 3.12 stdlib (`re`, `os`, `html`) + pyyaml. Vanilla inline browser JS. pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-actionable-findings-design.md` — the source of truth.

## Global Constraints

- Python 3.12 in `.venv` (uv-managed). Run tests with `.venv/bin/python -m pytest -q`. **NO pip** — stdlib + existing deps (pyyaml) only. NO new dependency.
- **DETERMINISTIC, ZERO-LLM-TOKEN.** Same inputs → byte-identical `dashboard.html`. **NO network in any unit test**; git is injected/monkeypatched. The ONLY live network is Task 5's manual eBay-URL verification + the eval run.
- **SAFETY-CRITICAL:** a git remote with embedded credentials (`https://user:token@host/…`) must **NEVER** appear in the produced `dashboard.html`. The strip happens at **CAPTURE** in `scan_util.normalize_remote` (Python, tested) — `safeUrl` (http(s) allow-list) CANNOT catch a token in a valid http(s) URL, so it is not the defense. Belt-and-suspenders: also assert no token in the rendered HTML.
- The dashboard stays a **SELF-CONTAINED** file: inline CSS+JS+embedded JSON, no CDN, opens from `file://`. The `safeUrl` scheme allow-list stays **http(s)-ONLY** (no `vscode://` — local repos get copy-path). Permalink URLs are built in **Python** (tested); the JS is a dumb renderer.
- Permalinks **pin to `head_sha`** (never a branch) so they don't drift. **Unknown git host → plain text** (never a guessed/broken link).
- Backward compatibility: `remote_url` is **ADDITIVE** to the repo doc; existing artifacts/consumers unchanged. The eval harness (`bin/drift-eval run ebay` = 5/5) is the regression net for the scanner-capture change.
- TDD, frequent commits, DRY, YAGNI. **NON-GOALS** (do not build): #4 private-vs-unknown section, #2 ceiling-surfacing/corpus-pin, a `migration:` catalog field, `vscode://` links, editor-launch, vendor-page scraping, reachability probes.

---

## File Structure

| File | Change |
|---|---|
| `agent/lib/scan_util.py` | `normalize_remote()` (new, safety-critical) + `git_meta` captures `remote_url`. |
| `agent/lib/superset.py` | `to_superset_repo` threads `remote_url` into the repo doc. |
| `agent/lib/dashboard_render.py` | `_permalink()` (new) + `_build_projection` rewrites `files` to `[{loc,href}]` + the JS "Used at" render. |
| `agent/vendor_sunsets.yaml` | eBay entries repointed to specific API pages (Task 5). |
| `tests/test_scan_util.py` | new — the normalizer's 7 cases. |
| `tests/test_dashboard_render.py` | extend — `_permalink`, projection rewrite, JS render, XSS/no-credential. |
| `tests/test_vendor_sunsets.py` | extend — the shared-`source` lint. |
| a superset/scan test | extend — `remote_url` reaches the doc, credential-free. |

**Ordering:** Task 1 (capture) → Task 2 (thread into doc) → Task 3 (Python permalink + projection) → Task 4 (JS render) → Task 5 (citations + lint, research, last).

---

## Task 1: `scan_util.normalize_remote` + `git_meta` capture (SAFETY-CRITICAL)

**Files:**
- Modify: `agent/lib/scan_util.py`
- Create: `tests/test_scan_util.py`

**Interfaces:**
- Produces: `normalize_remote(raw) -> str | None` (clean `https://host/owner/repo`, credentials stripped); `git_meta(...)` dict gains `"remote_url"`. Task 2 reads `meta["remote_url"]`; Task 3 parses the normalized URL.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_util.py`:

```python
"""The git-remote normalizer. Safety-critical: a token in the remote must NEVER survive —
it would otherwise land in the shared dashboard.html."""
from agent.lib.scan_util import normalize_remote, git_meta


def test_scp_ssh_remote():
    assert normalize_remote("git@github.com:owner/repo.git") == "https://github.com/owner/repo"


def test_ssh_scheme_remote():
    assert normalize_remote("ssh://git@github.com/owner/repo.git") == "https://github.com/owner/repo"


def test_plain_https_strips_dot_git():
    assert normalize_remote("https://github.com/owner/repo.git") == "https://github.com/owner/repo"


def test_https_with_embedded_token_is_stripped():
    # THE load-bearing case: a CI clone URL carrying a token must lose it.
    out = normalize_remote("https://oauth2:glpat-SECRET@git.topsdemo.in/rushikesh/ebayapi.git")
    assert out == "https://git.topsdemo.in/rushikesh/ebayapi"
    assert "glpat-SECRET" not in out and "@" not in out


def test_self_hosted_gitlab_host_preserved():
    assert normalize_remote("git@git.topsdemo.in:rushikesh/ebayapi.git") == \
        "https://git.topsdemo.in/rushikesh/ebayapi"


def test_garbage_and_empty_return_none():
    assert normalize_remote("not-a-remote") is None
    assert normalize_remote("") is None
    assert normalize_remote(None) is None


def test_git_meta_captures_normalized_remote():
    def fake_git(args):
        if "get-url" in args:
            return "https://user:token@github.com/o/r.git"
        return "abc123" if "rev-parse" in args and "HEAD" == args[-1] else ""
    meta = git_meta("/repo", run=fake_git)
    assert meta["remote_url"] == "https://github.com/o/r"      # token stripped at capture
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_scan_util.py -q`
Expected: FAIL — `ImportError: cannot import name 'normalize_remote'`

- [ ] **Step 3: Implement**

In `agent/lib/scan_util.py`, add `import re` at the top (after the existing imports), add `normalize_remote`, and extend `git_meta`:

```python
import re


def normalize_remote(raw) -> str | None:
    """Normalize a git remote to a clean `https://host/owner/repo`, or None.

    STRIPS any embedded credentials (`https://user:token@host/…`) — the credential-leak guard:
    a token must never reach the shared dashboard. Returns None for anything it can't parse to a
    clean scheme://host/path (fail safe → no link rather than a risky one).
    """
    s = str(raw or "").strip()
    if not s:
        return None
    if "://" not in s:                                   # scp-style ssh: git@host:owner/repo(.git)
        m = re.match(r"^[\w.+-]+@([\w.-]+):(.+)$", s)
        if not m:
            return None
        host, path = m.group(1), m.group(2)
    else:                                                # scheme://[userinfo@]host[:port]/path
        m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([\w.-]+)(?::\d+)?/(.+)$", s, re.I)
        if not m:
            return None
        host, path = m.group(1), m.group(2)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not host or not path or "@" in host or "@" in path:
        return None
    return f"https://{host}/{path}"
```

And in `git_meta`, add the `remote_url` key (after `head_sha`):

```python
def git_meta(repo_abs: str, *, run=_default_git) -> dict:
    def g(*a):
        return run(["-C", repo_abs, *a]) or ""
    return {
        "head_sha": g("rev-parse", "HEAD"),
        "remote_url": normalize_remote(g("remote", "get-url", "origin")),
        "ref": g("rev-parse", "--abbrev-ref", "HEAD"),
        "last_activity_at": g("log", "-1", "--format=%cI"),
        "ref_is_default": True,          # best-effort locally (v1 simplification)
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_scan_util.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add agent/lib/scan_util.py tests/test_scan_util.py
git commit -m "feat(scan): capture credential-stripped git remote_url

normalize_remote() -> clean https://host/owner/repo, stripping any embedded
token (https://user:token@host/...) at CAPTURE — a leaked credential must never
reach the shared dashboard. git_meta now returns remote_url. Fail-safe: None on
anything unparseable."
```

---

## Task 2: thread `remote_url` into the repo doc

**Files:**
- Modify: `agent/lib/superset.py:18-31` (`to_superset_repo`)
- Test: `tests/test_superset.py` (extend if it exists; else a new focused test)

**Interfaces:**
- Consumes: `meta["remote_url"]` (Task 1).
- Produces: `repos[].remote_url` in the inventory doc. Task 3 reads it.

- [ ] **Step 1: Write the failing test**

Add to the superset test (create `tests/test_superset_remote.py` if there's no obvious existing home):

```python
from agent.lib.superset import to_superset_repo


def test_repo_doc_carries_remote_url_credential_free():
    meta = {"id": 1, "path": "svc", "head_sha": "abc",
            "remote_url": "https://github.com/o/r"}      # already normalized by git_meta
    doc = to_superset_repo(meta, {"runtimes": [], "frameworks": [], "sdks": []}, [])
    assert doc["remote_url"] == "https://github.com/o/r"
    assert "@" not in (doc["remote_url"] or "")          # never a credential


def test_repo_doc_remote_url_none_when_absent():
    meta = {"id": 1, "path": "svc", "head_sha": "abc"}    # no remote_url (local/no-origin)
    doc = to_superset_repo(meta, {"runtimes": [], "frameworks": [], "sdks": []}, [])
    assert doc["remote_url"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_superset_remote.py -q`
Expected: FAIL — `KeyError: 'remote_url'`

- [ ] **Step 3: Implement**

In `agent/lib/superset.py`, add the `remote_url` key beside `head_sha` in the returned dict:

```python
        "last_activity_at": meta.get("last_activity_at"), "head_sha": meta.get("head_sha"),
        "remote_url": meta.get("remote_url"),
```

(`repo_scan.scan_repo` already passes the full `git_meta` dict as `meta` — no change there.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_superset_remote.py -q`
Expected: PASS, 2 passed

- [ ] **Step 5: Commit**

```bash
git add agent/lib/superset.py tests/test_superset_remote.py
git commit -m "feat(scan): thread remote_url into the repo doc

Additive: repos[].remote_url (credential-free from git_meta) sits beside
head_sha for the dashboard to build permalinks. None for local/no-origin repos."
```

---

## Task 3: `_permalink` + projection rewrite (Python, tested)

**Files:**
- Modify: `agent/lib/dashboard_render.py`
- Test: `tests/test_dashboard_render.py`

**Interfaces:**
- Consumes: `repos[].remote_url` + `repos[].head_sha` (Tasks 1-2); an action's `repo` (path) + `files` (list of `"path:line"`).
- Produces: `_permalink(remote_url, head_sha, loc) -> str | None`; the projection's action `files` become `[{loc, href}]`. Task 4's JS reads `f.loc`/`f.href`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dashboard_render.py`:

```python
def test_permalink_github_blob_shape():
    from agent.lib.dashboard_render import _permalink
    assert _permalink("https://github.com/o/r", "SHA", "src/x.php:37") == \
        "https://github.com/o/r/blob/SHA/src/x.php#L37"


def test_permalink_gitlab_dash_blob_shape():
    from agent.lib.dashboard_render import _permalink
    assert _permalink("https://gitlab.com/o/r", "SHA", "src/x.php:37") == \
        "https://gitlab.com/o/r/-/blob/SHA/src/x.php#L37"


def test_permalink_self_hosted_gitlab_via_env(monkeypatch):
    from agent.lib.dashboard_render import _permalink
    monkeypatch.setenv("DRIFT_GITLAB_HOSTS", "git.topsdemo.in")
    assert _permalink("https://git.topsdemo.in/rushikesh/ebayapi", "SHA", "src/config/ebay.php:39") == \
        "https://git.topsdemo.in/rushikesh/ebayapi/-/blob/SHA/src/config/ebay.php#L39"


def test_permalink_unknown_host_and_missing_bits_are_none(monkeypatch):
    from agent.lib.dashboard_render import _permalink
    monkeypatch.delenv("DRIFT_GITLAB_HOSTS", raising=False)
    assert _permalink("https://bitbucket.org/o/r", "SHA", "src/x.php:1") is None   # unknown host
    assert _permalink(None, "SHA", "src/x.php:1") is None                          # no remote
    assert _permalink("https://github.com/o/r", None, "src/x.php:1") is None       # no sha


def test_permalink_missing_line_omits_anchor():
    from agent.lib.dashboard_render import _permalink
    assert _permalink("https://github.com/o/r", "SHA", "src/x.php") == \
        "https://github.com/o/r/blob/SHA/src/x.php"


def test_projection_rewrites_files_to_loc_href_dicts():
    # a sunset action whose repo has a github remote -> each file becomes {loc, href}
    from agent.lib.dashboard_render import _build_projection
    inv = {"repos": [{"path": "r", "remote_url": "https://github.com/o/r", "head_sha": "SHA",
                      "endpoints": []}]}
    audit = {"actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "status": "DEPRECATED",
                          "worst": "SUNSET", "finding_count": 1, "files": ["src/x.php:37"],
                          "fixes": [], "sources": []}]}
    proj = _build_projection(inv, audit)
    f = proj["actions"][0]["files"][0]
    assert f == {"loc": "src/x.php:37", "href": "https://github.com/o/r/blob/SHA/src/x.php#L37"}


def test_projection_files_href_none_for_local_repo():
    from agent.lib.dashboard_render import _build_projection
    inv = {"repos": [{"path": "r", "remote_url": None, "head_sha": "SHA", "endpoints": []}]}
    audit = {"actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "status": "DEPRECATED",
                          "worst": "SUNSET", "finding_count": 1, "files": ["src/x.php:37"],
                          "fixes": [], "sources": []}]}
    f = _build_projection(inv, audit)["actions"][0]["files"][0]
    assert f == {"loc": "src/x.php:37", "href": None}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q -k "permalink or projection_rewrites or files_href"`
Expected: FAIL — `_permalink` not defined / files are still bare strings.

- [ ] **Step 3: Implement**

In `agent/lib/dashboard_render.py`, add `import os` and `import re` if not present (check the top; `html`/`json` are already imported), and add `_permalink`:

```python
def _gitlab_hosts() -> set:
    return {h.strip() for h in os.environ.get("DRIFT_GITLAB_HOSTS", "").split(",") if h.strip()}


def _permalink(remote_url, head_sha, loc) -> str | None:
    """Build a GitHub/GitLab blob permalink pinned to head_sha, or None (plain text).
    A self-hosted GitLab host isn't guessable from the URL — it's allow-listed via
    $DRIFT_GITLAB_HOSTS. Unknown host -> None (never a guessed/broken link)."""
    if not remote_url or not head_sha or not loc:
        return None
    path, _, line = str(loc).rpartition(":")
    if not path or not line.isdigit():        # no "path:line" split -> whole loc is the path
        path, line = str(loc), ""
    m = re.match(r"^https://([\w.-]+)/(.+)$", remote_url)
    if not m:
        return None
    host, owner_repo = m.group(1), m.group(2)
    anchor = f"#L{line}" if line else ""
    if host == "github.com":
        return f"https://github.com/{owner_repo}/blob/{head_sha}/{path}{anchor}"
    if host == "gitlab.com" or "gitlab" in host or host in _gitlab_hosts():
        return f"https://{host}/{owner_repo}/-/blob/{head_sha}/{path}{anchor}"
    return None
```

Then rewrite the `files` in `_build_projection` (it has the inventory; `_project_action` does not). Replace the `actions = [...]` line and add the rewrite:

```python
def _build_projection(inventory: dict, audit: dict) -> dict:
    repo_meta = {r.get("path"): {"remote_url": r.get("remote_url"), "head_sha": r.get("head_sha")}
                 for r in inventory.get("repos", [])}
    actions = [_project_action(a) for a in _actions_of(audit)]
    for a in actions:
        rm = repo_meta.get(a["repo"], {})
        a["files"] = [{"loc": loc, "href": _permalink(rm.get("remote_url"), rm.get("head_sha"), loc)}
                      for loc in a["files"]]
    endpoints = _endpoints_of(inventory)
    # …rest unchanged…
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q -k "permalink or projection_rewrites or files_href"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/lib/dashboard_render.py tests/test_dashboard_render.py
git commit -m "feat(dashboard): build call-site permalinks in Python

_permalink pins GitHub /blob and GitLab /-/blob links to head_sha (self-hosted
GitLab via \$DRIFT_GITLAB_HOSTS; unknown host -> None). The projection rewrites
each action's files to {loc, href} so the JS is a dumb renderer."
```

---

## Task 4: the JS "Used at" render (own line, link-or-copy) + XSS/no-credential

**Files:**
- Modify: `agent/lib/dashboard_render.py` (the `actionDetail` JS, the `Used at` line)
- Test: `tests/test_dashboard_render.py`

**Interfaces:**
- Consumes: `a.files` = `[{loc, href}]` (Task 3), the existing `esc`/`escA`/`safeUrl` JS helpers.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dashboard_render.py` (these render the full HTML and assert on it — reuse the file's existing `render_dashboard`/`_audit`/`_inv`-style helpers; if a sunset helper isn't present, build the audit/inventory inline as below):

```python
def _sunset_inv_audit(remote_url, files=("src/x.php:37", "src/y.php:39")):
    inv = {"repos": [{"path": "r", "remote_url": remote_url, "head_sha": "SHA", "endpoints": []}]}
    audit = {"generated": "2026-07-17", "coverage": {},
             "actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "status": "DEPRECATED",
                          "worst": "SUNSET", "finding_count": 1, "recommendation": "migrate",
                          "files": list(files), "fixes": [], "sources": []}]}
    return inv, audit


def test_call_sites_render_one_per_line_with_blob_link_for_remote():
    from agent.lib.dashboard_render import render_dashboard
    inv, audit = _sunset_inv_audit("https://github.com/o/r")
    js = render_dashboard(inv, audit, "2026-07-17").split("<script>")[-1]
    # the render emits an <a href> to the pinned blob and does NOT comma-join
    assert "/blob/SHA/src/x.php#L37" in render_dashboard(inv, audit, "2026-07-17")
    assert "'Used at: '+a.files.map(esc).join" not in js          # the old inline join is gone


def test_local_repo_call_site_is_text_plus_copy_no_href():
    from agent.lib.dashboard_render import render_dashboard
    inv, audit = _sunset_inv_audit(None)                          # local repo, no remote
    html_out = render_dashboard(inv, audit, "2026-07-17")
    js = html_out.split("<script>")[-1]
    assert "navigator.clipboard.writeText" in js                  # a copy affordance exists
    assert "f.href" in js and "f.loc" in js                       # renders the {loc,href} shape


def test_no_token_in_rendered_html_even_if_remote_had_one():
    # belt-and-suspenders: even though Task 1 strips at capture, assert nothing leaks here.
    from agent.lib.dashboard_render import render_dashboard
    inv, audit = _sunset_inv_audit("https://github.com/o/r")       # already stripped upstream
    out = render_dashboard(inv, audit, "2026-07-17")
    assert "glpat-" not in out and "@github.com" not in out


def test_call_site_loc_is_xss_escaped():
    from agent.lib.dashboard_render import render_dashboard
    inv, audit = _sunset_inv_audit(None, files=['a<script>alert(1)</script>:1'])
    out = render_dashboard(inv, audit, "2026-07-17")
    assert "<script>alert(1)</script>" not in out                 # not literal in the HTML
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q -k "call_sites or local_repo_call or no_token or loc_is_xss"`
Expected: FAIL — the old inline `Used at:` join is still present; `f.href`/`f.loc` not referenced.

- [ ] **Step 3: Implement**

In the `_CLIENT_JS` `actionDetail` function, replace the single `Used at` line:

```javascript
    if(a.files && a.files.length){ h+='<div>Used at: '+a.files.map(esc).join(", ")+'</div>'; }
```

with a block that renders one entry per line (a link when `href` is set, else text + copy). **Use a DISTINCT `copy-loc` class, NOT `copy`** — the existing command handler does `det.querySelector(".copy")` (first match) and binds it to `a.command`; a sunset action has no command, so a shared `.copy` on a call-site button would be wrongly bound to the undefined command. Keeping the class distinct avoids that collision:

```javascript
    if(a.files && a.files.length){
      h+='<div class="usedat"><b>Used at:</b>';
      a.files.forEach(function(f){
        if(f.href){
          var u=safeUrl(f.href);
          h+='<div class="callsite">'+(u? '<a href="'+escA(u)+'" rel="noopener">'+esc(f.loc)+'</a>'
                                        : esc(f.loc))+'</div>';
        } else {
          h+='<div class="callsite">'+esc(f.loc)
            +' <button class="copy-loc" data-loc="'+escA(f.loc)+'">copy</button></div>';
        }
      });
      h+='</div>';
    }
```

Wire the call-site copy buttons in the SAME accordion-open block, immediately after the existing single command-copy bind (the `var b=det.querySelector(".copy"); if(b)…` at ~line 238). Add:

```javascript
                  det.querySelectorAll(".copy-loc").forEach(function(b){
                    b.addEventListener("click", function(ev){ ev.stopPropagation();
                      if(navigator.clipboard) navigator.clipboard.writeText(b.getAttribute("data-loc")); });
                  });
```

`stopPropagation` prevents the row from collapsing on copy. The existing command bind (`querySelector(".copy")`) is unchanged and returns `null` for a command-less sunset (its `if(b)` guard already handles that). Add CSS to the inline `<style>` — reuse the existing `.copy` button styling for `.copy-loc`, plus one-per-line for `.callsite`:

```css
.callsite{padding:2px 0;font-family:ui-monospace,monospace;font-size:12px}
.copy-loc{cursor:pointer;border:1px solid var(--line);background:none;color:var(--text);border-radius:4px;margin-left:6px;font-size:11px}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dashboard_render.py -q`
Expected: PASS (all dashboard tests, incl. the pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add agent/lib/dashboard_render.py tests/test_dashboard_render.py
git commit -m "feat(dashboard): call-sites on their own line, clickable or copyable

Each 'Used at' file:line renders on its own line: a blob permalink (safeUrl+escA)
when the repo has a known remote, else the loc as text with a copy button. General
(any files list). safeUrl stays http(s)-only. XSS + no-credential asserted."
```

---

## Task 5: repoint eBay `source` URLs + the catalog lint (research + data, runs last)

**Files:**
- Modify: `agent/vendor_sunsets.yaml`
- Test: `tests/test_vendor_sunsets.py`

**This task uses live docs — verify, never invent.**

- [ ] **Step 1: Verify the specific retired-API pages**

The two eBay sunset entries (`svcs.ebay.com` = Finding API, `open.api.ebay.com` = Shopping API) both currently point at the generic `https://developer.ebay.com/develop/get-started/api-deprecation-status`. Find the most specific stable page for each:
- Open eBay's API-deprecation-status page and the Finding API / Shopping API doc landing pages; confirm the URLs resolve (HTTP 200).
- Prefer the specific API's own deprecation/landing page. Where only the shared table exists, keep that URL but append a **text fragment**: `…/api-deprecation-status#:~:text=Finding%20API` — open it in a browser and confirm it scrolls/highlights. If the fragment doesn't apply, use the best-verified specific URL without it.
- Record which URL you chose for each and why in the commit message. **Do not invent a URL** — if a specific page can't be confirmed, keep the generic one for that entry (the lint permits up to 2 sharing a URL).

- [ ] **Step 2: Repoint the entries**

Edit the two eBay entries' `source:` in `agent/vendor_sunsets.yaml` to the verified specific URLs. Keep every other field unchanged.

- [ ] **Step 3: Write the lint test**

Add to `tests/test_vendor_sunsets.py`:

```python
def test_no_more_than_two_entries_share_a_source_url():
    # genericness guard: a lazy shared citation (many APIs -> one index page) regresses loudly.
    import collections
    from agent.lib import vendor_sunsets as vs
    cat = vs.load_sunsets()
    counts = collections.Counter(s.get("source") for s in cat if s.get("source"))
    offenders = {url: n for url, n in counts.items() if n > 2}
    assert not offenders, f"more than 2 sunset entries share a source URL: {offenders}"
```

- [ ] **Step 4: Run the lint + the eval regression net**

```bash
.venv/bin/python -m pytest tests/test_vendor_sunsets.py -q          # lint + existing sunset tests pass
DRIFT_GITLAB_HOSTS=git.topsdemo.in ./bin/drift-eval run ebay --now 2026-07-17   # recall MUST still be 5/5
```
Expected: lint passes; `drift-eval run ebay` prints `RECALL 5/5 … [PASS]` (the `remote_url` capture is additive — recall must not move). If recall dropped, the scanner change regressed — stop and fix before committing.

- [ ] **Step 5: Commit**

```bash
git add agent/vendor_sunsets.yaml tests/test_vendor_sunsets.py
git commit -m "feat(sunset): precise per-API citations + shared-source lint

Repointed the eBay Finding + Shopping sunset sources to <the verified specific
pages / text-fragment>. Lint fails if >2 entries share one source URL so a
generic citation can't silently regress. drift-eval run ebay still 5/5."
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `remote_url` capture, credential strip at capture | 1 |
| normalizer test cases incl token-strip | 1 |
| thread `remote_url` into repo doc (additive) | 2 |
| `_permalink` GitHub/GitLab shapes, sha-pinned, env allow-list, unknown→None | 3 |
| projection rewrites `files` → `[{loc,href}]` | 3 |
| JS: each call-site own line, link-or-copy, general | 4 |
| safeUrl unchanged (http(s) only); local = copy-path | 4 |
| XSS + no-credential-in-HTML asserted | 4 |
| #1 repoint sources + text-fragment | 5 |
| shared-source lint | 5 |
| eval 5/5 regression net | 5 (Step 4) |
| determinism / no network in unit tests | all (git injected, no live calls) |

No gaps.

**Placeholder scan:** the only deferred-to-build value is Task 5's concrete eBay URLs (explicitly a verify-not-invent research step, with a documented fallback). All code steps carry complete code; all test steps carry test bodies.

**Type consistency:** `normalize_remote(raw) -> str|None` (T1) → `git_meta` `remote_url` (T1) → `to_superset_repo` `remote_url` (T2) → `_build_projection` reads `r["remote_url"]`/`r["head_sha"]` and calls `_permalink(remote_url, head_sha, loc)` (T3) → JS reads `f.loc`/`f.href` (T4). Cross-checked end to end. The action `files` shape changes from `list[str]` to `list[{loc,href}]` exactly once, in T3's `_build_projection`, and T4's JS is the only consumer — no stale reader of the old shape (the old inline `map(esc).join` line is deleted in T4, asserted by a test).

**Resolved collision (T4):** the existing command-copy binds `det.querySelector(".copy")` (first match) to `a.command`. A sunset action has no command, so a shared `.copy` class on call-site buttons would wrongly bind the first call-site button to the undefined command. T4 gives call-site buttons a **distinct `copy-loc` class** bound via `querySelectorAll(".copy-loc")`, leaving the command bind untouched (its `if(b)` guard already handles a command-less action). Verified against the current JS at `dashboard_render.py:238`.
