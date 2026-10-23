# Business model: what Pukaar costs, what it may save, and who pays

Written 23 October 2026. All amounts are in rupees a year unless stated (US$1 ≈ ₹94.82, ECB reference rate, 22 October 2026).

Every number below is either **cited** (a linked source), **[repo]** (from this repository) or **[est]** (an estimate, with its formula). The cost and benefit formulas are code: [`frontend/src/lib/pilotCost.ts`](../frontend/src/lib/pilotCost.ts), tested in [`pilotCost.test.ts`](../frontend/src/lib/pilotCost.test.ts), and the [/pilot](https://main.d15r7ktz99l46x.amplifyapp.com/pilot) page renders them. Change a number there and this page must change with it.

**In one paragraph.** A 300-village district costs about **₹1.17 crore a year all in (about ₹39,100 per village)** [est]. It breaks even if it helps save **one life about every 15 months**, valuing a life at ₹1.5 crore, the lowest Indian estimate found. The district benefit-cost ratio is **0.9 in the low case, 3.4 in the central case and 23 in the high case** [est]. The case rests on lives, and the number of lives a flash-flood warning saves in the Indian Himalaya has never been measured, so those figures are assumptions. Messaging, the number most often quoted, is the small part: about **₹22.69 per registered number per monsoon**.

## 1. Messaging: ₹22.69 per registered number per monsoon

Formula (per alert event, per village): numbers × (voice + re-call share × voice + SMS segments × SMS price) × (1 + GST). Defaults [repo, `pilotCost.ts`]:

| Input | Default | Basis |
|---|---|---|
| Households per village | 71 | Mandi, Census 2011: 2,03,747 rural households in 2,850 villages ≈ 71.5 ([villageinfo.org](https://villageinfo.org/district/mandi); [Wikipedia, Mandi district](https://en.wikipedia.org/wiki/Mandi_district)) |
| Numbers per household | 1.5 | [est] |
| Alert events per season | 15 | [est], no source; deliberately high (a realistic low case is 5) |
| Re-called (did not confirm) | 40% | [est] |
| Voice | ₹0.38 a minute, 1-minute pulse | cited: [Plivo India voice pricing](https://www.plivo.com/voice/pricing/in/) |
| SMS | ₹0.25 a segment × 3 Hindi segments | top of MSG91's ₹0.15–0.25 range ([MSG91](https://www.msg91.com/in/pricing)) |
| GST | 18% | |
| Telegram | free | [Telegram Bot API](https://core.telegram.org/bots/faq) |
| Polly (Hindi neural voice) | about ₹0.45 an alert, left out | [AWS Polly pricing](https://aws.amazon.com/polly/pricing/), $16 per million characters × 300 characters |

Result: **₹22.69 per registered number per monsoon**; an average Mandi village (106.5 numbers) costs **about ₹2,417 a monsoon** in messaging. The /pilot page used to show "₹5,100 per village" at 150 households, twice Mandi's average; that figure was messaging only and is now labelled so beside the all-in figure. A low case (5 events, ₹0.18 SMS) gives ₹6.32 per number [est: (0.38 + 0.4 × 0.38 + 3 × 0.18) × 1.18 × 5].

Costs the per-number figure leaves out:

| Item | Amount | Basis |
|---|---|---|
| Calls past 60 seconds | If the Hindi alert and the "press 1" prompt run past a minute, each answered call bills 2 minutes: **about +41%** on messaging at the defaults (the voice and re-call lines double) | [est] from the formula; measure the alert's length before quoting |
| Number rental | ₹200 a month (₹2,400 a year), once per deployment | [Plivo](https://www.plivo.com/voice/pricing/in/) |
| DLT registration | ₹5,900 once per principal entity, ₹590 a year per header | [Message Central](https://www.messagecentral.com/sms-guideline/india); [Infobip](https://www.infobip.com/docs/essentials/asia-registration/dlt-registration) |
| 1600-series government number | No published tariff found; exempt from TRAI's new ₹0.05 a minute A2P termination charge | [TRAI, 18 Sep 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf) |
| Exotel | No public per-minute rate; sold as bundles; a two-leg call bills as two calls | [Exotel support](https://docs.exotel.com/business-phone-system/why-am-i-charged-for-incoming-calls) |

## 2. All-in cost at three scales

Unit costs [est unless cited]: platform and support fee ₹12,000 a village a year (the proposed price, section 6); drills and training ₹3,000 a village a year; a field coordinator ₹3.6 lakh a year (₹30,000 a month); a technician ₹4.5 lakh a year with travel; cloud from AWS ap-south-1 list prices, rounded up ([AWS price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSLambda/current/ap-south-1/index.json)). The alarm layer (siren node, gauge, rain node, pradhan box, relay share) is **₹1.63 lakh per village once and ₹30,000 a year** [repo, [docs/hardware/ALARM.md](hardware/ALARM.md), an untested bill of materials], annualised over 7 years at 8% (capital recovery factor 0.192): ₹31,300 + ₹30,000 = **₹61,300 per village a year**. It is in every pilot village and in one village in five at district and state scale. No salary survey was used for people costs.

| ₹ a year (estimate) | Pilot: 5 villages, 1,125 numbers | District: 300 villages, 3 lakh people, 98,600 numbers | State: 1,000 villages, 10 lakh numbers |
|---|---|---|---|
| Messaging (₹22.69 a number) | 0.26 lakh | 22.4 lakh | 2.27 crore |
| Number rental and a DLT header | 0.03 lakh | 0.03 lakh | 0.03 lakh |
| Cloud (AWS ap-south-1) | 0.6 lakh | 1.5 lakh | 6 lakh |
| Platform and support (₹12,000 a village) | 0.6 lakh | 36 lakh | 1.2 crore |
| Drills and training (₹3,000 a village) | 0.15 lakh | 9 lakh | 30 lakh |
| Field coordinators | 0.5 FTE: 1.8 lakh | 2 FTE: 7.2 lakh | 12 FTE: 43.2 lakh |
| Technicians | 0.25 FTE: 1.1 lakh | 1 FTE: 4.5 lakh | 3 FTE: 13.5 lakh |
| Alarm layer, annualised and upkeep | 5 villages: 3.1 lakh | 60 villages: 36.8 lakh | 200 villages: 1.23 crore |
| **Total a year** | **₹7.6 lakh** (~US$8,000) | **₹1.17 crore** (~US$124,000) | **₹5.62 crore** (~US$593,000) |
| **Per village a year** | ₹1.53 lakh | **₹39,100** | ₹56,200 |
| Phone loop only (no alarm layer), per village | ₹91,200 | ₹26,900 | ₹44,000 |
| One-time alarm hardware (inside the total, annualised) | ₹8.2 lakh | ₹97.8 lakh | ₹3.26 crore |

District people: 3,00,000 ÷ 4.56 people a household (Mandi, Census 2011) × 1.5 numbers ≈ 98,600 numbers. The pilot villages are market towns, larger than Mandi's average village. State "villages" are panchayat-sized units of about 1,000 numbers each, which is why the state's per-village cost is higher than the district's.

For scale: Odisha's coastal siren towers cost about ₹56 lakh each, or ₹5.7 lakh per village covered ([OSDMA](https://www.osdma.org/national-cyclone-risk-mitigation-project/), ₹68.86 crore ÷ 122 towers ÷ 1,205 villages), and Uttarakhand approved ₹118 crore for 250 siren sites ([Drishti IAS](https://www.drishtiias.com/state-pcs-current-affairs/uttarakhand-multi-hazard-early-warning-system/print_manually)). Those are high-power, tested systems; Pukaar's kit is neither yet.

## 3. What a warning can save, and how it is valued

What a flash-flood warning can save: lives, livestock, vehicles, cash, grain, documents and shop stock. What it cannot: houses, cowsheds, land, roads, bridges, power lines. Most of Himachal's ₹8,665 crore 2023 loss ([NDMA PDNA, via The Tribune](https://www.tribuneindia.com/news/himachal/himachal-pradesh-floods-climate-change-illegal-construction-greenery-loss-increasing-disaster-risk-in-himalayas-says-ndma-report-586698)) is the second kind. Bangladesh saw the same at Cyclone Amphan: deaths fell to 26, but "loss of infrastructure, crops, and cattle was barely reduced" ([TBS News](https://www.tbsnews.net/thoughts/50-years-cyclone-preparedness-success-saving-lives-not-livelihood-368398)).

Benefit = lives averted × VSL + large animals saved × ₹37,500 + exposed households × share warned in time × goods saved per household [est, formula in `pilotCost.ts`].

| Input | Value | Basis |
|---|---|---|
| Value of a statistical life (VSL) | **₹1.5 crore** (low and central); ₹4.47 crore (high) | Lowest Indian estimate found ([SANDEE WP 27](https://ideas.repec.org/p/snd/wpaper/27.html)); hedonic-wage estimate ([ISEC WP 407](https://econpapers.repec.org/RePEc:sch:wpaper:407)). Not the ₹4 lakh ex-gratia, which is a compensation payment |
| Large animal | ₹37,500 | Reported current SDRF norm for a buffalo ([statement](https://vikramsahney.com/remove-anomalies-and-increase-allocation-under-sdrf-mp-vikram-sahney/)); **unverified** against the MHA letter |
| Goods saved per household warned in time | ₹20,000–40,000 | 27–55% of the ₹73,000 Nepal's Karnali households saved with 2.75 hours of warning ([Rai et al. 2020](https://www.dpnet.org.np/public/uploads/files/CBA%20of%20EWS%20in%20Karnali%20Feb%202020%202021-09-12%2010-18-25.pdf)), cut for minutes of warning instead of hours |

| District, a year | Lives averted | Animals | Exposed households × share × ₹ | Averted | Cost | Benefit-cost |
|---|---|---|---|---|---|---|
| Low | 0.5 | 25 | 500 × 20% × ₹20,000 | ₹1.04 crore | ₹1.17 crore | **0.9** |
| Central | 2 | 50 | 1,000 × 30% × ₹25,000 | ₹3.94 crore | ₹1.17 crore | **3.4** |
| High | 5 (at ₹4.47 crore) | 150 | 2,000 × 50% × ₹40,000 | ₹26.9 crore | ₹1.17 crore | **23** |

Statewide, same method, central case: 7 lives, 170 animals, 3,300 households → ₹13.6 crore against ₹5.62 crore, about 2.4 [est]. The 5-village pilot (central, about 1.4) exists to learn, not to pay for itself.

**Break-even:** ₹1.17 crore ÷ ₹1.5 crore = 0.78 lives a year, **one life about every 15 months**, before any livestock or goods.

Why the central case is not generous: 2 lives a year is about 2% of the ~110 statewide flood-type deaths and missing of 2025 (68 landslide, cloudburst and flash-flood deaths and 41 missing by 7 September; [Swarajya/PTI](https://swarajyamag.com/amp/story/news-brief/himachal-suffers-rs-4079-crore-losses-as-monsoon-wreaks-havoc-report)), for a district in the worst-hit region. Houses, roads, injuries, rescue costs and stress are given no value. Costs include hardware in 60 villages, 15 village-wide events everywhere and SMS at the top of its price range.

## 4. The honest caveats

1. **The case rests on lives.** Without them the central case is about 0.8: livestock and goods alone do not pay for the system.
2. **The lives averted are assumptions, not findings.** No cost-benefit study of flash-flood or cloudburst warning in the Indian Himalaya exists. The 0.5 / 2 / 5 lives a year are planning figures. Only a monsoon of measured reach (who got the call, who confirmed, who moved) turns them into evidence, which is what [docs/PILOT_PROTOCOL.md](PILOT_PROTOCOL.md) is for.
3. **The low case is below 1.** It is shown on purpose.
4. **Pukaar does not borrow other systems' ratios.** Published benefit-cost ratios come from hours or days of warning: 4 to 36 for weather services and warning in developing countries ([Hallegatte 2012, World Bank WPS 6058](http://documents1.worldbank.org/curated/en/190261468181486694/txt/WPS6058.txt)) and 24 to 73 (83 in the base case) for a community river-flood warning in Nepal with 2.75 hours of lead ([Rai et al. 2020](https://www.dpnet.org.np/public/uploads/files/CBA%20of%20EWS%20in%20Karnali%20Feb%202020%202021-09-12%2010-18-25.pdf)). The Global Commission on Adaptation's "24 hours' warning cuts damage by 30%" is about storms and heat waves. None of them is applied to Himachal's flash floods here.
5. **Nothing has been measured in the field yet:** 0 real alerts; 1 drill to 3 phones with 0 acknowledgements; simulated gauges; sirens and rain nodes are firmware only.
6. **The hardware prices are an untested bill of materials,** and one siren per village is optimistic for scattered hamlets.

Two cheap changes raise the benefit more than any price cut: upstream gauges and rain nodes (in Karnali one more hour of lead time multiplied household savings by 1.83), and reaching livestock owners directly (livestock were a third of Karnali's saved value).

## 5. Who pays: the payer ladder

| Stage | Who pays | Instrument | Size [est] |
|---|---|---|---|
| Pilot, 2027 monsoon | A company's CSR or a trust, at no cost to the government | Companies Act Schedule VII item (xii), "disaster management", read liberally ([Corporate Law Reporter](https://corporatelawreporter.com/companies_act/schedule-7-of-companies-act-2013-activities-which-may-me-included-by-companies-in-their-corporate-social-responsibility-policies/)); a DC order, not a tender ([docs/MOU_TEMPLATE.md](MOU_TEMPLATE.md)) | ₹7.6 lakh a year, ₹8.2 lakh hardware |
| District, 2028 | The DDMA budget, SDRF preparedness or the State Disaster Mitigation Fund | The SDMF must spend at least 10% a year on non-structural measures and up to 5% on a small-grants window for "innovation, technology", with Himalayan states 90% centrally funded ([MHA SDMF guidelines](https://srcodisha.nic.in/dmrule/SDMF%20Guidelines.pdf)); bought on GeM, whose Startup Runway accepts startups "irrespective of their DPIIT-certification" ([GeM](https://gem.gov.in/gem-exclusive)) | ₹30–36 lakh phone tier, or ₹1.17 crore all in |
| Villages below dams | HPSEBL (Larji), BBMB (Pandoh), NHPC (Parbati) | The Dam Safety Act 2021 requires emergency action plans with downstream warning ([CWC EAP guidance](https://cwc.gov.in/sites/default/files/EAPChapters.pdf)); BBMB tendered a ₹96.01 lakh flood-warning system at Pandoh ([TenderDetail](https://www.tenderdetail.com/Indian-Tenders/TenderNotice/47376423/da37dfc5487a964be92f60500a61ad7a)) | 20 villages: ₹32.6 lakh once + ₹9.6 lakh a year |
| State, 2028–29 | HPSDMA through HP-READY or an SDMF project | The World Bank's US$245 million HP-READY loan (₹2,687 crore project) to 2031 aims to "enhance early warning systems" ([The Week/PTI](https://www.theweek.in/wire-updates/national/2025/10/09/des40-hp-cm-ready-project.html)) | ₹5.62 crore a year |

HP's SDMF is about ₹82–95 crore a year if a [PIB table](https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=1907163&reg=48&lang=2) row is read as ₹ crore (column headers unconfirmed), so the 5% window would be about ₹4–4.75 crore a year [est]. Insurance data licences and Digital Public Good grants are supporting levers, not revenue.

## 6. Proposed pricing [est]

- **Tier 1, phone loop:** ₹12,000 per village a year, or a flat ₹30–36 lakh per district a year up to 300 villages; messaging passed through at cost plus GST, invoiced against the DDMA's own DLT principal entity.
- **Tier 2, alarm layer:** hardware and installation at about ₹1.63 lakh per village plus 10–15% integration, then annual maintenance of ₹30,000–36,000 per village.
- **Supplier team:** 5–6 people, about ₹80 lakh–1 crore a year fully loaded (no salary survey). It breaks even at about 670 villages on Tier 1 alone (₹80 lakh ÷ ₹12,000), or at one district, one dam operator and a two-year CSR grant.
- The code stays open, and the money is in hosting, support, drills and maintenance, the mix that sustains Somleng's open warning platform ([UNICEF Venture Fund](https://www.unicefventurefund.org/story/alumni-news-somleng-powers-government-early-warning-systems-second-dpg)).

## 7. What would change these numbers

A measured AWS bill (replacing the cloud line), provider quotes for voice and SMS under the DDMA's DLT entity, the measured length of the Hindi alert, a hardware build with real prices, and a monsoon of measured reach and protective action. Each is a line in [docs/PILOT_PROTOCOL.md](PILOT_PROTOCOL.md).
