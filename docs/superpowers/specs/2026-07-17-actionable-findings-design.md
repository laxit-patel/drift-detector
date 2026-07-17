# Spec A — Actionable Findings (citations + clickable call-sites)

**Date:** 2026-07-17
**Status:** approved for planning
**Scope:** two PM-demo fixes — #1 precise citation links, #3 clickable file:line call-sites. Strategy by Fable 5; the `getCategoryFeatures` finding (#2) was verified to be the deterministic ceiling (no bug) and, with #4, is deferred to Spec B.

## Problem

A PM demo surfaced that findings are hard to *act on*:
1. A sunset finding's **"source ↗"** opens the whole eBay API-deprecation-status page, not the specific retired API — the citation is generic.
2. The **"Used at"** call-sites are rendered inline, comma-separated, and are **not clickable** — you can't jump from a finding to the code.

Both are the same user moment: "I see a finding — now let me act on it." This spec makes that moment work.

## Goals

- **#1:** each sunset finding cites the *specific* retired API, not a generic index page. Prevent generic-citation regressions with a lint.
- **#3:** every call-site renders on its own line and is **clickable** — a GitHub/GitLab blob permalink pinned to the scanned commit when the repo has a remote, or a copy-path button for a local repo. **No credential ever appears in the shared dashboard.**
- Deterministic, zero-LLM, and the dashboard stays a self-contained `file://` document.

## Non-goals

- **#4** (private-vs-unknown dashboard section) and **#2's** ceiling-surfacing + corpus pin → **Spec B**.
- SDK-session / config-driven call resolution or any dataflow/taint analysis — that's the deferred **cognition tier** (the `getCategoryFeatures` Trading-via-`$session` call is genuinely undetectable by string-literal AST; verified this session — the file's *literal* REST URLs are already detected correctly).
- A separate `migration:` catalog field — deferred; the repointed `source` carries the guidance.
- `vscode://` links — deferred; would require widening the `safeUrl` scheme allow-list (the dashboard's XSS gate). Local repos get copy-path only.
- Scraping vendor pages to synthesize anchors; live reachability probes.

## #1 — Citations (pure catalog data + a lint)

**No dashboard code changes** — the dashboard already renders whatever `source` an entry holds (via `safeUrl`). This is curation:

- **Repoint each `agent/vendor_sunsets.yaml` entry's `source`** at the specific retired API's own doc/deprecation page. Where only the shared table page exists, append a **[text fragment](https://developer.mozilla.org/en-US/docs/Web/URI/Fragment/Text_fragments)** — `…/api-deprecation-status#:~:text=Finding%20API` — which highlights/scrolls to that text in modern browsers and degrades gracefully to the plain page in others. Do **not** rely on row `id` anchors (eBay's table has none).
- The concrete URLs are a **build task**: verified against eBay's live docs, never invented. Each entry keeps its required `source`.

**Catalog lint** (a test, not runtime): fail if **more than 2** loaded sunset entries share the same `source` URL — so a lazy generic citation regresses loudly. Lives in `tests/test_vendor_sunsets.py`.

## #3 — Clickable call-sites

### Data flow

1. **`agent/lib/scan_util.py::git_meta`** gains `remote_url` — `git remote get-url origin`, **normalized and credential-stripped** (see below). Absent/no-remote → `None`.
2. It flows through `agent/lib/repo_scan.py` → `agent/lib/superset.py` into the repo doc: `repos[].remote_url` (beside the existing `head_sha`).
3. **`agent/lib/dashboard_render.py::_build_projection`** builds a `{repo_path: {remote_url, head_sha}}` map from `inventory["repos"]`, and for each action rewrites its `files` from `["path:line", …]` to **`[{loc, href}]`**, where `href = _permalink(remote_url, head_sha, loc)` or `None`.
4. The inline JS renders each `{loc, href}` on **its own line**: `href` present → a link (through `safeUrl`); else `loc` as text + a **copy button** (copies the `loc` string).

**The permalink URLs are built in Python** (tested), not JS — so the credential-strip and host-detection logic is unit-testable and the JS stays a dumb renderer.

### `remote_url` normalization + credential strip (safety-critical)

A single tested function (in `scan_util.py`). Rules:

- `git@host:owner/repo.git` (scp-style ssh) → `https://host/owner/repo` (no credentials possible).
- `ssh://git@host/owner/repo.git` → `https://host/owner/repo`.
- `https://host/owner/repo.git` → `https://host/owner/repo`.
- **`https://user:token@host/owner/repo.git` → `https://host/owner/repo`** — the userinfo (`user:token@`) is **stripped**. This is the credential-leak guard.
- Always strip a trailing `.git`.
- If the result would still contain an `@` before the host, or can't be parsed to a clean `scheme://host/path`, return `None` (fail safe — no link rather than a risky one).

Test cases (all required): scp-ssh, ssh://, plain https, **https-with-token** (asserts the token is gone), self-hosted GitLab host, a garbage remote → `None`, empty → `None`.

### `_permalink(remote_url, head_sha, loc)` (in dashboard_render.py)

- Split `loc` into `path` + `line` (last `:` — paths have no `:` on Linux; a missing line → no `#L`).
- Host-detect (deterministic; a self-hosted GitLab host isn't guessable from the URL alone, so it's configured, not inferred):
  - host **exactly** `github.com` → `https://github.com/<owner>/<repo>/blob/<head_sha>/<path>#L<line>`.
  - host `gitlab.com`, **or** host containing `gitlab`, **or** host in the `DRIFT_GITLAB_HOSTS` env allow-list (comma-separated; e.g. `git.topsdemo.in`) → `https://<host>/<owner>/<repo>/-/blob/<head_sha>/<path>#L<line>`.
  - **anything else → `None`** (plain text; never a guessed link — a wrong permalink is worse than none).
- `remote_url` `None` or `head_sha` `None` → `None`.
- Pinned to `head_sha` — never a branch — so permalinks don't drift.

### Render (JS)

Replace the single line `h+='<div>Used at: '+a.files.map(esc).join(", ")+'</div>'` with a block that emits one `<div>` per file: an `<a href>` (via `safeUrl` + `escA`) when `href` is set, else `esc(loc)` + a copy button. Files render **generally** — the renderer is permalink-aware wherever `files` appear, not sunset-only.

## Escaping & safety (unchanged gate + the new guard)

- `href`s still pass through the existing `safeUrl` (http(s) allow-list) + `escA` — so a blob URL renders, a non-http scheme is dropped.
- **`safeUrl` cannot catch a leaked credential** (a `https://token@host/…` URL is valid http(s)). The defense is the **capture-time strip** in `scan_util`, tested. This is the one hard safety requirement of the spec.
- Copy button copies the `loc` text via `navigator.clipboard` (already used for the command copy).

## Testing

- **`tests/test_scan_util.py`** (new or extend): the `remote_url` normalizer — the 7 cases above, with the token-strip assertion the load-bearing one.
- **`tests/test_dashboard_render.py`**: `_permalink` builds the correct GitHub `/blob/` and GitLab `/-/blob/` shapes pinned to the sha; returns `None` for a non-git host, missing remote, or missing sha. The projection rewrites `files` to `[{loc, href}]`. The rendered HTML puts each call-site on its own line; a remote repo yields an `<a href>` blob link; a local repo yields text + a copy affordance. **XSS: a repo path / remote containing `"`/`<`/`</script>` doesn't break out** (existing escA/safeUrl coverage extended to the new links). **No credential: a token-bearing remote never appears in the output** (belt-and-suspenders with the capture-time strip).
- **`tests/test_vendor_sunsets.py`**: the >2-shared-`source` lint; the real catalog passes it after the repoint.
- No network in any unit test (git injected). The **eval harness** is the regression net for the scanner-capture change: `bin/drift-eval run ebay` must still pass recall 5/5 (the added `remote_url` is additive and must not perturb detection).

## Success criteria

Re-rendering the real `rushikesh/ebayapi` scan (remote on `git.topsdemo.in`, with `DRIFT_GITLAB_HOSTS=git.topsdemo.in` set) yields a dashboard whose eBay sunset "Used at" shows each of the four call-sites (`src/Ebay/…:37`, `src/config/ebay.php:39`, …) **on its own line as a clickable GitLab `/-/blob/<sha>/…#L37` permalink**, with **no token** anywhere in the file even if the clone URL carried one. (Without the env override, the same host renders as plain text + copy — safe, never a guessed link.) A local-folder scan renders the same call-sites as text with a working copy button. The eBay sunset's "source ↗" opens to the specific Finding/Shopping API deprecation notice, not the generic index. The catalog lint passes, and `drift-eval run ebay` still passes 5/5.
