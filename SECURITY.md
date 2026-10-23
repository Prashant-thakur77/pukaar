# Security policy

Pukaar is a flood early-warning pilot. A flaw in it could stop a real warning, send a false one, or expose villagers' phone numbers. Please report anything you find privately, and give us time to fix it before you tell anyone else.

## How to report

E-mail **prashant101007@gmail.com** with the subject line `SECURITY: Pukaar`. Include:

- what you found and where (URL, API route, file and line, or device);
- the steps to reproduce it, and what an attacker could do with it;
- whether you believe it is being exploited now.

Please do **not** open a public GitHub issue, pull request or discussion for a vulnerability. If you need to send something sensitive, say so in a first e-mail and we will agree a safer way. The same contact is published at [`/.well-known/security.txt`](frontend/public/.well-known/security.txt) on the live site.

## What happens next

| When | What we do |
|---|---|
| Within 3 days | Acknowledge your report and tell you who is handling it |
| Within 10 days | Confirm or rule out the problem, and give it a severity |
| Within 30 days, sooner for anything that touches alert delivery | Fix it, or tell you why not and what we are doing instead |
| After the fix | Credit you in [CHANGELOG.md](CHANGELOG.md) if you want, and agree with you when the details can be published |

Pukaar is run by a small team, not a company with a security desk. These are targets we hold ourselves to, not a contract.

## Scope

In scope:

- the web app at `https://main.d15r7ktz99l46x.amplifyapp.com` and the API on `execute-api.us-east-1.amazonaws.com` behind it;
- the code in this repository: backend, frontend, infrastructure template, Cedar policies, the approval workflow, the CAP feed, the Telegram bot [@PukaarRescuebot](https://t.me/PukaarRescuebot) and the voice webhooks;
- the device firmware in `firmware/` and its signed-command protocol, on the device and in the backend.

Out of scope:

- the published judge accounts (`judge`, `judge_pradhan`) doing what the README says they can do: they are public on purpose and Cedar limits them to replays;
- denial of service by volume, and anything that needs you to flood the live API or send real alerts;
- AWS, Telegram, Exotel, Plivo or Open-Meteo themselves (report those to their owners);
- social engineering of anyone, and physical attacks on devices you do not own.

## Rules for testing

- Use the judge accounts and replays. Never approve, send or try to trigger a live or drill alert, and never send anything to a real villager's phone.
- Do not read, keep or share personal data (names, phone numbers, Telegram chat ids, report photos, locations). If you reach any by accident, stop, tell us, and delete it.
- Stop as soon as you have shown the problem.

We will not take action against anyone who follows this policy in good faith.

## Public safety comes first

If the problem could stop a real warning from reaching a village, could make Pukaar send a false warning, or is happening during a monsoon alert, say so in the first line of your e-mail. We will treat it before anything else and, if a live alert is at risk, tell the district disaster management authority (DDMA) using Pukaar. A false public warning is an offence under section 54 of the Disaster Management Act 2005, so never test by sending one.

Pukaar is a pilot. People in danger should follow DDMA and IMD warnings and call **112**, or the district control room on **1077**.

## More

How the system defends itself (report-abuse limits, device signing, browser security headers): [docs/SECURITY.md](docs/SECURITY.md). Indian law that applies (CERT-In's 6-hour reporting, DPDP breach notice): [docs/COMPLIANCE_INDIA.md](docs/COMPLIANCE_INDIA.md).
