# v0.1-Pukaar-submission

Reproducible demo artifacts for Pukaar.

The full deployment runs on a Raspberry Pi camera node plus the Pukaar Android
app. This release ships a hardware-replay package so judges can verify the
demo without owning the physical hardware: captured visual inputs, resident
audio reports, telemetry logs, model and runtime configuration, expected
outputs, and Android / dashboard demo builds where available.

## Assets

- `Pukaar-demo-artifacts.zip` — the full package
  (`inputs/`, `outputs/`, `app/`, `config/`, `eval/`, `DEMO.md`, `manifest.json`).
- `pukaar-demo.apk` (optional) — standalone Android Pukaar demo build.
- `pukaar-dashboard-demo.zip` (optional) — static dashboard demo build.
- `SHA256SUMS.txt` — checksums for the above.

## How to use

1. Download `Pukaar-demo-artifacts.zip`.
2. Follow `DEMO.md` inside the zip — Option A (Pukaar Notebook replay) or
   Option B (Raspberry Pi deployment).

## Project Links

- Repo: https://
- Pukaar Notebook (live demo): `Pukaar + Pukaar — Live Hardware Replay Demo`
- Pukaar Dataset (inputs/configs only): `Pukaar-demo-artifacts`
- This release: `v0.1-Pukaar-submission`
