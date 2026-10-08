# Talking-head — Guía de grabación

Documento auto-contenido. No requiere contexto previo. Seguilo paso a paso.

---

## 1. Contexto del proyecto (lo mínimo que necesitás saber)

**Proyecto:** Pukaar. Sistema dual de alerta temprana de inundaciones para Argentina, presentado al Project **Pukaar** (deadline lunes 18-may-2026).

**Componentes:**
- **Pukaar (nodo edge):** Raspberry Pi con cámara, corre Pukaar AI multimodal vía LiteRT-LM. Detecta agua/inundación en vivo.
- **Pukaar (app Android):** corre Pukaar AI con LiteRT-LM Android (mismo `.litertlm` que el backend). Permite a un ciudadano reportar en español rioplatense (offline). Sincroniza al volver red.
- **Backend FastAPI:** fusiona señales nodo + ciudadano, emite alerta CAP v1.2 a Defensa Civil, dispara sirena/LoRa.

**Objetivo de la demo (video 3 min):** mostrar al jurado que el sistema funciona end-to-end, con foco en por qué Pukaar AI + edge + español local resuelve el problema mejor que las alternativas (Flood Hub, PetaBencana, etc.).

---

## 2. Qué es el talking-head

Tomas a cámara, frontales, de una persona presentando. Aparecen en apertura (~15 s) y cierre (~15 s) del video. Cosen la narrativa: dan cara humana al proyecto y enmarcan el problema antes de que arranquen los actos técnicos.

**No hace falta filmar locuciones intermedias** — la narración técnica entre bloques ya está grabada en `docs/Project/video/narration.wav`.

---

## 3. Guion

**Fuente primaria:** `docs/Project/video/narration.md`. Abrir ese archivo, identificar los bloques marcados como **apertura** y **cierre** (o equivalente: bloques 01 y 08 del EDL).

Si el guion no tiene texto explícito de talking-head, usar este draft (~80 palabras cada uno, ~15 s a 5 palabras/segundo):

### Apertura (B01)
> "En Argentina, las inundaciones urbanas matan personas todos los años. La alerta oficial llega tarde porque depende de modelos satelitales y reportes manuales. Nosotros construimos Pukaar más Pukaar: un nodo en la calle que ve el agua subir, y una app que escucha al vecino que lo reporta en castellano. Los dos corren Pukaar AI on-device. Sin nube. Sin esperar. Esto es lo que detecta en tiempo real."

### Cierre (B08)
> "Pukaar más Pukaar no reemplaza al SMN ni a Defensa Civil — los alimenta. Detección local, idioma local, latencia local. Pukaar AI hace que esto entre en una Raspberry Pi de cien dólares y en cualquier Android. Repositorio abierto, documentación en español, listo para conveniar con Defensa Civil municipal. Gracias."

Ajustar palabras al estilo de quien filma. Mantener duración 12-18 s por bloque.

---

## 4. Setup técnico

### Cámara
- Celular moderno (cualquiera 2022+). Trípode o pila de libros. **Horizontal 1080p mínimo**, 4K si el cel banca.
- Lente trasera (no la frontal selfie — peor sensor).
- Bloquear exposición y enfoque tocando la cara en pantalla 2 segundos antes de grabar.

### Audio (más importante que la imagen)
- **Lavalier USB-C** o **auriculares con micrófono** (los del cel sirven). NUNCA el micrófono interno del celular a 1 metro: queda ecoso.
- Grabar audio de referencia 5 segundos de silencio antes de cada toma (para denoising en post).

### Luz
- Luz natural de ventana **lateral** (45°), nunca de frente ni de espalda.
- Si es de noche: lámpara con difusor (sábana blanca) lateral. Sin luces mixtas (cálida + fría) — eligen una temperatura.

### Fondo
- Pared lisa, librería, planta. **Sin escritorio caótico, sin logos de empresa ni marcas, sin ventanas con sol directo.**
- Distancia persona-pared: mínimo 1 metro (evita sombra dura atrás).

### Encuadre
- Plano medio corto: del pecho hacia arriba. Ojos a 1/3 superior de la pantalla.
- Mirá al lente, NO a la pantalla del cel.

---

## 5. Protocolo de filmación

Por cada bloque (apertura y cierre):

1. Grabá 5 s de silencio (referencia audio).
2. Tomá 3 versiones completas seguidas. Pausá 2 s entre cada una (corte limpio en edición).
3. Una toma extra "de seguridad" más lenta.
4. Mirá las tomas en el cel antes de guardar. Si hay foco mal, audio cortado o ruido raro: regrabar.

**Total esperado:** 15-20 minutos de filmación para 30 segundos de material usable.

---

## 6. Qué NO hacer

- No usar filtros del celular.
- No grabar con auto-HDR si el fondo tiene ventana (clipping).
- No leer el guion mirando una pantalla fuera de cuadro — se nota. Memorizar bloque por bloque.
- No filmar con notificaciones activas (modo avión obligatorio).
- No vestir camisetas con logos, rayas finas (moire) o blanco puro.

---

## 7. Entrega

Subir los archivos crudos a `docs/Project/video/raw/talking_head/` con nombres:

```
talking_head_B01_take1.mp4
talking_head_B01_take2.mp4
talking_head_B01_take3.mp4
talking_head_B08_take1.mp4
...
```

NO editar. NO cortar. El ensamblado final se hace después con el resto del material (hyperframes, UI scenes, narration.wav, screencast B05, clip P4).

---

## 8. Tiempo estimado

- Preparación setup: 30 min
- Filmación: 30 min
- Total: **~1 hora**

Se puede hacer hoy. No depende de ningún otro componente del proyecto.
