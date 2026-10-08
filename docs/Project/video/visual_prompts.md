# Visual prompts — generated B-roll and stills

Use these prompts for any AI-image / AI-video tool. Style: serious documentary,
no sci-fi exaggeration, no fake metrics, grounded in Argentina's Litoral.

## P01 — Hero river shot (S01)

```
Cinematic documentary shot of a river in Argentina's Litoral during a stormy
afternoon, water rising near a small riverside town, wet road, distant
emergency lights, realistic weather, handheld documentary feel, dramatic
clouds, no people in close-up, no text, 16:9, natural colors, serious but not
apocalyptic, 24 fps, 12 seconds.
```

## P02 — Dashboard / control room B-roll (background context)

```
Close-up cinematic shot of a rugged edge AI device inside a small municipal
monitoring room, cables connected to a camera feed, laptop screen showing a
flood monitoring dashboard, realistic Latin American civil defense office,
low light, rain outside window, no readable brand logos, 16:9, 6 seconds.
```

## P03 — Volunteer in the field (S05)

```
Documentary-style shot of a volunteer near a riverside neighborhood in
Argentina, holding a smartphone and recording a short voice report during
light rain, realistic clothing, no disaster exaggeration, natural handheld
camera, human and grounded, 16:9, no text, 6 seconds.
```

## P04 — Operations room close (S08 / B07 cutaway)

```
Municipal emergency operations room in Argentina, simple desks, radio
equipment, map of a riverside region on a wall screen, local operators
reviewing an alert dashboard, calm but urgent, realistic documentary style,
no fake logos, 16:9, 6 seconds.
```

## P05 — Litoral town wedge (S03)

```
Wide static documentary shot of a small Litoral town near a river under heavy
clouds, daytime, calm, parked cars, no rain yet, no people in close-up,
realistic, 16:9, 5 seconds.
```

## P06 — Airplane mode close-up (S09)

```
Macro close-up of a hand toggling airplane mode on a generic Android phone,
realistic skin and lighting, screen content blurred to avoid fake UI,
3 seconds, 16:9.
```

## P07 — End card backdrop (B08)

```
Slow cinematic dolly across a calm river at dusk in the Litoral region after
a storm, soft golden light, low contrast, no people, no buildings dominating
the frame, ambient feel, 16:9, 8 seconds.
```

## HyperFrames-rendered scenes (for reference, NOT image prompts)

- `hf_pukaar.mp4` <- `ui_scenes/02_volunteer_report_input.html` and `03_volunteer_report_json.html`
- `hf_evidence_pack.mp4` ← `ui_scenes/04_fixed_node_evidence_pack.html`
- `hf_reasoning_chain.mp4` <- `ui_scenes/05_alert_reasoning_chain.html`
- `hf_sinagir_export.mp4` ← `ui_scenes/06_sinagir_export.html`
- `hf_litoral_map.mp4` ← `ui_scenes/07_offline_queue.html` is the queue; the map will be a separate HF composition (see `hyperframes/litoral_map.md` to be authored).

## Style guardrails for any visual

- No clean, hyperreal saturated "VFX flood". Use natural colors only.
- No fake people in distress in frame. The story is the system, not casualties.
- No agency / branded logos in B-roll unless cleared.
- Aspect ratio: 16:9 always. Vertical re-cut comes later.
- Avoid signage in any language other than Spanish or English.
