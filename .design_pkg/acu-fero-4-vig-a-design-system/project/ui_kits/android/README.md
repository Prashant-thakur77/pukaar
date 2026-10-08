# Volunteer App — Android UI Kit

Cosmetic React/JSX recreation of the **Pukaar** Android volunteer app, based on `android/app/src/main/java/com/pukaar/pukaar/android/ui/` in [prashant/Pukaar](https://).

The phone-in-the-field surface that brigadistas use to file reports — typically outdoors, often offline — with MediaPipe LLM Inference parsing reports fully on-device via Pukaar AI.

The kit lives inside the **AndroidDevice** starter frame (412×892, status bar, gesture nav). All visuals are pure HTML/CSS approximations of the live Jetpack Compose + Material 3 screens.

## Files

- `index.html` — phone-framed click-thru with bottom nav and four screens
- `android-frame.jsx` — starter component (status bar, app bar slot, gesture nav, frame chrome)
- `AndroidApp.jsx` — top-level routing, sample state, palette + style tokens
- `AndroidDashboard.jsx` — header, queue/LLM status cards, site list
- `AndroidSiteDetail.jsx` — sample-clip analysis, hydromet snapshot, report form
- `AndroidQueue.jsx` — pending offline reports
- `AndroidSettings.jsx` — server URL editor + backend connectivity switch

## Palette (this surface only)

| Token | Value | Use |
|---|---|---|
| Emerald | `#0D3B2A` | Headings, bold body text on Sand |
| River | `#1476B8` | Primary CTA, selected nav item |
| Clay | `#B45F22` | "Save offline" CTA, warning chips |
| Sand | `#F3E9D2` | Page background — sets the field tone |

Defined inline in `ui/PukaarApp.kt` and lifted verbatim here.

## Screens covered

| Tab | Component | Key state |
|---|---|---|
| Dashboard | AndroidDashboard | LLM + Queue status cards, site cards from backend |
| Site detail | AndroidSiteDetail | Sample analysis with Pukaar AI description chip |
| Queue | AndroidQueue | List of pending reports, "Flush queue" CTA |
| Settings | AndroidSettings | Server URL field + backend connectivity switch |

## What's omitted

- Real Compose ripple / state-layer animations (using opacity hover for cosmetic parity only)
- Material 3 motion specs (the live app uses defaults; we ship no motion)
- Calibration screen (the codebase calibration is numeric coord entry — low design value)
- Real on-device Pukaar AI path — the "Analizado con Pukaar AI en este dispositivo" chip is rendered statically

## Running

Open `index.html` directly. No build step.
