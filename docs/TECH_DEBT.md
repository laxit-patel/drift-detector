# Tech debt & banked ideas

Deferred work that is understood but deliberately not built yet. Each entry says what it is,
why it's deferred, and where it would plug in — so picking it up later doesn't start cold.
(The big one — the Rust port — lives in `CLAUDE.md`, not here, because it has its own trigger
gate.)

---

## Pluggable source-resolver drivers (GitHub / GitLab / filesystem / public URL)

**Status:** idea, banked for the polished product. Not scheduled.

**Today.** A single resolver, `agent/lib/source_resolver.py::resolve_sources(roots, …)`, turns
each `fleet:` entry into scannable project dirs. It already handles four input *shapes* — a git
checkout, a plain folder, a git/GitLab URL (cloned into `<state>/sources/`), and a GitLab
*group* URL (expanded to its member repos via `agent/lib/gitlab.py`). Auth is whatever the
machine's own git can do, plus a `GITLAB_TOKEN` used as a transient clone credential. The fleet
is validated in `agent/lib/ops_config.py` to a **single https host** (so a GitLab group can be
expanded and the delivery host derived unambiguously).

**The limitation.** The resolver is effectively hardwired to *git-clone + GitLab-group* semantics
on one host. There's no first-class notion of a **source driver**, so:
- GitHub is only reachable as "a git URL to clone" — no GitHub-API group/org expansion, no
  GitHub-native archived/visibility filtering, no per-host token.
- A mixed fleet (some repos on GitLab, some on GitHub, some a local vendored drop) is impossible
  — `ops_config` rejects mixed hosts, and delivery assumes one GitLab host.
- "Scan this public URL / this tarball / this path on disk" is supported only incidentally (the
  plain-folder path), with no config knobs.

**The idea.** Formalize the seam into a small set of **drivers**, each selected per source and
carrying its own config block:

    fleet:
      - driver: gitlab
        host: git.topsdemo.in
        group: chetan            # API-expanded to member repos
        auth: GITLAB_TOKEN       # env-var name (matches config-v2 auth style)
      - driver: github
        org: acme-inc
        auth: GITHUB_TOKEN
      - driver: fs
        path: /mnt/client-drop/acme-src   # a vendored source folder, no history
      - driver: url
        url: https://example.com/src.tar.gz

Each driver implements one interface — roughly `expand() -> [source]` and
`materialize(source, state) -> (abs_dir, identity, kind)` — mirroring the injectable
`clone=` / `expand_group=` seams `resolve_sources` already exposes. `kind`
(`remote | local-git | local-plain`) is already carried into the report, so honest-coverage
messaging still works per driver.

**What this unblocks:** a genuinely multi-forge fleet, GitHub-org / GitLab-group expansion
through each forge's own API, per-host credentials, and scanning non-git sources (a client's
zipped drop, a public URL) as first-class config rather than a happy accident.

**Coupled changes when it's built:**
- `ops_config`'s single-host invariant relaxes to per-driver validation (the "one host" rule
  exists so group-expansion + delivery-host derivation are unambiguous — a driver model has to
  answer both per-entry instead).
- Delivery currently assumes one GitLab host; a multi-forge fleet means delivery routing
  becomes per-source too (a GitHub repo's findings can't be filed as GitLab issues).
- The config-v2 `auth:` block (env-var *names*) already fits — each driver names its own token
  var, no schema fight.

**Why deferred:** the current single-GitLab-host model covers the near-term deployments, and a
multi-forge resolver drags delivery routing along with it (above). Bank it until a real fleet
spans more than one forge, or a client needs GitHub-org / non-git sources.
