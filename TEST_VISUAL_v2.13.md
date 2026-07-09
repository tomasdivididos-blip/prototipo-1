# Test visual — Batch v2.13 (T4 · T6 · T9 · T8)

> Guion paso a paso para validar a ojo lo que no se puede ver headless.
> Marcá cada `[ ]` a medida que confirmás. Si algo no coincide con el
> "✅ Deberías ver", anotá qué pasó y avisá.

---

## 0. Arrancar la app

```
cd "C:\Users\aceve\OneDrive\Escritorio\prototipo 1"
C:\Users\aceve\anaconda3\python.exe main.py
```

- [ ] La ventana abre sin error, con 3 pestañas: **Geometría · Acústica · Predicción**.

### Sanity rápido SIN GUI (opcional, terminal)
Confirma que el cómputo está sano antes de clickear:
```
set PYTHONIOENCODING=utf-8
C:\Users\aceve\anaconda3\python.exe bench_sbir.py
C:\Users\aceve\anaconda3\python.exe bench_location_opt.py
C:\Users\aceve\anaconda3\python.exe bench_predict_location.py
```
- [ ] Los tres terminan en **TODOS OK**.

---

## 1. Preparar la base (necesaria para T6/T9)

1. Pestaña **Geometría**: dejá la sala default o armá una (ej. 6 × 4 × 3 m).
2. Pestaña **Acústica**:
   - [ ] Botón **Añadir** → aparece una fuente en la lista. (También: `Ctrl + click derecho` en el 3D la coloca donde apuntás.)
   - [ ] Botón **Materiales…** → asigná piso/techo/paredes (ej. preset piso/techo/paredes). Cerrá. El resumen muestra **RT60 medio** y **@500 Hz**.
   - [ ] Botón **Calcular modos (FEM)** → corre y la lista de modos se puebla.

---

## 2. T4 — Bafle orientado + dimensiones (render 3D)

> Lo único que faltaba confirmar de T4 era el render 3D del bafle.

1. En **Acústica**, seleccioná una fuente → **Editar**.
2. En el diálogo, buscá el grupo **"Bafle (visual)"**:
   - [ ] Hay control de **Orientación** (azimut, grados) y dims **An / Al / Pr**.
3. Cambiá la **orientación** (ej. 0°, 90°, 180°) y aceptá.

✅ **Deberías ver** en el visor 3D:
- [ ] La fuente dibujada como una **caja** (bafle), no un punto.
- [ ] Dos círculos (**woofer + tweeter**) en la **cara frontal**.
- [ ] La caja **apunta** según la orientación elegida (gira al cambiarla).
- [ ] Mover/arrastrar la fuente (Shift+drag) sigue funcionando (el picking no se rompió).

---

## 3. T6 — SBIR (interferencia fuente-frontera)

> Necesita ≥1 fuente + receptor (ya los tenés del paso 1). NO necesita modos.

1. En **Acústica**, ubicá el grupo **"FRF (Respuesta en frecuencia)"**.
2. Click en **"Ver SBIR (fuente-frontera)"**.

✅ **Deberías ver** un diálogo con:
- [ ] Eje X **logarítmico 20–500 Hz** con **grilla de 1/3 de octava** (look tipo REW).
- [ ] Una **curva por fuente** + (si hay 2+) una curva **Total**.
- [ ] Línea de **0 dB** punteada (referencia anecoica).
- [ ] Marcadores verticales naranjas en los **notch c/(4d)** por pared.
- [ ] Lectura **"Realce máx … / Atenuación máx …"** y la lista **"Notch por pared: … m → … Hz"**.
- [ ] Botones **Exportar PNG/SVG/PDF/CSV/TXT** funcionan.

**Prueba del efecto físico (opcional pero linda):**
1. Cerrá el SBIR, editá la fuente y ponéla **pegada a una pared** (flush) → "Ver SBIR".
2. Después alejála ~0.8 m de esa pared → "Ver SBIR".
- [ ] Pegada a la pared: el notch en banda baja **desaparece / se va a alta frecuencia**.
- [ ] A 0.8 m: aparece un **notch profundo** alrededor de ~107 Hz.

---

## 4. T9 — f_cross + Figuras de mérito (FoM)

### 4a. f_cross junto a f_Schroeder
1. En **Acústica**, con **modos ya calculados** (paso 1), buscá el grupo **"Campo acústico 3D"**.
2. Click en **"Calcular f_Schroeder"**.

✅ **Deberías ver**:
- [ ] La línea **`f_Schroeder ≈ … Hz`** (como siempre).
- [ ] Debajo, **`f_cross (M≥3, numérico) ≈ … Hz`** con un valor (o `> X Hz (no cruza en banda válida)` si la malla es gruesa — eso es correcto).
- [ ] Si cambiás materiales (Materiales…) y volvés, el f_cross se **recalcula** (cambia con el RT60).

> Tip: si querés que f_cross dé un número en vez de "> X Hz", subí el `n_per_meter` (malla más fina) — el techo de validez sube por encima del cruce.

### 4b. FoM en la FRF
1. En el grupo **FRF**, click en **"Calcular FRF"** (si no hay modos, los calcula solo).

✅ **Deberías ver** en el diálogo de FRF:
- [ ] La curva de FRF de siempre, con grilla 1/3 oct.
- [ ] **Debajo del gráfico**, una línea: **"FoM — planitud (FoM_flat): … dB · consistencia espacial (FoM_espacial): … dB (banda ≤ … Hz, N receptores)"**.
- [ ] Pasando el mouse por esa línea, un tooltip explica qué es cada FoM.

---

## 5. T8 — Optimizador de ubicación de fuentes (Predicción)

> El track grande. Tres modos. Está en la pestaña **Predicción**.

### 5a. Modo y pesos
1. Pestaña **Predicción** → grupo **"5. Modo de predicción"**.
- [ ] El combo **Optimizar** tiene: **Geometría · Ubicación de fuentes · Combinado**.
2. Elegí **"Ubicación de fuentes"**.
- [ ] Aparece el grupo **"Pesos del objetivo de ubicación"** con 4 sliders: **Planitud · Espacial · SBIR · Suavidad modal**.
- [ ] Cambiá el **Uso** (grupo 1) a uno de música y a uno de voz → los **pesos default se ajustan** (música prioriza Espacial; voz prioriza Planitud).
3. Volvé a **"Geometría"** → el grupo de pesos **se oculta**.

### 5b. Predicción de UBICACIÓN (recinto fijo = tu diseño de Geometría)
1. Modo **"Ubicación de fuentes"**. Click **"Predecir"**.

✅ **Deberías ver** (tras unos segundos de FEM):
- [ ] Hasta **3 cards** tipo **"Ubicación"** con score /100.
- [ ] Cada card muestra: **FUENTES** (ej. "2 fuentes · estéreo · delay 2.0 ms"), **Posiciones**, **RESPUESTA** (planitud/espacial), **SBIR**, y chips **Planitud/Espacial/SBIR/Suavidad**.
- [ ] Las 3 son **estrategias distintas** (no la misma repetida): p.ej. esquina / estéreo / flush / subs.

2. En la mejor card, **"Aplicar ▾" → "Colocar fuentes en Acústica"**.
- [ ] Salta a la pestaña **Acústica** y las **fuentes recomendadas aparecen** en la lista + en el 3D, en las posiciones sugeridas.
- [ ] Podés **"Calcular modos"** y verlas funcionar (FRF/SBIR) con esa ubicación.

### 5c. Modo COMBINADO (geometría + ubicación)
1. Volvé a **Predicción**, modo **"Combinado"**, **"Predecir"**.

✅ **Deberías ver**:
- [ ] 3 cards que muestran **el recinto** (dims + V + "geometría XX/100") **y** el layout de fuentes.
- [ ] En "Aplicar ▾" hay **dos opciones**: "Colocar fuentes en Acústica" y **"Aplicar geometría (parámetros)"**.
- [ ] Flujo correcto: primero **aplicar geometría**, después **colocar fuentes** (el layout fue optimizado para ese recinto).

### 5d. Modo GEOMETRÍA (regresión: que NO se rompió lo viejo)
1. Modo **"Geometría"**, **"Predecir"**.
- [ ] Siguen apareciendo las cards de geometría de siempre (Modal/Voz/Música/Práctico/Robustez) con "Aplicar ▾ → Como parámetros / Como CAD".

---

## 6. Extra (ya testeados headless, confirmación opcional)

- **T5 (offset de fase):** Acústica → Editar fuente → grupo "Respuesta en frecuencia Q(f)" → campo **Fase (°)**. Poné 180° y aplicá; equivale a invertir polaridad (no cambia |H|, rota la fase).
- **T7 (geometría lofteada):** Geometría → dibujar planta → **"Cortes laterales…"** → asistente de perfil por pared. (Standalone para probar el wizard solo: `python section_dialog.py`.)

---

## Resumen de qué reportar
Si todo da ✅, avisá y lo cerramos + integramos al MANUAL. Si algo falla, decime:
**qué paso**, **qué viste vs qué esperabas**, y si hay un error, el texto del **log** (panel de estado abajo) o de la consola.
