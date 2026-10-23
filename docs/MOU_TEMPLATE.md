# Draft: DC/DDMA order adopting Pukaar for a pilot

A starting text for the Deputy Commissioner, as chairperson of the District Disaster Management Authority, to adapt. It follows the pattern of IIT Mandi's February 2022 MoUs with the Mandi and Kangra DDMAs for landslide early warning, in which the DDMA funds or hosts the system, the district provides staff and protected sites, and alerts go to the DDMA control room ([The Tribune](https://www.tribuneindia.com/news/himachal/kangra-to-have-100-early-landslide-warning-systems-366247/amp); [India Science and Technology portal](https://www.indiascienceandtechnology.gov.in/technologies/landslide-monitoring-and-early-warning-system)). The text of those MoUs was not available to us; this draft is modelled on what was reported about them. **It is a draft for the DDMA's legal officer, not legal advice.** Words in [brackets] are to be filled in.

---

**Office of the Deputy Commissioner-cum-Chairperson, District Disaster Management Authority, [Mandi]**

**Order No. [ ] dated [ ]**

**Subject: Adoption of the Pukaar flood early-warning system as a component of the district's early-warning mechanism, on a pilot basis, for the 2027 monsoon.**

Whereas section 30(2)(xiv) of the Disaster Management Act, 2005 empowers the District Authority to set up, maintain, review and upgrade the mechanism for early warnings and dissemination of proper information to the public; and section 30(2)(xxviii) requires it to ensure that communication systems are in order and that drills are carried out periodically;

And whereas [the operator: name, legal form, address] ("the Operator") has offered the Pukaar system, which reads rain and river forecasts and gauge readings, proposes a flood level per village by fixed rules, and sends an officer-approved spoken Hindi alert to registered phones and village sirens;

Now therefore the District Authority orders as follows.

**1. Adoption and scope.** Pukaar is adopted as a component of the district early-warning mechanism, on a pilot basis, for the villages of [Thunag, Janjehli, Gohar, Pandoh] from [1 April 2027] to [31 October 2027]. It supplements and does not replace warnings issued by IMD, CWC, HPSDMA or this Authority through any other channel.

**2. The mechanism is the Authority's.** Pukaar operates as this Authority's mechanism under section 30(2)(xiv). The Operator provides technical support and acts only on the Authority's directions. The Operator shall not issue any warning to the public in its own name.

**3. No public alert without approval.** No alert, drill or message shall reach the public unless approved by an approving officer named under paragraph 4. Automatic sending of a critical alert when no approving officer responds is [not permitted / permitted only under the following written rule: ...]. Every approval, decline and refusal is recorded in the system's audit trail, which the Operator shall not alter or delete.

**4. Approving officers and delegation.** The approving officers are the duty officers of the District Emergency Operations Centre on the published duty roster, in the order: primary duty officer, backup duty officer, then the [Additional District Magistrate as CEO of the Authority / District Magistrate]. An approval request unanswered for [10] minutes ([5] at Critical) passes to the next officer. The [ADM] shall keep the roster current for every shift. Village pradhans may report and keep the shelter ledger for their own village but may not approve alerts.

**5. Thresholds aligned with official forecasts.** Alert levels shall use IMD rain categories and CWC products as inputs, with thresholds reviewed by [IMD Meteorological Centre Shimla] and [IIT Mandi] before [1 June 2027]. No Pukaar alert shall contradict a current IMD red or orange warning for the area; where local gauges or reports differ from official forecasts, the alert shall be issued as a local advisory of this Authority. Any change to the rules or thresholds requires the [ADM]'s written approval and is recorded with its date and reason.

**6. Data.** This Authority is the data fiduciary under the Digital Personal Data Protection Act, 2023, processing under section 7(c) and section 7(h); the Operator is its data processor and shall: process personal data only for this order; store it only in India (AWS ap-south-1 or a facility the Authority approves); keep processing logs for at least one year; give each enrolled person a Hindi notice and a way to opt out; report any personal-data breach to the Authority within [6] hours of noticing it, so that the Authority can meet its own duties to the Data Protection Board and CERT-In; and return or delete the data under paragraph 9.

**7. Telecom sender.** This Authority [or NIC Himachal Pradesh on its behalf] shall register as the principal entity on the TRAI DLT platform, with a government ("-G") SMS header, Hindi and English templates, a 1600-series number for voice calls, and the pre-declaration of automated calls required by TRAI. The Operator's telecom providers act only as aggregators in the Authority's name.

**8. Operation and maintenance.** The Operator shall: keep the system available through the pilot period, with a named contact reachable [24 hours] during the monsoon; run a full drill with the DEOC before [15 June 2027] and monthly drills thereafter, each labelled as a drill; install and maintain sirens, gauges and rain nodes at sites provided by the district and the gram panchayats, and test each siren monthly; and publish the pilot metrics set out in the pilot protocol, including misses. The district shall provide [protected sites, power where available, and access for maintenance]. The costs of the pilot are borne by [the Operator / its CSR or grant partner], at no cost to the Authority, unless agreed otherwise in writing.

**9. Exit and handover.** Either party may end this order with [30] days' written notice, or at once on a breach of paragraph 2, 3 or 6. On ending or expiry the Operator shall, within [30] days: hand over to the Authority the alert and audit records, the device registry and keys, the source code and configuration of the deployed version, and the documentation needed for another party to run the system; transfer installed equipment to [the Authority / the gram panchayats]; and delete all personal data held by it once the Authority confirms receipt. The Authority's DLT registration, header and numbers remain the Authority's.

**10. Review.** The [ADM] shall review the pilot after the monsoon with the Operator, IMD and IIT Mandi, and place the report before the Authority for its decision on continuation and for the district plan review under section 31(4).

**11. Good faith.** The Operator acts under this order on the Authority's directions. [Whether section 73 of the Act extends to the Operator is to be confirmed by the Authority's legal officer.]

[Signature]
Deputy Commissioner-cum-Chairperson, DDMA [Mandi]

Copy to: ADM-cum-CEO DDMA; District Emergency Operations Centre; HPSDMA; IMD Meteorological Centre Shimla; IIT Mandi; NIC [Mandi]; the pradhans of the named gram panchayats; the Operator.

---

What goes with the order: the pilot protocol ([PILOT_PROTOCOL.md](PILOT_PROTOCOL.md)), the compliance checklist ([COMPLIANCE_INDIA.md](COMPLIANCE_INDIA.md)), the cost estimate ([BUSINESS_MODEL.md](BUSINESS_MODEL.md)) and the duty officer's guide ([field/officer-guide.md](field/officer-guide.md)).
