# Demo recording path · Persona C — Backend & Fusion command center

This file documents exactly what the Backend & Fusion lead (Persona C) clicks and shows during the 3-minute Project recording. The whole story plays out on **one screen**: the operator dashboard at `/`.

Target resolution: **1440 × 900** (zoom browser to ~100%, hide bookmarks bar).

---

## 1. Pre-roll setup (do this BEFORE the camera rolls)

```bash
# Terminal A
cd backend && PYTHONPATH=src python3 -m Pukaar.scripts.seed
PYTHONPATH=src python3 -m uvicorn Pukaar.main:app --host 127.0.0.1 --port 8000

# Terminal B
./scripts/run_pukaar-ai_local.sh   # Ollama + pukaar-model:2b warming up

# Terminal C
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173
```

Then in the browser:

1. Open `http://localhost:5173`.
2. Confirm header pill says **`Online`** (green).
3. Confirm the **bottom nav** reads `Comando · Reporte · Cola (n) · Runtime`.
4. (Optional) trigger a real incident in Terminal D so the demo isn't sample state:
   ```bash
   curl -sf -X POST http://127.0.0.1:8000/api/sites/silverado-fixed-cam-usgs/sample-node-analysis | jq
   ```
   If no real alert is present, the dashboard **automatically falls back** to a clearly-labeled `DEMO · sample state` view — that's safe to record too.

---

## 2. What Persona C says + clicks (3-min cut)

### 0:00 – 0:20 · "The 5-second read"

**Click**: nothing yet — just land on `/`.

**Say**: *"Esto es lo que ve el operador en Defensa Civil cuando llega una alerta. En menos de cinco segundos sabe el nivel, el sitio, y el score."*

**Show**: the **RiskBanner** at the top — full-bleed red strip with `CRÍTICO`, score `87%`, site name, summary. If a real alert is loaded, the red strip will pulse softly; if it's demo, the `DEMO · sample state` badge is in the strip's top-right.

### 0:20 – 0:50 · "Why we trust this alert: signal fusion"

**Click**: nothing — point at the panel titled `Fusión de señales`.

**Say**: *"El motor no decide por una sola señal. Acá tenés las tres entradas: la cámara fija detectó cruce de línea crítica, un brigadista mandó el reporte por la app Pukaar, y el modelo hidrometeorológico de Open-Meteo da una probabilidad alta. Cada tile tiene su score y cuándo llegó."*

**Show**: the three slate tiles — `cv_node` 87, `vol_report` 62, `hydromet` 45. All three status dots green.

### 0:50 – 1:15 · "Multimodal Pukaar AI narration"

**Click**: nothing — point at the evidence frame.

**Say**: *"Acá Pukaar AI multimodal narra el frame en español. La visión por computadora sigue siendo la fuente del score; Pukaar AI solo describe lo que se ve para que el operador audite la decisión."*

**Show**: the evidence frame with the bottom strip `Pukaar AI · pukaar-model:2b · conf 78%` and the Spanish description.

### 1:15 – 1:40 · "Auditable reasoning"

**Click**: nothing — point at `Razonamiento de Pukaar AI` and the numbered list below.

**Say**: *"Cada alerta no-verde lleva su razonamiento de Pukaar AI en español, más una traza determinística de qué reglas dispararon. No es una caja negra: el operador puede defender la decisión ante un superior."*

**Show**: the reasoning summary + the `Traza de auditoría determinística` panel listing `RULE_CRITICAL_LINE_CROSSED`, `RULE_RISE_VELOCITY`, etc., each with `disparada` / `no aplicó`.

### 1:40 – 2:10 · "Function calling — the operator acts"

**Click**: in this order, with about 4 seconds between each:
1. `Emitir CAP v1.2`
2. `Disparar sirena`
3. `Enviar alerta LoRa`
4. `Notificar Defensa Civil`

After each click, the button spins for ~1s and a `stdout · function_call log` line appears below the action rail.

**Say**: *"Cuando el operador decide actuar, dispara funciones que Pukaar AI también puede invocar autónomamente. Emitir el XML CAP versión 1.2 — ese es el estándar internacional de Common Alerting Protocol, mapeado a SINAGIR. Disparar la sirena vía relay GPIO. Enviar alerta por LoRa a los nodos hermanos. Notificar al webhook de Defensa Civil municipal."*

**Show**: the `Estado CAP v1.2 · export` card flips from idle/emitido as the actions fire, and the `Línea de tiempo del incidente` at the bottom gets new dots.

### 2:10 – 2:30 · "Connectivity loss"

**Click**: header pill `Online` → flips to `Offline`. Wait ~1s.

**Say**: *"Si se cae la conexión, el operador no pierde la vista. Banner rojo `SIN CONECTIVIDAD`, la cola sigue contando reportes locales, y el motor local sigue tomando decisiones. Cuando vuelve la red, se sincroniza solo."*

**Show**: the `SIN CONECTIVIDAD — operación local activa · cola: N` banner under the header. The `Cola offline · última sincronización` card on the right shows offline state.

**Click**: header pill back to `Online`. The green `Sincronizado` flash appears for 2.5s.

### 2:30 – 2:50 · "Lifecycle in one strip"

**Click**: nothing — point at the timeline.

**Say**: *"Toda la historia del incidente en un strip: detección CV, reporte voluntario, fusión, emisión CAP, sirena, notificación. Auditable de punta a punta."*

**Show**: the `Línea de tiempo del incidente` at the bottom, dots in amber for completed events. The events we just triggered are at the right end.

### 2:50 – 3:00 · close

**Say**: *"Pukaar: alerta temprana híbrida, on-device, auditable, lista para Defensa Civil."*

---

## 3. Implementation notes

- **Demo fallback is labeled.** When `useAppStore.alerts` is empty, the dashboard renders `DEMO_ALERT` + `DEMO_FUSION` + `DEMO_TIMELINE` constants from `pages/Dashboard.tsx` with a visible `DEMO · sample state` badge in the RiskBanner. No hidden backend mocking.
- **Action rail.** Buttons in `Acciones del operador` dispatch a 900ms simulated busy state and log to a `stdout` panel. They do NOT call the backend in this commit — wiring to `POST /api/alerts/{id}/export-sinagir`, `/api/alerts/{id}/siren`, etc. is a follow-up. The visual contract is in place.
- **Spanish strings.** Every demo-critical label is Spanish: `Incidente activo`, `Fusión de señales`, `Razonamiento de Pukaar AI`, `Traza de auditoría determinística`, `Acciones del operador`, `Emitir CAP v1.2`, `Disparar sirena`, `Enviar alerta LoRa`, `Notificar Defensa Civil`, `Cola offline · última sincronización`, `Línea de tiempo del incidente`, `Sitios monitoreados`, `Abrir sitio`, `Comando`, `Reporte`, `Cola`. The English fragments that remain are deliberate function-call identifiers (`emit_cap_xml`, `function_call`, etc.) — those are operator/dev shibboleths and reading them in Spanish would be wrong.
- **Responsive.** The `cc-grid` collapses to a single column under 1100px; the fusion row stacks under 720px. The recording target is 1440 × 900 — at that resolution everything above the timeline fits without scrolling.
- **Build.** Compiles under `noUnusedLocals`, `noUnusedParameters`, `verbatimModuleSyntax`, `erasableSyntaxOnly` per the existing `tsconfig.app.json`.

## 4. Files patched

| File | Change |
|---|---|
| `frontend/src/pages/Dashboard.tsx` | Full rewrite — command center layout, demo fallback, action rail wiring |
| `frontend/src/pages/SiteDetail.tsx` | Added CAP status card + audit trace at the bottom of the analysis section |
| `frontend/src/components/Layout.tsx` | Spanish nav labels: Dashboard → Comando, Report → Reporte, Queue → Cola |
| `frontend/src/components/CommandCenter.tsx` | **NEW.** Reusable atoms — RiskBanner, SignalFusionRow, EvidencePanel, Pukaar AIReasoning, AuditTrace, ActionRail, CapStatusCard, OfflineSyncCard, IncidentTimeline, SectionPanel, EmptyCommandCenter |
| `frontend/src/index.css` | Added slate/ops palette + 1440×900 grid utilities (`cc-grid`, `cc-fusion`, `cc-action-btn`, severity strips, etc) |

## 5. If something looks wrong on the day

- **Risk strip is wrong color.** The level comes from the live alert. If a real RED alert came in, the strip is RED and pulses. If the level is wrong, run the seed + the sample-node-analysis curl above to force RED.
- **Action rail does nothing.** Check the browser console for React errors. Buttons are pure UI in this commit and won't fail silently — every click writes to the `stdout` panel.
- **Spanish strings are wrong.** Search `frontend/src/pages/Dashboard.tsx` and `components/CommandCenter.tsx` for the label and fix in place — there's no i18n indirection.
- **No timeline events.** Timeline is initialized from `DEMO_TIMELINE_FACTORY()`. To restart, refresh the page. New events appear when action-rail buttons are clicked.
