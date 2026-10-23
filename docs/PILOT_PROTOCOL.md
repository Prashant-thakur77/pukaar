# Pilot protocol: the 2027 monsoon, registered before it starts

Draft of 23 October 2026. This protocol is to be **frozen before 1 June 2027**: committed to this repository with a dated tag and shared with the DDMA, IMD Shimla and IIT Mandi. After that date the hypotheses, metrics and success gate do not change; anything added later is labelled as added later. Misses are published in the same report, in the same detail, as hits.

## 1. Setting

- **Where:** the villages named in the DC/DDMA order ([MOU_TEMPLATE.md](MOU_TEMPLATE.md)); planned: Thunag, Janjehli, Gohar and Pandoh (Mandi) and Sujanpur (Hamirpur, with that district's agreement).
- **When:** 15 June to 30 September 2027, with a full drill before 15 June and monthly drills outside alert periods ([field/drill-plan.md](field/drill-plan.md)).
- **Who decides:** every public alert is approved by a DDMA officer ([ADR 0002](adr/0002-human-approval-for-every-public-alert.md)). The protocol measures the system; it never changes who decides.
- **Build:** the version in [CHANGELOG.md](../CHANGELOG.md) that the safe-to-host audit certified, on `pukaar-prod` in ap-south-1. Any change to the rules or thresholds during the season is logged with its date and reason.
- **Starting point (23 Oct 2026):** 0 real alerts; 1 drill delivered to 3 phones with 0 acknowledgements; gauges simulated; sirens and rain nodes firmware only; voice calls off.

## 2. Hypotheses

- **H1, reach.** Of enrolled numbers, at least 70% confirm a live or drill alert within 30 minutes of the first send.
- **H2, the households who matter most.** Households flagged as needing help (elderly, disabled, alone, no phone) are reached, through a named neighbour or relay, at no less than 80% of the rate of other households.
- **H3, speed.** The median time from the level rising to the first confirmation on a phone is under 15 minutes, including the officer's approval.
- **H4, accuracy.** Over the season, at least half of the village-events verified from DDMA records, the patwari or the press as harmful floods were preceded by a Watch or higher; and fewer than half of Warning and Critical alerts were followed by nothing anyone reported.
- **H5, action.** Of households that confirmed a Warning or Critical alert, at least half report a protective action (moving people, animals or goods; avoiding the khad or the road).

These are tests, not promises. The figures are set now so they cannot be moved later.

## 3. The ten metrics, published after every alert and at season's end

| # | Metric | Definition | Source |
|---|---|---|---|
| 1 | Coverage | Enrolled households ÷ all households in the village (household list from the pradhan and patwari), and enrolled numbers per 1,000 people | Enrolment register, Census and panchayat lists |
| 2 | Confirmed reach at 15, 30 and 60 minutes | Share of enrolled numbers that pressed "मिल गया" or 1 within each time of the first send | Delivery and acknowledgement records |
| 3 | Assisted-household reach | Metric 2 for households flagged as needing help, and the share confirmed by their named neighbour | Same, with the assisted flag |
| 4 | Time chain | First signal → level rise → officer asked → approved → first send → first confirmation, each step's median and worst | The alert timeline and after-action report |
| 5 | Lead time achieved | Minutes from the first confirmation to the time harm began (verified), per village-event | After-action review with the DDMA |
| 6 | Hit rate and false-alarm rate | Verified harmful village-events preceded by Watch or higher ÷ all verified events; Warning and Critical alerts followed by no reported effect ÷ all such alerts. Ground truth fixed by the DDMA and IIT Mandi without seeing the alert log first | Ground-truth file, alert log |
| 7 | Siren proof | Commands sent, soundings verified by current and microphone, `not_confirmed` cases and their follow-up | Siren events ([ADR 0006](adr/0006-sirens-prove-they-sounded.md)) |
| 8 | Data health | Forecast checks made ÷ expected; gauge and rain-node uptime; silent-while-raining events; stale-data minutes during alerts | Sweep heartbeat, device health |
| 9 | Protective action | Share of a random sample of confirmed and unconfirmed households (phone survey within 72 hours, three questions) that moved people, animals or goods | Survey |
| 10 | Readiness | Drills held, officers on the roster each shift, safe places checked by the pradhan, readiness checklist items done | Roster, drill log, shelter ledger, `data/pilot_readiness.json` |

Also reported, not gated: measured cost per village against the estimate ([BUSINESS_MODEL.md](BUSINESS_MODEL.md)), and Transcribe accuracy on Himachali Hindi reports.

## 4. Success gate (fixed before June 2027)

The pilot **passes** and the case for district scale-up is made only if all of these hold over the season (live alerts and drills pooled; drills reported separately too):

1. Coverage of at least 60% of households in each village.
2. Confirmed reach at 30 minutes of at least 70% (H1), and assisted-household reach at least 80% of that (H2).
3. Median level-rise-to-first-confirmation under 15 minutes (H3), and no live alert left unapproved for more than 30 minutes.
4. No public alert sent without a DDMA officer's approval, unless the order's written auto-send rule allowed it; no replay or drill reaching a phone unlabelled.
5. Forecast checks at least 98% of expected, and every installed siren's monthly test verified.

It **fails** if any of these misses. A miss on H4 or H5 does not fail the pilot on its own, because one season gives few events, but it is reported in full and decides what changes before a second season. If no harmful flood happens in the pilot villages, the season is judged on drills and on metrics 1, 2, 3, 8 and 10 alone, and the report says so.

## 5. Consent and ethics

- **Legal basis:** the DDMA is the data fiduciary and Pukaar's operator its data processor ([COMPLIANCE_INDIA.md](COMPLIANCE_INDIA.md)). Even where the law allows processing without consent, every person is told in Hindi, by voice or in writing, what is kept, why, for how long and how to stop it, before enrolment.
- **Opt-out:** anyone can leave at any time (Telegram `/stop`, a missed call, or the pradhan) and is removed within 7 days.
- **Surveys:** voluntary, three questions, no names in the published data, and never a condition of getting alerts.
- **Drills:** always labelled "अभ्यास (DRILL)" and announced to the village beforehand; never at night.
- **Data:** only in India; reported only as counts per village; village-events with fewer than 5 households are shown as "fewer than 5".
- **Review:** the protocol is shared with IIT Mandi; if the partners require an institutional ethics review for the survey, it happens before the survey starts.
- **Harm:** if a pilot alert is followed by panic or injury, the DDMA is told the same day, and the event is reviewed and published.

## 6. Publishing

- After each live alert: the ten metrics as far as known, within 7 days, on the public `/pilot` page and in this repository.
- After the season, by 31 October 2027: one report with every alert, every verified flood, every miss and every false alarm, the cost per village and the gate result, co-authored with the partners who agree to. It feeds the district plan review (DM Act s.31(4)).
- Misses are published as plainly as hits. A metric that could not be measured is shown as "not measured", never left out.
