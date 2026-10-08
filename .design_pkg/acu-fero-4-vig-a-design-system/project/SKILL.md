---
name: Pukaar-design
description: Use this skill to generate well-branded interfaces and assets for Pukaar — the hybrid flood early-warning system (fixed-camera CV nodes + offline-first volunteer reports + a local Pukaar AI decision engine). Contains design guidelines, two-surface palette, typography, severity language, and React UI-kit components for both the operator console (web) and the volunteer app (Android).
user-invocable: true
---

# Pukaar — Design skill

Read `README.md` in this folder first. It documents:

- **What the product is** and where the source lives ([prashant/Pukaar](https://))
- **Two-surface palette:** operator-console blue (`#2563EB`) vs. volunteer-app warm earth (Emerald `#0D3B2A` / River `#1476B8` / Clay `#B45F22` / Sand `#F3E9D2`). They share the severity scale.
- **Content fundamentals** — voice, bilingual rules (EN chrome, ES for ops-critical), no emoji, specific phrasings to copy verbatim
- **Visual foundations** — color, type, spacing, radii, two-step shadow system, motion-as-state, no gradients/glass/illustrations
- **Iconography** — lucide-react on web, Material Icons Rounded on Android; no logo (typographic lockup is a substitute)

## Then explore

- `colors_and_type.css` — design tokens as CSS vars. Import once at the top of any HTML you produce.
- `preview/` — single-card token specimens (colors, type, radii, etc). Useful as visual reference.
- `ui_kits/web/` — operator console kit (`index.html` is an interactive prototype; `*.jsx` are the screens; `Primitives.jsx` has buttons/badges/icons).
- `ui_kits/android/` — volunteer app kit, wrapped in the `AndroidDevice` phone frame on a Sand background.
- `assets/` — typographic lockup, monogram, severity swatches.

## When the user asks for an artifact

- **Marketing slides / pitch deck**: lean on the operator-console palette (blue + gray). Bring in the typographic lockup. Keep slides text-light; if you need data, copy the actual API field names (`waterline_ratio`, `alert.level`, `pukaar-model:2b`).
- **Static prototype / mockup of an app screen**: copy from `ui_kits/web/` or `ui_kits/android/` instead of redrawing. Pick the surface that matches the user/context (operator → web; brigadista → Android).
- **Production code**: pull tokens from `colors_and_type.css`; reuse class names; do NOT reinvent the severity scale.

## Rules to enforce

1. **Two surfaces, one severity language.** Don't mix the warm Android palette with the cool web palette in the same view. Both ALWAYS share `green / yellow / orange / red` for alerts.
2. **Bilingual is load-bearing.** EN for UI chrome. ES for `SIN CONECTIVIDAD`, `Sincronizado`, `Razonamiento de Pukaar AI`, `Analizado con Pukaar AI en este dispositivo`. Never translate either side.
3. **No emoji. No gradients. No glassmorphism. No decorative SVG illustrations.** This is a serious operator tool — its strength is operational restraint.
4. **Sentence-case everything except the offline banner.** That one ALL-CAPS string is the only ALL-CAPS string.
5. **Icons must be real.** Use lucide (web) or Material Icons Rounded (Android). If the user needs an icon you don't have, flag it; never hand-draw a placeholder.

## Font substitution flag

The codebase uses system stacks (`Segoe UI`, `Roboto`, `Consolas`). This skill substitutes **Inter** + **JetBrains Mono** for cross-platform reproduction. If you need brand fidelity, swap `--font-sans` back to the system stack in `colors_and_type.css` and tell the user.

## Logo flag

The product has no real logo today. `assets/logo-lockup.svg` and `assets/logo-monogram.svg` are typographic substitutes that re-use the lucide `Activity` pulse glyph the operator console already ships with. If the user provides real artwork, swap them and update the README.

## If invoked with no prompt

Ask the user what they want to build (slide, app screen, marketing page, internal handoff doc?), which surface (operator console or volunteer app?), whether the audience is technical (judges / engineers) or non-technical (community), and what content they want surfaced. Then act as an expert designer outputting HTML artifacts or production code.
