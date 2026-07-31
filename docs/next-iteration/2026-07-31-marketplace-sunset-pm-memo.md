# Memo: marketplace-integration retirement risk — findings & gaps

**Date:** 2026-07-31 · **From:** Drift Detector (Ashen Oracle) · **Re:** the newly-detected seller-portal integrations

We recently taught the scanner to see the config-driven marketplace integrations it was previously
blind to (Catch, Magento, MySale, Marketplacer/Myer, Mirakl/Bunnings, Virtualstock/Harvey Norman,
plus MyDeal, TheMarket, Kogan, Trade Me, BigCommerce, THE ICONIC, Temu). The open question was:
**do these platforms publish retirement schedules we can act on, or are we flying blind?**

We ran a live web search under our strict rule — **no date enters the catalog without a source URL
fetched this session**. Here is what came back.

---

## 1. Acted on already — integrations pointing at DEAD platforms 🔴

The most urgent finding: **three marketplaces our code still calls have shut down entirely.** A call
to a dead marketplace is not "deprecated someday" — it is broken in production today. All three are
now flagged as action-required, at exact `file:line`:

| Platform | Shut down | Call-sites flagged | Where |
|---|---|---|---|
| **Catch** (Wesfarmers) | 2025-04-30 | 44 | `catchapi` wrapper |
| **MySale / OZSale** | 2026-01-27 | 15 | `mysaleapi` wrapper |
| **MyDeal** (Woolworths) | 2025-09-30 | 4 | **`channelwiz` production app** — `config/constants.php`, a controller |

Sourced from trade press (Inside Retail, Power Retail, ACS) + live corroboration (the sites now
redirect away; the seller-API domains are DNS-dead). First parties are gone, so the vendor's own
page cannot be the citation — provenance is flagged in each catalog entry.

**Recommended action:** treat the MyDeal hits in `channelwiz` as a cleanup priority — that code path
calls an API that returns nothing since September.

---

## 2. Available to add now — real dated calendars (first-party) ✅

- **Adobe Commerce / Magento** — Adobe publishes a full software end-of-life table (2.4.4 support
  ended 2025-04-12 … 2.4.9 ends 2029-05-31), corroborated by endoflife.date. This is *software* EOL,
  not an API sunset — to flag it we need to detect *which* 2.4.x version each repo pins (a small
  follow-up). Worth doing: several repos integrate Magento.
- **BigCommerce** — official deprecations page lists dated tool sunsets (Google AMP 2023-01-18,
  Universal Analytics 2023-07-01, Stencil CLI v6 2024-06-03) and undated v2-endpoint deprecations.

---

## 3. Confirmed dead, but needs manual verification before cataloguing ⚠️

- **TheMarket.com** (Warehouse Group, NZ) — front-end **confirmed closed ~late June 2024** (redirects
  to thewarehouse.co.nz), but (a) no exact retirement *day* is publicly sourced and (b) the CEO said
  the **back-end was retained** for integration into The Warehouse's own site — so the seller API may
  be migrated rather than dead. We deliberately did **not** invent a date. **Ask:** confirm with the
  client whether TheMarket API calls still function, or chase a Warehouse Group FY announcement for
  the precise date.

---

## 4. Has a deprecation policy, but no public dated calendar 🟡

These publish *that* they deprecate, but not *when* — the removal dates live in gated schemas or
are announced ad-hoc. We can flag them as "deprecated, no fixed date" (a soft warning), and wire the
machine-readable ones for ongoing monitoring:

| Platform | Situation | Monitorable? |
|---|---|---|
| **Marketplacer** (Myer) | Legacy REST API de-facto retired; removal dates hidden inside the gated GraphQL `@deprecated` schema | Changelog exists (JS-rendered) — needs a browser session |
| **THE ICONIC** | Legacy API → OAuth 2.0 migration underway, **no deadline published** | No |
| **Kogan** | Public changelog with a "Deprecated" category; one undated item | ✅ pollable public changelog |
| **Trade Me** | Evergreen v1 (no version retirements); breaking changes posted ad-hoc | ✅ `/notifications` feed |
| **BigCommerce** | ~11 v2 endpoints deprecated with V3 replacements, no removal dates | ✅ dated changelog feed |

---

## 5. No public calendar — needs partner-portal access (the upkeep cost) ⚪

These are **live** platforms our client integrates with, but their retirement information is behind a
login. We cannot monitor them automatically without credentials. **This is the recurring cost of
keeping these integrations safe — it needs a decision:**

- **Mirakl** — powers **both Bunnings and Catch**. Release notes are gated on the `help.mirakl.net`
  partner portal; a reported API-key → OAuth 2.0 deprecation appears in search snippets but we could
  not verify it (JS-rendered docs). **Highest-value target** — Mirakl underpins multiple integrations.
  *Needs:* Mirakl partner-portal credentials (the client likely has them as a Mirakl seller).
- **Virtualstock ("The Edge")** — powers **Harvey Norman**. Docs are a gated single-page app; v3
  retirement status unknown. *Needs:* Virtualstock support contact / credentials.
- **Temu** — ISV/partner-gated documentation portal. *Needs:* an ISV account.

**The ask for the client:** for the three above, either (a) share the partner-portal logins so we can
extract and monitor their deprecation schedules, or (b) accept that these are checked **manually on a
cadence** (e.g. quarterly), and we report them as "watched, not auto-monitored." Mirakl is the one
worth pushing on first, given its reach.

---

## Bottom line

- **3 integrations are calling dead marketplaces** (Catch, MySale, MyDeal) — flagged now, cleanup
  priority, MyDeal is in production code.
- **2 platforms have real dated calendars** we can add (Magento EOL, BigCommerce).
- **5 have policies but no public dates** — we'll soft-flag and monitor the 3 with feeds.
- **3 live platforms are un-monitorable without partner access** (Mirakl, Virtualstock, Temu) — the
  one genuine gap that needs a business decision, not more engineering.

The scanner did its job: it turned "we integrate with ~13 marketplaces" into a ranked, sourced,
`file:line`-precise picture of which are dead, which are dated, and which we're blind to and why.
