# Diferenciacion vs sistemas existentes

Pukaar (A4V) no compite con los grandes sistemas globales ni con los oficiales nacionales: ocupa un hueco verificado en la ultima milla de la alerta hidrologica local cuando la conectividad cae. Esta seccion compara honestamente y delimita el alcance.

## Tabla comparativa

| Sistema | Cobertura | Metodo | Latencia tipica | Conectividad requerida | Idioma local | Costo despliegue | Diferencia con A4V |
|---|---|---|---|---|---|---|---|
| Google Flood Hub | ~80-150 paises, >1.800 sitios, ~460M personas | LSTM hidrologico + modelo de inundacion sobre datos publicos (lluvia, cuencas) | Pronostico hasta 7 dias | Cloud Google, internet permanente para usuario | Multi-idioma de UI; sin dialecto | Cero para usuario final; depende de infra Google | Forecast de cuenca, no deteccion in-situ; no opera offline; no integra reporte ciudadano local |
| PetaBencana.id | Indonesia | Crowdsourcing via WhatsApp/Telegram/Twitter/FB Messenger + chatbot, mapeo en tiempo real | Minutos | Internet o SMS basico para enviar | Bahasa Indonesia; sin NLU profundo | Bajo, open source | Sin nodo fijo de vision; sin razonamiento auditable; sin alerta automatica edge; sin schema gubernamental estructurado |
| GDACS (UN + JRC) | Global, 2.500 sitios fluviales en 132 paises | AMSR-E microondas pasivas satelitales + Global Flood Observatory | Diaria | Cloud, suscriptores institucionales | EN principal | Cero usuario; infra JRC | Alerta humanitaria post-evento a escala pais; no llega a coordinador municipal en tiempo de respuesta |
| SISSA / CRC-SAS | Cono Sur (sequias, no inundaciones primarias) | Indices climaticos regionales | Mensual/estacional | Cloud institucional | ES | Institucional | Otro fenomeno (sequia); no aplica a crecida rapida |
| PREVENIR (CONICET + JICA) | 2 cuencas piloto AR (BA, Cordoba) | Modelado meteo-hidrologico + alerta comunitaria | En desarrollo | Internet + estaciones | ES | Institucional | Sistema oficial complementario; A4V puede alimentar su capa de campo |
| INA / SIyAH (Argentina) | Cuencas hidrograficas oficiales AR | Estaciones de aforo + modelos hidrologicos | Horaria/diaria | Cloud INA | ES | Estatal | Cobertura limitada a estaciones; no llega a arroyos urbanos pequenos |
| FarmWise (Vulcan) | EE.UU. (vegetales CA) | CV edge sobre tractor para deshierbe | Tiempo real | Equipo local | EN | Hardware agricola | Otro dominio (agricultura); cita solo para descartar overlap |

## Por que A4V es complementario, no redundante

A4V cubre cinco propiedades que ninguno de los sistemas anteriores ofrece junto:

1. **Edge offline real.** El nodo fijo (Raspberry Pi 5 + Pukaar AI via LiteRT-LM) y la app voluntario (Android + LiteRT-LM Android, mismo `.litertlm`) siguen produciendo veredictos y encolando reportes durante el corte de internet que la propia tormenta provoca. Flood Hub, GDACS y SISSA dejan de ser utiles para el usuario final en ese momento.
2. **Dual-source bajo un solo schema.** Vision temporal del nodo + reporte de voluntario en dialecto rioplatense se funden en un unico `FusedAlert` con `decision_trace` auditable. PetaBencana fusiona solo crowdsource; Flood Hub solo modelo hidrologico.
3. **Espanol rioplatense/litoraleno.** Corpus de 82 ejemplos y prompting few-shot mapean "ya paso la marca", "tapo la calle", "esta subiendo rapido" a enums SINAME. Ningun competidor tiene NLU dialectal hidrologico para AR.
4. **Razonamiento auditable.** Cada alerta no-verde lleva cadena de razonamiento en castellano + traza deterministica de reglas. Defendible ante coordinador municipal o proceso judicial. Flood Hub publica numeros; GDACS publica niveles; ninguno publica el *por que*.
5. **Costo de despliegue bajo y soberano.** Pi 8 GB + camara + Android comodity, sin dependencia de nube extranjera para datos sensibles de campo. PREVENIR/INA son institucionales y de alcance limitado por estacion.

## Lo que A4V NO es

- **No reemplaza al SMN ni al SINAGIR.** Es una capa local que produce evidencia SINAGIR-ready (`POST /api/alerts/{id}/export-sinagir`) para alimentar el flujo oficial.
- **No compite con Flood Hub a escala continental.** Flood Hub es superior para pronostico hidrologico de cuenca a 7 dias; A4V es superior para deteccion in-situ del arroyo concreto en los proximos 60 minutos.
- **No es crowdsourcing puro al estilo PetaBencana.** A4V exige nodo fijo calibrado por sitio; eso eleva precision y reduce falsos positivos a cambio de menor escala.

## Posicionamiento honesto

A4V apunta a Defensa Civil municipal del Litoral argentino (cuencas Parana, Salado, Paraguay) y a coordinadores de barrios ribereños. Es la "ultima milla offline auditable" entre la alerta meteorologica nacional y la decision de evacuar una calle. Bahia Blanca, marzo 2025: las alertas SMN llegaron; falto la senal local del arroyo. Ese hueco es A4V.

## Fuentes

- Google Flood Hub: https://sites.research.google/floods/ ; https://support.google.com/flood-hub/answer/16508958 ; https://blog.google/technology/ai/expanding-flood-forecasting-coverage-helping-partners/
- PetaBencana.id: https://info.petabencana.id/ ; https://oecd.ai/en/catalogue/tools/petabencanaid-bot ; https://restofworld.org/2021/hi-im-disaster-bot/
- GDACS: https://gdacs.org/ ; https://www.gdacs.org/Knowledge/models_fl.aspx ; https://en.wikipedia.org/wiki/Global_Disaster_Alert_and_Coordination_System
- SISSA / CRC-SAS: https://sissa.crc-sas.org/
- PREVENIR (CONICET + JICA): https://sites.google.com/view/prevenir-es/home ; https://www.argentina.gob.ar/noticias/argentina-y-japon-desarrollaran-un-sistema-de-alerta-de-inundaciones-urbanas-repentinas
- INA SIyAH: https://www.ina.gov.ar/siyah/index.php?seccion=1
- FarmWise: https://farmwise.io/ ; https://www.therobotreport.com/inside-the-development-of-farmwises-weeding-robot/
