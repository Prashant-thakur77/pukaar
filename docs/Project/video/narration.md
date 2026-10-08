# Narration — English VO + Spanish subtitles

Voice: prashant (project lead). Tone: serious, grounded, no hype.
Pace target: 145–155 wpm. Total English VO ≈ 410–430 words for 3:00.

Honesty constraint repeated at top so VO never drifts:
- No accuracy claims.
- No "deployed" / "in production" claims.
- No "X minutes earlier" temporal claims.
- "MVP demo on public or simulated scenarios" must appear at least once spoken and once on screen.

---

## B01 — Hook (0:00–0:12)

EN:
> Flood warnings often depend on the one thing that disappears first in an emergency: connectivity.

ES (subtitle):
> Las alertas de inundación dependen de lo que se cae primero en una emergencia: la conectividad.

---

## B02 — Problem (0:12–0:30)

EN:
> In Argentina's Litoral, when the network goes down, communities still need someone watching the river.
> We are building Pukaar plus Pukaar: an offline-first flood warning system where Pukaar AI runs close to the evidence, not only in the cloud.

ES:
> En el Litoral argentino, cuando se cae la red, alguien tiene que seguir mirando el río.
> Construimos Pukaar: alertas tempranas offline-first, con Pukaar AI cerca de la evidencia.

---

## B03 — Pukaar volunteer (0:30–0:55)

EN:
> Pukaar is the human layer. A volunteer sends a local report, in Rioplatense Spanish, even when offline.
> "Che, el agua ya pasó la marca y viene con barro. Hay familias en la zona baja."
> Pukaar AI structures that into evidence: hazard, urgency, observed signals, recommended action.
> This is structured local reporting, not a benchmark result.

ES:
> Pukaar es la capa humana. Un voluntario envía un reporte local, en castellano rioplatense, incluso sin conexión.
> Pukaar AI lo convierte en evidencia estructurada.

---

## B04 — Pukaar fixed node (0:55–1:30)

EN:
> Pukaar is the fixed node. It watches camera evidence near critical sites.
> Instead of streaming raw video to a cloud GPU, the node builds a compact temporal evidence pack from curated frames and asks Pukaar AI for a node assessment.
> The output is an assessment level, a temporal summary, a reasoning summary, and the critical evidence the operator should look at first.
> This is an MVP flow on a public demo clip.

ES:
> Pukaar es el nodo fijo. Construye un pack temporal con frames curados y le pide a Pukaar AI una evaluación.

---

## B05 — Connectivity loss (1:30–2:00)

EN:
> Now the network is gone.
> The volunteer report is queued locally. The fixed node keeps reasoning. The alert still fires, with an audible siren on the device itself.
> When connectivity returns, the queue drains and the central dashboard catches up. No data loss, no silent failure.

ES:
> Se cae la red. El reporte queda en cola, el nodo sigue razonando, suena la sirena local. Vuelve la red y todo se sincroniza.

---

## B06 — Audit trail (2:00–2:25)

EN:
> In disaster response, a red badge is not enough.
> Every non-green alert carries a Pukaar AI-produced reasoning summary in Spanish, plus a deterministic rule trace, the curated frames, and the runner that produced it.
> Operators see why the alert fired and what evidence to review first.

ES:
> Cada alerta lleva su razonamiento, su traza de reglas y su evidencia. Evidencia, no solo notificación.

---

## B07 — SINAGIR + impact (2:25–2:48)

EN:
> The exported alert package is schema-tagged for SINAGIR, Argentina's national disaster-risk system, and aligns with the 2025 to 2029 Plan Nacional priorities on local preparedness.
> One endpoint, one JSON, one auditable record.

ES:
> El paquete exporta a SINAGIR y se alinea con el Plan Nacional 2025–2029.

---

## B08 — Close (2:48–3:00)

EN:
> Today, this is an MVP demo on public and simulated scenarios.
> Next: evaluation on public flood data, then on real local data.
> Pukaar plus Pukaar. Local flood intelligence that keeps working when the cloud cannot.

ES:
> Hoy: MVP demo. Después: evaluación pública. Después: datos locales reales.
> Inteligencia local que sigue funcionando cuando la nube no.

---

## Pickup lines (in case timing slips)

- "Local language. Local context. Structured response." — drop into B03 if room.
- "No cloud round-trip. No silent failure." — B05 alt close.
- "From watching to evidence to action." — B06 alt close.

## Lines that must NOT appear

- "Beats baseline by..."
- "98% accurate"
- "Deployed with Defensa Civil"
- "Predicts floods N minutes in advance"
- "Validated on real Litoral data" (until that work is actually done)
