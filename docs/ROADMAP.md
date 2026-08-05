# Drift Detector — roadmap & direction

> Kept out of the README to keep the front page focused on *using* the tool. This is where it's headed.

## 🦀 This is the pilot — the destination is Rust

The current tool is written in **Python**: it's the **pilot** that proves the whole idea in
production — the pipeline, the reviewed catalogs, and the `verify` contract. The intended
end-state is a single, no-network **Rust** binary.

Why Rust specifically: it is the *only* language that links the **ast-grep** scan engine
**natively** (the same crates the ast-grep CLI uses) — Go has no binding, and the Node route puts
PHP on a 0.0.x grammar. The reviewed YAML catalogs port for free; the pipeline modules follow once
they've held a quarter without structural change. It is **not** a performance play (the scan
already runs inside a Rust binary today) — it's about shipping **one hardened artifact** with no
Python/venv to provision.

The next iteration is expected to be a **from-scratch Rust rewrite**, with this Python repo kept as
the archived precursor.

## What's next

- **A native Rust engine** — the destination above.
- **Trend history** — the dashboard shows the *latest* run; week-over-week burn-down needs a
  multi-run archive (a real persistence layer, not faked from one run).
- **Broader fleet access** — the scanner only covers repos its token can *read*; the rest are
  flagged blind. Giving the bot read access across the fleet unlocks full coverage.
- **More integration shapes** — each new vendor/API idiom is a reviewed catalog contribution
  through the `absorb` gate (the reviewed adaptation mechanism).
- **AI — undecided.** An opt-in probabilistic cross-check exists, but whether AI becomes a
  first-class feature (leads shown *beside* certified findings, behind a strict
  certified/unverified firewall) is an open question. The deterministic core is the product; AI
  stays an experiment until it earns its keep.

---

🦀 *Heading to Rust.*
