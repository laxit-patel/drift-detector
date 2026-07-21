# Design & Branding — The TOPS Artifact Collection

This document is the single source of truth for how TOPS packages are **named** and how
their **icons** are made — the sibling of the Laxit collection's `DESIGN.md`, for tools
published under **`tops-tools`**. Read it before creating a new package, a new icon, or
regenerating an existing one. The goal is that every relic reads as part of **one matched
set**.

---

## 1. The Collection

Every TOPS package is a **mystical artifact / relic**. The functional package name says
what it *does*; the **artifact alias** is its identity — a codename in the collection, the
way Android had Cupcake → Oreo. Each alias follows the formula:

> **`[evocative word] + [mystical object]`** — where the metaphor *encodes the package's function*.

| Emoji | Artifact alias   | Package (`tops-tools/…`) | Does                                                          | Accent color         |
| :---: | ---------------- | ------------------------ | ------------------------------------------------------------ | -------------------- |
|  🔮   | **Ashen Oracle** | **`drift-detector`**     | **Detects dying/retired third-party API integrations before they break** | **Ember crimson**    |

**Why "Ashen Oracle" for Drift Detector:** an *oracle* gives you foresight — it foretells
what is coming while there is still time to act. *Ashen* is the pallor of decay and the
grey of burnt-out embers: a dead or dying API. So the Ashen Oracle **reads the ashes and
foretells which of your integrations are turning to dust** — exactly what the tool does:
it names the deprecated, sunset, and end-of-life dependencies, with dates, before they
break in production.

**Tagline:** **"Know before it breaks."**

The TOPS line begins its own accent sequence; **Ember crimson** is relic #1. A new TOPS
package should claim an *unused* accent color.

---

## 2. Naming conventions

**Package slug** (`tops-tools/<slug>`) — clear on reading. Descriptive (`drift-detector`)
or a clean coinage are both fine; obscure is not. The slug is what a stranger reads, so it
must telegraph the function.

**Artifact alias** — the `[evocative word] + [mystical object]` formula above. Prefer the
`[adjective] [noun]` rhythm (*Ashen Oracle*) over possessive forms (*Oracle of Ash*). The
object should feel like a **physical relic** you could hold — a stone, orb, sextant,
lodestone, lantern. When the object is abstract (an "oracle"), render it in the icon as a
concrete relic (a scrying-orb, an oracle-bone) so it still reads as a held artifact.

**Tagline** — one line, lower-drama than the alias. Ashen Oracle's is **"Know before it breaks."**

---

## 3. Icon conventions

TOPS relics share the collection frame — **circular game-item relics** in a Mobile
Legends: Bang Bang equipment-icon style: semi-realistic painted fantasy asset, dramatic
inner glow, centered composition, **no text**.

### 3.1 The collection DNA — keep IDENTICAL on every relic

These four elements are the family signature. Do **not** vary them between packages:

1. **Ornate polished gold beveled ring border** (same thickness & ornament on every icon).
2. **Dark teal → black radial-gradient background** with a soft vignette.
3. **Glowing light particles** drifting around the central object.
4. A faint **engraved gold gear-and-rune arc at the bottom** of the medallion.

### 3.2 What changes per relic — the only two variables

1. **The central object** (the ashen scrying-orb, a future relic's own object…).
2. **The accent glow color** (must be an unused color in the TOPS sequence).

### 3.3 Palette

| Slot            | Value                                            |
| --------------- | ------------------------------------------------ |
| Ring            | Warm polished gold (shared)                      |
| Background      | Dark teal `#0c2b2e`-ish → near-black, radial     |
| **Ashen Oracle**| **Ember crimson `#b4232a`-ish + drifting ash & sparks** |

---

## 4. Generation workflow

Icons are generated with **Google Gemini** (image model). Claude / SVG is **not** used — it
can't match the painted raster look. Midjourney / DALL·E are acceptable substitutes.

**Process**

1. Start from the prompt template below; swap only the *central object* and *accent color* lines.
2. If the tool supports it, **attach an existing relic as a style reference** and instruct
   it to match ring, background, particles, and bottom arc exactly. This locks the family
   look far better than words.
3. Generate **4+** candidates, re-run a couple of times, pick the one whose ring & lighting
   best match the collection.
4. Export square, transparent or white background. Save per §5.

### 4.1 Prompt template

> **Context:** A circular game-item icon for a matched collection of fantasy "artifact"
> relics (Mobile Legends: Bang Bang equipment-icon style). Every relic shares the same frame
> and lighting; only the central object and glow color change.
>
> **Generate:** A circular fantasy game item icon. An ornate, polished **gold beveled ring
> border** frames the emblem, set against a **dark teal-to-black radial-gradient background**
> with a soft vignette. At the center: **[CENTRAL OBJECT]**, glowing with **[ACCENT COLOR]**
> light. Glowing **light particles** drift around it. A faint **engraved gold gear-and-rune
> arc sits at the bottom** of the medallion. Semi-realistic painted fantasy game asset,
> dramatic inner glow, rich detail, clean centered composition, no text, no letters. Square
> image, transparent or plain white background.

### 4.2 The exact prompt for the Ashen Oracle (`drift-detector`)

> Context: I'm designing a circular game-item icon for a matched collection of fantasy
> "artifact" relics (like Mobile Legends: Bang Bang equipment icons). Each relic shares the
> same frame and lighting — only the central object and its glow color change. This one is
> the **"Ashen Oracle"**: a seer's relic that foretells which things are dying and turning
> to ash.
>
> Generate the icon: A circular fantasy game item icon. An ornate, polished **gold beveled
> ring border** frames the emblem, set against a **dark teal-to-black radial-gradient
> background** with a soft vignette. At the center floats a **cracked ancient scrying orb of
> smoky obsidian-grey glass** (an oracle's seeing-stone), its fractures leaking **ember-crimson
> light** as if something inside is burning out; **drifting grey ash, floating cinders, and
> glowing light particles** swirl around it. A faint **engraved gold gear-and-rune arc sits
> at the bottom** of the medallion. Semi-realistic painted fantasy game asset, dramatic inner
> glow, rich detail, clean centered composition, no text, no letters. Square image,
> transparent or plain white background.

---

## 5. Asset conventions

| File                     | Purpose                                                   |
| ------------------------ | -------------------------------------------------------- |
| `art/drift-detector.png` | Master icon (the Ashen Oracle), square, ≥ 1024×1024      |
| `art/social-preview.png` | Optional 1280×640 GitHub social card                     |
| `art/prompt.txt`         | The exact generation prompt, for reproducibility         |

- Keep the **master at high resolution**; downscale as needed for READMEs / marketplace.
- Never bake **text** into the icon — the wordmark lives in the README, not the relic.
- When regenerating, update §4.2 with the new prompt so the icon stays reproducible.
