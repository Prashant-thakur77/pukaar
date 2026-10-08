# P4 - Candidatos de Clip de Video para Demo Project (Pukaar)

Proyecto: Pukaar. Uso: ~10-30s de B-roll en video demo de presentacion al jurado.
Fecha de busqueda: 2026-05-16. Filtros: video real (no IA), licencia clara o citable.

Orden: score descendente. NO descargar todavia, solo URLs.

---

## 1. AFP - "Inundacion en Argentina deja 16 muertos y USD 400 millones en danos" (Bahia Blanca)  [Score: 9/10]

- **URL:** https://www.youtube.com/watch?v=wVYMnB88Fjc
- **Fuente original:** Canal AFP Espanol (YouTube oficial de Agence France-Presse)
- **Licencia:** Standard YouTube License. Uso en Project: fair use educativo con cita explicita "Imagenes: AFP / Agence France-Presse" en credits.
- **Duracion total:** ~1-2 min (clip de noticia). **Fragmento util:** primeros 00:05-00:25 (tomas calle/auto/agua corriendo).
- **Ubicacion:** Bahia Blanca, Provincia de Buenos Aires, Argentina.
- **Fecha filmacion:** 7-8 marzo 2025.
- **Descarga:** `yt-dlp -f "bv*[height<=1080]+ba/b" https://www.youtube.com/watch?v=wVYMnB88Fjc`
- **Notas:** Mejor candidato AR. Tomas a nivel de calle, autos arrastrados, casas inundadas. Calidad broadcast HD. Tiene voz en off en espanol (silenciar y poner subtitulos propios). Watermark AFP en esquina - aceptable porque ya implica atribucion.

## 2. "Cloudburst en Bahia Blanca - Provincia de Buenos Aires" (Wikimedia Commons)  [Score: 7/10]

- **URL:** https://commons.wikimedia.org/wiki/File:Cloudburst_en_Bah%C3%ADa_Blanca_-_Provincia_de_Buenos_Aires.webm
- **Direct file:** https://upload.wikimedia.org/wikipedia/commons/f/f6/Cloudburst_en_Bah%C3%ADa_Blanca_-_Provincia_de_Buenos_Aires.webm
- **Fuente original:** Usuario EzequielKees95, datos del Servicio Meteorologico Nacional Argentino (SMN).
- **Licencia:** CC BY-SA 4.0 (animacion) + CC BY 2.5 AR (imagenes radar SMN). Atribucion: "EzequielKees95 / SMN, CC BY-SA 4.0".
- **Duracion total:** 36s. **Fragmento util:** completo (loop).
- **Ubicacion:** Bahia Blanca, AR.
- **Fecha filmacion:** 7 marzo 2025.
- **Descarga:** wget directo desde upload.wikimedia.org URL.
- **Notas:** NO es footage de calle - es animacion radar meteorologico mostrando la celula de tormenta. Excelente para B-roll tecnico/cientifico (refuerza narrativa "Pukaar detecta antes que llegue"). Licencia 100% limpia. 722x720, pequeno.

## 3. CNN Espanol - "Las intensas lluvias ocasionan graves inundaciones en Argentina"  [Score: 8/10]

- **URL:** https://cnnespanol.cnn.com/2025/05/20/argentina/video/inundaciones-lluvias-buenos-aires-cafe-tv
- **Fuente original:** CNN en Espanol, video TV original via Cafe TV.
- **Licencia:** Copyright CNN. Fair use educativo con cita "Imagenes: CNN en Espanol / Cafe TV (mayo 2025)".
- **Duracion total:** ~1 min. **Fragmento util:** ~00:10-00:25.
- **Ubicacion:** AMBA / Buenos Aires, Argentina.
- **Fecha filmacion:** mayo 2025.
- **Descarga:** yt-dlp sobre URL embebida del player CNN (puede requerir extractor especifico) o capturar via OBS si yt-dlp falla.
- **Notas:** Calidad noticiero. Watermarks CNN+Cafe TV - cita doble en credits. Buena estetica urbana AMBA reconocible.

## 4. "Urban Flooding in Mexico City Streets" - Pexels (Israyosoy S.)  [Score: 8/10]

- **URL:** https://www.pexels.com/video/urban-flooding-in-mexico-city-streets-28730771/
- **Download directo:** https://www.pexels.com/download/video/28730771/
- **Fuente original:** Israyosoy S. en Pexels.
- **Licencia:** Pexels License (gratis uso comercial, atribucion opcional pero recomendada). Sin restricciones para Project.
- **Duracion total:** no listada explicita, ~15-30s. **Fragmento util:** completo.
- **Ubicacion:** Ciudad de Mexico (Latinoamerica, contexto cultural compatible).
- **Fecha filmacion:** 2024.
- **Descarga:** click directo en "Free Download" o wget URL anterior. Hasta 4K (1440x2560 vertical 60fps).
- **Notas:** Licencia mas limpia del set. Vertical (smartphone-style) - ideal para storytelling "ciudadano grabando con celular". Mexico DF, no AR, pero indistinguible visualmente para jurado no-experto.

## 5. "Driving on Flooded Roads" - Pexels (Kelly)  [Score: 6/10]

- **URL:** https://www.pexels.com/video/driving-on-flooded-roads-5667622/
- **Fuente original:** Kelly en Pexels.
- **Licencia:** Pexels License (libre, atribucion opcional).
- **Duracion total:** ~20s. **Fragmento util:** completo.
- **Ubicacion:** no especificada (global).
- **Fecha:** no listada.
- **Descarga:** Boton "Free Download", hasta 4K UHD 2560x1440 24fps.
- **Notas:** POV desde auto sobre ruta inundada con efecto espejo. Util como transicion. Menos urbano - mas rural/suburbano. Backup si los AR no se pueden conseguir.

## 6. (Backup) DW/EFE - "Argentina: graves inundaciones en Bahia Blanca dejan ya 15 muertos"  [Score: 7/10]

- **URL:** https://www.youtube.com/watch?v=ZvciOQ3pUcc
- **Fuente:** noticiero internacional (verificar canal exacto al fetch).
- **Licencia:** Copyright canal. Fair use con cita.
- **Fragmento util:** segmentos de calle/vecinos rescatando.
- **Notas:** Backup AR. Bajar prioridad por watermark fuerte y posible musica con copyright (silenciar audio).

---

## Recomendacion final

**Top-1:** AFP Bahia Blanca (#1). Gana porque es AR real, reciente (marzo 2025), broadcast quality, tomas de calle con impacto emocional, y la cita "AFP" es estandar y aceptada universalmente en Projects.

**Combinacion sugerida para demo:**
- Hook (0-5s): clip AFP (#1) calle inundada.
- Tecnico (5-10s): animacion radar Wikimedia (#2) - refuerza "deteccion temprana".
- Cierre humano (10-15s): Pexels CDMX (#4) o segundo corte AFP.

**Plan B si AFP da problemas de copyright en YouTube:** sustituir con CNN Espanol (#3) o Pexels CDMX (#4).
