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

---

## Public-lane freshness research as a Workflow (parallel fan-out)

**Status:** banked 2026-07-29. Today the freshness agent (`/drift-refresh`, the Curator) is a
**promptfile** — one Claude session working vendors sequentially. That is correct for the
current scale (a handful of unaudited vendors) and for the **portal lane** (human-in-the-loop
seller logins — you cannot parallelize a person).

**The upgrade, when it's worth it:** the **public lane** — vendors whose deprecation docs are
public (AWS, Google, Kogan, Mailgun, …) — is compute-bound and independent. Each vendor's
changelog is its own web-research task, so it fans out cleanly: a Workflow script spawns one
`agent()` per vendor via `parallel()`, each returns a candidate sunset (schema-validated), then
ONE `absorb` pass sweeps them all. Wall-clock collapses from Σ(vendors) to the slowest single
vendor (~12 min → ~3 min for 6, in the sketch).

**What must NOT change:** every candidate still funnels through the deterministic `absorb` gate
(no `source` + parseable date → refused), and a human still merges the catalog MR. The workflow
parallelizes only the *research*, never the firewall. The portal/HIL lane stays a promptfile.

**Why deferred:** at today's vendor count the promptfile handles both lanes fine; parallelism
buys nothing until the unaudited-**public**-vendor list grows to ~a dozen+. Build the Workflow
for the public lane only when that list is long enough that sequential research is the
bottleneck. Not a rewrite — a second entry point beside the promptfile.

---

# Banked concerns — 2026-07-29 (runtime signal + detectability feedback loop)

Five ideas raised together. The first two are one axis (a **dynamic/runtime** egress signal to
complement today's **static** analysis); the middle two are one axis (a **feedback loop** that
makes the codebase easier to scan over time); the last is a minor note.

## 1 · Runtime egress from access logs (dynamic detection)

**Idea:** identify the actual network calls from **access logs** (not necessarily live) rather
than only from source. Especially for languages we read poorly (the 7-of-8 egress-rule gap —
Kotlin/Go/etc.), a log line `GET https://api.x/v2/orders` is **language-agnostic ground truth**:
it sidesteps "every language abstracts egress differently."

**Honest assessment.** High-value as a SECOND signal that *augments* static (confirms calls,
adds hosts/versions static missed), never replaces it. But it breaks three things static gives:
(a) **determinism** — logs vary run to run; (b) **exhaustiveness** — a log only shows code paths
that actually EXECUTED, so absence in logs ≠ absence in code (the opposite failure mode from
static); (c) **access/PII** — needs staging/prod egress logs, which carry privacy + credential
exposure. The user's "not live, a batch of historical logs" framing is the right one — a day of
egress as a corpus, less friction than live tapping. Would feed the SAME endpoint/attribution
model (host → vendor, path → version), tagged `attribution: observed-runtime` so a reader can
tell a real hit from a static match. **Deferred:** it's a whole new ingestion path + a
determinism carve-out; bank until a client has weak-static-language repos AND accessible logs.

## 2 · Async local observer / middleware (embedded runtime signal)

**Idea:** a middleware / log hook that runs **async** (never blocks the main thread) alongside
the project locally and observes its outbound calls — the embedded, dev-time version of #1.

**Honest assessment.** This is exactly what **OpenTelemetry / APM HTTP-client instrumentation**
already produces (outbound HTTP spans: method, host, path, status). The honest move is to
**consume OTel/APM egress spans** rather than build a bespoke per-framework observer — otherwise
it's a Laravel middleware + a Guzzle interceptor + a Node hook + … forever. Same value and
caveats as #1 (ground truth, but execution-coverage-bound, non-deterministic). It's also a
different PRODUCT surface (an agent/sidecar, not a static scanner) — a bigger commitment than a
CI job. **Deferred:** revisit if a client already runs OTel and wants drift fed from real
traffic; then it's "read their existing spans," not "build an observer."

## 3 · Flag confusing net-call code for standardization (detectability linter)

**Idea:** when someone writes confusing/non-standard network-call code the scanner can't follow,
**flag it for simplification/standardization** — so next scan it's an easy catch, making the net
we cast more robust (we stop missing obvious strings).

**Honest assessment.** The tool ALREADY localizes exactly this: `residue.sinks` +
`config-driven-url` path literals ARE the "confusing code" signals, at `file:line`. So this is
mostly a RENDERING + a suggested-pattern library on top of data we compute: turn a residue entry
into an actionable "this call assembles its URL in a way we can't trace — here's the standard
shape." Creates a virtuous loop: as devs standardize, detection improves for free. Fits the
Developer/Maintainer streams as a low-severity "detectability" suggestion. **Guardrail:** only
flag where it actually caused a MISS (residue), never stylistic nagging — a preachy linter gets
muted. **Deferred:** additive and low-risk; do it when someone wants the loop, after the higher-
value access work.

## 4 · URLs in `.env` (minor)

**Concern:** base URLs may live in `.env` (unreadable — gitignored/secret), so a host set only
there is invisible. **Assessment — mostly a non-issue, as the user reasoned:** `.env` typically
holds the HOST + credentials; the PATH + VERSION (what retirement detection needs) is written at
the call site, so the version is usually still visible in code. And a host-less versioned path is
NOT a silent miss — it lands in `config-driven-url` residue, honestly flagged. Cheap future win:
read `.env.example` (often committed) for the host when present. Low priority.

## 5 · PR in-house libraries to improve their detectable shape

**Idea:** the wrapper libs (`tops/*`) are in-house — we can modify them — so the tool should be
able to open PRs against THEM to make their integration calls easier to detect (explicit URL
assembly, operation markers, standard patterns).

**Honest assessment.** Strong, and it's the counterpart to absorption: instead of teaching the
SCANNER a confusing shape (a vendor-scoped idiom — itself banked), **fix the CODE to a standard
shape** so no idiom is needed and every future scan catches it plainly. Fits the Developer/
Maintainer MR stream, scoped to in-house repos: scan the wrapper as a fleet repo → its residue
localizes the un-scannable calls → generate a suggested-refactor MR. **Blast radius:** a shared
library's code change affects every consumer, so these MRs are proposals a human weighs, not
auto-applied. **Relationship:** often *cheaper and more durable* than the vendor-scoped-idiom
enhancement — a one-time code cleanup vs. a permanent detection special-case. Bank alongside
vendor-scoped idioms; when both are on the table, prefer fixing in-house code over teaching the
scanner a workaround.
