# Next-Iteration Decision Record

One page. The verdicts and their triggers, distilled from
[`2026-07-30-go-rewrite-and-wild-learning.md`](2026-07-30-go-rewrite-and-wild-learning.md)
(§1–13, Fable-5 review, pressure-tested across 7 rounds). This is the compass, not the map.

## The decisions

| # | Decision | One-line why |
|---|---|---|
| 1 | **Do NOT rewrite the core now** — keep the Python scan core; refactor in place (mypy-strict CI, import-linter, split `cli.py`, extract templates) | ~700 tests encode already-fixed bugs a rewrite re-derives; the core is still evolving; a rewrite ships zero new capability |
| 2 | **Greenfield language = Rust** | Closed-vocabulary (sum-types) domain where a silent wrong answer is the worst outcome — Rust's exhaustive `match` + `Result`/`#[must_use]` make the *compiler* do for code what the *absorb gate* does for data |
| 3 | **Migrate incrementally, not big-bang** — new surfaces (`drift-wild`, later `drift-fleet`) are Rust from day one; the core is ported later, oracle-guided | Same destination, safe path: `bin/drift-eval` is the equivalence oracle, byte-diff first, **port test-by-test** |
| 4 | **Learn-from-the-wild = deterministic corpus miner** (`drift-wild`, Rust): scan public vendor wrappers/specs with our own scanner → reviewed catalog data through `absorb` | Wild signals are Curator *leads, never dates*; never-invent-a-date is untouched. No AI in the core |
| 5 | **Analysis stays at rung 1** (AST-find + regex-classify) and enriches cheaply (wild-mined path signatures, version grammars) | Cheap signals + honest residue beat a dataflow engine — the residue conscience only works because every stage below it is simple enough to trust |
| 6 | **Engine = Front-End Contract** — per-language lanes behind one shared IR; generic tree-sitter is the universal rung-1 fallback; unknown files stay honest `UNKNOWN` | Not a new architecture — the ruleset already dispatches per-language; the contract *names the seam* so each lane is as deep as its language's best tooling allows, honestly reporting its rung |
| 7 | **Deep lanes = Mago (PHP), oxc (JS/TS), ruff (Python)** — all Rust-native crates, at the rungs we use | The strongest Rust exhibit: a Rust core embeds all three as *libraries*; a Go/Python/Kotlin core shells out to all three. PHP→Mago is lane #1 by sequencing |
| 8 | **SDK profiles — SHIPPED** (`agent/sdk_profiles.yaml` + `agent/lib/sdk_profiles.py`): read a wrapper's pinned version from its own constants → synthetic endpoints the audit dates, evidenced at the const `file:line` | The `sdk-only-no-callsite` wrappers hide vendor+version behind constants; no idiom reaches that, a profile does. First profile fired 4 retired-Shopify findings on `shopify-api`. Invents nothing (version is a read literal; date is the vendor rule) |
| 9 | **Autonomous absorption via the Claude Agent SDK (§14) — build near-term** as an opt-in, SEPARATE CI stage | The banked P4 scout, safe now the gate exists: the agent holds no token, authors *staged YAML only*, `absorb --check` is the firewall, a **human merges — no auto-merge, ever**. Bootstraps the profiles Mago later industrializes |
| 10 | **AI-native / hosted mode (§15) — build trigger-gated** as §14's gated loop re-hosted (Managed Agents scheduled deployment + MCP connectors) | A *delivery* evolution, not epistemic. **AI is the front-end (read/propose); the deterministic core is the back-end and the source of truth — never the front-end.** "AI-native" is a deployment adjective; SCAN + LEARN stay the only two loops |
| 11 | **The reader router (§16) — classify → auto-dispatch → merge**; the shape verdict routes needs-cognition repos to the AI, deterministic handles the rest | Not a new reader — **auto-dispatch to the ONE absorb mechanism** (AI proposes → gate measures → human merges → deterministic inherits): one mechanism, three artifacts (idioms/sunsets/profiles), four entry points (manual · autonomous-CI §14 · routed §16 · hosted §15) |

**Empirically validated (live experiment, 2026-07-30):** deterministic tool vs an AI reader (20 Sonnet agents), integration-detection only, 20 in-house repos. Tool saw **8/20** repos, all claims certified, ≈0 tokens. AI saw **20/20** — every one of the 12 config-driven/SDK blind spots (incl. inferring Myer→Marketplacer, Bunnings→Mirakl, which no rule could) — none of its claims verified, **782k tokens**. *Coverage* (20/20 vs 8/20) is the real metric, not the raw count. **The product is the pipeline that turns the AI's uncertified column into the tool's certified one** — i.e. §16 routing → §14 gate.

## Triggers — when each future step fires (never on aesthetics)

- **Core → Rust port:** pipeline stable ~a quarter with no structural change **AND** (single-binary distribution needed **OR** sold as a product). Executed **test-first, oracle-guided**.
  → **Python retires when its full test suite is absorbed into Rust and passes byte-identically.** The tests are both the spec and the equivalence proof.
- **Deep lane in the *scan path*** (Mago/oxc/ruff, not just the miner): the Rust core exists **AND** fleet residue proves client-side rung-2 misses actually occur (not just wrapper-side, which SDK profiling already covers). Lanes built **on demand**, never speculatively.
- **BM25 / embeddings / SLM:** only on a *logged* retrieval failure or a proven need — the corpus is lexical (URLs, paths), so BM25 before embeddings, and nothing before it's earned.
- **Autonomous SDK absorption (§14):** near-term, on commodity CI — proves the gated-author loop.
- **AI-native hosted mode (§15):** a hands-off / multi-tenant customer, CI plumbing becoming the measured bottleneck, or Managed Agents GA.
- **Mago extractor:** scale-gated behind §14 — ~20+ profiled packages or routine quarterly re-profiling, at which point it deterministically regenerates the Claude-bootstrapped profiles (each of which is its labeled example).

## Do NOW (cheap, weighting-independent)

- The **§8 Python refactor** package (mypy-strict as a CI gate — near-free given existing annotations — import-linter, split `cli.py`, extract dashboard templates).
- **Name the Front-End Contract in the IR** + a conformance suite (IR tests + rung-1 differential vs. the fallback lane) — this is what makes every future lane a plug-in instead of a fork.
- Build **`drift-wild` in Rust**; keep **Mago in the learn loop** (miner-side), server-side, behind the regeneration gate, with `mago@<version>` in provenance.

## Never

- Rung-4 type checking (or anything non-deterministic) in the scan path.
- AI / a model influencing the deterministic scan path.
- An invented or borrowed retirement date.
- A speculative all-language lane build — lanes follow real residue evidence.

---
*Real-world vs. greenfield delta:* greenfield, the answer is "Rust, whole system." The only reason the core stays Python is the sunk value of a working, still-moving, ~700-test codebase — a reason that expires exactly when the port triggers fire.
