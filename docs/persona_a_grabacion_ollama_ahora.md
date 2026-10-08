# Persona A - Grabacion Pukaar ahora con Ollama

Documento autocontenido. Seguilo tal cual. Objetivo: producir material usable para el video final mientras sigue la migracion a LiteRT-LM.

---

## 1. Objetivo

Grabar una demo corta de **Pukaar** funcionando con el estado actual del repo, usando el runner Pukaar AI compatible via **Ollama**.

Esto sirve para el video como:

- demo reproducible del nodo fijo,
- evidencia de pipeline multimodal actual,
- fallback visual si LiteRT-LM no llega antes del corte final.

No lo presentes como LiteRT-LM final. No digas que corre en Pi con LiteRT si en esta toma esta corriendo con Ollama.

Frase correcta:

> "Demo actual de Pukaar con runner Pukaar AI compatible via Ollama, mientras la migracion a LiteRT-LM esta en curso."

---

## 2. Que hay que entregar

Entregar al menos uno de estos archivos:

```text
docs/Project/video/raw/screencast_node_analysis.mp4
```

Idealmente tambien:

```text
docs/Project/video/raw/pukaar_ollama_runtime_check.mp4
docs/Project/video/raw/pukaar_node_console_log.txt
```

Duracion objetivo del video: **20 a 40 segundos utiles**.

Resolucion minima: **1080p**.

Audio: puede ir sin audio. Si hay audio, que no haya notificaciones ni conversaciones privadas.

---

## 3. Que debe verse en pantalla

La toma tiene que mostrar, en este orden:

1. Backend/frontend corriendo.
2. Pantalla del sitio demo:

   ```text
   /sites/silverado-fixed-cam-usgs
   ```

3. Boton o accion:

   ```text
   Analyze bundled sample
   ```

4. Resultado del analisis:
   - `frames_analyzed`
   - `assessment_level` o alert level
   - score/confidence si aparece
   - evidence frame
   - reasoning summary de Pukaar AI si aparece

5. Si hay terminal visible, mostrar una salida corta donde se vea:
   - modelo/runner usado,
   - `runner_mode`,
   - `fallback_used`.

No hace falta mostrar toda la terminal. La prioridad es que la UI sea clara.

---

## 4. Comandos sugeridos

Desde la raiz del repo:

```powershell
cd C:\Users\76hz\Documents\GitHub\Pukaar
```

Seed de datos:

```powershell
$env:PYTHONPATH="backend/src"
python -m Pukaar.scripts.seed
```

Levantar backend + frontend:

```powershell
.\scripts\dev.ps1
```

En otra terminal, verificar que el nodo sample funciona:

```powershell
$env:PUKAAR_MULTIMODAL_ENABLED="true"
python scripts\pi_pukaar_node.py --sample-site --site-id silverado-fixed-cam-usgs
```

Resultado ideal:

```text
runner.mode = ollama-multimodal-temporal
fallback_used = false
```

Si aparece:

```text
fallback_used = true
```

igual sirve como backup, pero avisar a D/E. No vender como analisis visual Pukaar AI exitoso.

---

## 5. Como grabar

Usar OBS, Xbox Game Bar, QuickTime, o cualquier grabador de pantalla.

Config:

- 1920x1080 si se puede.
- 30 fps.
- Capturar solo navegador + terminal necesaria.
- Cerrar WhatsApp, Discord, mail, notificaciones y tabs no relacionadas.
- Zoom del navegador 100% o 110%.
- Tema claro u oscuro da igual, pero que el texto se lea.

Secuencia recomendada:

1. Abrir frontend:

   ```text
   http://127.0.0.1:5173/sites/silverado-fixed-cam-usgs
   ```

2. Empezar grabacion.
3. Mostrar 2 segundos la pagina cargada.
4. Click en:

   ```text
   Analyze bundled sample
   ```

5. Esperar resultado.
6. Hacer scroll o encuadrar para que se vea:
   - panel de metricas,
   - alert result,
   - evidence frame.
7. Si hay terminal con salida limpia, mostrarla 3 a 5 segundos.
8. Cortar grabacion.

Guardar como:

```text
docs/Project/video/raw/screencast_node_analysis.mp4
```

---

## 6. Que NO hacer

No decir ni mostrar texto que afirme:

- "LiteRT-LM ya esta listo" si esta toma usa Ollama.
- "corre en produccion".
- "validado en Litoral".
- "detecta inundaciones con X% accuracy".
- "predice con X minutos de anticipacion".
- "Defensa Civil lo usa".

No mostrar:

- datos personales,
- chats privados,
- API keys,
- `.env`,
- logs con tokens,
- tabs de navegador no relacionadas.

---

## 7. Texto de credito / disclaimer para D+E

Cuando pases el archivo, incluir este mensaje:

```text
Archivo: docs/Project/video/raw/screencast_node_analysis.mp4
Estado: demo Pukaar con runner Pukaar AI compatible via Ollama.
LiteRT-LM: migracion en curso, no usar esta toma como claim LiteRT.
Runner observado: <pegar runner_mode>
Fallback usado: <true/false>
Modelo observado: <pegar model si aparece>
Notas: <cualquier fallo o detalle>
```

---

## 8. Si algo falla

Si el frontend no carga:

1. Confirmar que `.\scripts\dev.ps1` sigue corriendo.
2. Abrir:

   ```text
   http://127.0.0.1:8000/api/health
   http://127.0.0.1:5173
   ```

Si el analisis sample falla:

1. Correr:

   ```powershell
   $env:PYTHONPATH="backend/src"
   python -m Pukaar.scripts.seed
   ```

2. Reintentar.

Si Ollama/modelo no responde:

1. Grabar igual la UI hasta el error si sirve para debug.
2. Avisar a D/E que el material es fallback.
3. No inventar que Pukaar AI respondio.

---

## 9. Definition of done

La tarea esta lista cuando existe:

```text
docs/Project/video/raw/screencast_node_analysis.mp4
```

y D/E reciben:

- archivo grabado,
- runner/mode observado,
- fallback true/false,
- estado LiteRT-LM real.

Si LiteRT-LM queda listo despues, se puede grabar una segunda version y reemplazar esta.
