# Pukaar's CAP feed and SACHET

SACHET is NDMA's national CAP alerting platform. Pukaar publishes CAP 1.2 at
`/cap/alerts.atom` (an ATOM index) and `/cap/alerts/{id}.xml` (one message each).
Pukaar cannot publish into SACHET itself. SACHET messages come from authorised
originators (SDMAs, IMD, CWC and others), so only an authority can relay a Pukaar alert.

## What SACHET's live feed looks like

These observations come from the public RSS at
<https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml> and the CAP files
it links to (`FetchXMLFile?identifier=...`), read on 22 Oct 2026. The 100 items that
day came from Andhra Pradesh SDMA, IMD regional centres and CWC, with Rajasthan SDMA
re-issuing an IMD Jaipur warning.

| Field | SACHET, as seen | Pukaar |
|---|---|---|
| RSS item | `<author>controlroom@ndma.gov.in (Andhra Pradesh SDMA)</author>`, link to the CAP file, guid = numeric id | ATOM entry per message: unique id (the CAP URL), `application/cap+xml` link, related village page |
| `identifier` | `IN-1792661906424028_28` | alert id (`alr_...`), or `allclear-{village}-{UTC stamp}` for a Cancel |
| `sender` | agency code: `Andhra-Pradesh-SDMA`, `Rajasthan-SDMA`, `CWC` | template parameter `CapSender` (`PUKAAR_CAP_SENDER`; default `pukaar-{stage}@{web host}`; a prod deploy refuses it empty) |
| `senderName` | not used | `CapSenderName` / `CapSenderNameHi`; on dev the default "Pukaar — District Disaster Management (demo)", Hindi and English |
| `status` / `msgType` | `Actual`; `Alert` and `Update` | `Actual`, or `Exercise` for replays and drills; `Alert`, `Update`, `Cancel` |
| `references` | `IMD-Jaipur,IN-1792661906424028_57,2026-10-22T15:07:55+05:30` | every earlier alert still in force, same form |
| times | IST, `+05:30` | IST, `+05:30` |
| languages | `en-IN` first, then a regional block tagged `HI` or `TL` | `hi-IN` and `en-IN` |
| `category` / `event` | `Met`; free text ("Flood", "Lightning", "Moderate Thunderstorms with surface wind") | `Met`; "Flood"/"बाढ़" or "Flash Flood"/"अचानक बाढ़" |
| `eventCode` | none seen | `OET:v1.2` OET-081 (flood) or OET-079 (flash flood) |
| `description` | often empty; the headline carries the message | always filled; differs from the headline and the instruction |
| area | `areaDesc` (district or mandal names), a `Polygon URL` parameter, `altitude`/`ceiling` 0 | `areaDesc` of 50 characters or fewer, a 5 km `circle` around the village point |
| geocode | `LGD District Code` on the Rajasthan message (103 Jaisalmer, 772 Phalodi); none on the AP and CWC ones | `LGD District Code`: Mandi 22, Hamirpur 17 |

The LGD district codes come from the Local Government Directory list as mirrored by
Google Data Commons (`scripts/india_lgd`) and the India Data Portal (`district_lgd.csv`).
Both lists give Himachal Pradesh as state 2, Hamirpur 17 and Mandi 22, and both give
Jaisalmer 103, the same code SACHET's live message uses. Code 33 is Hoshiarpur in
Punjab, not Mandi. The codes are data: each district's in `data/districts.json`, a village's
own as `lgd_code` in `data/villages.json`; the seed copies them onto the village record and
`services/cap.py` reads them from there (a new district needs no code edit:
`scripts/add_village.py`, docs/DEPLOY.md). Village-level LGD codes are not included yet. None
of the five villages' codes could be checked against a public LGD extract, so none carries
one until someone verifies it. Sujanpur is a town, so it would need a local body code, not a
village code.

## How an authority would relay Pukaar's alerts

1. **Own the decision.** The district (DDMA Mandi or Hamirpur) or HP SDMA decides
   that Pukaar's village alerts may go out under its name. The dev stack's messages say
   "(demo)" and "not an official government channel" and stay that way. A production
   stack carries the authority's own `CapSender` and `CapSenderName` (docs/DEPLOY.md,
   "Production stage"); the deploy refuses Stage=prod with either empty, and the demo
   note is then left out.
2. **Read the feed.** Subscribe to `/cap/alerts.atom`. Each entry links to one CAP
   message that passes the OASIS CAP 1.2 schema and Google's profile rules
   (`backend/tests/test_cap_profile.py`).
3. **Never relay an Exercise.** Replays and drills carry `status=Exercise` and an
   "EXERCISE" headline. Only `Actual` messages describe a real flood.
4. **Re-issue under the authority's sender.** In SACHET's composer, or through
   whatever ingest NDMA and C-DOT agree for that agency, the authority issues its own
   message. It uses its SACHET sender code and identifier, keeps Pukaar's Hindi and
   English text and the `LGD District Code`, and draws its own targeting polygon from
   Pukaar's circle and village. Pukaar's identifiers are not SACHET identifiers.
   The authority keeps its own mapping from each Pukaar id to the SACHET id.
5. **Carry updates and cancels through.** A Pukaar `Update` lists every earlier alert
   still in force. The authority's re-issue should reference the matching SACHET ids.
   When the village returns to normal, Pukaar's feed carries a `Cancel` with
   `responseType=AllClear` and a Hindi and English "all clear". Relay it the same way,
   so cell broadcast and SMS recipients hear that the danger has passed. The Cancel is
   built from the village's current level, so it leaves the feed if the level rises
   again. Relay it when it appears.
6. **Google Public Alerts.** Google takes feeds only from official alerting
   authorities. The authority would submit its own feed (or SACHET's) to Google's
   Public Alerts program, not Pukaar's demo feed.
