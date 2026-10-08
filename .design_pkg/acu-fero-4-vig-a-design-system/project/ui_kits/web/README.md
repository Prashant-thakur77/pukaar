# Operator Console — Web UI Kit

High-fidelity React/JSX recreation of the **Pukaar** operator console, based on `frontend/src/` in [prashant/Pukaar](https://).

The browser-first PWA that civil-defence operators use indoors to scan fused alerts, run fixed-camera analysis, and inspect Pukaar AI's auditable reasoning.

## Files

- `index.html` — click-thru prototype showing all five primary screens with simulated state
- `Layout.jsx` — top bar (blue-600), connectivity pill, severity banner row, bottom nav
- `Dashboard.jsx` — active alerts + monitored sites grid
- `SiteDetail.jsx` — hydromet + calibration + node analysis with evidence frame
- `ReportForm.jsx` — volunteer report submission with offline/online behaviour
- `Queue.jsx` — pending offline reports waiting to flush
- `Settings.jsx` — Pukaar AI runtime + Hydromet provider status
- `Primitives.jsx` — `Button`, `Field`, `Badge`, `Card`, `Banner`, `LucideIcon` helpers

## Screens covered

| Route | Component | What it shows |
|---|---|---|
| `/` | Dashboard | 4–6 active fused alerts (level-coloured), monitored sites with active/inactive badge |
| `/sites/:id` | SiteDetail | Hydromet snapshot, calibration summary, node-analysis output with evidence-frame overlay |
| `/report` | ReportForm | Site picker, transcript textarea, photo + audio attachments, online/offline CTA swap |
| `/queue` | Queue | Pending reports list, "Sync Now" CTA, offline orange info banner |
| `/settings` | Settings | LLM endpoint status, hydromet provider, recommended env vars in a black mono block |

## Patterns reused from the source

- Tailwind-style class names hand-rolled in `colors_and_type.css` and a small kit-local stylesheet — no Tailwind toolchain
- Severity-level keys (`green/yellow/orange/red`) map 1:1 to API values
- All icons are loaded inline from the bundled lucide CDN (no `lucide-react` npm package)
- Sentence-case button labels, imperative verbs (`Submit Report`, `Refresh`, `Analyze bundled sample`)
- Spanish operator strings retained verbatim (`SIN CONECTIVIDAD`, `Razonamiento de Pukaar AI`)

## What's omitted from the kit

These are cosmetic-only recreations — they don't try to be production code:

- No real fetch / IndexedDB — all state is in-memory React
- No service worker / PWA install hooks
- The calibration page is not reproduced (it's numeric coord entry — low design value)
- No bundle splitting; everything ships in one file via Babel-standalone

## Running

Open `index.html` directly. No build step.
