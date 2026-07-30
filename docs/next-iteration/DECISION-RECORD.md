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

## Triggers — when each future step fires (never on aesthetics)

- **Core → Rust port:** pipeline stable ~a quarter with no structural change **AND** (single-binary distribution needed **OR** sold as a product). Executed **test-first, oracle-guided**.
  → **Python retires when its full test suite is absorbed into Rust and passes byte-identically.** The tests are both the spec and the equivalence proof.
- **Deep lane in the *scan path*** (Mago/oxc/ruff, not just the miner): the Rust core exists **AND** fleet residue proves client-side rung-2 misses actually occur (not just wrapper-side, which SDK profiling already covers). Lanes built **on demand**, never speculatively.
- **BM25 / embeddings / SLM:** only on a *logged* retrieval failure or a proven need — the corpus is lexical (URLs, paths), so BM25 before embeddings, and nothing before it's earned.

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
