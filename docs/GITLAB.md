# Scanning a GitLab fleet

The scanner works on a folder of local clones. `gitlab-sync` materializes your GitLab projects
into that folder, so the whole fleet — **including the private `tops/*` wrapper repos** — gets
scanned instead of silently missing.

Deterministic, read-only, no LLM.

## 1. Create a read-only token (one time)

On your GitLab (e.g. `https://git.topsdemo.in`): **Settings → Access Tokens** → create a token with
scopes **`read_api`** + **`read_repository`**. Copy it.

## 2. Keep the token out of everything

The token is read from the **`GITLAB_TOKEN` environment variable only** — never a CLI flag (which
would land in shell history and process args), never stored in `agent.json`, never committed. The
sync injects it into the clone URL transiently and then **strips it from each repo's `.git/config`**
(`remote set-url` back to the plain URL), so it isn't left on disk either. Any token text in error
output is redacted.

Put it somewhere private, outside any repo — e.g.:

```bash
printf '%s' 'glpat-…' > ~/.drift-gitlab-token && chmod 600 ~/.drift-gitlab-token
```

## 3. Sync, then scan

```bash
export GITLAB_TOKEN="$(cat ~/.drift-gitlab-token)"

# clone/pull everything the token can see (add --group <path> to scope to a group)
<plugin>/bin/drift-scan gitlab-sync \
  --base-url https://git.topsdemo.in \
  --dest ~/gitlab-fleet \
  --active-days 90            # optional: only projects touched in the last 90 days

# then the usual pipeline over the synced folder
/drift-detector ~/gitlab-fleet
```

Re-running is cheap: existing clones are fetched (`--depth 1`) instead of re-cloned, and the
scanner's per-repo commit-SHA cache means only changed repos are re-analyzed.

## Notes
- Archived projects are skipped; one repo failing to clone doesn't abort the sync (it's reported).
- `--group <path>` uses the group API (`include_subgroups=true`); without it, `membership=true`
  syncs every project the token can see.
- Because the `tops/*` wrapper repos are themselves projects in GitLab, syncing the fleet makes
  their endpoints visible. (Attributing a wrapper's endpoints back to the apps that depend on it
  is a further step — for now they show under the wrapper's own repo.)
- **Rotate the token** if it was ever pasted into a chat, ticket, or shared terminal.
