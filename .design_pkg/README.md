# Designer source bundle

Reference export from the brand/design system handoff. Contains the original
design tokens, SVG assets, color/typography sheets, and the project tree
snapshots that informed the live `frontend/` and `android/` code.

This directory is reference-only. The running app does NOT read from here:

- Frontend lives in [`../frontend/`](../frontend/).
- Android lives in [`../android/`](../android/).
- Brand SVGs in use ship from the per-app asset folders, not from this bundle.

If you need the original Figma plugin export, see
`acu-fero-4-vig-a-design-system/` below. Redundant archives
(`package.bin`, `package.unzipped`, secondary zips) are kept out of the repo
by [`../.gitignore`](../.gitignore).
