# Plan — Mejoras v2.13 (geometría, predicción, fuentes, SBIR)

> **Estado:** ✅ **BATCH CERRADO (26 Jun 2026)** — test visual humano OK, MANUAL integrado.
> Único pendiente: **T2** (auditoría RT60, diferido por el usuario, espera caso testigo).
>
> ## 📍 ESTADO ACTUAL DEL BATCH (actualizar al avanzar)
> - ✅ **CERRADO (26 Jun 2026) — test visual humano confirmado por el usuario:**
>   T6 (SBIRDialog) · T9 (FoM + f_cross en la FRF) · C13/C21 (overlay EQ rojo/amarillo) ·
>   T4 (snap = botón "Pegar a pared más cercana") · A6/A3 (chips FSI+Bonello + lectura ψ
>   en la sección MODAL de la card de Predicción) · T8 (selector geometry/location/combined +
>   sliders de pesos + `LocationCard` + botón aplicar fuentes → Acústica). MANUAL v2.13 ya
>   integrado. Fix de color: labels de diagnóstico de la FRF (`fom_lbl`/`eq_lbl`) → blanco
>   `#ffffff` (estaban gris/rojo oscuro, ilegibles sobre fondo Catppuccin). **Solo queda T2**
>   (diferido). Trabajo NUEVO fuera del batch (pendiente de decisión del usuario): gate de
>   materiales + preset placeholder {piso madera / paredes ladrillo / techo madera}, y
>   undo/redo global ctrl+z/ctrl+y (10 acciones).
> - ✅ **Hechos:** T7 (geometría lofteada, wizard probado OK), T1 (Cox+relabel),
>   T3 (altura por uso), T5 (offset de fase), **T4 (bafle orientado — render 3D
>   CONFIRMADO por el usuario + extensiones fuera de plan: ver §T4b)**, T6 (SBIR
>   analítico — núcleo + bench con 6 oráculos OK, UI verificada headless; falta
>   test visual humano), T9 (wiring 2c: f_cross junto a f_Schroeder + FoM en la
>   FRF; verificado headless; parte opcional —alimentar Predicción— diferida a T8).
> - ✅ **T8 COMPLETO (A+B+C, 18 Jun 2026)** — optimizador de ubicación de fuentes:
>   A=`location_opt.py` (6 oráculos OK); B=`predict_axis` con 3 modos en `prediction.py`
>   (4 tests OK); C=UI en `prediction_panel.py` (selector de modo + sliders de pesos +
>   `LocationCard` + aplicar fuentes a Acústica via señal `applySourcesRequested` →
>   `main._on_prediction_apply_sources`). Verificado headless; **falta test visual humano**.
> - ⏳ **Pendiente:** T2 (auditoría RT60 — auditada headless: los 3 displays de Acústica
>   coinciden con Sabine de libro a precisión de máquina; el "mismatch" es esperado
>   —Sabine/Eyring o Acústica/Predicción α-uniforme—; el usuario decidió SALTEARLO,
>   falta su caso testigo para pinpointear cuál y cerrarlo).
> - **Estado del batch:** hechos T1/T3/T4/T5/T6/T7/T8/T9 + extensiones de bafle (§T4b).
>   Solo queda T2 (diferido por el usuario). Pendiente transversal: **test visual humano**
>   de T6/T9/T8 (T4 ya confirmado) + integrar el batch al MANUAL (.md/.tex/.pdf) al cerrar.
> - **Modo de trabajo:** un track por vez, con bench/oráculo headless por track;
>   docs (este archivo + `notas_para_claude.md` §13) se actualizan al cerrar cada uno.
> **Contexto:** las Fases 0–2c del feature de fuentes (`plan_fuentes_respuesta_frecuencia.md`)
> ya están hechas (Q(f), FRD, anclaje, `.room` v5, UI del diálogo, `modal_metrics.py`).
> Este plan agrega 8 ítems pedidos por el usuario. El `modal_metrics.py` (FoM §8 +
> cruce modal §9) es insumo directo del ítem 8.

---

## Decisiones cerradas (16 Jun 2026)

- **(7)** El bafle **tiene orientación**: el frente es la cara con los dos círculos
  (parlantes). → la fuente necesita un campo de orientación.
- **(2)** Hay un **mismatch real** de RT60: el usuario vio valores distintos al
  simular y al hacer las curvas. → auditoría con caso testigo (pedir repro).
- **(5.1/5.2)** **NO se suma el Q por contorno.** El efecto "fuente en esquina"
  ya está en `φₙ(xₛ)` del modelo modal; un factor explícito sería doble conteo.
- **(6)** SBIR con las **6 superficies**. Visualización: a recomendar (abajo).
- **(3)** Altura default = **3 m**, por uso, editable. Sin cap duro de 4 m.
- **(4/4.1)** Geometría **lofteada**: seguir extruyendo la planta, pero además
  extruir **cortes laterales** (perfil vertical por cara, simetría con la opuesta;
  piso y techo se asumen iguales). NO son escalones reales en el piso.
- **(8/8.1)** El optimizador de ubicación es **un eje de predicción separado** del
  de geometría. Corren por separado o combinados (a elección del usuario) → 3
  predicciones finales. La función objetivo **contempla todas** las métricas
  (FoM_flat, FoM_espacial, SBIR, suavidad modal) y **todos** los métodos de
  búsqueda (heurístico + grilla/local).

---

## T1 · Ítem 1 — Ratios: agregar Cox + corregir etiquetas  ✅ HECHO (16 Jun 2026)

> Aplicado en `prediction.py`: `RATIO_LIBRARY` corregido (Louden/Bolt/Sepmeyer)
> + Cox (1:1.56:1.86); `generate_candidates` evalúa los 4 y `predict()` recorta
> a top-3 por score (+ control negativo). Verificado end-to-end.

**Objetivo.** Sumar el ratio **Cox & D'Antonio (1 : 1.56 : 1.86)** y corregir los
nombres cruzados de `RATIO_LIBRARY` en `prediction.py`.

**Enfoque.** Re-etiquetar según la literatura:
- "Bolt" (1:1.4:1.9) → **Louden**
- "Bonello" (1:1.26:1.59) → **Bolt**
- "Louden" (1:1.6:2.33) → **Sepmeyer**
- **+ Cox (1:1.56:1.86)** nuevo.
La generación de candidatos itera **toda** la librería y muestra los **3 mejores
por score** (se conecta con el ítem 8: "3 predicciones finales").

**Archivos.** `prediction.py` (`RATIO_LIBRARY`, `generate_candidates`).
**Éxito.** Cada ratio con su nombre real + Cox presente; las dimensiones generadas
coinciden con `s·ratio`. Smoke en `prediction.__main__` o bench.
**Riesgo.** Bajo. Las predicciones no se persisten con el nombre del ratio.
**Costo.** ~1 h.

---

## T2 · Ítem 2 — Auditoría de consistencia de RT60

**Objetivo.** Que el RT60 sea **el mismo en todas las instancias** donde el usuario
lo puede calcular.

**Sitios que computan RT60 (a enumerar/verificar):**
- `face_materials.py` — Sabine/Eyring por banda (lo que ve el `RT60PlotDialog`).
- `acoustic_panel` — derivación `ξₙ = 1.1/(fₙ·RT60(fₙ))` para la FRF/damping.
- `prediction.py` — FEM-lite con `alpha_default` y `_score_rt60_feasibility`
  (invierte Sabine).
- `fem_modal.py` / `acoustic_analysis.py` — si tienen su propia copia.

**Enfoque.**
1. **Reproducir el mismatch** con el caso testigo del usuario (PEDIR: qué sala,
   qué materiales, qué dos números no cuadraron).
2. Mapear cada path: ¿usan la misma `RT60(f)`, el mismo α(f), las mismas áreas S,
   el mismo V? La sospecha fuerte: Predicción usa α uniforme de referencia y la
   pestaña Acústica usa α por cara → **distinto input, distinto RT60** (esperable).
   El bug sería **mismo input → distinto RT60**.
3. Definir **una función canónica** y hacer que todos la llamen.

**Archivos.** los listados; un `bench_rt60_consistency.py` que corre la misma sala
por todos los paths y tabula.
**Éxito.** Mismo (V, materiales) → RT60(f) idéntico (float) en las 3 instancias;
documentado cuál es la función canónica.
**Riesgo.** Bajo, pero depende del repro para no "arreglar" lo que es input distinto.
**Costo.** ~2–3 h (mayormente investigación).

---

## T3 · Ítem 3 — Altura por uso (sin cap de 4 m)  ✅ HECHO (16 Jun 2026)

> `USE_PRESETS` tiene `h_default` por uso (HT/aula/estudio=3 m; conferencias 3.2,
> live 3.5, polivalente 5, cámara 6, sinfónica 12 — los últimos PROPUESTOS,
> ajustables). `generate_candidates` usa el default del uso como techo efectivo
> (sin el cap duro de 4 m); el usuario lo edita con "Override altura"
> (`prediction_panel._on_use_changed` lo pre-carga). Verificado: sinfónica >4 m,
> HT ≤3 m, override del usuario manda.

**Objetivo.** Sacar el límite duro de 4 m. La altura default sale del **uso** (3 m),
y el usuario la puede cambiar.

**Enfoque.**
- Agregar `h_default` por preset de uso (3 m en home theater / aula / estudio;
  mayor en sinfónica / cámara / polivalente).
- El `h_max` constraint pasa a ser **editable** con default = `h_default` del uso;
  el usuario puede subirlo. Quitar el cap fijo de 4 m de `generate_candidates`/scoring.

**Archivos.** `prediction.py` (presets, generación, constraints), `prediction_panel.py`
(UI del campo altura).
**Éxito.** Predicción de sinfónica no se topa en 4 m; home theater arranca en 3 m
pero el usuario lo sube; el valor es visible y editable.
**Riesgo.** Bajo. Revisar que el sub-score "Fit"/"Aspect" no asuma el cap viejo.
**Costo.** ~2 h.
**PEDIR:** alturas default del resto de los usos (sinfónica, cámara, control, etc.).

---

## T4 · Ítem 7 — Bafle orientado + dimensiones (prerequisito de T8)  ✅ HECHO (16 Jun 2026)

> `OmniSource.orientation` (azimut, None→90°) + `baffle_size` (w,h,d); `SourceMarkers`
> dibuja bafles orientados (caja + woofer/tweeter) como `GLMeshItem` (picking por
> proyección, intacto); `SourceEditDialog` con orientación + dims; `.room` v6
> serializa. Testeado datos/UI/geom; **falta confirmar el render 3D visualmente**.
> Posible refinamiento: orientación default apuntando al centro de la sala.

**Objetivo.** Dibujar la fuente como un **bafle** (caja más alta que ancha, más
profunda que ancha) con tweeter + woofer en el frente, **orientado**.

**Enfoque.**
- `OmniSource`: agregar `orientation` (yaw [°], opcional pitch) y `baffle_size`
  (w, h, d) — acústicamente sigue omni (5.1 descartado); orientación y dims son
  visuales **y** insumo de T8 (constraint distancia-pared).
- `acoustic_viewer.SourceMarkers`: dibujar la caja con los 2 círculos en la cara
  frontal; rotar por `orientation`. Default: frente hacia el centro del recinto.
- `.room`: serializar `orientation` + `baffle_size` (extiende v5 → v6).
- `SourceEditDialog`: control de orientación (dial/spinbox) + dims del bafle.

**Archivos.** `sources.py`, `acoustic_viewer.py`, `acoustic_panel.py`, `main.py`.
**Éxito.** La caja renderiza con el frente apuntando según `orientation`; gira en vivo.
**Riesgo.** Bajo (estético), salvo la integración con el `.room` (versión).
**Costo.** ~3–4 h.
**PEDIR:** dimensiones default del bafle (ej. 0.25 × 0.40 × 0.35 m).

---

## T4b · Bafle — extensiones FUERA DE PLAN (18 Jun 2026, durante el test visual)

> Surgió todo al confirmar el render 3D de T4 con el usuario. El principio se
> mantiene: orientación/pitch/montaje son **puramente geométricos** (dibujo +
> insumo de T8); **NO tocan FEM/FRF/SBIR para una posición dada** (el monopolo es
> omni, ignora el ángulo) — verificado headless (|p| idéntico con/sin ángulo). El
> SBIR sí cambia al **montar**, pero por la POSICIÓN (acerca a la pared), no por el ángulo.

**1) FIX render del bafle (lo que faltaba de T4).** El render de T4 (`GLMeshItem`
con `shader=None` + `faceColors`) **no se dibujaba** en este OpenGL. Reescrito como
**wireframe rosa** (prisma de 12 aristas + 2 círculos woofer/tweeter en la cara
frontal), mismo patrón que las aristas del recinto (`GLLinePlotItem`, pos float32,
color único = `EDGE_COLOR (0.96,0.74,0.95)`). **CONFIRMADO a ojo por el usuario.**
GOTCHA: en este proyecto NO usar `GLMeshItem(shader=None, faceColors=...)`.

**2) Inclinación (pitch) + montaje en pared.** `OmniSource`: `pitch` (−90..90,
0=horizontal) + `mounted` (bool, one-shot informativa). `_baffle_wireframe` aplica
yaw+pitch (base local sin roll). `SourceEditDialog`: spinbox "Inclinación" + botón
**"Pegar a pared más cercana"** (`get_walls` callback ← face groups): mueve flush
(d_bafle/2), orienta el frente al interior (normal hacia el centro, robusto al
winding), `mounted=True`. `.room` guarda/carga `pitch`+`mounted` (con `.get()`, sin
bump de versión). Decisiones del usuario: mounted one-shot (no re-snap); aplicar al OK.

**3) Gestos directos en el 3D (trackball del bafle).** **Alt+Ctrl + click izq. +
arrastrar** sobre el bafle: **horizontal = girar (azimut), vertical = inclinar
(pitch)**, a la vez. Señales `sourceRotateRequested`/`sourceTiltRequested` →
`main` muta orientation/pitch in-place. Sensibilidad `BAFFLE_ROTATE_DEG_PER_PX=0.6` /
`BAFFLE_TILT_DEG_PER_PX=0.5`. No pisa Shift+drag (mover) ni Ctrl+Right (agregar).

**4) Dos fixes encontrados en el camino:**
- `SourceMarkers` actualiza los items GL **in-place vía `setData`** (no remove/add
  por frame) — reconstruir el scene graph en cada frame del drag colgaba el event
  loop (mismo gotcha que ReceiverMarker ya documentaba).
- `_on_source_moved_from_viewer` (Shift+drag mover) **reconstruía** la fuente y
  perdía orientación/pitch/bafle/respuesta/sensibilidad/mounted; ahora muta SOLO
  `position` in-place → preserva todo.

**Falsa alarma "crashea al inclinar":** era **pérdida de foco por Shift+Alt** (atajo
de Windows para cambiar idioma), no un crash (volvía con Alt+Tab, sin traceback). Por
eso el gesto final es **Alt+Ctrl sin Shift**. GOTCHA: evitar Shift+Alt en gestos.

**Archivos.** `sources.py`, `acoustic_viewer.py`, `acoustic_panel.py`, `viewer.py`,
`main.py`. Todo verificado headless (compila/importa; pitch inclina; acústica
invariante; snap a pared; gesto único azimut+pitch; marcador in-place sin rebuild).
**Pendiente:** test visual humano de los gestos + el snap (el render ya lo confirmó
el usuario).

---

## T5 · Ítem 5 — Fase: offset constante (menor)  ✅ HECHO (16 Jun 2026)

> Agregado spinbox "Fase (°)" (−180..180) al atajo manual de `SourceEditDialog`;
> `_apply_manual` combina `g = e^{i(φ₀ + π·inv)}·e^{-i2πfτ}`. Verificado headless.

**Objetivo.** Control de fase de la fuente. **Ya cubierto en gran parte** por la
Fase 2 (delay = fase lineal, polaridad = π). Falta sólo un **offset de fase
constante** `φ₀` si se quiere (`g = e^{iφ₀}`).

**Enfoque.** Sumar un campo `φ₀ [°]` al atajo manual del `SourceEditDialog`,
combinándolo con delay/polaridad: `g(f) = e^{i(φ₀ + π·inv) } · e^{-i2πfτ}`.
**Archivos.** `acoustic_panel.SourceEditDialog._apply_manual`.
**Éxito.** φ₀=180° equivale a polaridad invertida; rota la fase sin tocar |H|.
**Riesgo.** Trivial. **Costo.** ~0.5 h.

---

## T6 · Ítem 6 — Criterio SBIR (Speaker-Boundary Interference Response)  ✅ HECHO (18 Jun 2026)

> Nuevo `sbir.py` (cómputo puro, solo numpy): fuentes imagen de **1er orden** por
> cada superficie (plano = `centroid`+`normal` del `FaceGroup`), atenuadas por
> `R(f)=√(1−α(f))` del material de esa cara; monopolo idéntico a
> `sources.free_field_pressure` (misma convención `e^{+ikr}`). Salida = **dB
> relativo al directo**: `20·log₁₀(|p_dir+Σreflejadas|/|p_dir|)` por fuente + la
> **suma** (con 2 fuentes ≡ L, R, L+R). `SBIRResult` da `band_extremes`
> (realce/atenuación máx) y `first_notches` (c/(4d) por par fuente-pared).
> `bench_sbir.py`: 6 oráculos analíticos, **todos OK** (notch en c/(4d) ±3% y
> −40 dB con R=1; flush-mount d→0 → sin notch, +6 dB; boundary lift = 20log₁₀(1+R);
> absorbente → notch menos profundo; shoebox → 6 notches; suma estéreo = suma
> compleja). `SBIRDialog` + botón "Ver SBIR" en el grupo FRF (espejo del
> `FRFDialog`: grilla 1/3 oct, eje log 20–500, curvas por fuente + total,
> marcadores de notch, export PNG/SVG/PDF/CSV/TXT). `_open_sbir` arma las paredes
> desde `_get_face_groups` + `_group_to_material_dict` y usa `self.receiver`.
> Verificado headless (panel importa, camino real shoebox→notches correctos,
> diálogo con figura). **Falta test visual humano** en la GUI real.
> **Decisión:** solo 1er orden (estándar SBIR); `order` queda como parámetro,
> 2do orden anotado como extensión no implementada.

**Objetivo.** El peine de interferencia entre el sonido directo y las reflexiones
en las paredes cercanas a la fuente, en el punto de escucha, para el par estéreo.

**Enfoque (info NUEVA, complementaria al FEM).** Fuentes imagen de las **6
superficies** (1er orden) por altavoz:
- Imagen respecto a cada pared: posición espejo, atenuada por el coeficiente de
  reflexión `R = √(1 − α(f))` del material de esa cara (usa la librería de
  materiales → más realista que R=1).
- Presión en el receptor: `p(f) = Σ_fuentes Σ_imágenes (e^{-ikr}/r)` (campo libre,
  directo + reflejadas). Par estéreo = suma de L + R con sus imágenes.
- Notch teórico de control: primer nulo en `f ≈ c/(4d)` por cada pared (d =
  distancia fuente-pared).

**Visualización recomendada** (a tu OK):
- Diálogo tipo FRF: eje x log 20–500 Hz con la **grilla 1/3 octava** (`plot_utils`),
  curvas **L**, **R** y **L+R (estéreo)** en dB relativo.
- Marcadores en el primer notch por pared + readout de las 6 distancias fuente-pared.
- Lectura de "máximos realces / máximas atenuaciones" (pico y valle del comb en banda).

**Archivos.** `sbir.py` (nuevo, analítico), diálogo en `acoustic_panel.py`,
`bench_sbir.py`.
**Éxito.** Geometría conocida → primer notch en `c/(4d)` ± tolerancia; flush-mount
(d→0) → sin notch en banda. Bench con oráculo de 1 pared.
**Riesgo.** Medio-bajo. Definir si 1er orden alcanza (estándar SBIR) o sumar 2do.
**Costo.** ~1–2 días.

---

## T7 · Ítems 4 + 4.1 — Geometría lofteada (corte lateral) [track largo, paralelo]

**Objetivo.** Además de la planta, dibujar el **corte lateral** de cada cara
(perfil vertical), con simetría opcional con la cara opuesta. Piso y techo se
asumen iguales.

**Modelo geométrico propuesto.** El recinto = planta poligonal donde **cada pared
tiene un perfil vertical propio** (su borde superior puede variar) → superficie
lofteada. Mirror: el perfil de una pared se espeja en la opuesta. El techo conecta
los bordes superiores (reusa la maquinaria de triangulación de techos existente).

**Modelo confirmado (16 Jun 2026):** Modelo 1, techo que **sigue los topes**.

**Fases.**
- **A. Motor geométrico — ✅ HECHO (16 Jun 2026).** `geometry.make_lofted_room(base_polygon,
  wall_profiles)`: piso plano + perfil de tope por pared; piso y techo comparten el
  perímetro muestreado y el techo se triangula por el rim (ear-clipping, sin interpolar
  interior) → watertight y conforme. Perfil plano = shoebox exacto. Validado en
  `bench_lofted_room.py` (regresión, volumen rakeado, watertight con pico, mirror,
  chequeo de esquina). El "techo sobre rim no-plano" se resolvió sin la dificultad temida.
- **B. Integración + `.room` v6 — ✅ HECHO.** `geometry.build_room_geometry(params)`
  despacha lofteado vs prisma; `main.py` lo usa (2 puntos, path viejo intacto);
  `controls.get_params`/`set_params`/`set_wall_profiles` manejan `wall_profiles`;
  `FILE_VERSION=6` (perfiles viajan en `params`, JSON; v4/v5 → prisma, compat).
  Testeado headless (dispatcher, fallback, serialización).
- **C. UI wizard — ✅ HECHO (falta test visual humano).** `section_dialog.py`:
  `ProfileCanvas` (dibujo de elevación) + `SectionWizard` (perfil por pared en
  orden, altura de esquina arrastrada, "simétrica a la opuesta" para n par).
  Enganchado al `ShapeDrawDialog` ("Cortes laterales…") → `main` → `controls`.
  Lógica testeada headless (gable por simetría → V=68.18 m³, malla OK). Standalone
  para test visual: `python section_dialog.py`. **Limitaciones MVP:** re-abrir
  no pre-carga perfiles previos; simetría solo n par; lid del techo por rim
  (watertight, algo grueso).
- **D. Mallado — ✅ verificado.** El voxel malla los lofteados sin problema
  (benches A y C). gmsh caería por T-junctions → fallback voxel (ya cubierto).

**Archivos.** `geometry.py`, `shape_dialog.py`, `main.py` (`.room` v6), verificar
`acoustic_mesh.py`.
**Éxito.** Dibujar planta + perfil de pared inclinado/variable → 3D correcto → FEM
mallable → modos. Mirror simétrico funciona. Bench de volumen/watertight.
**Riesgo.** **ALTO** (es el más grande). Punto delicado: triangulación del techo
sobre un rim superior arbitrario, y mantener watertight para el raycast del voxel.
**Costo.** ~1–2 semanas. **Track independiente** (no bloquea a los demás).
**PEDIR/confirmar:** semántica exacta de "piso y techo se asumen iguales"
(¿planta plana arriba y abajo, y solo varían las paredes? ¿o el techo copia el
perfil del piso?).

---

## T8 · Ítems 8 + 8.1 — Optimizador de ubicación de fuentes [depende de T4, T6, 2c]

> **Decisiones del usuario (18 Jun 2026):** (1) pesos del objetivo combinado =
> **por uso + ajustables** (no fijo, no 100% sin default); (2) espacio de búsqueda
> **COMPLETO** (ítem 8.1 entero: posiciones + delays/polaridad + nº de fuentes +
> montaje flush + dims de bafle).
>
> **Fase A — núcleo de cómputo ✅ HECHA (18 Jun 2026).** `location_opt.py` (puro,
> reusa `modal_metrics` + `sbir` + `sources`):
> - `SourceLayout` (parametrización completa: positions, delays_s, inverted, mounted,
>   baffle) → `to_source_array` (delay/polaridad → `SourceResponse`).
> - `LocationContext.from_modal(modal_result, walls, use, …)`: precomputa grilla de
>   receptores, punto de escucha, banda válida y suavidad modal (room-fija).
> - `evaluate_layout`: FoM (`modal_metrics`, banda válida) + SBIR (`sbir`, banda de
>   **graves 20–200 Hz** — donde la regla soffit empuja el notch fuera de banda) +
>   suavidad modal → sub-scores 0–100 → score combinado con pesos.
> - `default_location_weights(use)`: perfiles por uso (música prioriza espacial,
>   voz prioriza planitud), ajustables.
> - Búsqueda: `seed_layouts` (mono/estéreo/estéreo-ancho/subs-¼/esquina/flush) →
>   `optimize_layout` refina las top-K semillas (perturbación de posición + barrido
>   de delay + polaridad) → top-N con **diversidad por familia de semilla**.
> - `bench_location_opt.py`: **6 oráculos OK** — optimizado>baseline aleatorio;
>   flush→notch fuera de banda (mejor SBIR); esquina→media más plana (excita todos
>   los modos); el delay relativo cambia el objetivo; los pesos dirigen la elección;
>   top-3 = estrategias distintas. **Hallazgo:** `make_room` centra el recinto en el
>   origen (x∈[−L/2,L/2]); las paredes para SBIR se construyen desde los face groups
>   (centroide+normal en el frame real), como el panel.
>
> **Fase B — integración en Predicción ✅ HECHA (18 Jun 2026).** En `prediction.py`:
> - `LocationPrediction` (recinto + `SourceLayout` + score + FoM/SBIR + mensajes
>   legibles: layout_msg/fom_msg/sbir_msg/positions_msg).
> - `predict_locations(inputs, cand, weights, …)`: FEM **completo** del recinto fijo
>   (con `locator`, no el FEM-lite que lo descarta) → paredes desde face groups con
>   R uniforme de referencia (α=0.10) → `LocationContext` → `optimize_layout` → top-N.
>   Damping desde `rt60_target` (ξₙ=1.1/(fₙ·RT60_target)).
> - `predict_combined(inputs, …)`: para las top-K geometrías, optimiza ubicación y
>   combina `0.5·geom + 0.5·ubicación` (peso calibrable `_COMBINED_W_GEOM`) → top-N.
> - `predict_axis(inputs, mode, fixed_candidate, weights)`: dispatcher de los 3 modos
>   (geometry→`Prediction`; location/combined→`LocationPrediction`).
> - `bench_predict_location.py`: **4 tests OK** (geometría = regresión; ubicación = 3
>   layouts ordenados, posiciones dentro del recinto, mensajes, reconstruye SourceArray;
>   combinado = geom_score + mezcla; pesos cambian el ranking).
>
> **Fase C — UI ✅ HECHA (18 Jun 2026).** En `prediction_panel.py`:
> - Grupo "5. Modo de predicción": combo **Geometría / Ubicación de fuentes /
>   Combinado** + grupo de **sliders de pesos** (Planitud/Espacial/SBIR/Suavidad),
>   visible solo en ubicación/combinado, default por uso (`_load_weight_defaults` ←
>   `location_opt.default_location_weights`), ajustables.
> - `LocationCard` (renderiza `LocationPrediction`: layout_msg, posiciones, FoM, SBIR,
>   chips de sub-scores; en combinado muestra geometría + geom_score). Botón "Aplicar ▾":
>   "Colocar fuentes en Acústica" (señal `applySourcesRequested(SourceArray)`) y, en
>   combinado, "Aplicar geometría (parámetros)" (reusa `applyAsParamsRequested`).
> - `_on_predict` despacha por modo a `predict_axis`; `_render_results` maneja
>   `Prediction` (CandidateCard) y `LocationPrediction` (LocationCard).
> - `main.py`: `applySourcesRequested` → `_on_prediction_apply_sources` (limpia y
>   coloca las fuentes en Acústica via `_refresh_sources_list`, va a la pestaña).
> - Verificado headless (panel instancia, toggle de pesos, `LocationCard` emite la
>   SourceArray, render mixto, todo compila). **Falta test visual humano.**
> - **Nota:** la parte opcional de T9 (alimentar `prediction._score_schroeder` con el
>   cruce numérico §9) quedó SIN hacer — el optimizador de ubicación usa el cruce vía
>   la suavidad modal, pero el scorer de GEOMETRÍA sigue con el Schroeder analítico.
>   Pendiente menor si se quiere.

**Objetivo.** Dentro de Predicción, sumar **dónde poner las fuentes** como un eje
separado del de geometría. Corren solos o combinados → 3 predicciones finales a
elección del usuario.

**Arquitectura.**
- **Scorer de geometría:** los 13 criterios actuales (+ Cox de T1, + altura de T3).
- **Scorer de ubicación (nuevo):** función objetivo = combinación **ponderada** de
  TODAS las métricas (a elección del usuario):
  - `FoM_flat` y `FoM_espacial` (de `modal_metrics.py`, ya hecho),
  - **SBIR** (de T6: minimizar realces/atenuaciones),
  - **suavidad modal** (densidad/Bolt-spacing del cruce §9).
- **Modos de salida:** geometría sola / ubicación sola / combinado → el usuario
  elige y se muestran 3 candidatos.

**Espacio de búsqueda (8.1).** número de fuentes, separación, fases/delays,
montadas-o-no en pared, dimensiones del bafle. **Constraint:** distancia
fuente-pared ≤ menor dimensión del bafle (regla flush/soffit → empuja el notch
SBIR fuera de banda; ata T6 + T4).

**Método (contempla todos).** Semillas heurísticas (estéreo simétrico, subs a ¼
del largo, esquina, flush-mount) → evaluar cada una con la métrica combinada →
**refinamiento local** (grilla chica alrededor de la mejor) → top-N. El FEM-lite
+ `modal_metrics` + `sbir` corren por candidato (paralelizable como hoy).

**Archivos.** `prediction.py` (+ nuevo scorer), `prediction_panel.py` (UI de modos
y selección), reusa `modal_metrics.py` y `sbir.py`.
**Éxito.** Para una sala conocida, recomienda ubicaciones con FoM/SBIR medibles
mejores que un baseline (esquinas random); las 3 salidas reflejan el modo elegido.
**Riesgo.** **ALTO** (es el más integrador). Depende de T4 (bafle/dims), T6 (SBIR)
y 2c (ya listo). Calibrar pesos y costo de cómputo (cada candidato corre FEM-lite).
**Costo.** ~1–2 semanas.

---

## T9 · Pendiente previo — Wiring de 2c a la UI  ✅ HECHO (18 Jun 2026)

> **f_cross junto a f_Schroeder:** label `lbl_fcross` en el grupo "Campo acústico
> 3D". Helper `_rt60_callable()` arma un `RT60(f)` log-interp de la Sabine por
> cara; `_update_modal_crossover()` llama `modal_metrics.modal_overlap_crossover`
> acotado a la banda válida (≤ `_validity_freq(h_max)`). Se refresca tras cada
> solve (en `_refresh_modes_combo`), al editar materiales (`_on_face_materials_applied`)
> y con el botón f_Schroeder. Maneja el caso "no cruza en banda válida" (muestra
> "> X Hz") — pasa con malla gruesa cuyo f_max_malla < f_cross.
> **FoM junto a la FRF:** en `_compute_frf`, tras la FRF, calcula la respuesta
> forzada sobre `default_receiver_grid` en la banda válida y muestra
> `FoM_flat`/`FoM_espacial` en el `FRFDialog` (param nuevo `fom`/`fom_band`, con
> tooltip). **Best-effort** (try/except): si falla, la FRF igual se muestra.
> Verificado headless (shoebox: FoM 4.37/5.28 dB, cruce computa, panel importa,
> `FRFDialog` con FoM construye). **Falta test visual humano.**
> **Diferido a T8:** la parte *opcional* de alimentar `prediction._score_schroeder`
> con el cruce numérico — se hace en el optimizador (T8), que ya consume estas
> métricas, para no tocar el flujo de Predicción ahora.

(Ya estaba pendiente.) Mostrar `f_cross` (cruce modal) junto al `f_Schroeder`, y las
FoM junto a la FRF; opcionalmente alimentar `prediction._score_schroeder` con el
cruce numérico. Es prerequisito natural de que el ítem 8 sea visible/usable.
**Costo.** ~0.5 día.

---

## Dependencias y secuencia sugerida

```
Rápidos / independientes:  T1(Cox) · T3(altura) · T5(fase) · T2(audit RT60)
Estético + base de fuentes: T4(bafle+dims)  ─────────────┐
Analítico:                  T6(SBIR) ────────────────────┤
Wiring previo:              T9(2c a UI) ─────────────────┤
                                                          ▼
                                            T8(optimizador de ubicación)
Track paralelo grande:      T7(geometría lofteada)  — independiente, en cualquier momento
```

**Orden propuesto:** T1 → T3 → T5 → T2 → T4 → T6 → T9 → **T8**; con **T7** como
track paralelo que arranca cuando quieras (no bloquea nada).

**Racional:** los 4 primeros son quick wins de bajo riesgo que dejan valor rápido;
T4+T6+T9 son los insumos del optimizador; T8 cierra el pedido grande de fuentes;
T7 es el único que no comparte dependencias y conviene tratarlo como proyecto aparte.

---

## Preguntas abiertas (para arrancar)

1. **T2:** caso testigo del mismatch de RT60 (sala + materiales + los dos números).
2. **T3:** alturas default del resto de los usos (no home theater/aula/estudio).
3. **T4:** dimensiones default del bafle (w × h × d).
4. **T7:** confirmar "piso y techo se asumen iguales" (¿planos arriba/abajo y solo
   varían paredes?).
5. **T8:** pesos default de la métrica combinada (¿priorizás planitud, consistencia
   espacial o SBIR?) — o lo dejamos 100% configurable sin default.

---

*Discusión: 16 Jun 2026. Pendiente de aprobación para arrancar (sugerencia: T1).*
