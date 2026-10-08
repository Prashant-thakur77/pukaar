# **Pukaar 4 \+ Pukaar**

*Sistema híbrido de alerta temprana de inundaciones con IA en el borde, resiliente a la caída de conectividad.*

> **Documento de producto y narrativa.** Pitch extenso en español: problema,
> encaje en el track, cómo se ve la demo, arquitectura, factibilidad,
> diferenciación y Novelty Assessment. Para la grilla de criterios del
> Project con proof links, ver [`Project.md`](Project.md). Para
> reproducibilidad paso a paso, ver
> [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).

---

## **Pitch de una línea**

Cuando la tormenta corta internet, Pukaar 4 \+ Pukaar sigue viendo el río: un nodo fijo analiza video en el borde y los voluntarios reportan por voz en su dialecto, todo procesado localmente por Pukaar AI hasta que vuelve la conexión.

---

## **Problema**

Las inundaciones son el **60% de los desastres registrados en Argentina** (Plan Nacional de Reducción del Riesgo de Desastres 2025-2029, Resolución 334/2026). El sistema oficial — SINAGIR / SINAME — existe, pero la información de campo llega tarde y desestructurada: los voluntarios reportan por grupos de WhatsApp con frases como *"ya pasó la marca del puente, está subiendo rápido"*, y esa señal crítica se pierde entre mensajes.

Peor aún: cuando la propia tormenta corta internet, los monitores IoT tradicionales colapsan exactamente cuando más se los necesita. **Bahía Blanca, marzo 2025**: las alertas meteorológicas nacionales llegaron a tiempo, pero no hubo alerta de riesgo local por la crecida de los arroyos — y hubo muertos.

Hay un hueco estructural entre la alerta meteorológica nacional y la alerta de riesgo local. Ese hueco se agranda precisamente cuando la conectividad cae. Ahí está nuestro usuario: **coordinadores de Defensa Civil municipal y voluntarios ribereños del Litoral argentino** (cuencas del Paraná, Salado, Paraguay).

---

## **Encaje**

* **Track**: Global Resilience (Climate & Green Energy) del Pukaar Release.  
* **Premio objetivo**: LiteRT Prize (USD 10.000) — Excelencia en el ecosistema Google AI Edge / LiteRT-LM.  
* **Contexto regulatorio**: Ley 27.287 (SINAGIR, 2016\) \+ Plan Nacional 2025-2029 que exige explícitamente *"fortalecer sistemas de alerta temprana hidrometeorológicos"*.  
* **Gap verificado**: el Novelty Assessment confirma que no hay entradas previas de flood / climate / LatAm en el Pukaar AI 3n Impact Challenge, ni publicaciones que combinen nodo fijo edge \+ voluntario offline \+ schema SINAME.  
* **Precedente ganador**: replica el patrón de **EpiCast** (Grand Prize MedPukaar AI, USD 30k) — voz coloquial de voluntarios → JSON estandarizado — aplicado a hidrología en lugar de salud pública, usando las capacidades nuevas de Pukaar AI (function calling nativo, thinking mode, video temporal) que EpiCast no tenía.

---

## **Cómo usa las fuerzas únicas de Pukaar AI**

1. **Video temporal largo en el borde.** El nodo fijo captura un frame por segundo durante 60 segundos. Pukaar AI E4B absorbe la secuencia completa (\~16.800 tokens, fracción de su ventana de 128k) y razona sobre la evolución del nivel del agua, descartando oscilaciones de vegetación o lodo como ruido inocuo. Ningún modelo anterior de esta clase permitía ingestión temporal sostenida en el borde.

2. **Thinking Mode auditable.** Antes de clasificar una alerta en verde / amarillo / naranja / rojo, el modelo genera una cadena de razonamiento explícita que queda guardada en `decision_trace`. Un coordinador municipal puede leer *por qué* el sistema escaló a rojo, no solo *que* escaló. Defensa Civil nunca más depende de una caja negra.

3. **Multimodal real.** Un solo pipeline procesa imagen del puente \+ audio del voluntario \+ texto de toggles rápidos (corte de ruta, casas afectadas). Pukaar AI corre localmente vía Ollama en hardware comodity — no hay llamadas a nubes remotas.

4. **Function calling nativo.** El modelo no solo analiza: dispara acciones. Tool calls conectados a actuadores locales (`AlarmActuator`, `RadioActuator`, `NotificationActuator`) activan sirena de 120 dB, empaquetan payload LoRaWAN para Defensa Civil, o encolan el sync cuando vuelva internet.

5. **Hiperlocalización lingüística.** Few-shot prompting con ejemplos del español rioplatense/litoraleño (*pasó la marca*, *tapó la calle*, *ya toca el puente*, *está subiendo rápido*) mapeando a enums estandarizados del schema SINAME. Aplica el principio ganador de *"hiperlocalización lingüística para homogeneización de datos"*: el voluntario habla en su dialecto, el modelo traduce a JSON institucional. Roadmap explícito hacia LoRA fine-tuning cuando haya corpus.

---

## **Cómo se ve la demo (video pitch)**

1. **Abre**: plano de una cámara fija sobre un arroyo (clip USGS Silverado, dominio público). El nodo corre en laptop / Raspberry Pi con Ollama \+ Pukaar AI\.  
2. **Voluntaria en el campo** abre la PWA en su celular, saca foto del puente y dicta: *"el agua ya pasó la marca, está subiendo rápido"*. La UI confirma envío.  
3. **Se corta el wifi en vivo**, a la vista del jurado. Badge de conectividad pasa a rojo.  
4. **Segundo reporte** de otra voluntaria: corte de ruta. La UI lo marca "guardado localmente, en cola". Todo sigue funcionando.  
5. **El nodo fijo detecta** cruce de línea crítica en 8 de 10 frames. Pukaar AI corre Thinking Mode y la cadena de razonamiento aparece en pantalla: *"reporte de Pukaar coincide con nodo; dos señales corroboradas; severidad → rojo"*. La sirena local suena.  
6. **Vuelve internet**: la cola se drena sola, el dashboard central muestra el alerta rojo compuesto con el `decision_trace` completo y el payload JSON SINAME-compatible.  
7. **Cierre**: *"Cuando la red cae, nosotros seguimos viendo el río."*

---

## **Arquitectura técnica**

**Nodo fijo (edge)**

* Raspberry Pi 5 (8 GB demo, 16 GB prod) o x86 comodity.  
* `ffmpeg` de sistema para muestreo temporal de la cámara fija; el frame curado va **directo a Pukaar AI multimodal** (OpenCV ya no participa de la decisión visual, queda sólo como utilidad de curación de ROI).  
* Pukaar AI E2B/E4B vía **LiteRT-LM** en el Pi (mismo `.litertlm` que la app Android); Ollama queda como path de dev en workstation. Thinking Mode + descripción multimodal del evidence frame producen el paquete completo de `assessment_*` + `reasoning_*` por nodo.  
* Actuadores detrás de interfaces (`AlarmActuator`, `RadioActuator`, `NotificationActuator`) — en producción conectables a GPIO \+ LoRaWAN; en demo simulados con WAV / log / banner.

**App voluntario (PWA mobile-first)**

* React \+ TypeScript \+ Vite \+ `vite-plugin-pwa`, instalable.  
* IndexedDB para cola offline; badge de conectividad explícito; transcript manual siempre disponible como fallback si falla ASR local.  
* Envía al backend local cuando hay conexión, encola JSON estructurado cuando no.

**Backend (local o central)**

* FastAPI \+ SQLModel \+ SQLite, con dos bases de datos (`edge.db` y `central.db`) para simular sync realista.  
* Adaptadores reemplazables: `TextStructuringAdapter`, `AudioTranscriptionAdapter`, `ImageAssessmentAdapter`, `VideoAssessmentAdapter`. Implementaciones rule-based como fallback obligatorio; Pukaar AI como upgrade path.  
* Scoring transparente: `fused_score = max(node_score, report_score) + corroboration_bonus`, con overrides duros por frases críticas o cruce verificado de línea.  
* Enriquecimiento hidrometeorológico vía Open-Meteo APIs usando coordenadas del sitio.

**Contrato JSON**: normalizado y SINAME-ready. Mapeo documentado en `docs/Project/sinagir-mapping.md`. No se reclama compliance oficial sin verificación.

---

## **Factibilidad**

**Stack liviano**. Corre en CPU/GPU integrada; Ollama \+ Pukaar AI E2B caben en laptop con 8 GB RAM. E4B opcional si hay VRAM (RTX 3060 12 GB alcanza).

**Demo asset real**. Clip público USGS Silverado fixed camera ya integrado; cualquier jurado lo reproduce con `python3 scripts/fetch_demo_assets.py`.

**Estado actual del repositorio** `prashant/Pukaar`:

| Pieza | Estado |
| ----- | ----- |
| Backend con endpoints salud / sites / calibración / análisis de nodo / reportes / alertas / sync | ✅ Implementado |
| Frontend PWA con dashboard, reporte, cola, sitios, calibración, settings | ✅ Implementado |
| Offline-first con IndexedDB \+ cola \+ sync queue | ✅ Implementado |
| Integración Pukaar AI operativa (Ollama central + LiteRT-LM nodo/Android) | ✅ Implementado |
| Análisis multimodal real sobre clip fijo (no mock) | ✅ Implementado |
| Tests backend (health, parser, sync, attachments, node analysis) | ✅ Declarados |
| Thinking Mode visible en `decision_trace` | ✅ Implementado — ver [`docs/Project/thinking-mode.md`](docs/Project/thinking-mode.md) |
| Pukaar AI describiendo el evidence frame multimodal | ✅ Implementado — ver [`docs/Project/multimodal-comparison.md`](docs/Project/multimodal-comparison.md) |
| Few-shot rioplatense con casos de test | ✅ Implementado — corpus de 82 ejemplos, ver [`docs/Project/rioplatense_eval.md`](docs/Project/rioplatense_eval.md) |
| Click-to-draw en calibración | ✅ Implementado (commit `ce62b88`) |
| Mapeo SINAGIR concreto | ✅ Implementado — ver [`docs/Project/sinagir-mapping.md`](docs/Project/sinagir-mapping.md) |
| Pukaar Android on-device (LiteRT-LM, mismo `.litertlm` que el backend) | ✅ Implementado — ver [`docs/Project/android_pukaar-ai.md`](docs/Project/android_pukaar-ai.md) |

---

## **Por qué destaca**

1. **Replicación de patrón ganador, dominio nuevo**. EpiCast ganó MedPukaar AI aplicando este patrón a salud pública. Nadie lo aplicó a hidrología. Nadie lo aplicó a español rioplatense. Nadie lo combinó con nodo fijo. El Novelty Assessment confirma el gap.

2. **Arquitectura híbrida sin precedente publicado**. Nodo fijo edge \+ reportes humanos offline \+ motor local de decisión bajo un único schema de alerta. Los papers adyacentes (Bandung CCTV \+ MMLLM, FloodBrain) son todos cloud-only; los sistemas IoT+LoRa con TinyML no son multimodales; las apps de citizen science no tienen edge inference.

3. **Defensa sólida contra *"¿por qué no cloud GPT?"***. La tormenta corta internet; lo demostramos **en vivo** en la demo. Esa es la diferencia entre un producto que funciona en el peor día del año y uno que colapsa.

4. **Fit regulatorio y temporal exacto**. La Resolución 334/2026 del gobierno argentino se aprobó hace días y pide literalmente reforzar alertas tempranas hidrometeorológicas. Hay destinatario identificado: Defensa Civil municipal del Litoral.

5. **Trazabilidad auditable por diseño**. El `decision_trace` con cadena de pensamiento hace que cada alerta sea defendible frente a un coordinador de emergencias o un proceso judicial posterior. Es una ventaja estructural sobre cualquier CNN caja-negra.

6. **Soberanía de datos**. Todo el pipeline corre en el dispositivo; los reportes de voluntarios no viajan a nubes extranjeras. Relevante para adopción pública argentina.

---

## **Pitfalls**

### **Técnicos**

* **E4B puede no caber** en el hardware de demo del jurado. Caer a E2B pierde calidad en razonamiento multimodal. *Mitigación*: E2B con prompting cuidadoso alcanza para el pitch; E4B queda como upgrade path documentado.  
* **El analizador CV es heurístico** y está tuneado para cámaras con encuadre estable. Cámaras móviles pueden generar falsos positivos. *Mitigación*: limitación declarada abiertamente; calibración por sitio resuelve la mayoría.  
* **ASR en el browser** depende de capacidad local; si falla, se degrada a entrada manual. *Mitigación*: el transcript manual cubre la demo sin perder el flujo.

### **De narrativa y jurado**

* **"¿Por qué no un CNN \+ reglas \+ WhatsApp bot?"** *Defensa*: corte de conectividad en vivo, soberanía de datos, schema SINAME, cadena de razonamiento auditable, dialecto local.  
* **Riesgo de sonar "dos productos"**. *Mitigación*: insistir en "una arquitectura, dos entradas, un schema, un pipeline de alerta". Nunca decir "Pukaar y Pukaar"; siempre "Pukaar 4 \+ Pukaar".  
* **Claim de SINAGIR compliance** sin verificar es autogol. *Mitigación*: decir "SINAME-ready mapping", nunca "SINAGIR-compliant".

### **De ejecución y percepción**

* La salida del MVP a `main` y el tag `v1.0-Project-submission` ya se hicieron; release con changelog y trazabilidad de PRs publicada. Próximo paso en este eje: CI visible (GitHub Actions) si la entrega lo requiere.

# Novelty Assessment — Pukaar 4 \+ Pukaar

  Classification: partially\_addressed → mostly\_novel (Score: 3.5 / 5\)

  No exact-match prior submission or paper. Each component individually solved; novelty lives in integration \+ jurisdictional/linguistic specialization.

  Key prior work

  Pattern precedent (cite in pitch):  
  \- EpiCast (MedPukaar AI Impact Challenge grand prize, $30k) — colloquial volunteer speech → WHO IDSR structured signals. Pukaar \= EpiCast pattern swapped  
  health→hydrology. User's intuition correct.  
  \- Pukaar AI 3n Impact Challenge (600+ submissions, 8 winners) — no flood/climate/LatAm entry. Gap real.  
  \- Pukaar Release — "Global Resilience" track explicit fit.

  Closest threats:  
  \- Bandung CCTV \+ MMLLM flood paper (MDPI Water 2025\) — cloud GPT-4.1/Gemini on CCTV flood classification. No edge, no temporal video, no actuation, no  
  voice. Reviewers ask "why not cloud GPT?" → answer: connectivity loss during storm.  
  \- FloodBrain (arxiv 2311.02597) — LLM+RAG cloud flood reporting, post-hoc. Not edge/real-time.  
  \- LoRaWAN vision-AI cameras (SenseCAP A1101) — commercial edge camera \+ LoRa, but TinyML CNN, not multimodal LLM.  
  \- EdgeAI\_llamacpp — LLM+GPIO on Pi exists, home automation domain.

  Solved adjacents (don't claim novelty here):  
  \- IoT \+ LoRa flood EWS → Nature 2025, L'Aquila IEEE, etc. Mature.  
  \- CNN water-level on Pi → MDPI 2024\. Standard.  
  \- Citizen-science flood apps → Springer 2024, PMC Frederikssund. Established.

  Genuine gaps (claim novelty here):  
  \- Rioplatense Spanish hydrological LoRA — zero prior work.  
  \- SINAGIR-schema function calling — no volunteer-facing offline app found in Argentina.  
  \- Temporal 60-frame MMLLM reasoning on Pi-class node for flood actuation — unpublished.  
  \- Dual-input hybrid (fixed node \+ mobile volunteer → same alert schema) — novel composition.

  Recommendation: Proceed

  Strong novelty framing:  
  1\. Lead with EpiCast as precedent — judges recognize, signals homework.  
  2\. Kill the "why not cloud" objection first — storm kills connectivity; demo video must show this.  
  3\. Emphasize integration, not components — "no one has combined X+Y+Z for SINAGIR".  
  4\. Scope risk real — user already flagged. Build one architecture, two inputs, one alert pipeline. Do not pitch "two products".

  Weakness to pre-empt

  Components each solvable with cloud \+ CNN \+ WhatsApp bot. Defend with: connectivity loss, sovereignty, Spanish dialect, government schema compatibility,  
  auditable thinking-mode chain.  
