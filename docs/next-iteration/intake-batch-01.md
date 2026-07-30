# Intake batch 01 — the AI-vs-tool experiment, absorbed

The 2026-07-30 experiment (20 AI agents vs the deterministic tool) surfaced integrations the
tool was blind to. This is the triage of that output into what was absorbed, what is a
work-order, and what is priced upkeep. **Rule held throughout: no retirement date enters
without a live source; coverage entries carry a verified `file:line`.**

## The mechanism split (the load-bearing finding)

A blind wrapper repo becomes KNOWN only through the mechanism its code shape allows. The
experiment's 8 new vendors split cleanly — and **only host-literal vendors are a one-line add**:

| Vendor | Repo | Host in code? | Mechanism | Status |
|---|---|---|---|---|
| **Tradevine** | tradevine | `$baseUrl = "https://api.tradevine.com/"` @ `Tradevine.php:23` | vendor host row | ✅ **absorbed** (0→KNOWN) |
| **Trade Me** | tradevine | literal @ `Trademe.php:23` | vendor host row | ✅ **absorbed** (0→KNOWN) |
| Marketplacer | myerapi | config-injected (`config['source_url']`) | SDK-profile / concat-idiom | work-order |
| Magento | magento_api | config-injected (`ENDPOINT` runtime) | SDK-profile / concat-idiom | work-order |
| MySale | mysaleapi | config-injected (`config['base_url']`) | SDK-profile / concat-idiom | work-order |
| Catch | catchapi | config-injected (`config['host_name']`) | SDK-profile / concat-idiom | work-order |
| Mirakl | bunnings | config-injected (per-tenant `*.mirakl.net`) | SDK-profile / concat-idiom | work-order |
| Harvey Norman | harveynorman | config-injected | SDK-profile / concat-idiom | work-order |

**Proven, both directions:**
- Adding the Tradevine + Trade Me host rows flipped `tradevine` from 0 → 2 KNOWN vendors.
- Adding a Marketplacer host row did **nothing** to `myerapi` (0 → 0) — no host literal to match.
  A vendor row is inert without a host literal or a distinctive path-signature.

**Note:** THE ICONIC and TheMarket (catalogued earlier this session) are in the *same*
config-injected boat — catalogued but their repos still score 0 until they get a profile/idiom.
Cataloguing a vendor is a *prerequisite*, not a detector, for the config-injected shape.

## Why the 6 need more than a row

Their hosts are injected at runtime, so there is no URL literal to classify. What they *do*
have is **path constants** (`v1/SalesOrder`, `V1/products`, `api/v2/client/adverts`,
`/api/offers`, …) assembled onto the base via `$this->baseUrl . $path`. Two ways to read them:

1. **SDK-profile** (repo → vendor, version from a const) — the mechanism shipped this session.
   Fastest; yields *coverage* (attributes the repo to the vendor at the const `file:line`).
   Yields *findings* only once a retirement is catalogued for that vendor — none of these 6
   have one yet, so profiles buy coverage, not findings, today.
2. **concat-idiom** (the amazonspapi 3→272 mechanism) — reads the base+path assembly to
   attribute each operation at its own `file:line`. More work, but recovers the operation axis.

The tool's residue already points at exactly these blind sinks (e.g. `myerapi` residue = 4
egress sinks), so the "cannot see" is honest and located, not silent.

## Pile B — Curator lead (not absorbable as a coverage row)

- `channelwiz-api` Shopify Admin **2025-01** @ `config/constants.php:39`, AI flagged retired.
  This is **already covered**: the tool computes Shopify version lifecycle deterministically
  (it fired 4 Shopify findings in the 33-repo fleet scan). No new date to invent.

## Pile C — priced upkeep (no detectable signal → honest UNKNOWN)

- **Neto/Maropost** (`neto`): action-constant API (`apiGetOrder` POSTed to a config URL) — no
  host, no path, no version. Nothing deterministic to grip.
- **Vendored AWS SDK** (`amazonapi`): the full SDK is vendored but no app code calls it.
- Config-driven Mirakl base in `channelwiz-api` (host in a `GlobalSetting` DB row).

These are the "cost of upkeep" line in the detectability report, not catalog entries.

## Recommended next step

Not 6 inert vendor rows. One proper vertical: pick the richest config-injected repo
(**Magento**, ~22 endpoints, or **Catch**, ~15) and build the concat-idiom that reads its path
constants → prove operation-level intake end-to-end at real `file:line`s, through the absorb
gate. That is the Project-Hybrid operation axis, exercised on a real repo the AI mapped for us.
