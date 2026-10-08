# Compliance Argentina - Pukaar

Marco normativo aplicable a un sistema de alerta temprana basado en cámaras + IA edge (Raspberry Pi, Android) que detecta inundaciones/emergencias y emite alertas CAP. Documento de referencia para writeup del Project Pukaar.

Última revisión: 2026-05-16. Todas las afirmaciones citan fuente oficial (.gob.ar, infoleg, AAIP) o normativa primaria.

---

## 1. Protección de datos personales (Ley 25.326)

- La **Ley 25.326** protege los datos personales en archivos, registros y bancos de datos públicos o privados. Texto actualizado en Infoleg: https://servicios.infoleg.gob.ar/infolegInternet/anexos/60000-64999/64790/texact.htm
- La autoridad de aplicación es la **Agencia de Acceso a la Información Pública (AAIP)**, creada por Ley 27.275 (2017): https://www.argentina.gob.ar/aaip
- Por **Disposición DNPDP 10/2015**, una imagen o registro fílmico es **dato personal** cuando la persona es determinable; las bases de videovigilancia deben **inscribirse** y acompañar "manual de tratamiento de datos personales": https://www.argentina.gob.ar/aaip/datospersonales/responsables/videovigilancia
- **Base legal** para tratar imágenes captadas en espacio público: interés público / seguridad (art. 5 y 23 Ley 25.326) y/o consentimiento cuando aplique. Para fines distintos a seguridad (p.ej. investigación, IA), conviene base legal documentada y minimización.
- **Resolución AAIP 38/2024** aprobó nuevo cartel de señalización obligatoria con nombre, domicilio, web, mail y teléfono del responsable: https://www.argentina.gob.ar/noticias/recoleccion-de-imagenes-digitales-la-aaip-aprobo-el-nuevo-cartel-para-facilitar-el-acceso
- **Resolución AAIP 126/2024** actualiza clasificación y graduación de infracciones (multas de hasta varios millones de pesos / unidades móviles).

Implicancia A4V: si las cámaras filman vía pública y permiten identificar personas, hay tratamiento de datos personales aunque el dispositivo sea edge.

---

## 2. Cámaras en espacio público (nacional + CABA / PBA)

- **CABA - Ley 5688 (Sistema Integral de Seguridad Pública)**, Libro III regula la videovigilancia pública y privada que capta espacio público: http://www2.cedom.gob.ar/es/legislacion/normas/leyes/anexos/drl5688e.html
- El Ministerio de Justicia y Seguridad de CABA fija características técnicas y exige **enmascaramiento** cuando una cámara capta accidentalmente interiores privados (Ley 5688 reglamentación).
- Todo privado o público no estatal con cámara que capte espacio público debe **inscribirse en RECAVIP** (Registro de Cámaras de Videovigilancia Privadas): https://buenosaires.gob.ar/tramites/inscripcion-al-registro-de-camaras-de-videovigilancia-privadas-recavip-ley-5688-libro
- **Señalización**: cartel genérico visible obligatorio; la ubicación exacta de las cámaras es información reservada (Ley 5688 reglamentación): http://www2.cedom.gob.ar/es/legislacion/normas/leyes/anexos/drl5688e.html
- **Retención** de imágenes: típicamente 30-60 días salvo orden judicial o causa abierta (Ley 5688 reglamentación CABA; Pcia. Santa Fe Ley 13.164 fija 60 días: https://www.santafe.gov.ar/normativa/getFile.php?id=224672&item=109633&cod=d5a30a6fe7c91cb2c9698247228d09ad). Provincia de Buenos Aires regula por normas municipales y por Ministerio de Seguridad provincial; revisar ordenanza municipal del sitio de despliegue.
- **Acceso** a las grabaciones: limitado a autoridad judicial o fuerzas de seguridad con orden; el titular del dato puede ejercer derechos ARCO ante el responsable inscripto.

Implicancia A4V: cada nodo desplegado en vía pública requiere (a) inscripción ante AAIP, (b) inscripción municipal o RECAVIP si aplica, (c) cartel AAIP visible, (d) acuerdo con autoridad local.

---

## 3. Alertas tempranas oficiales (SINAGIR, CAP, SAT)

- **Ley 27.287** (2016) crea el **Sistema Nacional para la Gestión Integral del Riesgo y la Protección Civil (SINAGIR)**: https://servicios.infoleg.gob.ar/infolegInternet/anexos/265000-269999/266631/norma.htm y https://www.argentina.gob.ar/sinagir/institucional
- Decreto reglamentario 383/2017: https://www.saij.gob.ar/383-nacional-reglamentacion-ley-27287-sistema-nacional-para-gestion-integral-riesgo-proteccion-civil-dn20170000383-2017-05-30/123456789-0abc-383-0000-7102soterced
- **Decreto 225/2025** creó la **Agencia Federal de Emergencias (AFE)** bajo Min. de Seguridad; SINAGIR queda en su órbita.
- Roles: Nación coordina (AFE/SINAGIR); provincias y municipios operan sus Direcciones de Defensa Civil; ONGs y sector científico-técnico integran la Red GIRCyT.
- **SMN** opera el **Sistema de Alerta Temprana (SAT)** para fenómenos meteorológicos y los **Avisos a Muy Corto Plazo (ACP)** se publican en formato **CAP** (Common Alerting Protocol): https://www.smn.gob.ar/comunicacion/sistemadealertas y https://www.argentina.gob.ar/noticias/novedades-en-los-acp
- SMN envía diariamente a Protección Civil nacional y a defensas civiles provinciales; los ACP también se distribuyen por mail a las defensas civiles del país: https://www.smn.gob.ar/comunicacion/sistemadealertas
- CAP es estándar OASIS recomendado por OMM/UNDRR para interoperabilidad: https://www.undrr.org/early-warnings-for-all/common-alerting-protocol

Implicancia A4V: emitir alertas CAP es técnicamente compatible con el stack oficial; pero la **alerta pública oficial** la emite el SMN/Defensa Civil. A4V debería posicionarse como **fuente de detección complementaria** que notifica a Defensa Civil municipal, no como emisor oficial al público general.

---

## 4. IoT / sensores en espacio público

- Equipos que usan espectro radioeléctrico (LTE, LoRa, Wi-Fi, BT) requieren **homologación ENACOM**: https://www.enacom.gob.ar/homologacion-de-equipos_p347
- Régimen actualizado en 2026 simplifica el trámite e incorpora "familia de productos": https://www.enacom.gob.ar/institucional/enacom-agiliza-los-permisos-para-comercializar-equipos-de-telecomunicaciones-en-el-pais_n4823
- Para nodos basados en hardware comercial (Raspberry Pi + módem 4G ya homologado, Android comercial), la homologación normalmente la cubre el fabricante. Si se diseña un PCB con radio propia, se requiere trámite específico.
- **Permisos municipales**: instalación física (postes, alumbrado, mobiliario urbano) requiere convenio o permiso de uso del espacio público con el municipio (ordenanzas locales). Conexión a alumbrado público requiere autorización de la prestadora eléctrica.

---

## 5. Responsabilidad civil

- **Código Civil y Comercial (Ley 26.994)**, arts. 1716-1780, rige la responsabilidad por daños: https://servicios.infoleg.gob.ar/infolegInternet/anexos/235000-239999/235975/norma.htm
- **Falsa alerta** que cause daño (evacuación innecesaria, accidentes, pérdida económica): puede generar responsabilidad por hecho propio (art. 1749) o por actividad riesgosa (art. 1757) si el sistema se considera cosa o actividad riesgosa.
- **Omisión / falla** ante un evento real: la responsabilidad recae principalmente sobre el organismo público que tiene el deber legal de alertar (Defensa Civil). Un proveedor privado de detección puede ser corresponsable si asumió obligación contractual de medio o de resultado y la incumplió.
- Mitigación: **disclaimers** claros ("sistema experimental complementario, no reemplaza canales oficiales"), convenio con municipio que delimite alcance, seguro de responsabilidad civil, logs auditables.

---

## 6. Sugerencias prácticas para Pukaar

- **Anonimización on-device**: procesar frames en el nodo edge y descartar el frame original; persistir solo metadatos (timestamp, clase de evento, confianza, hash). Evita constituir base de datos personales en sentido estricto.
- **No retener frames** salvo eventos confirmados; si se retienen, máx. 30 días y cifrados en reposo.
- **Inscripción AAIP** de la base de datos si se retiene cualquier imagen identificable; designar responsable y DPO de contacto.
- **Señalización** con cartel AAIP Res. 38/2024 en cada nodo visible desde la vía pública.
- **Opt-in institucional**: convenio firmado con Defensa Civil municipal antes de operar; la alerta CAP se entrega a Defensa Civil, no se difunde directo al público.
- **Logging mínimo y auditable**: registrar decisiones del modelo (entrada, salida, versión, hash de modelo) para trazabilidad ante incidentes, sin guardar PII.
- **Modelo edge versionado**: documentar dataset, métricas, falsos positivos esperados; publicar model card.
- **Privacy by design**: blur automático de rostros y patentes si por algún motivo se transmite frame; geofencing del FOV para excluir interiores privados (cumple Ley 5688 art. enmascaramiento).
- **Hardware homologado** (Raspberry Pi oficial, módems con sello ENACOM, cámaras CE/FCC con homologación local cuando aplique).
- **Términos del servicio**: disclaimer público de que A4V es sistema complementario y no reemplaza al SMN ni a Defensa Civil oficial.
- **Plan de respuesta a incidentes**: protocolo ante falla, falso positivo masivo, o brecha de datos (notificación AAIP en 72 hs si hay incidente con datos personales).

---

## Fuentes

- Ley 25.326 (Infoleg): https://servicios.infoleg.gob.ar/infolegInternet/anexos/60000-64999/64790/texact.htm
- AAIP - Videovigilancia: https://www.argentina.gob.ar/aaip/datospersonales/responsables/videovigilancia
- AAIP - Nuevo cartel Res. 38/2024: https://www.argentina.gob.ar/noticias/recoleccion-de-imagenes-digitales-la-aaip-aprobo-el-nuevo-cartel-para-facilitar-el-acceso
- AAIP (sitio): https://www.argentina.gob.ar/aaip
- Ley 5688 CABA reglamentación: http://www2.cedom.gob.ar/es/legislacion/normas/leyes/anexos/drl5688e.html
- RECAVIP: https://buenosaires.gob.ar/tramites/inscripcion-al-registro-de-camaras-de-videovigilancia-privadas-recavip-ley-5688-libro
- Santa Fe Ley 13.164: https://www.santafe.gov.ar/normativa/getFile.php?id=224672&item=109633&cod=d5a30a6fe7c91cb2c9698247228d09ad
- Ley 27.287 SINAGIR: https://servicios.infoleg.gob.ar/infolegInternet/anexos/265000-269999/266631/norma.htm
- SINAGIR institucional: https://www.argentina.gob.ar/sinagir/institucional
- Decreto 383/2017 reglamentario: https://www.saij.gob.ar/383-nacional-reglamentacion-ley-27287-sistema-nacional-para-gestion-integral-riesgo-proteccion-civil-dn20170000383-2017-05-30/123456789-0abc-383-0000-7102soterced
- SMN SAT: https://www.smn.gob.ar/comunicacion/sistemadealertas
- SMN ACP / CAP: https://www.argentina.gob.ar/noticias/novedades-en-los-acp
- UNDRR CAP: https://www.undrr.org/early-warnings-for-all/common-alerting-protocol
- ENACOM homologación: https://www.enacom.gob.ar/homologacion-de-equipos_p347
- ENACOM régimen 2026: https://www.enacom.gob.ar/institucional/enacom-agiliza-los-permisos-para-comercializar-equipos-de-telecomunicaciones-en-el-pais_n4823
- Código Civil y Comercial Ley 26.994: https://servicios.infoleg.gob.ar/infolegInternet/anexos/235000-239999/235975/norma.htm
