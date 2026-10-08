# Pukaar — Design System

A design system for the **Pukaar** hybrid flood early-warning platform: fixed-camera CV nodes, offline-first volunteer reports from the field, and a local decision engine whose alerts carry an auditable Pukaar AI reasoning trace.

The product was built for Argentina's Litoral region and submitted to the **Pukaar Release — Global Resilience track**.

## What this design system is built from

Everything here is derived from a single source: the open-source product repository.

- **Source repo:** [prashant/Pukaar](https://) (`main` branch, Project submission)
- **Sub-surfaces studied:**
  - `frontend/` — Vite + React + TypeScript browser-first operator console (PWA). Tailwind-style utility CSS hand-rolled into `index.css`, `lucide-react` icons, `react-router-dom` shell.
  - `android/` — Jetpack Compose + Material 3 volunteer app. Custom warm earth palette declared inline in `ui/PukaarApp.kt` (`Emerald`, `River`, `Clay`, `Sand`). MediaPipe LLM Inference wrapper for on-device Pukaar AI.
  - `README.md`, `Project.md`, `Project-agent-brief.md` — voice, product copy, Spanish operator phrases.

Anyone iterating on this system should clone the repo and read the same files. The Project brief and the live screens are the single source of truth.

## Why two palettes (and why that's the point)

The product is one logical system but lives across two **physically different contexts**:

| Surface | Primary user | Where it runs | Palette anchor |
|---|---|---|---|
| **Operator console** (`frontend/`) | Provincial civil-defence operator | Browser on a desk | `#2563EB` blue + neutral grays |
| **Volunteer app** (`android/`) | Brigadista / community reporter | Phone in the field, often offline | `#1476B8` River blue on a `#F3E9D2` Sand bg, with `#0D3B2A` Emerald headings |

The volunteer surface is warmer and more grounded — it's used outdoors, in stressful conditions, by non-experts. The operator surface is cooler and denser — it's used indoors, by trained staff who need to scan a lot of state quickly. Both share the same **severity language** (green / yellow / orange / red) and the same **bilingual operator vocabulary** (English UI, Spanish for critical operator-facing strings: `SIN CONECTIVIDAD`, `Sincronizado`, `Razonamiento de Pukaar AI`).

The system below documents the shared core and notes where each surface diverges.

---

## Content fundamentals

### Voice
Technical, terse, Project-honest. The product talks the way an engineer would talk to another engineer who is on the same incident channel. It does not market itself; it explains what it does and what it doesn't do. The Project README ships an explicit **"Known limitations"** section before the feature list — that posture is the brand.

### Casing
- **Sentence case** for headings, buttons, labels: `Active Alerts`, `New Observation`, `Adjust calibration`, `Submit Report`.
- **ALL-CAPS** is reserved for one thing: the offline emergency banner — `SIN CONECTIVIDAD — operación local activa · cola: 3`. Do not use it anywhere else; the rarity is what makes it work.
- Inline code, model names, env vars stay lowercase with backticks: `pukaar-model:2b`, `silverado-fixed-cam-usgs`, `PUKAAR_LLM_BASE_URL`.

### Bilingualism (this is load-bearing — do not "fix" it)
- **English** is the default UI language for navigation, labels, generic copy.
- **Spanish** appears for three specific things:
  1. **Critical operator-facing status strings**: `SIN CONECTIVIDAD — operación local activa`, `Sincronizado`.
  2. **Pukaar AI's reasoning output** (the whole audit trail): `Razonamiento de Pukaar AI (pukaar-model:2b)`, `Analizado con Pukaar AI en este dispositivo`.
  3. **Domain copy that originates from the region**: site descriptions, transcript examples (`"El agua ya cruzó la marca crítica y trae barro, evacuar zona baja."`).
- Never translate Spanish operator strings to English. Never translate English UI chrome to Spanish. The split is intentional.

### Person & pronouns
- Imperative for actions: `Submit Report`, `Refresh`, `Analyze bundled sample`, `Adjust calibration`.
- "You" appears only in field-facing prose: `You are offline. Reports will sync when connection is restored.`
- No first person ("we"). The system is a tool, not a personality.

### Emoji
**None.** The codebase contains zero emoji. Severity is communicated through color + lucide iconography (`AlertTriangle`, `Siren`, `WifiOff`, `CheckCircle2`), never with `🚨` `⚠️` `✅`. Don't introduce them.

### Numbers, units, precision
- Percentages: integer, no decimal — `Score: 87%`, `12h rain probability: 60%`.
- Physical quantities: one decimal with SI unit — `12.4 mm`, `185.0 m3/s` (note: `m3/s` not `m³/s` — the codebase avoids superscript glyphs).
- Ratios used internally: two decimals — `Waterline ratio: 0.42`.
- Confidence: percent — `conf 78%`.
- Latency / file sizes: drop them unless they tell the operator something actionable.

### Specific phrasings to copy verbatim
These appear across the codebase and should be reused, not paraphrased:
- `Pukaar` (in code/UI, no accents — accents only in marketing copy)
- `No active alerts at the moment.`
- `Queued photo: silverado_060s.jpg`
- `Razonamiento de Pukaar AI (pukaar-model:2b)`
- `Analizado con Pukaar AI en este dispositivo`
- `SIN CONECTIVIDAD — operación local activa · cola: {n}`
- `Sincronizado`
- `MVP Android conectado al backend real, con queue offline y operaciones sobre el clip fijo demo.`

---

## Visual foundations

### Color
Both surfaces share the same neutral spine (Tailwind-style gray-50 → gray-900) and the same severity scale. They diverge on which **primary** anchors the chrome.

- **Operator-console primary:** `#2563EB` (blue-600). Used on the top bar, primary action buttons, links, and section anchors.
- **Volunteer-app primary:** `#1476B8` (River). Same family, slightly more saturated and a step darker; reads better on the warm `#F3E9D2` Sand background.
- **Headings on Sand (Android):** `#0D3B2A` Emerald. Never used as a UI fill, only as text on warm surfaces.
- **Earth accent:** `#B45F22` Clay. Used on Android for warning-but-not-emergency CTAs.

**Severity scale** — the same 4 levels everywhere. The level name is also the API value (`alert.level: "red"`):
| Level | Bg | Border | Text | Use |
|---|---|---|---|---|
| `green` | `#DCFCE7` | `#BBF7D0` | `#166534` | Nominal / synced |
| `yellow` | `#FEF3C7` | `#FDE68A` | `#854D0E` | Watch — single weak signal |
| `orange` | `#FFEDD5` | `#FED7AA` | `#9A3412` | Warning — corroborated signal |
| `red` | `#FEE2E2` | `#FECACA` | `#991B1B` | Critical — crossed critical line |

Two **solid** semantic banners sit outside the soft-fill scale and are reserved for global page-level state:
- `bg-red-600 #DC2626` text-white — offline banner (pulses).
- `bg-green-600 #16A34A` text-white — sync-complete flash (2.5s).

### Typography
- **Sans** (UI): `"Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`. This is a deliberate system stack — the product never ships a webfont. Web-substituted to **Inter** in this design system for cross-platform legibility; flag noted below.
- **Mono** (code, calibration coordinates, env vars): `Consolas, Monaco, "Courier New", monospace`. Substituted to **JetBrains Mono** in `colors_and_type.css`.
- **Display** — there is no separate display face. Headings are the sans at 1.25 / 1.5 / 2 rem and weight 600 / 700.

> ⚠️ **Font substitution flag.** The codebase relies on locally-installed system fonts (Segoe UI on Windows, Roboto on Android, SF on macOS). For consistent reproduction across platforms, this design system substitutes **Inter** (web) and **JetBrains Mono** (code). The substitutes match the metrics closely enough that no layout reflow is needed, but they are not what the live product renders. If you have access to the original product's font licensing posture, swap `--font-sans` back to the system stack in `colors_and_type.css`.

### Spacing
Tailwind-style 0.25rem step (`gap-1` through `gap-6`, etc). The codebase uses `gap-2`, `gap-3`, `gap-4` heavily on flex/grid containers — almost never inline-block + margin. Standard page padding is `p-4` on mobile, `p-5` on cards, `p-6` on density-tolerant containers.

### Radii
- `4px` — pill tags, badges (`rounded`)
- `8px` — buttons, inputs, list cards (`rounded-lg`) — this is the default
- `12px` — section containers, evidence-frame chrome (`rounded-xl`)
- `9999px` — toggles, attachment chips, connectivity pill

### Shadows
Only two are used in the codebase, and never combined:
- `shadow-sm` — `0 1px 2px rgba(15, 23, 42, 0.08)`. Default for cards.
- `shadow-md` — `0 8px 24px rgba(15, 23, 42, 0.12)`. Used on the operator-console top bar to lift it off the page.

No drop-shadows on text. No inner shadows. No glow.

### Borders
Single source: `1px solid` with `border-gray-200` (`#E5E7EB`) on cards, `border-gray-300` (`#D1D5DB`) on form fields. Severity cards use the **same-level border token** — soft orange card has an orange border, not gray.

### Backgrounds
- The brand uses **flat color**, full stop. No gradients except where they're functionally necessary (the dark overlay strip on the bottom of an evidence frame to keep the Pukaar AI description legible: `bg-black/70`).
- No background patterns, no textures, no hand-drawn illustrations, no decorative photography. The only photography is **evidence** — fixed-camera frames and operator-uploaded photos.
- The Android app is the one exception to "white bg": its scaffolds sit on `#F3E9D2` Sand to differentiate the field-facing surface from the operator console.

### Animation
Almost none. The codebase ships exactly three motion behaviors:
1. `transition-colors` (160ms ease) on every interactive element — hover/active state changes.
2. `animate-pulse` on the offline banner — communicates "still wrong".
3. `animate-spin` on `LoaderCircle` while running analysis.

No bounces, no slides, no parallax, no easing-out-back. Motion is purely confirmation/state, never decoration.

### Hover / press
- **Hover** lightens or saturates the same hue: `bg-blue-600 → hover:bg-blue-700`, `bg-orange-500 → hover:bg-orange-600`. Card hover adds a `border-blue-300` accent and bumps the shadow.
- **Press** state is implicit (the color change is the press). No transform-scale on press.
- **Disabled** is uniform: `disabled:opacity-50` or `disabled:bg-gray-300`. Never style disabled state with a different hue.
- **Focus** is a 2px ring of `rgba(59, 130, 246, 0.35)`. Always visible on keyboard focus; never `outline: none` without a replacement.

### Transparency & blur
- `bg-black/70` only — over evidence frames to keep Pukaar AI's Spanish description legible against any image.
- No `backdrop-blur`, no frosted glass, no glassmorphism.

### Cards
Cards always have all three of: `bg-white`, `border-gray-200`, `rounded-lg`. They usually also have `shadow-sm`. Inside a card, sub-cards drop the shadow and use `bg-gray-50` to differentiate (see Site Detail node-metrics blocks).

### Fixed elements
- Operator-console header: sticky/scrolling top bar with `bg-blue-600 shadow-md`.
- Operator-console bottom nav: `fixed bottom-0 w-full md:relative` — bottom-fixed on mobile, inline on tablet+.
- Severity banners: full-bleed strip directly under the header, never floating.

### Imagery treatment
The product's only imagery is **evidence**: still frames from fixed CV cameras and operator-uploaded photos. Treatment is "no treatment":
- No filters, no LUT, no grain.
- Calibration overlays (ROI polygon, critical line) are drawn in solid 2px strokes directly on the frame, not via image effects.
- Overlay strip at the bottom (`bg-black/70`, white text) carries Pukaar AI's narration and confidence.

### What to avoid
- Bluish-purple gradients (these were the Vite/React starter aesthetic — not the product's).
- Glassmorphism, frosted surfaces, backdrop blur.
- Decorative SVG illustrations.
- Emoji as iconography.
- Rounded cards with a colored left-border accent stripe.
- Drop shadows on text.
- "Hero" sections with photographic flood imagery — this is a serious operator tool, not marketing.

---

## Iconography

### Web (operator console)
**[lucide-react](https://lucide.dev)** is the only icon family. The codebase imports specific symbols:

`Activity` (used as the product mark), `AlertTriangle`, `ArrowRight`, `CheckCircle2`, `CloudRain`, `Cpu`, `FileText`, `Gauge`, `LoaderCircle`, `MapPin`, `Mic`, `PlayCircle`, `Save`, `Send`, `ServerCrash`, `Settings`, `Siren`, `Trash2`, `TriangleAlert`, `Upload`, `UploadCloud`, `Video`, `Waves`, `Wifi`, `WifiOff`.

Default sizing: `w-4 h-4` inline with body text, `w-5 h-5` on buttons and section headers, `w-6 h-6` on the product mark in the top bar. Stroke weight is lucide's default (2). Color is inherited from the surrounding text; severity icons get explicit color (`text-orange-500`, `text-red-500`).

### Android (volunteer app)
**Material Icons Rounded** via Compose Material 3. The codebase uses `Icons.Rounded.CloudUpload`, `Icons.Rounded.PlayArrow`, `Icons.Rounded.Refresh`, `Icons.Rounded.Save`. Stick to the **Rounded** variant — never the Outlined or Sharp variants — to match the rest of the app's geometry.

### Emoji / unicode
Not used. Unicode that *does* appear in copy: `·` (middle dot) as a separator in the offline banner — `SIN CONECTIVIDAD — operación local activa · cola: 3`. That's it.

### Brand mark / logo
**The product has no logo.** The codebase's `favicon.svg` and `hero.png` are leftover Vite-starter assets (purple lightning bolt + isometric cube) and are explicitly **not** brand. The product mark today is the typographic lockup `<Activity /> Pukaar` in the operator-console header. This design system ships a typographic lockup in `assets/logo-lockup.svg` and a monogram in `assets/logo-monogram.svg` as best-effort substitutes; flag this with the user and replace with real artwork when available.

### Asset rule for designers
Always prefer the **real icon set** (`lucide-react` on web, `Icons.Rounded` on Android) over redrawing. When mocking in static HTML, this design system loads lucide from CDN — see `colors_and_type.css` for the recommended `<script>` tag.

---

## File index

```
README.md                       — this file
colors_and_type.css             — design tokens (CSS vars) + semantic helpers
SKILL.md                        — entry point for Agent Skills compatibility
assets/
  logo-lockup.svg               — typographic lockup (substitute; flagged)
  logo-monogram.svg             — A4·V monogram (substitute; flagged)
  severity-swatches.svg         — green/yellow/orange/red reference strip
ui_kits/
  web/                          — operator-console React kit
    index.html                  — interactive dashboard + site detail prototype
    Layout.jsx, Dashboard.jsx, AlertCard.jsx, SiteCard.jsx,
    SiteDetail.jsx, ReportForm.jsx, Queue.jsx, Settings.jsx,
    Primitives.jsx              — Button, Badge, Card, Banner, Field
  android/                      — volunteer-app Compose-style kit
    index.html                  — phone-framed click-thru
    Phone.jsx, AndroidDashboard.jsx, AndroidSiteDetail.jsx,
    AndroidReportForm.jsx, AndroidQueue.jsx, AndroidSettings.jsx
preview/                        — Design System tab cards (one HTML each)
```

The repo also includes raw imports under `frontend/` and `android/` — these are reference source files copied from the upstream GitHub repo and are not part of the design-system surface area. Read them, don't ship them.

---

## A note on completeness

This is a Project product. Several things you might expect from a "real" design system are deliberately absent because they don't exist upstream:

- No marketing site, no brand book, no logo, no photography style guide.
- No animation language beyond "transition-colors 160ms" and three specific exceptions.
- No dark mode — `color-scheme: light` is hard-coded in `index.css`.
- No tablet or large-screen breakpoint beyond `md:`.

When you build on top of this system, **prefer copying the existing patterns** to inventing new ones. The product's strength is operational seriousness; novelty is anti-brand here.
