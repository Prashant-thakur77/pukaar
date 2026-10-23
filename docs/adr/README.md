# Architecture decision records

Short records of the choices that decide whether a warning is right, approved, heard and lawful. Each says what was decided, why, and what it costs. A change to any of them is a change to how the district is warned: it needs a new record that supersedes the old one, and a review by a code owner ([.github/CODEOWNERS](../../.github/CODEOWNERS)).

| # | Decision | Status |
|---|---|---|
| [0001](0001-rules-not-ai-set-the-level.md) | Rules, not a model, set the level | Accepted |
| [0002](0002-human-approval-for-every-public-alert.md) | A DDMA officer approves every public alert | Accepted |
| [0003](0003-voice-first-with-acknowledgement.md) | Voice first, with an acknowledgement from each phone | Accepted; voice calls pending telecom registration |
| [0004](0004-cap-1-2-for-every-published-alert.md) | Every published alert is a CAP 1.2 message | Accepted |
| [0005](0005-personal-data-stays-in-india.md) | Real personal data stays in India | Accepted; the India stack is not deployed yet |
| [0006](0006-sirens-prove-they-sounded.md) | A siren must prove it sounded | Accepted; firmware only, untested on hardware |

Format: context, decision, consequences, and how the code holds us to it. Dates are when the decision was written down; most were taken earlier, in the commits listed in [CHANGELOG.md](../../CHANGELOG.md).
