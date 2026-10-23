# 0006. A siren must prove it sounded

- Status: Accepted. Firmware builds and host tests only; no siren is built or installed, and nothing here is tested on hardware.
- Date: 23 October 2026

## Context

Phones fail when towers fail, and a flood often takes the towers. Sirens reach people without phones, but a silent failure is the worst kind: in Odisha during Fani some villages reported no siren, and in Nepal's Babai basin (2014) a single gauge and its reader were cut off before the flood arrived. An unsigned command channel would also let anyone sound a village's siren, which is a false warning under DM Act s.54.

## Decision

- Every siren command is signed per device and carries a counter, so a replayed or forged command is refused, and a reboot never turns the counter against a device.
- After approval a `SoundSirens` step sends the command; it never blocks phone delivery.
- A siren reports back that it sounded, not only that the command arrived: during the first tone it measures the amplifier current against its reference and the microphone's sound rise. A failed check never silences a real alarm. A command not verified in 180 s is `not_confirmed`, and the duty officer is told to phone the pradhan. Alarms fire when an installed siren did not confirm, failed its self-test, or was not heard on any path for two sweeps.
- The siren keeps working when the cloud is gone: the pradhan's key-and-hold and the LoRa link from the upstream gauge can sound it locally (the gauge-triggered edge path is off by default).
- Siren proof is one of the pilot's ten published metrics.

## Consequences

- The alarm layer costs about ₹1.63 lakh per village plus ₹30,000 a year, from an untested bill of materials ([docs/hardware/ALARM.md](../hardware/ALARM.md)).
- Outdoor sirens are not meant to wake sleepers; they add to the phone call, they do not replace it.

## Held by

The device protocol golden vectors shared by the backend and the firmware (`firmware/test`), the siren state machine tests, and the CloudWatch alarms listed in [docs/RUNBOOK.md](../RUNBOOK.md).
