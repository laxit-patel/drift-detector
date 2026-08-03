# Design note: runtime egress as a third detection modality (and why ZAP isn't us)

**Prompted by:** "Does OWASP ZAP do what we do? What if we made a Laravel *probe* package — would
it be more effective?" Short answers: no, and it's a strong idea at the wrong altitude. This note
records the model it led to.

## ZAP is a different quadrant

| | OWASP ZAP | Drift Detector |
|---|---|---|
| Type | **DAST** — dynamic app *security* testing | **Static** source analysis + curated retirement catalog |
| Question | "Can an attacker break *in*?" (XSS, SQLi, headers) | "Which of my outbound integrations are *dying*?" |
| Target | the app's **inbound** attack surface | the app's **outbound** third-party dependencies |
| Needs | the app **running**, actively probed | just the **source**, zero footprint |

Near-zero overlap. ZAP is not a competitor and not a template. But it forces the right axis:
**static vs. runtime**, which is exactly where our known weakness lives.

## The three detection modalities

Our hardest blind spot — the thing the path-constant idioms and the AI probabilistic scan both
*work around* — is the **runtime-resolved URL**: host in `$config['host_name']`, path assembled at
call time. Three ways to see an integration, each with a different failure mode:

| Modality | Sees | Certainty | Fails when |
|---|---|---|---|
| **Static** (shipped) | *every* code path, zero footprint, deterministic | inferential | the value is resolved at runtime |
| **AI probabilistic** (shipped 2026-07-31) | intent, config-driven wiring, exotic idioms | probabilistic (unverified) | it guesses wrong — must pass the gate |
| **Runtime egress** (banked) | the **actual** outbound call: real host, path, version | ground truth | the path never *ran* during observation; invasive |

The three are complementary, not ranked: **static for coverage of every path, runtime for ground
truth on the paths that ran, AI for cognition on the rest.**

## Why a Laravel *package* is the wrong altitude

The instinct — instrument the app to observe real calls — is right. A framework package is not.

- Laravel's `Http::` facade emits events you could hook cheaply. **But the wrappers that actually
  gave us trouble** (Catch, Magento, MySale, Marketplacer…) instantiate their **own raw
  `curl_exec` / Guzzle clients**. A Laravel-HTTP-client hook sees *none* of them — it catches the
  easy calls and misses exactly the hard ones we built path-constant idioms for.
- Catching raw-curl wrappers needs **network-level egress capture** — eBPF, an OTel
  auto-instrumentation agent, or a sidecar that observes the socket `connect()` regardless of which
  HTTP library made it. That is **library- and framework-agnostic**, and it is where the ground
  truth actually lives.
- Many shops already emit this via **APM/OTel** (Datadog / New Relic / OpenTelemetry spans carry
  outbound host + path). Consuming that is far cheaper than building — and maintaining — a package
  per framework (Laravel, then Symfony, then Node, then…).

So the effective runtime approach is **observe egress at the network/OTel layer**, not a framework
package.

## Where it fits: it feeds the ONE gate

Runtime egress is not a new engine. It is the **highest-confidence lead source** for the pipeline
we already built:

```
static ─┐
AI ─────┼─▶  a proposed integration/finding  ──▶  absorb gate (verify)  ──▶  certified
runtime ┘        (runtime leads are near-certain: the call actually happened)
```

"The app called `api.catch.com.au/v2/orders` at 14:03" is a stronger lead than AI's inference and
stronger than a static path-constant guess — but it is still a **lead**, not a certified finding,
until it passes the gate (which sources the vendor + any retirement date). Same discipline, better
input. The trust boundary is unchanged: observation proposes, the deterministic gate certifies.

## The caveat that keeps it a complement, not a replacement

**A runtime probe only knows about integrations that *ran* during the observation window.** The
rarely-hit call that breaks in prod six months from now — the exact one you most want to catch —
may never fire while you're watching. Static sees it because it *reads the code*; runtime doesn't
because it never *executed*. Runtime also breaks our two crown-jewel properties:

- **Zero footprint** — static reads a repo and touches nothing; runtime requires an agent in a
  live environment.
- **Deterministic / reproducible** — static is byte-identical run to run; runtime coverage depends
  on traffic, which is not reproducible. It therefore lives **outside** the `verify` contract, like
  the AI probabilistic pass — a lead source, never a certified surface.

## Verdict & first step

Compelling as a **third modality that feeds the gate**, not as a replacement for static scanning.
For a Laravel-heavy client:

1. **Do NOT build a framework package first** — it misses the raw-curl wrappers, the exact case we
   care about, and it's a per-framework treadmill.
2. **Cheap high-value first step:** check whether the client already runs OTel/APM and **consume its
   egress spans** (outbound host+path) → join against the vendor/sunset catalog exactly like a
   scanned endpoint. Ground-truth integration map for near-zero build.
3. If they don't emit egress telemetry, a **socket-level capture** (eBPF or a thin sidecar) beats a
   framework package because it is library- and framework-agnostic.

## Non-goals

- No runtime signal in the deterministic scan path or the `verify` contract — it's a lead source,
  gated like AI.
- No per-framework package treadmill — go network/OTel-layer, once, for all stacks.
- Don't confuse this with the existing `drift-scan probe` (the pre-scan *scope gate* — a different
  "probe"). This is runtime **egress observation**.

*Relates to `docs/next-iteration/DECISION-RECORD.md` (§14/§16 gated intake) and the probabilistic
scan (`docs/superpowers/specs/2026-07-31-probabilistic-scan-design.md`) — runtime egress is the
same "observe → propose → gate → certify" loop with a higher-confidence observer.*
