# Compliance in India: what applies to Pukaar, what it does now, what is pending

Written 23 October 2026 from the primary texts where we could read them, and from secondary sources where we could not. **UNVERIFIED** marks a point we could not confirm against a primary source. This is a working checklist for a district, not legal advice: the DDMA's legal officer and NIC should review it before a pilot order is signed.

**The one-line version.** In India only the DDMA may run a district's early-warning mechanism, so Pukaar is lawful only as the DDMA's tool: the DDMA approves every public alert, is the data fiduciary, and is the sender of record for every call and SMS. Pukaar's operator is a technical supplier and data processor.

Status words: **Done** (in the code or the docs today), **Partly**, **Pending** (needs the DDMA, a telecom operator or work not yet started).

## 1. Disaster Management Act 2005

| Provision | What it says | What Pukaar does now | Pending |
|---|---|---|---|
| s.30(2)(xiv) | The DDMA may "set up, maintain, review and upgrade the mechanism for early warnings and dissemination of proper information to public" ([s.30](https://www.advocatekhoj.com/library/bareacts/disastermanagement/30.php)) | **Partly.** Built to be the DDMA's mechanism: rules propose, a DDMA officer approves, every decision audited ([ADR 0002](adr/0002-human-approval-for-every-public-alert.md)) | **Pending:** a DC/DDMA order or MoU adopting Pukaar for named villages ([MOU_TEMPLATE.md](MOU_TEMPLATE.md)). Without it Pukaar must not warn anyone |
| s.30(2)(xxviii), (xix) | The DDMA keeps communication systems in order and runs drills; it coordinates NGOs in the district | **Partly.** Labelled drills through the real workflow (`make drill`); a monthly drill plan ([field/drill-plan.md](field/drill-plan.md)) | A pre-monsoon drill with the DEOC under the order |
| s.54 | "Whoever makes or circulates a false alarm or warning as to disaster or its severity or magnitude, leading to panic" may be imprisoned up to one year or fined ([s.54](https://www.advocatekhoj.com/library/bareacts/disastermanagement/54.php)) | **Done in design.** Nothing reaches the public without a DDMA officer's approval; critical auto-send is off by default; replays never reach a real phone; drills are labelled; siren commands are signed | Name the approving officers and the delegation chain in the order. The Jan Vishwas (Amendment of Provisions) Act 2026 amends DM Act penalties; whether it touches s.54 is **UNVERIFIED** |
| s.73 | Protects action taken in good faith under the Act by the authorities and those acting for them ([DM Act](https://prsindia.org/files/bills_acts/bills_parliament/2024/Disaster_Management_Act_2005.pdf)) | Relevant only once Pukaar operates under a DDMA order | Whether s.73 covers a contracted technical supplier is **UNVERIFIED**; the order should state that the operator acts on the DDMA's directions |
| 2025 amendment | Act 10 of 2025 (in force 9 April 2025) adds state-notified "hazard-wise nodal Departments" for early warning (s.38(2)(ia)), lets DDMAs co-opt experts, and sets district plan review at least every two years (s.31(4)); it leaves s.30 and s.54 unchanged ([Gazette](https://www.thc.nic.in/Central%20Governmental%20Acts/Disaster%20Management%20Act,%202005.pdf)) | Nothing needed for a district pilot | At state scale, the notified nodal department for flash floods must agree; which department HP has notified is **UNVERIFIED** |

**Official forecasts come first.** IMD and CWC are the authoritative forecasters. Pukaar's rules must use their products as inputs and must never contradict a live IMD red or orange warning; where local gauges disagree, the alert goes out as a DDMA "local advisory". Status: **Pending** (threshold validation with IMD Shimla and IIT Mandi; an IMD feed is not yet an input).

## 2. SACHET and cell broadcast

| Item | Fact | What Pukaar does now | Pending |
|---|---|---|---|
| SACHET | NDMA's CAP-based alert platform, built by C-DOT, in all 36 states and UTs. The warning agencies (IMD, CWC, INCOIS, DGRE, FSI) and the SDMAs "issue and authorise" alerts ([ThePrint/PTI, 28 July 2026](https://theprint.in/india/from-avalanches-to-man-made-disasters-mobile-alert-system-issues-warnings-in-regional-languages-govt-in-ls/2999197/)). No public process for a third-party originator was found | **Done:** every published alert is a schema-valid CAP 1.2 message with Hindi and English blocks and the district's LGD geocode ([ADR 0004](adr/0004-cap-1-2-for-every-published-alert.md), [SACHET.md](SACHET.md)) | Consume the Himachal SACHET feed as an input rule; ask HPSDMA for its district request procedure; whether DDMAs in HP hold SACHET authoriser logins is **UNVERIFIED** |
| Cell broadcast | C-DOT's system launched nationwide on 2 May 2026; it can target single towers and reads text aloud on some handsets ([News On AIR](https://newsonair.gov.in/cell-broadcast-system-launched-to-enhance-disaster-communication/)). Triggered through the agencies and SDMAs | Not integrated. Pukaar is a complement: it reaches named households and asks each to confirm, which a broadcast cannot | A "request SACHET / cell broadcast" action that hands HPSDMA a ready CAP message and polygon |

## 3. Telecom: TRAI's commercial-communication rules and DLT

| Rule | What it says | What Pukaar does now | Pending |
|---|---|---|---|
| TCCCPR Second Amendment, 12 Feb 2025 | A "Government Message or Government Voice Call", sent on the directions of the Central or State Government through the DLT platform, needs **no consent and cannot be blocked**; TRAI's reasoning names "disaster warnings"; SMS headers ending "-G" mark government senders ([TRAI](https://trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf)) | **Voice off.** The press-1 voice call is built and off by default; there is no SMS ([VOICE.md](VOICE.md)). Telegram is outside these rules | **The DDMA (or NIC HP for it) registers as the DLT principal entity:** a "-G" header, Hindi and English templates. Whether operators accept a district body as "State Government" is **UNVERIFIED**; ask NIC HP |
| 1600 series | DoT earmarked 1600xx numbers for BFSI and government entities; TRAI's 10 July 2026 clarification puts government-to-citizen calls on 1600xx ([TRAI PR 135/2025](https://trai.gov.in/sites/default/files/2025-11/PR_No.135of2025.pdf); [SCC Online](https://www.scconline.com/blog/?p=390749)) | None | A 1600-series number allocated to the DDMA or the State through the operator. Whether a district body can hold one, and how, is **UNVERIFIED** |
| TCCCPR Third Amendment, 18 Sep 2026 | Every sender must **pre-declare A2P and robo-calls and their caller-ID ranges** to the originating operator, or the calls count as spam (reg 4, in force 60 days after Gazette publication, around late November 2026, exact date **UNVERIFIED**). The 1600xx series is exempt from the new ₹0.05 a minute A2P termination charge (reg 35A) and from AI spam flagging (reg 21A) ([TRAI](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)) | None | Pre-declare A2P use and the 1600 range in the DDMA's name before any voice call goes out. Exotel or Plivo act only as aggregator |

If Pukaar sent in its own name it would be a commercial sender that needs each person's consent and the 140 or 160 series, and the disaster case would collapse. So it never will.

## 4. Data protection: the DPDP Act 2023 and Rules 2025

| Provision | What it says | What Pukaar does now | Pending |
|---|---|---|---|
| s.7(c), s.7(h) | Personal data may be processed without consent "for the performance by the State or any of its instrumentalities of any function under any law" (c) and "to ensure safety of… any individual during any disaster" as defined in the DM Act (h) ([DPDP Act](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf)). Both work only when the State is the fiduciary | **Partly.** A Hindi notice draft and consent notes per recipient ([RUNBOOK.md](RUNBOOK.md), "Consent records") | The order names **the DDMA as data fiduciary** and Pukaar's operator as **data processor** under a written contract; a record of processing citing s.7(c) (routine enrolment) and s.7(h) (during a disaster). s.7(h) covers "during any disaster", so quiet-season storage rests on s.7(c); that reading is ours, not tested law |
| Rules 2025 dates | Notified 14 November 2025. Notice (Rule 3), security safeguards (Rule 6), breach reporting (Rule 7: each person "without delay", the Board within 72 hours) and retention (Rule 8(3): logs at least one year) apply 18 months later, **about 13 May 2027**, a month before the 2027 monsoon ([DPDP Rules](https://www.meity.gov.in/static/uploads/2025/11/53450e6e5dc0bfa85ebd78686cadad39.pdf)) | **Partly.** Report retention by TTL (`RetentionDays=365`, [DEPLOY.md](DEPLOY.md)); no personal data on public routes; encryption at rest; an audit trail | By 15 April 2027: the consent and notice step in Telegram `/start`, a `/stop` command, an opt-out and grievance contact, recipient retention and erasure jobs, a Hindi IVR notice, one-year log retention on prod, and the 72-hour breach runbook |
| s.16 | The Centre may restrict transfers to notified countries; none notified as of October 2026 (**UNVERIFIED**) | Real personal data stays in India by design ([ADR 0005](adr/0005-personal-data-stays-in-india.md)) | Deploy `pukaar-prod` in ap-south-1 |

## 5. CERT-In directions, 28 April 2022

Issued under IT Act s.70B(6), they apply to "service providers, intermediaries, data centres, body corporate and government organisations": both the DDMA and Pukaar's operator. Cyber incidents must be reported to CERT-In **within 6 hours** of noticing them, and ICT logs kept for a rolling **180 days within India** ([Mondaq](https://www.mondaq.com/india/it-and-internet/1202576/everything-you-need-to-know-about-indias-new-guidelines-related-to-cyber-incident-reporting-by-cert-in)).

- **Now:** CloudWatch logs on the dev stack keep 30 days, in us-east-1. A private vulnerability-disclosure route exists ([SECURITY.md](../SECURITY.md)).
- **Pending:** one-year log retention in ap-south-1 (covers CERT-In and DPDP Rule 8(3)); a named point of contact; a 6-hour incident runbook; clocks synced to an approved time source (AWS Time Sync; whether the directions accept it is **UNVERIFIED**).

## 6. Hosting: MeitY empanelment and ap-south-1

MeitY empanels cloud providers after an STQC audit; AWS Mumbai (ap-south-1) and Hyderabad (ap-south-2) are fully empanelled ([AWS](https://aws.amazon.com/blogs/publicsector/aws-achieves-full-empanelment-for-the-delivery-of-cloud-services-by-indias-ministry-of-electronics-and-information-technology/)).

- **Now:** a production stage, `pukaar-prod` in ap-south-1, is defined in the same template, with MFA for officers, WAF, retention and the authority's own CAP sender ([DEPLOY.md](DEPLOY.md), "Production stage"). **It is not deployed.** The live stack is `pukaar-dev` in us-east-1, with demo and test data only.
- **Pending:** deploy prod before any real villager's data is collected. Whether a state or district buying a SaaS needs the application itself empanelled is **UNVERIFIED**; ask DoIT HP.

## 7. GIGW 3.0 and a safe-to-host audit

Before a government web application goes live, GIGW 3.0 expects a "safe-to-host" certificate from a CERT-In-empanelled auditor, STQC or NIC, tied to a specific build ([TCSA summary](https://www.tcsa.in/learn/gigw-compliance-before-go-live)). This rests on vendor summaries and is **UNVERIFIED** against the GIGW text for a district pilot.

- **Now:** WCAG 2.1 A/AA checked with axe on the public pages; a strict Content-Security-Policy and security headers ([SECURITY.md](SECURITY.md)); [CHANGELOG.md](../CHANGELOG.md) names each version up to v0.9-pilot, so an audit can name the build it certified.
- **Pending:** a VAPT by a CERT-In-empanelled auditor on the build that will run the 2027 monsoon.

## 8. Procurement

A pilot at no cost to the government can run under a DC order, as IIT Mandi's landslide warning did in Mandi and Kangra. Paid district work goes through GeM, whose Startup Runway accepts startups "irrespective of their DPIIT-certification" ([GeM](https://gem.gov.in/gem-exclusive)); a buyer may refuse startup relaxations for public-safety purchases (**UNVERIFIED** primary source). Money and payers: [BUSINESS_MODEL.md](BUSINESS_MODEL.md).

## Order of work

1. DC/DDMA order or MoU (DM Act s.30(2)(xiv)).
2. DDMA as DLT principal entity: "-G" header, templates, 1600 number, A2P declared (TRAI 2025 and 2026).
3. `pukaar-prod` in ap-south-1 with one-year logs; CERT-In and DPDP runbooks.
4. DPDP notice, opt-out and erasure by 15 April 2027.
5. VAPT, then the pre-monsoon drill with the DEOC, then the season under the pilot protocol ([PILOT_PROTOCOL.md](PILOT_PROTOCOL.md)).
