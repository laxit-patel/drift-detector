"""
§14 AI intake — the ENTIRE thing. Reference sketch, not production code.

The point of this file: to show that "let AI read the blind spots and feed the gate" is
~40 lines of plumbing, NOT an AI application. The AI is the `query(...)` call — 4 lines.
Everything else already exists in the repo. Read the "WHAT IS NOT HERE" block at the bottom;
that is your entire RAG/MCP/embeddings/multi-agent wishlist, mapped to "not needed, and why".

Pieces that ALREADY EXIST (zero new work):
  • docs/drift-absorb.md  — the prompt. A markdown promptfile. (Kevin.)
  • `drift-scan absorb`       — the gate. Deterministic. Refuses unsourced/invented/false claims.
  • the shape verdict         — the classifier. Already labels repos KNOWN / UNKNOWN+reasons.
The ONLY new thing is the ~40 lines below that connect them.
"""
import asyncio
import subprocess
from claude_agent_sdk import query, ClaudeAgentOptions   # pip install claude-agent-sdk


# ── the ONLY AI step: read the repo, write staged YAML. Nothing else. ──────────────
async def ai_read_and_stage(repo_path: str, staging_dir: str) -> None:
    opts = ClaudeAgentOptions(
        system_prompt=open("docs/drift-absorb.md").read(),   # the promptfile — EXISTS
        # locked down: it may READ code and WRITE ONLY into the staging dir. Nothing else.
        allowed_tools=["Read", "Grep", "Glob", f"Edit({staging_dir}/**)"],
        permission_mode="dontAsk",     # unlisted tools are DENIED, never prompted
        cwd=repo_path,                 # it reads the repo directly — no index, no RAG
    )
    prompt = (f"Absorb {repo_path}. Stage idioms/profiles into {staging_dir} as reviewed YAML. "
              f"Cite a real file:line for every claim. Never record a date you did not read.")
    async for _ in query(prompt=prompt, options=opts):
        pass    # we don't parse the model's chatter — its OUTPUT is the staged YAML on disk


# ── the loop: classify (exists) → AI stage (above) → gate (exists) → human MR ──────
async def intake(scan_state, staging_dir: str) -> None:
    # 1. WHICH repos need cognition? The deterministic scan ALREADY told us.
    flagged = [r for r in scan_state.repos
               if r["verdict"] == "UNKNOWN" and "needs-cognition" in r["reasons"]]

    for repo in flagged:
        # 2. AI reads → stages YAML.  (the 4-line call above; the WHOLE "AI app")
        await ai_read_and_stage(repo["path"], staging_dir)

        # 3. THE GATE — deterministic, already exists. It, not the model, decides truth:
        #    refuses an unsourced date, a false attribution, or grown residue. Loops the
        #    agent on machine-readable problems; hard-fails after N rounds.
        gate = subprocess.run(
            ["drift-scan", "absorb", "--check", "--staged", staging_dir, "--repo", repo["path"]],
            capture_output=True)

        # 4. On a clean gate: open an MR. A HUMAN MERGES. The bot never pushes to the catalog.
        if gate.returncode == 0:
            open_merge_request(staging_dir, repo["path"])   # git plumbing, not AI


def open_merge_request(staging_dir: str, repo: str) -> None:
    ...   # `glab mr create` on an absorb/<repo> branch — boring git. The human clicks merge.


if __name__ == "__main__":
    # In CI: run after the deterministic scan, on a manual/scheduled trigger. Opt-in stage.
    scan_state = ...          # read <state>/inventory.json (the scan already produced it)
    asyncio.run(intake(scan_state, staging_dir=".drift-detector/absorb-staged"))


# ══════════════════════════════════════════════════════════════════════════════════
# WHAT IS *NOT* HERE — your entire "AI application" wishlist, and why each is absent:
#
#   RAG / vector DB / embeddings ....... NOT NEEDED. The agent reads the ONE repo directly
#                                        (Grep/Read). There is no corpus to retrieve from —
#                                        it has the whole repo in front of it.
#   BM25 / multi-index search .......... NOT NEEDED. Nothing to index; one repo at a time.
#   MCP server/client .................. NOT NEEDED. The SDK's built-in Read/Grep/Edit are
#                                        the only tools it needs. (Later, if it must reach a
#                                        private forge on managed infra, that's ONE connector
#                                        — still not an "application".)
#   Multi-agent orchestration .......... The router (§16) dispatches one agent PER flagged
#                                        repo — but each is a single `query()`. No panel,
#                                        no debate, no chaining.
#   Prompt-eval framework / XML prompts  NOT NEEDED. The GATE is the eval. The prompt is a
#                                        markdown file. There is no "did the model do well?"
#                                        metric to engineer — `absorb` passes or it doesn't.
#   Citation engine .................... NOT NEEDED. The gate REQUIRES evidence file:line, so
#                                        the model produces it or the gate rejects it. Citation
#                                        is enforced by the firewall, not built as a feature.
#   "Provide docs/files if it needs" ... NOT NEEDED. The code IS the source of truth; it reads
#                                        it. (Vendor docs are the Curator/freshness lane, gated,
#                                        and that's a HUMAN-portal task, not this.)
#   A system prompt / structured output  These two you DO have — and they're 2 lines:
#                                        system_prompt=<the promptfile>, and the output is
#                                        "staged YAML on disk" (structure enforced by the gate,
#                                        not a JSON schema you maintain).
#
# The moat is NOT any of the above. Anyone can wire an SDK to a repo. The moat is the GATE +
# the curated catalog + `verify` — the deterministic parts that make the output trustworthy.
# This file is the intake; those parts are the product. Don't confuse the two.
# ══════════════════════════════════════════════════════════════════════════════════
