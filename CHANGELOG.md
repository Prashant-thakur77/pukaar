# Changelog

Which build did what, so a district can tell which version ran in which monsoon. Versions before v0.9 were not tagged at the time; they are reconstructed from the commit history and named after the commit that closed each stage. Dates are 2026.

## v0.9-pilot (23 October)

Made the project evidence-honest and ready for a district to adopt.

- Public copy reads design as design ("built so that every household confirms") and states what has been measured: 0 real alerts; 1 drill to 3 phones with 0 acknowledgements; simulated gauges; sirens and rain nodes firmware only; voice off pending a DDMA as DLT principal entity.
- Borrowed figures removed (the "ten times their cost" ratio, "24 hours' warning cuts damage by 30%"); Himachal's 2023 monsoon given as about 500 deaths, with its source.
- /pilot: messaging cost labelled as messaging only beside the all-in cost of about ₹39,100 per village a year at district scale; the benefit-cost range (0.9 / 3.4 / 23) and the break-even of one life about every 15 months; number rental, DLT fees and the two-minute billing risk added; the default village is Mandi's average of 71 households.
- A pilot notice on the home and village pages and in the README: follow DDMA and IMD warnings; emergency 112 / 1077.
- Adoption documents: [business model](docs/BUSINESS_MODEL.md), [compliance in India](docs/COMPLIANCE_INDIA.md), [pilot protocol](docs/PILOT_PROTOCOL.md), [draft DC/DDMA order](docs/MOU_TEMPLATE.md), [architecture decision records](docs/adr/README.md), [vulnerability disclosure](SECURITY.md) with `/.well-known/security.txt`, and code owners on the rules, thresholds, approval workflow and policies.

## v0.8 (23 October): the answer first, and the alarm layer in firmware

- Firmware for siren nodes, the gauge v3, rain nodes, the pradhan box and a LoRa relay: signed commands, replay counters that survive reboots, alarm patterns, edge autonomy and the pradhan's key-and-hold. Host-tested against the backend's golden vectors; **untested on hardware**.
- A boot painter paints the village and home answer in 1.2 s on slow 3G (was 7.7 s and 6.7 s); a 2 kB village answer kept on the phone.
- An officer console for the night shift: inbox with a decision panel, hold to approve, keyboard shortcuts, edit and snooze, a district selector.
- Fewer pages: /how (loop, agents, sensors, trust), /proof (the July 2023 story and the back-test), /pilot; every old link redirected.

## v0.7 (22 October): pilot hardening

- CAP feed ready for SACHET relays: updates, all-clear cancels, OASIS event codes, LGD geocodes.
- Replays on their own village copies; judge accounts act on replays only; no personal data on public routes.
- Voice calls with "press 1" (Exotel, Plivo fallback), built and off; district duty rosters with escalation to the ADM or DM; a wake-up call for the duty officer (off until a voice provider is live).
- Field-grade gauge rules (2 of the last 3 readings), a river trigger chosen per village cell, a get-ready outlook, a heavy-burst rain rule.
- Report-abuse protection, browser security headers, a production stage for ap-south-1 (defined, not deployed), field material for Mandi, and sirens that must prove they sounded (software and simulators).

## v0.6 (11 October): live on AWS

- The deployed stack: 15-minute sweep, Step Functions approval, Polly Hindi, Telegram delivery with "मिल गया", AppSync live push, CAP 1.2 feed, Cedar policies and an append-only audit log.
- River gauges over AWS IoT Core (simulated), safe places and walking routes from OpenStreetMap, virtual staff gauges, Bedrock Guardrails on villager reports.
- The back-test scored against reported floods with a source ablation; the Mandi 2025 cloudburst shown as a miss.
- First drill to real phones (Gohar, 11 October).

## v0.1 (9 October): the rebuild

- A backend on DynamoDB, Bedrock agents and Step Functions; an offline test suite, back-test and demo scripts; the web app (landing, live map, console, report, track).
