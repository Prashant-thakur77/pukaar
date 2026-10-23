# 0003. Voice first, with an acknowledgement from each phone

- Status: Accepted. Telegram voice notes and the "मिल गया" button are live; the outbound voice call is built and off until a DDMA registers as the DLT principal entity.
- Date: 23 October 2026

## Context

Many villagers in the hills read little, use keypad phones, or both. Studies of flood warning found communities "strongly preferred voice" (Cumiskey et al., 2015), and Cambodia's EWS1294 users preferred IVR (46%) over SMS (3%). A broadcast never says who heard it, and none of the deployed systems reviewed publishes confirmed reach.

## Decision

- Every alert is spoken in Hindi (Amazon Polly) and sent with its text.
- Each recipient confirms: the "मिल गया" button on Telegram, or "press 1" on a voice call. Anyone who has not confirmed is sent the alert again; a voice call is retried at most three times.
- The village relays (pradhan, gauge reader, task force) are reached first, because trained relays raised timely receipt by 46.5% in Bihar (Jagnani & Pande, 2024).
- Confirmed reach (who confirmed, how fast) is counted per alert and published.

## Consequences

- Today the only live channel is Telegram, so keypad phones cannot be reached. Outbound calls must come from a government principal entity on TRAI's DLT platform with a 1600-series number and declared A2P calling ([docs/COMPLIANCE_INDIA.md](../COMPLIANCE_INDIA.md)); Pukaar must not call in its own name.
- A press-1 alert longer than 60 seconds bills two minutes per call ([docs/BUSINESS_MODEL.md](../BUSINESS_MODEL.md)).
- An acknowledgement shows a phone was answered, not that a household moved. Protective action is measured separately in the pilot.
- So far, one drill (11 October 2026) reached 3 phones and none confirmed. The acknowledgement rate is unmeasured.

## Held by

The delivery, acknowledgement and IVR tests (forged key presses refused, retry counters, replays never dial), and [docs/VOICE.md](../VOICE.md).
