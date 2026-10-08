# 02_shot_plan.md

Shot plan handoff for production and edit.

## Primary Blocks

| Block | Primary asset | Owner | Fallback |
| --- | --- | --- | --- |
| B01 | River/storm B-roll | visual_designer | generated illustrative B-roll |
| B02 | Talking head | director | narration over Litoral B-roll |
| B03 | Pukaar HyperFrames/UI | renderer_hyperframes | static UI scene screenshots |
| B04 | Node analysis screencast | screencast_operator | `hf_evidence_pack.mp4` |
| B05 | Wifi off -> sync screencast | screencast_operator | offline queue HyperFrames scene |
| B06 | Reasoning chain HyperFrames | renderer_hyperframes | static reasoning panel |
| B07 | SINAGIR export + map | renderer_hyperframes | static export panel + map |
| B08 | End card/talking close | editor | `hf_end_card.mp4` |

## Capture Rules

- No real incident PII.
- No unapproved logos.
- No fake metrics in frame.
- Generated B-roll must never look like claimed field evidence.

## Needed Before Final

- Confirm P4 footage license/credit or replace with safe fallback.
- Confirm final exact asset filenames match `../edit/edl.json`.
