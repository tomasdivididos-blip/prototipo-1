# Notas para Claude — bootstrap de contexto

> Este documento es para vos, instancia futura de Claude que recién entra a
> esta sesión sin memoria del trabajo anterior. Su objetivo es darte el
> contexto **meta** (cómo está estructurado el proyecto, quién es el
> usuario, cómo trabajamos juntos, qué decisiones ya están tomadas y por
> qué) sin duplicar lo que ya está en los otros tres `.md`.
>
> Leelo entero, después leé los otros docs en el orden recomendado, después
> arrancá.

---

## 1. Orden de lectura recomendado

1. **Este archivo** (`notas_para_claude.md`) — el "manual de instrucciones"
   meta. ~10 min.
2. **`MANUAL.md`** — el manual de usuario del producto. Es maestro: tiene
   la arquitectura, las 19 secciones funcionales, y todos los changelogs
   (v2.0 a v2.10). Para entender qué hace la app y por qué, leé al menos
   las secciones 1 (Introducción), 7 (FEM), 14 (Conceptos físicos), el
   apéndice "FEM a mano vs FEniCS", y los changelogs **v2.7 a v2.10**
   (los más recientes y relevantes). El resto se puede leer "a demanda".
3. **`acoustic_mesh_explicado.md`** — explicador línea por línea del
   mallador volumétrico (voxelización Freudenthal + raycast Möller-Trumbore
   + filtro de slivers). Importante para entender por qué la malla es
   escalonada y cómo eso interactúa con paredes rígidas.
4. **`acoustic_fem_explicado.md`** — explicador línea por línea del solver
   modal. **El documento más denso**. Tiene secciones críticas:
   - §0 "Contexto — ¿por qué FEM a mano y no FEniCS?".
   - §3 ensamblaje vectorizado de K y M (con la caja "Cómo leer `nodes[tets]`").
   - §4 `solve_modes` con shift-invert.
   - §7 `FieldEvaluator` con la caja "¿Qué es un KDTree? — explicación desde cero".
5. **Docs de investigación + implementación (Jun 2026)** — ver §1b abajo:
   `criterios_room_geom_fuente.md`, `numerica_fem_validez.md`,
   `cobertura_criterios_en_soft.md`, `plan_integracion_criterios_T8.md`,
   `plan_gaps_criterios.md`.

Total: ~40 min de lectura para tener contexto completo.

---

## 1b. Trabajo reciente (Jun 2026) — criterios de diseño + scorer T8

Un ciclo grande de **investigación bibliográfica → auditoría de cobertura →
implementación de gaps**. Si entrás frío, leé estos docs en este orden:

**Investigación (referencias):**
- **`criterios_room_geom_fuente.md`** — lista CERRADA (v2, ~107 criterios) de criterios
  de diseño acústico geometría↔fuentes (§A geometría, §B fuentes, §C combinado, §D
  perceptual, **§E síntesis accionable para T8**). Minado de Everest, Newell,
  Cox&D'Antonio, BBC/Rose, Beranek&Mellow, Carrión, Howard&Angus, Meyer + decks de
  cátedra. Cada criterio: nombre · FoM/fórmula · umbral · fuente · mapeo a la app.
- **`numerica_fem_validez.md`** — respaldo de las decisiones numéricas del solver
  (ppw, pollution `C₂k³h²`, O(h²), estructura `(A−k²B−ikC)`, error geométrico). E1-E9.
  NO son criterios de diseño; justifican el solver. Minado de Langdon&Chandler-Wilde,
  Desmet, Gallistl&Peterseim, Zhu et al.
- `referencias/_indice.md` — triaje del corpus + **`referencias/_scrape.py`** (pdftotext,
  ~10× más barato que `Read` de PDF para minar capa de texto). **Gotchas:** `python` solo
  falla (alias MS Store) → usar `/c/Users/aceve/anaconda3/python.exe`; PDFs escaneados
  (BBC) no tienen capa de texto → `Read` páginas como imagen.

**Auditoría:**
- **`cobertura_criterios_en_soft.md`** — matriz exhaustiva criterio×código: qué está ✅,
  qué es 🟡 proxy, qué es ❌ gap in-scope, qué es ⊘ fuera de alcance (la app es predictor
  modal LF + optimizador de fuentes; sin respuesta impulsiva/ray-tracing → todo lo
  temporal/early-reflection/mid-high queda afuera por diseño).

**Implementación (gaps cerrados, con bench cada uno):**
- **`plan_integracion_criterios_T8.md`** — A33/A36/B27 (todos ✅).
- **`plan_gaps_criterios.md`** — A6/A3/C8/D5/C9 (todos ✅); **C13/C21 pendiente**.

| Gap | Qué se hizo | Archivo·función | Bench |
|---|---|---|---|
| A33 | Ratio BBC/Rindel 1:1.14:1.4 | `prediction.py` `RATIO_LIBRARY` | bench_predict |
| A36 | ξ per-modo pesado por presión de cara (amortiguamiento selectivo) | `face_materials.py` `compute_xi_per_mode_per_face` + cableo en `acoustic_panel.py` `_xi_per_mode_from_faces` | `bench_xi_perface.py` |
| B27 | Advisory poroso(λ/4)-vs-resonante(esquina) | `face_materials.py` `lf_modal_absorption_hints` + `acoustic_panel.py` `_emit_lf_absorption_hints` | inline |
| A6 | FSI ψ(25) de Rindel | `modal_metrics.py` `modal_fsi` | `bench_modal_metrics.py` |
| A3 | Bonello densidad no-decreciente | `prediction.py` `bonello_monotonic`/`bonello_score` | predict() |
| C8 | FoM_flat con asimetría pico/nulo | `modal_metrics.py` `response_figures_of_merit` (`FoM_flat_asym`) | `bench_modal_metrics.py` |
| D5 | Bass Ratio real (calidez) | `face_materials.py` `bass_ratio` + display panel | inline |
| C9 | Umbral perceptual de Fazenda (2 curvas) | `modal_metrics.py` `fazenda_modal_threshold(f, stimulus)` + `prediction.py` `_score_modal_q`/`_fazenda_stimulus_for` | `bench_modal_metrics.py` |

**Decisiones de diseño tomadas en este ciclo:**
- A36 reduce EXACTO a la Sabine global con material uniforme (no regresiona); captura el
  amortiguamiento *selectivo* (qué modos amortigua según DÓNDE está el tratamiento). El
  efecto "axial decae más que oblicuo con α uniforme" quedó DIFERIDO (necesita la integral
  de superficie absoluta, sensible a la malla escalonada).
- **C9 wiring resuelto (idea del usuario):** Fazenda tiene 2 curvas —"artificial" (peor caso,
  sin enmascaramiento) y "music" (escucha real). La curva la elige el **programa** de la sala
  (música/cine→music, voz→artificial), NO un toggle. Así `score_modal_q` se calibra por uso.
- **Métricas A6/A3/C8/D5 expuestas pero NO metidas en `score_total`** (solo C9, que CORRIGE
  un criterio ya scoreado). Wiring de las otras al score = decisión pendiente del usuario.
- **`Q>30` viejo era groseramente laxo** (decía 0 modos audibles a RT 0.3s); Fazenda lo
  corrige. El `Q>30` queda como `n_audible_modes` de referencia.

**Pendiente (única tarea abierta del ciclo):** **C13/C21** — diagnóstico de corregibilidad
EQ (fase mín/no-mín de la respuesta de sala; reusar `frd.minimum_phase`). Alto esfuerzo.
Detalle en `plan_gaps_criterios.md` Fase 3.

**Papers cargados por el usuario (en `referencias/`):** Fazenda et al. 2015 (umbral C9) y
Zhu et al. 2006 (validación FEM-opt + métrica SRD = posible refinamiento de FoM_flat, E9).

---

## 1c. Batch v2.16 (5 Jul 2026) — origen, multi-punto, TRF

Changelog completo en MANUAL.md "Cambios v2.16" (10 ejes A-J). Lo que hay que
saber para no romperlo ni re-derivarlo:

**Features y dónde viven:**
- **Origen (0,0,0) configurable** (`origin_mode`: auto/center/corner en params):
  `geometry.origin_offset`/`anchor_vertices`; re-anclaje en `build_room_geometry`;
  compensación de fuentes/receptor/puntos en `main._on_params` (solo si SOLO
  cambió origin_mode → traslación pura) y `main._reanchor_cad` (CAD; auto≡center).
  El loader de `.room` re-ancla el CAD embebido según el origin_mode GUARDADO
  (antes re-centraba incondicional y pisaba el frame → fuentes desubicadas).
  `bench_origin_mode.py` 18/18.
- **f_Schroeder desde materiales**: punto fijo `f_S=2000·sqrt(RT(f_S)/V)` con
  RT por bandas de `fm.compute_sabine_rt60_per_face`; α=0.05 solo fallback.
  OJO: el default del FaceMaterialMap es `_names[0]` = "Alfombra fina" (alfabético),
  NO α=0.03 como dice un label viejo. El auto-tuner de malla sigue con α=0.05
  (pendiente conocido; cambiarlo altera el costo del FEM silenciosamente).
- **Mute por fuente**: `OmniSource.active` + `SourceArray.active_only()`;
  el panel usa `_active_sources()` en TODOS los caminos de cómputo.
- **Puntos de escucha**: `AcousticPanel.listen_points` [{name, position}];
  persistidos; se trasladan con el origen; esferas via `viewer.set_listen_points`.
- **Comparar…**: `CompareDialog` + `_compute_compare_data`. Mapeo de métricas
  CONFIRMADO por el usuario: **VSA = FoM_flat** (σ_f del promedio espacial),
  **MSV = FoM_espacial** (media del σ entre posiciones). La tabla usa las
  posiciones REALES del usuario (el FoM del diálogo FRF usa una grilla interna
  fija → NO cambia con el receptor; el flujo manual viejo del usuario leía
  números que no discriminaban posición).
- **TRF binario** (`frd.load_trf`, magic `JACKREF!`): formato descifrado por
  ingeniería inversa (spec en el docstring); anclaje auto-Relativo al cargar
  (la TF es relativa, no SPL). Fixtures `Focal_L/R.trf` en la raíz; `bench_trf.py`.
- **Predicción ubicación irregular**: FEM sobre malla real (leyenda "· malla
  real") + `LocationContext.inside_fn`/`repair_layout` (semillas fuera de la
  sala se reparan por bisección, NO descartar-y-fallback: con el pentágono
  real del usuario TODAS caían fuera). `bench_predict_location.py` 18/18.
- **Heatmap 2D con marcadores**: `SliceHeatmapDialog(markers=...)`; fuentes
  activas ○, receptores ✕, nombre debajo, semi-transparente si a >0.5 m del plano.

**Reglas ganadas con sangre (extensión mental de §8):**
- NUNCA reconstruir un QListWidget desde su propio `itemChanged` (clear()
  destruye el item bajo el mouse → mouse-grab colgado → TODA la app deja de
  recibir clicks/drags). Actualizar el item in place con señales bloqueadas.
- NO usar `GLScatterPlotItem` PERSISTENTE en el viewer (point sprites +
  resize en Windows = freeze del driver). Los transitorios (nube de presión)
  están OK. Para markers permanentes: esferas `GLMeshItem` (patrón probado).
- `set_imported_geometry` RECENTRA el receptor incondicionalmente (es para
  imports frescos). Si re-anclás el CAD, trasladar objetos ANTES y restaurar
  el receptor DESPUÉS (ver `_reanchor_cad`).
- Diagnóstico de freezes: `PROTO1_WATCHDOG=1 python main.py` → stacks en
  consola si la GUI se cuelga >20 s (faulthandler + QTimer que re-arma).

---

## 1d. Batch v2.17 (14 Jul 2026) — parches de absorción sub-cara

Changelog completo en MANUAL.md "Cambios v2.17" (5 ejes A-E) + §10.5/§10.6.
Lo que hay que saber para no romperlo ni re-derivarlo:

**Modelo mental:** un parche = **región de absorción sub-cara**. NO es física
nueva: es darle resolución sub-cara al mecanismo A36. Las φₙ se calculan con
paredes rígidas → **un parche NO cambia la forma modal ni el heatmap**; su α
entra por el RT60 de Sabine (restando área al anfitrión) y por ξₙ pesado por
φₙ² sobre la región. Lo observable es ξₙ → RT → FRF.

**Decisión de cuadratura (importante):** sin parches, ξ se integra con A36 crudo
(centroides de la malla de render) → los `.room` sin parches **no cambian ni un
dígito**. Con ≥1 parche se conmuta a **cuadratura fina** (tesela la cara, α por
punto). La fina es MÁS precisa: la brecha vs A36 es ~25% medio en ξ (A36 sobre
malla gruesa usa 1 punto por triángulo — el piso de un shoebox son 2 puntos).
Reduce EXACTO a A36 con material uniforme. Criterio elegido por el usuario.

**Archivos:** `absorption_patch.py` (núcleo + geometría de polígonos),
`patch_dialog.py` (editor 2D), wiring en `acoustic_panel.py`, `.room` v8 en
`main.py`, `viewer.set_patches`/`set_highlight_patch`. Bench:
`bench_absorption_patch.py` (8/8).

### ⚠️ Gotcha de render (costó ~6 iteraciones — LEER ANTES DE TOCAR EL VISOR)

**Un `GLMeshItem` con `shader=None` + `faceColors` NO RENDERIZA en esta escena.**
Y **no es cuestión del modo de profundidad**: se probó `translucent`, `additive`
y `opaque`, los tres invisibles. Ya estaba documentado en el docstring de
`acoustic_viewer.SourceMarkers` (por eso migró a `GLLinePlotItem`) y no se leyó
a tiempo.

- **El único patrón probado que funciona** es el de `viewer.set_highlight_faces`:
  **color UNIFORME + `shader=None` + `glOptions='additive'`**.
- Por eso `set_patches` crea **un item por parche** con color uniforme (cada
  parche tiene un solo material → no hace falta `faceColors`).
- Si necesitás color por-cara en un mesh, NO uses `faceColors`: partilo en items
  de color uniforme, o usá `GLLinePlotItem`.

**Lección de método:** ante "no se ve en el 3D", **instrumentar desde el 2º
intento** (imprimir nº de items, bbox de los verts, excepciones) en vez de
razonar sobre el pipeline de render. Un `print` del bbox habría cerrado el tema
en un turno.

### Falsa alarma: "no se mueve/rota el parlante"

Se reportó como regresión. Se instrumentó la cadena completa
(`mousePress → _pick_source → mouseMove → sourceMoveRequested → handler`) y
**funciona entera**: la fuente recorría la sala y el bafle rotaba a nivel de
datos. Era percepción visual (el overlay ni siquiera renderizaba entonces).
**NO volver a perseguir esto.** El picking de fuentes usa proyección a pantalla
de `_source_positions`, es independiente de los items GL.

---

## 2. Perfil del usuario

- **Profesión**: ingeniero en acústica.
- **Lo que SABE bien**: la física del problema. Ecuación de Helmholtz, modos
  acústicos, RT60, fórmulas de Sabine/Eyring, frecuencia de Schroeder,
  conceptos de FEM a nivel teórico. Sabe leer fórmulas matemáticas y
  derivaciones.
- **Lo que NO sabe bien**: trucos de NumPy/SciPy, patrones idiomáticos de
  Python científico, álgebra lineal computacional, estructuras de datos
  (KDTree, sparse matrices, etc.). Vos sos su puente entre la matemática
  que conoce y el código que ejecuta esa matemática.
- **Idioma**: español rioplatense (Argentina). Escribilo así: "vos",
  "tenés", "hacé". Mezcla un poco con notación matemática y código
  inglés (los nombres de variables y funciones están en español
  fragmentario).
- **Bias importante**: prefiere **entender por qué** antes que aceptar
  recomendaciones. Si le decís "hacé X", va a preguntar "por qué X y no Y".
  Anticipá el "por qué" en tu primera respuesta.

---

## 3. Estilo de respuesta que funciona

Lo que el usuario te confirmó (explícita o implícitamente) que le sirve:

### ✅ Hacé esto

- **Explicaciones que van de lo concreto a lo abstracto**. Ejemplo concreto
  primero (5 nodos, 2 tets, números reales) → patrón general después.
- **Diagramas ASCII** cuando ayuden (cubo con esquinas numeradas, tabla de
  formas (shapes) de arrays, etc.).
- **Tablas comparativas** para trade-offs (P1 vs P2, naive vs KDTree, etc.).
- **Anotar la forma `(shape)` de cada array** en cada paso del código.
  Ej.: `coords = nodes[tets]  # (Ne, 4, 3)`.
- **Conectar el truco de NumPy con el paso del método FEM**. Sin esto, los
  `einsum` y broadcasting son cripto para él.
- **Cerrar con una pregunta concreta**: "¿Querés que te muestre A o B?",
  para que él pueda decidir el siguiente paso.
- **Markdown con secciones cortas**, encabezados claros, bullets de máx
  2-3 líneas. Nada de párrafos murallón.
- **Negritas para los conceptos clave**, no para énfasis emocional.
- **Cajas dedicadas para conceptos opacos**. Cuando inventaste algo nuevo
  (KDTree, `nodes[tets]`, einsum), ponelo en un bloque visualmente
  separado dentro del flujo principal — no como apéndice al final.

### ❌ No hagas esto

- Respuestas largas sin estructura. Si supera 200 líneas, partilo en
  secciones.
- Asumir que entiende qué hace una función de NumPy. Especialmente
  `einsum`, `broadcasting`, `fancy indexing`, `np.linalg.inv` en lote.
- Saltar al "hagamos esto" sin explicar el "por qué este enfoque y no otro".
- Sugerir librerías pesadas (FEniCS, PETSc, dolfinx) sin contexto.
  Decisión ya tomada: **sin dependencias pesadas**. Solo `numpy + scipy +
  matplotlib + PyQt5`.
- Modificar la API pública de `build_KM`, `build_volume_mesh`,
  `solve_modes`, `mesh_info`. Son contratos estables.
- Borrar `n_per_meter` como palanca controlable. Ya consideramos
  reemplazarlo por auto-tuner y decidimos NO.
- Emojis salvo que él los use primero.

---

## 4. Snapshot del proyecto (a fecha 29 May 2026 = v2.10)

### Lo que hace la app
Modelador 3D de recintos acústicos con simulación FEM modal. Tres pestañas
(Geometría / Acústica / Predicción). El solver calcula los modos del
recinto (autovalores de `K · φ = λ · M · φ`), la FRF en un receptor por
superposición modal, y mapas 2D/3D de presión.

### Stack
- Python 3.12 (Anaconda).
- `numpy`, `scipy`, `matplotlib`, `PyQt5`, `pyqtgraph`, `trimesh`, `gmsh`.
- Voxel mesher propio (sin dependencia C++) + opcional `mesh_gmsh.py`
  para mallado boundary-fitted.
- Build: PyInstaller (`Prototipo 1.spec`), instalador con NSIS.

### Estado del solver
- **P1 lineal** elegido como solver de producción (decisión v2.10, ver §5).
- **Robustez v2.9**: filtro de slivers en mallado, retry de Lanczos con
  shift dinámico, simetrización forzada de K y M, métricas de calidad de
  malla (`h_min`, `h_ratio`, `n_slivers`).
- **API pública intacta** desde v2.0; todos los cambios son aditivos.

### Archivos clave del código (NO TOCAR sin razón)
- `acoustic_mesh.py` — mallador volumétrico voxel + Freudenthal.
- `acoustic_fem.py` — solver FEM (ensamble, eigsh, FRF, FieldEvaluator).
- `geometry.py` — superficie del recinto. Soporta `shape="ellipse"` /
  `"circle"` desde v2.10 (no expuesto en UI todavía).
- `sources.py` — fuentes monopolo, constantes físicas RHO0=1.21, C0=343.
- `mesh_router.py` — router entre voxel y gmsh.
- `acoustic_panel.py` — la UI del módulo acústico.
- `main.py` — entry point.

---

## 5. Decisiones tomadas con su rationale (condensadas)

Para no tener que re-discutir cada vez:

### D1. P1 lineal sobre P2 cuadrático
**Decisión v2.10**: solver de producción se queda en P1. P2 explorado,
validado, descartado.

**Por qué**: P1 con `n_per_meter=2` tiene error 0.4–3 % vs analítico. P2
reduce eso a < 0.05 % (~100× mejora). Pero P2 cuesta 5–36× más tiempo de
cómputo (medido en 5 salas × 30 modos). El error de P1 ya está por debajo
del ruido del modelado físico (RT60 estimado, posiciones de fuentes,
α de materiales). Más precisión numérica no cambia ninguna decisión
acústica práctica.

**Cómo escala P1 — para no equivocarse cuando lo expliques**:
- **Error en autovalores**: `O(h²)` (Galerkin para elementos lineales).
  Bajar `h` a la mitad reduce el error por **4**.
- **Cantidad de nodos en 3D**: `~ n_per_meter³`, equivalentemente `~ h⁻³`.
  Bajar `h` a la mitad multiplica los nodos por **8**.
- **Costo del solver** (Lanczos con shift-invert): `~ O(Nₙ · k · iter)`,
  típicamente entre lineal y cuadrático en `Nₙ` según el conditioning.
- **NO digas** que "P1 escala como `h³` en nodos" — eso confunde escala
  de error con escala de tamaño. Es `h⁻³` en nodos y `h²` en error.
- **Regla rápida**: pasar de `n_per_meter=2` a `n_per_meter=3` reduce el
  error a ~4/9 (≈ 45 %) por ~3.4× más nodos. Es buen trade — todavía más
  barato que migrar a P2.

**Si el usuario vuelve a preguntar por P2**: respondé que ya se evaluó,
los archivos se removieron, y el rationale está documentado en MANUAL.md
v2.10. NO empezar de cero.

### D2. FEM hecho a mano, NO FEniCS
**Decisión histórica**: implementación con NumPy/SciPy puro.

**Por qué**: ver el apéndice "FEM a mano vs FEniCS" en MANUAL.md. Resumen:
problema chico, transparencia pedagógica importante, cero dependencias
C++ en Windows + Anaconda.

**Rutas intermedias consideradas — qué decir si el usuario las trae**:
si el usuario menciona alternativas más livianas que FEniCS, conocelas
pero **no las recomiendes proactivamente** salvo que él pregunte:

- **`scikit-fem`** — librería Python pura sobre NumPy/SciPy, sin C++.
  Tamaño ~5 MB. Soporta P1/P2/Pk, mallas tet/hex/tri/quad, formas débiles
  declarativas. **Ventaja sobre lo nuestro**: API declarativa, elementos
  de orden superior built-in. **Costo**: dependencia más, perdés
  transparencia (el ensamblaje pasa por su backend). Para nuestro caso
  no aporta: el ensamblaje ya está vectorizado y el problema es chico.
  Mencionar **solo si** el usuario quiere experimentar con P2+ sin
  tragarse FEniCS.
- **Firedrake** — DSL UFL como FEniCS pero más liviano. Sigue siendo
  pesado en Windows (PETSc dependencia). No es opción seria para este
  proyecto.
- **`fenics-dolfinx`** — la versión moderna de FEniCS. Mismos problemas
  de instalación en Windows + Anaconda.

**Resumen para el push-back**: la decisión de "FEM a mano" no es
ideológica — es porque el problema no justifica ninguna dependencia
extra, sin importar cuán liviana sea. Si el usuario insiste, pedile el
caso de uso concreto que requiere más de lo que tenemos hoy. Si no hay
caso, no hay migración.

### D3. Voxel mesher propio + frontera escalonada
**Decisión histórica**: sin TetGen, sin CGAL.

**Por qué**: para paredes rígidas, la frontera escalonada no afecta el
ensamblaje (Neumann homogénea es condición *natural* en la forma débil →
desaparece sin necesitar la geometría exacta). Solo introduce error
volumétrico de ~1-2 % en los primeros modos.

**Cuándo no se banca**: con absorción modelada por impedancia ensamblada
en matriz `C` de superficie. Pero el proyecto usa damping modal (ξₙ del
RT60) que evita esto.

### D4. `n_per_meter` palanca del usuario
**Decisión v2.9**: NO reemplazar por auto-tuner.

**Por qué**: el usuario casual quiere previews rápidos con malla gruesa;
el usuario analítico quiere precisión con malla fina. El parámetro permite
ambos. Auto-tuner ocultaría la palanca.

**Compromiso aplicado en v2.12**: el slider sigue editable PERO debajo
aparece un label `npm sugerido: X.XX` con un botón `[Aplicar]` que carga
el valor calculado como `npm = ppw·f_S/c` (cubre exactamente hasta
f_Schroeder). Lo mejor de ambos mundos: preview rápido ignora la
sugerencia, análisis riguroso la aplica de un click. **NO sacar el
slider, NO automatizar**: la decisión sigue siendo D4. La sugerencia
es informativa, no impositiva.

### D5. M consistente, NO lumped
**Decisión histórica**: matriz de masa consistente (V/20 fuera de
diagonal, V/10 en diagonal). Lumped sería más rápida pero introduce error
O(h) en lugar de O(h²).

### D5b. Modal damping (ξn por modo), NO matriz C de impedancia
**Decisión v2.10**: confirmada empíricamente con benchmark
(`bench_modal_vs_impedance.py`, ejecutado 30 May 2026).

**Por qué**: la app modela absorción derivando `ξn = 1.1/(fn·RT60_Sabine)`
en lugar de ensamblar la matriz de superficie `C = (1/Z) ∫_∂Ω Ni Nj dS`.

**Datos medidos** (shoebox 5×4×3, α=0.30 uniforme, n_per_meter=2):
- Pipeline modal damping: **26 ms**. Pipeline C-matrix directo: **242 ms**.
  Ratio **9.5×**. Con Z(ω) compleja el ratio escala a 10²–10³×.
- Ambos métodos identifican **los mismos modos en las mismas frecuencias**.
- En banda modal 30–100 Hz (post-fix v2.11 de c²): **RMS diff 1.6 dB,
  max 2.8 dB** entre modal y C-matrix. Concuerdan dentro del ruido del
  problema. Los ~2 dB residuales vienen del mismatch α_random ↔ α_normal
  del C-matrix (no es resoluble sin medir Z(ω)).

**Si el usuario vuelve a preguntar por C-matrix**: respondé que se evaluó,
documentado en `acoustic_fem_explicado.md` §16. Sólo gana cuando hay
**Z(ω) medida en tubo de Kundt** por material, escenario que NO aparece
en el flujo de trabajo (catálogo Cox da α, no Z(ω)). Derivar Z desde α
no agrega información — es el mismo dato repackeado, con asunciones
adicionales (locally reacting, Z real, incidencia normal) que el catálogo
**no** garantiza.

**Hermiticidad como bonus**: con paredes 100 % rígidas, K y M son reales
simétricas → `eigsh` Lanczos directo. Añadir C compleja rompe la
hermiticidad → habría que ir a Arnoldi (`eigs`), 3–5× más lento, con
bi-ortogonalización en lugar de M-ortonormalización simple.

### D6. `shape="ellipse"` no expuesto en UI
**Decisión v2.10**: las primitivas de planta curva están en `geometry.py`
pero el panel no las muestra. Disponibles por API programática.

**Por qué**: el efecto del isoparamétrico (que motivó las curvas) resultó
marginal en la malla voxel. Exponer la opción sin un beneficio claro
agrega complejidad UI sin valor proporcional.

---

## 6. Convenciones técnicas y gotchas

### Path al Python que funciona
La instalación de Python en `WindowsApps` está rota (es un stub del
Microsoft Store). Usá:
```
/c/Users/aceve/anaconda3/python.exe
```

### Encoding al correr scripts
La consola Windows usa cp1252 por defecto. Si imprimís caracteres como
`→`, `≈`, `α` desde Python a stdout, falla con `UnicodeEncodeError`.
Solución:
```bash
PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe script.py
```
Alternativa: en el código, usá solo ASCII o `print('...'.encode('utf-8'))`.

### LaTeX
MiKTeX está en `/c/Users/aceve/AppData/Local/Programs/MiKTeX/miktex/bin/x64/pdflatex.exe`.
Compilación del manual: `pdflatex -interaction=nonstopmode MANUAL.tex` × 2
pasadas (para resolver TOC). Limpiar `.aux .log .toc .out` después.

### Git
**El proyecto YA tiene git inicializado** (desde 7-8 Jul 2026 — cambió la regla
histórica). Repo **PRIVADO** en `github.com/tomasdivididos-blip/prototipo-1`,
rama `main`. Subir cambios: `git add -A; git commit -m "..."; git push` (ya no
hace falta re-autenticar). El `.gitignore` excluye `dist/`, `build/`, `*.zip` y
`referencias/` (libros/slides de terceros con copyright). `gh` (GitHub CLI)
instalado en `C:\Program Files\GitHub CLI\gh.exe` (NO en el PATH de bash → usar
ruta completa). Convención de commits: terminar con `Co-Authored-By: Claude`.

### Reglas de cuadratura para FEM
Si volvés a trabajar con P2 (lo cual el usuario probablemente no quiere
después de la decisión D1), recordá:
- **Keast 5-pt** (5 puntos, grado 3, **peso central NEGATIVO**) sólo sirve
  para integrandos hasta grado 3. Para M con P2 (`N_i N_j` grado 4) DA
  ENTRADAS NEGATIVAS — bug confirmado en esta sesión. Solución: forma
  cerrada multinomial.
- **Multinomial**: `∫ L_0^a L_1^b L_2^c L_3^d dV = a! b! c! d! / (a+b+c+d+3)! · 6V_e`.

### Build pipeline + distribución (v2.12+)
**Salida del build**: PyInstaller `--onedir` genera `dist\Prototipo1\` (~1.6 GB
sin comprimir, 570 MB zipeado). Contiene `Prototipo1.exe` al lado de
`MANUAL.pdf`, `ejemplo.room`, `LEEME.txt` y un subfolder `_internal/`
con todas las DLLs, modulos Python embebidos y los 19 JSON de
`materials/`.

**Scripts del pipeline** (todos en raíz del proyecto):
- `build.bat` — corre PyInstaller con flags correctos (excludes PyQt6,
  pandas, sphinx, etc. + `--add-data "materials;materials"` + post-build
  que copia MANUAL.pdf/ejemplo.room/LEEME.txt al root del dist).
- `verify_distribution.py` — chequea archivos esperados + tamaño post-build.
- `test_distribution_smoke.py` — copia el bundle a `%TEMP%`, lanza el
  .exe, verifica que viva 15 s. Smoke test sin GUI interactiva.
- `pack_distribution.py` — comprime `dist\Prototipo1\` a `Prototipo1_v2.12.zip`.
- `installer.nsi` + `build_installer.bat` — alternativa NSIS para
  generar un instalador único `.exe` (requiere NSIS instalado).
- `ejemplo.room` — sala 5×4×3 de muestra que viene con el bundle.
- `LEEME.txt` — instrucciones de 5 párrafos para el destinatario
  (SmartScreen, etc.).

**Flujo típico** para mandarle al profesor / a otro: `build.bat` →
`verify_distribution.py` → `test_distribution_smoke.py` → test visual
humano → `pack_distribution.py` → mandar ZIP por WeTransfer/Drive.

**Bugs del pipeline ya cubiertos** (ver §7 B8, B9, B10): conflicto
PyQt5/PyQt6, bundle pesando 1.9 GB sin excludes, `materials/` no
bundleado por falta de `--add-data`. Todos fixeados en `build.bat`
desde v2.12.

**Detalle completo** en MANUAL.md §20 "Distribución del programa".

### Importes del módulo
La app importa todos los módulos al arrancar. Si rompés un import
durante refactoring, `main.py` falla en startup. Antes de borrar
funciones o cambiar firmas: `grep` por usos en TODO el proyecto.

---

## 7. Bugs históricos relevantes

### B1. K negative weight bug en P2 con cuadratura Keast 5-pt
**Síntoma**: primeros 5 modos a ~0 Hz, otros corridos 80-100 %.
**Diagnóstico**: `M_01` calculado por Keast 5-pt dio `-V/720` (debe ser
`+V/420`). El peso central negativo combinado con el grado 4 del
integrando hace que ciertas entradas off-diagonal salgan negativas. M no
es positiva definida → eigsh devuelve modos espurios.
**Fix**: forma cerrada multinomial para M.
**Aplicabilidad**: solo P2, que ya está fuera del solver de producción.

### B2. cp1252 al imprimir Unicode
Ya documentado en sección 6.

### B3. `mesh_info` con malla vacía
Si la geometría es degenerada, `build_volume_mesh` devuelve `(0, 0)`.
`mesh_info` debe manejar `len(tets) == 0` devolviendo un dict con ceros.
Cubierto en v2.9.

### B4. Lanczos no-convergencia
Más probable en mallas no axis-aligned (slivers en bordes oblicuos).
Cubierto en v2.9 con `try/except ArpackNoConvergence` y retry con sigma
desplazado. Si el usuario lo trae como tema, ya está resuelto.

### B5. Factor c² ausente en `frequency_response` y `modal_pressure_field` — FIXEADO v2.11
**Síntoma histórico** (hasta v2.10): la FRF reportada en dB SPL estaba
sistemáticamente ~101 dB por debajo del nivel físico real. Si se calibraba
contra una fuente de sensibilidad conocida (ej.: 90 dB/W/m), faltaban
~101 dB.
**Diagnóstico**: la fórmula vieja `H = iωρ₀ · Σ φn(xr)φn(xs) / (ωn² − ω²)`
era incorrecta. La derivación rigurosa de la Green function modal de
Helmholtz en cavidad da `p = iωρ₀ · c² · Σ φn(xr)φn(xs) / (ωn² − ω²)`
(porque `ωn² = c²·λn` y `k² = ω²/c²`). Falta el `c²` fuera del sumando.
**Cómo no se notó**: el FRF se interpretaba como forma relativa (picos,
nulls), no como SPL absoluto. La auralización normaliza a peak antes del
DAC (`audio_utils.apply_frf_filter` líneas 140-152), absorbiendo el offset.
**Fix v2.11**: agregado `c**2` al prefactor de las tres funciones
afectadas:
- `acoustic_fem.frequency_response` (línea ~421)
- `acoustic_fem.modal_pressure_field` (línea ~459)
- `fem_modal.frequency_response` (línea ~289, legacy shoebox-only)
**Validación**: smoke test en `acoustic_fem.__main__` (assert SPL pico
entre 50 y 100 dB para Q=1 mm³/s, ξ=0.05; obtiene 74.2 dB que coincide
con la analítica de 74.8 dB). Bench `bench_modal_vs_impedance.py` ahora
da RMS 1.6 dB de diff con C-matrix sin shifts manuales.
**Compatibilidad rota**: exports CSV/TXT pre-v2.11 quedan +101 dB
desfasados de los nuevos. Documentado en changelog v2.11 del MANUAL.md.

### B6. Modos arriba de `f_max_malla` numéricamente sucios — FIXEADO v2.12
**Síntoma**: al pedir muchos modos (con `Nº modos` cerca del Weyl-suggest),
los últimos modos del set quedan **arriba de `f_max_malla = c / (ppw·h_max)`**.
Esos modos son basura: dispersión del esquema, plegado de onda, frecuencias
corridas. `eigsh` los devuelve sin error.
**Diagnóstico**: `solve_modes(K, M, n_modes=N)` no sabe nada de la malla;
devuelve los N autovalores más bajos. La validez de malla la conoce el
panel (vía `_validity_freq(mesh_info["h_max"])` y el badge "válido hasta").
**Fix v2.12**: nuevo helper `_clip_modes_to_mesh_validity()` en
`acoustic_panel.AcousticPanel` que se llama **tras cada solve** (path
principal en `_compute_modes_async` ~línea 1657, fallback FRF ~línea 2030).
Filtra `modal_result.freqs` y `modal_result.phis` in-place para quedarse
sólo con modos `f ≤ f_max_malla`. Log al usuario: `"FEM: pediste N modos,
K son válidos. N-K excedían f_max_malla = X Hz."`.
**No tocar el solver**: el clip vive en el panel deliberadamente. Cualquier
usuario programático de `acoustic_analysis.run_fem_modal` mantiene el set
completo y decide qué hacer. La invariante UI es que el picker, el campo
3D y los heatmaps **nunca muestran modos arriba del badge de validez**.

### B7. Botones de diálogos con texto clipeado — FIXEADO v2.12
**Síntoma**: en el diálogo de importar/reparar CAD, los botones largos
("✓ Cerrar este hueco (auto)", "⛒ Soldar a vertices cercanos", etc.)
mostraban texto recortado al primer carácter (aparecía "errar" en lugar
de "Cerrar"). Igual en botones "Exportar PNG/SVG/PDF/CSV/TXT" de los
diálogos de FRF, RT60 y Slice heatmap.
**Diagnóstico**: dos causas combinadas.
  (1) Qt centra el texto del QPushButton por default. Cuando el
      sizeHint() es subestimado por la métrica irregular del Unicode al
      inicio del texto (`✓ ⛒ ✎ →`), el clipping cae sobre el primer
      carácter.
  (2) Los `setMinimumWidth` históricos (100/120) no alcanzaban para el
      padding QSS Catppuccin (8px 14px lateral) + texto + Unicode ancho.
**Fix v2.12**: triple defensa en `geom_repair_dialog.py`:
  (a) `left.setMinimumWidth(440)` en el panel izquierdo del splitter.
  (b) `setMinimumWidth(380)` por botón.
  (c) `text-align: left; padding-left: 16px` vía styleSheet local en
      cada botón con icono Unicode al inicio.
Y en `acoustic_panel.py` los export buttons subidos a `setMinimumWidth(140)`
con `sizePolicy(Preferred, Fixed)`.
**Para futuro**: si agregás un botón con icono Unicode al inicio del label,
aplicale el mismo styleSheet local o reemplazá el Unicode por un QIcon
real (que no rompe la métrica).

### B8. PyInstaller falla con "multiple Qt bindings" — FIXEADO v2.12
**Síntoma**: al correr `build.bat` el build aborta con:
```
ERROR: Aborting build process due to attempt to collect multiple Qt
bindings packages: attempting to run hook for 'PyQt6', while hook
for 'PyQt5' has already been run!
```
**Diagnóstico**: la Anaconda del usuario tiene **tanto PyQt5 como PyQt6
instalados** (PyQt6 puede haber venido como dep transitiva de algún pip
install). PyInstaller no permite bundlear los dos.
**Fix v2.12**: `build.bat` ahora pasa `--exclude-module PyQt6 / PySide6 /
PySide2` defensivamente. Si aparece otra variante (PyQt4, etc.), agregar
el exclude correspondiente.
**Aplicabilidad**: cualquier sesión de build. La primera vez que se
buildea en una Anaconda nueva puede aparecer; ya está cubierto.

### B9. Bundle pesa 1.9 GB sin excludes — FIXEADO v2.12
**Síntoma**: `dist\Prototipo1\` pesa 1.9 GB con el `build.bat` default.
Demasiado para email; complica WeTransfer.
**Diagnóstico**: PyInstaller arrastra transitivamente pandas, IPython,
jupyter, sphinx, sqlalchemy, lxml, openpyxl, pyarrow, bcrypt, cryptography,
nacl, jedi, parso, sphinxcontrib, docutils, pygments, tkinter, etc.
Ninguno se usa en el proyecto.
**Fix v2.12**: `build.bat` lleva ~25 flags `--exclude-module` que llevan
el bundle a ~1.6 GB. Para slimear más: agregar `botocore` (~92 MB),
`numba` + `llvmlite` (~66 MB), `panel` + `bokeh` (~100 MB) → llegaría
a ~1.2 GB. Más allá no se baja sin reinstalar numpy/scipy con OpenBLAS
en lugar de MKL (los `mkl_*.dll` suman ~400 MB).
**Tamaño aceptable**: 1.5–1.6 GB sin comprimir, ZIP ~570 MB. Pasa por
WeTransfer (2 GB) y Google Drive sin problema.

### B10. Materiales no bundleados en build PyInstaller — FIXEADO v2.12
**Síntoma**: el `.exe` arranca pero el diálogo "Materiales" sólo muestra
"default" (1 material) en lugar de los 19 que hay en la carpeta fuente.
**Diagnóstico**: `material_library.py` usa `Path(__file__).parent / "materials"`
para encontrar los JSON. En el dev environment esto resuelve al folder
fuente. En el bundle PyInstaller `--onedir`, `Path(__file__).parent` apunta
a `_internal/`, y si `materials/` no se bundleó, el folder no existe y
`MaterialLibrary.__init__` cae al `_default_material()` único.
**Síntoma engañoso**: corriendo el .exe DESDE el directorio fuente
"anda bien" por casualidad, porque Python encuentra los archivos via
otro path. El bug sólo aparece en otra PC o cuando movés el dist.
**Fix v2.12**: `build.bat` pasa `--add-data "materials;materials"`. El
folder queda bundleado en `dist\Prototipo1\_internal\materials\` que es
donde `Path(__file__).parent / "materials"` lo encuentra (porque los
.pyc también viven en `_internal/`).
**Verificación**: correr `verify_distribution.py` post-build; chequea
que haya 19 JSON en `_internal/materials/`.

---

## 8. Si te aparece X, hacé Y

| Si el usuario… | Hacé… |
|---|---|
| Pide explicar código línea por línea | Estilo de `acoustic_fem_explicado.md`: shape de cada array, conexión con la matemática, caja "Truco" cuando aparece un patrón NumPy nuevo |
| Pide implementar un cambio | Antes: grep usos, leer función, proponer plan (con trade-offs). Después: editar, correr verificación, reportar |
| Pide cuestionario / autoevaluación | Estilo de `cuestionario_acoustic.html`: HTML autocontenido, vanilla JS, opciones bloquean al marcar, explicación inline |
| Pide planificar algo grande | Markdown `plan*.md` con fases enumeradas, métricas de éxito, riesgos. Estilo del ahora-borrado `planP2.md` |
| Pide bench / medición | Script Python con `time.perf_counter()`, reporte tabular con columnas alineadas, opcional JSON de salida |
| Pide actualizar el manual | EDITAR `MANUAL.md` (markdown), DESPUÉS editar `MANUAL.tex` (versión condensada), DESPUÉS recompilar `MANUAL.pdf` con `pdflatex` × 2 pasadas. **NO omitir ninguno**: los tres viven sincronizados desde v2.0. Limpiar `.aux .log .toc .out` después |
| Confiesa que no entiende algo (NumPy, FEM, etc.) | Pasada profunda con la caja dedicada. Sin embellecimientos. Mini-experimento que pueda correr para verificar |
| Pide borrar archivos | Antes de borrar: grep referencias, listar consecuencias, **pedir confirmación** explícita. Mantener archivos que tengan valor independiente del feature que descartó |
| Pide automatizar `n_per_meter` (auto-tuner, derivar de `f_max`, sacar el slider, etc.) | **Push back con cortesía**. Ya se evaluó en v2.9 y se decidió NO. Ver D4. Mostrale el compromiso aplicado en v2.12: label "npm sugerido" + botón `[Aplicar]` debajo del slider. Si insiste en sacar el slider entero, requiere actualizar D4 con rationale nuevo (no sobrescribir) |
| Pide modificar el solver para que respete una frecuencia máxima | En lugar de tocar `solve_modes`, mirá `_clip_modes_to_mesh_validity()` en `acoustic_panel.py`. El clip por validez de malla ya vive ahí (post-solve) y mantiene la API pública del solver intacta. Aplica el mismo patrón para cualquier post-procesamiento nuevo |
| Pide agregar un widget con label/icono Unicode al inicio (`✓ ⛒ ✎ →`) | **Cuidado con el clipping**: Qt subestima sizeHint cuando hay Unicode ancho al inicio del texto centrado. Aplicale el patrón v2.12: `setMinimumWidth(suficiente)` + `styleSheet` con `text-align: left; padding-left: 16px`. Ver B7 en §7 |
| Pide distribuir el programa (enviar a otra PC, profesor, etc.) | Camino: `build.bat` → `verify_distribution.py` → `test_distribution_smoke.py` → test visual humano (Materiales = 19, ejemplo.room carga, FEM corre) → `pack_distribution.py` → mandar ZIP por WeTransfer / Drive. Detalle en MANUAL.md §20. NO sugerir mandar la carpeta fuente cruda (el destinatario no tendría Python ni Anaconda) |
| Reporta "el .exe abre pero el dialog Materiales sólo muestra 'default'" | Bug B10 (clásico): `materials/` no se bundleó. Verificar que `build.bat` tiene `--add-data "materials;materials"`. Diagnóstico rápido: `ls dist/Prototipo1/_internal/materials/*.json \| wc -l` debe dar 19 |
| Reporta build fail con "attempt to collect multiple Qt bindings" | Bug B8: la Anaconda tiene PyQt5 + PyQt6 simultáneamente. `build.bat` ya tiene `--exclude-module PyQt6 / PySide6 / PySide2` desde v2.12. Si aparece otra variante, agregale el exclude correspondiente |
| Pide slimear el bundle (1.6 GB es mucho) | Agregar excludes adicionales a `build.bat`: `botocore` (~92 MB), `numba` + `llvmlite` (~66 MB), `panel` + `bokeh` (~100 MB). Más allá de eso, hay ~400 MB de MKL DLLs que numpy/scipy necesitan para BLAS; reemplazar por OpenBLAS requiere reinstalar numpy y es invasivo. Ver B9 en §7 |
| Pide hacer commit / git push / git status | El proyecto **YA tiene git** (repo privado `tomasdivididos-blip/prototipo-1`, rama `main` — ver §6). Hacé `git add -A; git commit; git push` normal. NO re-inicialices el repo ni cambies el remote sin permiso |
| Pide migrar a P2 (otra vez) | Respondé que ya se evaluó y descartó en v2.10. Cita los números (5–36× más caro, error P1 ya despreciable vs ruido de modelado). NO empieces de cero: el rationale completo está en MANUAL.md §"Cambios v2.10" y en este archivo §5 D1. Solo reabrir el tema si el usuario presenta evidencia nueva |
| Pide migrar a FEniCS / dolfinx / deal.II | Decisión D2 ya tomada. Ver apéndice "FEM a mano vs FEniCS" en MANUAL.md. Push back salvo que aparezcan los criterios listados ahí (> 10⁶ DOFs, impedancia angular, multifísica) |
| Pregunta por **directividad / patrón polar** de fuentes | Ya se evaluó (13 Jun 2026) y se **descartó**: en banda modal (≤ Schroeder) los parlantes son casi omni; el dominio de la directividad casi no se solapa con la validez del FEM. Ver `plan_fuentes_respuesta_frecuencia.md` §1.1. Si insiste: monopolo+dipolo acoplado a ∇φₙ, pero NO en el plan actual |
| Pregunta por **respuesta en frecuencia / fase** de fuentes (mediciones FRD / VituixCAD) | **Fases 0 y 1 YA implementadas** (16 Jun 2026). Núcleo `Q(f)` = **ganancia compleja `g(f)` relativa al Q de hoy** (decisión "opción 1", NO SPL absoluto — ver §13). Fase 0: `sources.SourceResponse`/`synth_response`/`effective_Q_spectrum`, `acoustic_fem` con acople por f (`bench_source_response.py`, 5 oráculos OK). Fase 1: `frd.py` (parser + fase mínima), `SourceResponse.from_frd` con anclaje **absoluto/relativo**, `.room` **v5** con `response` (`bench_frd.py` OK). Fase 2: UI en `SourceEditDialog` (cargar/quitar FRD, combo anclaje, delay/polaridad, preview; `get_source` preserva la curva). Fase 2c: `modal_metrics.py` (FoM §8 + cruce modal §9, `bench_modal_metrics.py` OK), **capa de cómputo lista pero SIN wirear a UI/Predicción**. **Falta**: wiring (f_cross junto a f_Schroeder, FoM junto a FRF, alimentar Predicción) y **Fase 3** (data real). Plan en `plan_fuentes_respuesta_frecuencia.md`. NO arranques sin OK explícito |
| Pide una **versión Mac** / mandar a una Apple | No se cross-compila desde Windows (PyInstaller no compila cruzado). Entregar `Prototipo1_Mac.zip` (run-from-source), ya armado 13 Jun 2026. Ver memoria `[[mac-distribution]]` y §6. Para un `.app` real de doble clic hay que correr el build EN una Mac (`build_mac.sh` pendiente) |

---

## 9. Qué NO hacer

- ❌ Spawn subagents sin que el usuario lo pida explícitamente.
- ❌ Crear `.md` extras "por si acaso". Si el contenido va en uno existente, agregalo ahí.
- ❌ Sugerir tests con frameworks (pytest, unittest) salvo que sean
  estrictamente necesarios. Los smoke tests inline (en `__main__` de los
  módulos, o scripts `bench_*.py`) son el patrón del proyecto.
- ❌ Refactorizar código que no fue tocado en la sesión actual sin permiso.
- ❌ Cambiar el formato de los changelogs en `MANUAL.md`. Tienen estilo
  consistente desde v2.0.
- ❌ Asumir que un benchmark es "lo suficientemente representativo".
  Validar con la demo de caja 5×4×3 (modos analíticos conocidos) antes
  de claim de mejora.
- ❌ Modificar `_GAUSS_TET_5PT`, `HEX_TO_TETS`, `_M_REF_P2` (constantes
  precomputadas, validadas).
- ❌ Pisar las explicaciones de los `*_explicado.md` con cambios
  cosméticos. Son densos a propósito.

---

## 10. Workflow típico cuando el usuario trae una idea

Patrón observado y que funciona:

1. **Escuchar** el problema o idea.
2. **Reformular** lo que entendiste en una frase.
3. **Identificar la decisión de fondo** ("¿estamos optimizando precisión
   o velocidad?"). Hacer la pregunta si no está claro.
4. **Proponer un plan** corto (3-5 pasos), con métricas de éxito y costo
   estimado.
5. **Ejecutar** una vez que el usuario apruebe ("si", "dale", etc.).
6. **Verificar** con un experimento concreto (demo + comparación contra
   estado anterior).
7. **Documentar** en el manual (añadir bloque al changelog, sincronizar
   .tex y .pdf).
8. **Resumir** lo que cambió y preguntar qué sigue.

Si la idea es grande (>1 hora), usar `TaskCreate` para tracking; si es
chica, hacerlo inline.

---

## 11. Bonus — frases del usuario y su decodificación

- **"si"** / **"dale"** = aprobación. Procedé sin pedir más confirmación
  (a menos que la acción sea destructiva e irreversible).
- **"hace eso"** = imperativo, sin pluralizar. Argentino.
- **"explicame X"** = quiere profundidad y derivación, no respuesta
  ejecutiva.
- **"agregalo al manual"** = MANUAL.md **y** .tex **y** .pdf. Los tres.
- **"podes...?"** = sí, podés. Hacelo.
- **"que tan necesario es?"** = quiere un trade-off claro con costos
  numéricos.
- **"voy a clear y vuelvo"** = sesión nueva, recontextualizate con los
  4 `.md` (este + los tres grandes).

---

## 12. Casos diagnósticos — preguntas para validar el bootstrap

Si tras un `/clear` el usuario quiere comprobar que la recontextualización
funcionó, puede tirarte alguna de estas preguntas. Cada una está diseñada
para forzar el uso de un grupo específico de reglas. Si tu respuesta
contiene los elementos listados en **"Debe incluir"**, el bootstrap está
bien.

### Caso 1 — Estilo didáctico + memoria de decisión

> *Estoy revisando el código de `build_KM` y no entiendo por qué
> `np.einsum("eij,ekj->eik", grads, grads)` calcula la rigidez local.
> Explicámelo, y de paso decime si conviene migrar a P2 para mejorar la
> precisión.*

**Debe incluir:**
- Shape de `grads` anotada `(Ne, 4, 3)`.
- Tabla con el rol de cada índice `e, i, j, k`.
- Conexión explícita con `∇Nᵢ · ∇Nⱼ`.
- **Mención de D1**: P2 ya evaluado y descartado en v2.10, con números
  (5–36× más caro, error P1 ya < ruido de modelado).
- Cierre con opciones concretas (a/b/c) para el siguiente paso.

### Caso 2 — Auto-tuner de `n_per_meter` (testa D4 + push-back)

> *Me parece que `n_per_meter` debería elegirse automáticamente según el
> `f_max` que el usuario pide. ¿Lo implementás?*

**Debe incluir:**
- Push-back: ya se evaluó en v2.9 y se decidió mantener manual.
- Justificación: usuario casual (preview rápido) vs analítico
  (precisión); un valor auto no sirve a ambos.
- Posible compromiso: dejar el parámetro pero agregar `f_max_target`
  opcional que sugiera un default.
- **NO** debe lanzarse a implementar sin escuchar la respuesta del
  usuario.

### Caso 3 — Git (testa §6)

> *Cambié algo en el código y quiero hacer commit, ¿cómo arranco?*

**Debe incluir (ACTUALIZADO 7-8 Jul 2026):**
- El proyecto **YA tiene git** (repo privado `tomasdivididos-blip/prototipo-1`).
- Flujo normal: `git add -A; git commit -m "..."; git push`.
- (Histórico: antes NO había git; se inicializó el 7-8 Jul 2026.)

### Caso 4 — Actualizar manual (testa la regla de los 3 archivos)

> *Documentá esto en el manual.*

**Debe incluir:**
- Plan explícito: edito `MANUAL.md`, después `MANUAL.tex`, después
  recompilo `MANUAL.pdf` con `pdflatex` × 2 pasadas.
- Limpieza de auxiliares `.aux .log .toc .out` al final.
- **NO** debe modificar solo el `.md` y olvidarse del `.tex` / `.pdf`.

### Caso 5 — FEniCS / librería pesada (testa D2)

> *¿No sería más fácil migrar todo a FEniCS y olvidarnos del ensamblaje
> manual?*

**Debe incluir:**
- Decisión D2 ya tomada, ver apéndice "FEM a mano vs FEniCS" en MANUAL.md.
- Razones: cero dependencias C++, transparencia pedagógica, problema chico.
- Criterios bajo los cuales sí valdría la pena: > 10⁶ DOFs, impedancia
  angular, multifísica, paralelismo distribuido.

### Caso 6 — Explicación profunda de concepto NumPy (testa estilo)

> *No entiendo qué es broadcasting.*

**Debe incluir:**
- Caso elemental primero (escalar + array).
- Caso interesante después (arrays de distinta dimensión).
- Regla en una línea ("alineados desde la derecha, cada par de ejes…").
- Diagrama de formas mostrando cómo se estiran los ejes.
- Mini-experimento con código.
- Conexión con dónde aparece en el código del proyecto (`acoustic_mesh.py`,
  el truco `[:, None, :]`).

---

## 13. Última actualización de este archivo

- **29 May 2026** — versión inicial. Estado del proyecto: v2.10. Tras la
  sesión donde se evaluó y descartó P2.
- **29 May 2026** (segunda iteración) — afinado tras un test de bootstrap
  exitoso con sub-agente. Agregadas tres reglas explícitas a §8
  (auto-tuner de `n_per_meter`, git, P2 / FEniCS revisited) y la nueva
  §12 con 6 casos diagnósticos para validar futuras recontextualizaciones.
- **29 May 2026** (tercera iteración) — afinado tras la corrida completa
  de los 6 casos diagnósticos en paralelo. Dos correcciones puntuales:
  1. **D1** — agregada la sub-sección "Cómo escala P1" para evitar la
     confusión `h³` (nodos) vs `h²` (error). Reglita rápida de
     `n_per_meter=2 → 3` incluida.
  2. **D2** — agregada la sub-sección "Rutas intermedias consideradas"
     con `scikit-fem`, Firedrake y dolfinx, y la pauta de no
     recomendarlas proactivamente.
  Los 6 sub-agentes pasaron todos los criterios "Debe incluir" del
  checklist §12 — bootstrap considerado validado.
- **30 May 2026** — sesión sobre costo-beneficio modal damping vs matriz
  C de impedancia. Tres updates iniciales:
  1. **D5b nuevo** en §5: decisión confirmada empíricamente con
     `bench_modal_vs_impedance.py`. Datos: ratio 9.5× de costo, ambos
     métodos localizan los mismos modos, mismatch sistemático de 18 dB
     explicado por convención de α (random vs normal incidence).
  2. **B5 nuevo** en §7: factor c² faltante en `frequency_response`
     (offset de calibración absoluto de ~101 dB). NO fixeado por riesgo
     en la cadena de auralización.
  3. **`acoustic_fem_explicado.md` §16 nuevo**: benchmark completo
     (setup, tiempos, picos, veredicto). Bench script y JSON en raíz.
- **3 Jun 2026 (v2.12 distribución)** — sesión de empaquetado para enviar el programa a otra PC (caso: usuario quería mandarle al profesor). Tres bloques:
  1. **Fix del pipeline de build** (`build.bat`): agregado `--add-data "materials;materials"` (sin esto el bundle viene sin los 19 JSONs y Materials muestra sólo "default"), excludes para PyQt6/PySide6/PySide2 (evita conflicto "multiple Qt bindings"), y ~22 excludes adicionales para deps transitivas no usadas (pandas, IPython, sphinx, sqlalchemy, jupyter, etc.). Post-build copia automática de MANUAL.pdf/ejemplo.room/LEEME.txt al root del dist. Bundle bajó de 1.9 GB → 1.6 GB (570 MB zipeado).
  2. **Tres bugs nuevos en §7**: B8 (conflicto Qt bindings), B9 (bundle 1.9 GB sin excludes), B10 (materiales no bundleados sin --add-data). Cinco filas nuevas en §8 ("Si te aparece X, hacé Y"): distribución, materials missing, Qt conflict, slimming, build pipeline.
  3. **Nueva §20 en MANUAL.md "Distribución del programa"** y nueva sub-sección en §6 de notas: documenta el flujo build → verify → smoke test → ZIP. Archivos nuevos: `ejemplo.room`, `LEEME.txt`, `verify_distribution.py`, `test_distribution_smoke.py`, `pack_distribution.py`. `installer.nsi` reescrito de cero (la versión vieja apuntaba a archivos inexistentes).

- **30 May 2026 (v2.12)** — sesión de UX del solver modal + clip por validez de malla. Cinco bloques:
  1. **B6 nuevo** en §7: clip automático de modos con `f > f_max_malla`
     en el panel (`_clip_modes_to_mesh_validity()`). Bug físico que estaba
     escondido detrás de Weyl + npm sugerido.
  2. **B7 nuevo** en §7: fix estético de botones con Unicode al inicio
     (triple defensa: minimumWidth panel, minimumWidth botón, styleSheet
     local con text-align:left).
  3. **D4 actualizada** en §5: el slider sigue editable, ahora con
     compromiso de label "npm sugerido" + botón `[Aplicar]` debajo.
  4. **Picker de modos con filtro `f_min/f_max`**: feature UI. Helper
     `_current_mode_idx()` preserva el índice real vía `userData`.
  5. **Sugerencia Weyl `≈ N modos hasta f_S`** debajo del spinbox `Nº modos`.
     Spinbox bumpeado de `(2,80)` a `(2,500)`.
- **30 May 2026 (continuación)** — fix del factor c² aplicado (v2.11).
  Auditoría confirmó que la auralización es invariante (normaliza a peak)
  y que sólo afecta el display SPL absoluto (FRF plot, heatmap, exports).
  Cambios:
  1. **B5 actualizado**: marcado FIXEADO con los 3 lugares corregidos.
  2. **D5b actualizado**: las cifras del residual real (~2 dB en banda
     modal post-fix, no 18 dB como decía la versión previa).
  3. **`acoustic_fem.py` §16.6-16.8 corregido**: el "18 dB de mismatch"
     era artefacto de un cal_offset empírico mal interpretado por mí.
     Tras el fix de c², modal y C-matrix concuerdan dentro de 2 dB.
  4. **Smoke test v2.11**: `acoustic_fem.__main__` ahora valida SPL pico
     en rango fisico [50, 100] dB. Detecta regresión si vuelve a faltar c².

- **13 Jun 2026 — fuentes reales (Q(f)+fase), crítica de 2 papers, distribución a Mac.**
  Sesión larga y mayormente de **PLANIFICACIÓN**: el usuario pidió explícitamente
  *planear todo y aplicar junto al final*. NO empezar a implementar el feature de
  fuentes sin su OK. Cinco bloques:

  **1. Nuevo plan: `Q(f)` + fase por fuente** — archivo `plan_fuentes_respuesta_frecuencia.md`
  (sin implementar). Objetivo del usuario: simular fuentes reales (mediciones de
  **VituixCAD** → archivos **FRD**: `freq | mag dB | fase`) para que el estudio de
  distribución modal refleje fuentes no-ideales.
  - **Directividad DESCARTADA** (decisión nueva): en banda modal (≤ Schroeder) los
    parlantes son casi omni; el dominio donde la directividad importa (cientos de Hz)
    casi no se solapa con la validez del FEM. No paga el costo (cómputo + UX).
  - **Distinción que hay que repetir:** la *distribución modal* (`fₙ`, `φₙ`) **NO**
    depende de la fuente (ya es exacta; el efecto "distancia a paredes" ya está en
    `φₙ(xₛ)`). `Q(f)` solo mejora la *respuesta forzada* (FRF, campo |p|, audio,
    interferencia multi-fuente).
  - **`Q(f)` + fase SÍ se suma** (decisión): cómputo y storage triviales, rigor real
    (reemplaza una suposición —Q plano, fase 0— por dato medido; pasa el test de D5b
    porque es info *nueva*, no reempaquetada). Tier elegido: FRD completo (mag+fase)
    por fuente; delay+polaridad como atajo manual. Mapea a `Q(f)` con la misma física
    de `q_from_sensitivity` (curva SPL→caudal; el caso constante de hoy = curva plana).
    Se embebe en `.room` v5 (sin curva → Q constante, compat hacia atrás).
  - Fase 0 = núcleo + **curvas sintéticas como oráculo** (plana→FRF idéntica `rtol<1e-10`;
    delay→fase lineal; polaridad→cancelación §13.3). El usuario quiere arrancar por ahí.
  - Integración: `sources.py` (`OmniSource.response`, `amplitudes_spectrum`),
    `acoustic_fem.frequency_response`/`modal_pressure_field` (Q(f) por frecuencia),
    UI `SourceEditDialog`.
  - **SPL absoluto vs relativo** (era duda): absoluto = dB calibrado a 20µPa con
    referencia conocida → entra directo; relativo = solo la forma → anclar a la
    sensibilidad en `f_ref`. Para σ_SPL da igual (invariante a offset); para nivel /
    medición real / balance multi-fuente, importa.

  **2. Dos papers diseccionados** (insumo para los criterios de Predicción):
  - **Gunawan & Aditanoyo 2018** (splay wall, J.Phys.Conf.Ser. 1075): usa σ_SPL de
    **un punto** (esquina = peor caso) en sala **sin pérdidas** → σ es artefacto del Q
    numérico de la malla; su Tabla 6 muestra que mover el probe cambia σ 1.3–1.9 dB
    mientras el ranking se decide por 0.34 dB (no robusto). Solo axiales; volúmenes
    distintos confundidos.
  - **Wang, Du & Yu 2026** (MDCF, Archives of Acoustics 51(1)): paper serio. Crítica
    más fuerte: comparan la densidad modal numérica contra **Weyl** teniendo **Maa**
    (Ec.2) — buena parte del gap MDCF–SF es el término de superficie clásico que
    descartaron (peor en salas chicas). Otras: paradoja práctica (hay que correr el
    FEM para calcular la MDCF, que existe para decidir si correr el FEM); definición
    frágil ("el más bajo y todos los subsiguientes" → la decide un outlier, su "modelo
    C"); decaimiento por modo apoyado en α→impedancia asumida (D5b); Eyring usado
    debajo de Schroeder. Si el usuario los re-trae, NO empezar de cero.

  **3. Criterios nuevos del plan** (motivados por los papers):
  - **Figura de mérito mejorada** (§8 del plan): σ_SPL pero **con damping ξₙ +
    varianza espacial sobre zona de receptores + suavizado 1/N octava + solo banda
    válida**. Dos números: `FoM_flat` (planitud media) y `FoM_espacial` (consistencia
    asiento-a-asiento, estilo Welti). Arregla los 4 defectos de Gunawan.
  - **Cruce por solapamiento modal numérico** (§9, estilo MDCF): `M(f)=B_HP·n(f)`.
    Con densidad numérica (ve la forma, gratis, incluye el término de superficie que
    SF descarta) PERO ancho de banda **NO por modo** — eso necesitaría matriz C de
    impedancia, **descartado por D5b**. Con ξₙ de Sabine, `B_HP=2.2/RT60` constante →
    el aporte numérico es solo la densidad. Es "Schroeder con densidad modal real".
    Umbral robusto (mediana, NO "todos los subsiguientes").
  - **Grilla 1/3 octava en la FRF** (§3.4): xticks en los límites de banda ISO 266
    (media geométrica de centros), eje log, grilla tenue tipo REW. **Independiente** —
    se puede implementar primero.
  - **`RATIO_LIBRARY` mal etiquetado** (pendiente, aprobado como enfoque, aplicar al
    implementar): "Bolt"=1:1.4:1.9 es en realidad **Louden**; "Bonello"=1:1.26:1.59 es
    un ratio de **Bolt**; "Louden"=1:1.6:2.33 es **Sepmeyer**. Falta **Cox**
    (1:1.56:1.86). Corregir nombres + agregar Cox (con nota de compat `.room`). Y el
    criterio **Bonello propio** (densidad 1/3 oct no-decreciente) hoy se calcula
    (`bonello_ok_bands`) pero NO se scorea.

  **4. Distribución a macOS (HECHO, no es solo plan):**
  - No se cross-compila un `.app` desde Windows (PyInstaller no compila cruzado).
    Entregado **`Prototipo1_Mac.zip`** (~0.58 MB, en la raíz): paquete *correr desde
    fuente* = 26 `.py` de runtime + `materials/` + `requirements.txt` + MANUAL.pdf +
    ejemplo.room + `run.command` (launcher bash) + `LEEME_MAC.txt`. El profe: instala
    Python 3, abre Terminal, `bash ` + arrastra `run.command`, Enter (1ª vez crea
    `.venv_mac`). Se usa `bash run.command` para esquivar Gatekeeper.
  - **`audio_utils.py` ahora es multiplataforma** (cambio de código real, aplicado):
    era el ÚNICO bloqueo de arranque en Mac (`import winsound` al tope). Windows queda
    idéntico (winsound), Mac usa `afplay`, Linux `aplay/paplay/ffplay`. Verificado que
    importa OK en Windows. (`gmsh`/`trimesh` ya eran lazy; `app_settings` ya manejaba
    `darwin`.)
  - Gotchas de empaquetado desde Windows: zipear con **`zipfile` de Python**
    (`Compress-Archive` de PS 5.1 mete separadores `\` que rompen en macOS);
    `run.command` con saltos **LF** (no CRLF). Detalle en memoria `[[mac-distribution]]`.
  - Pendiente: `build_mac.sh` para un `.app` real cuando haya acceso a una Mac.

  **5. Dato útil:** el `.py` real de `acoustic_fem.py` tiene **550 líneas**, no las
  1627 de `acoustic_fem_explicado.md` (que es el explicador, no el código). No fiarse
  de los números de línea del doc; abrir el `.py`.

  **Archivos nuevos de la sesión:** `plan_fuentes_respuesta_frecuencia.md`,
  `Prototipo1_Mac.zip`, `memory/mac-distribution.md`.

- **16 Jun 2026 — Fase 0 fuentes Q(f) + grilla 1/3 oct + re-sync de docs.**
  El usuario pidió (a) grilla 1/3 octava en la FRF, (b) Fase 0 del plan de
  fuentes, (c) re-sincronizar los 4 docs congelados en v2.6. Las tres hechas.

  **(a) Grilla 1/3 octava en la FRF** (independiente, shippeable sola):
  - Nuevo `plot_utils.py` con `third_octave_edges(f_min, f_max)` (bordes ISO 266
    = media geométrica de centros nominales; reutilizable). Smoke test propio.
  - `acoustic_panel.FRFDialog`: eje X ahora **log** con xticks en los bordes de
    banda (FixedLocator), labels Hz enteras (FuncFormatter), minor off
    (NullLocator), grilla vertical tenue. El RT60PlotDialog YA era log; este no.
    Verificado headless (los bordes salen 22.4, 28.1, 35.5… como el plan §3.4).

  **(b) Fase 0 del plan de fuentes — DECISIÓN CLAVE "opción 1".**
  - **Inconsistencia del plan detectada y resuelta:** el plan (§2, §3.1) decía
    "curva SPL plana = sensibilidad constante de hoy → FRF idéntica". **Es
    falso**: hoy el código usa `q_from_sensitivity` → **Q constante** (SPL que
    sube +6 dB/oct, porque |p|∝ω|Q|). Un SPL plano da `Q∝1/f`, NO el Q de hoy.
  - **Decisión del usuario (opción 1):** la respuesta de fuente es una
    **ganancia compleja `g(f)` relativa al Q baseline**, NO un SPL absoluto.
    `effective_Q_spectrum(f) = effective_Q()·g(f)`. Ventaja: "sin curva" ≡ g≡1
    → FRF baseline bit a bit (regresión exacta); el Q de hoy queda intacto como
    ancla (cero riesgo a la calibración c²); el FRD absoluto entra en Fase 1
    como `g(f)=Q_FRD/Q_base` con el toggle de anclaje. NO se eligió SPL absoluto
    (§3.1 literal) para Fase 0 — eso obligaría a resolver el anclaje sin UI.
  - **Implementado:** `sources.py` → `SourceResponse` (g(f) como gain_db+phase_rad,
    interp lineal; fase SIN envolver), `synth_response` (5 oráculos:
    flat/delay/polarity/highpass/peak), `OmniSource.response` + `effective_Q_spectrum`,
    `SourceArray.amplitudes_spectrum` + `has_response`. `acoustic_fem.py` →
    `frequency_response` (acople `coupling = src_spec @ phi_s`, (Nf,Nm)) y
    `modal_pressure_field` (Q(f) a f única) ahora dependen de f. Sin curva =
    idéntico al path histórico.
  - **Oráculos (`bench_source_response.py`, todos PASAN):** truco usado = para
    UNA fuente `H_resp(f)=g(f)·H_base(f)` EXACTO (la curva factoriza). flat
    max_rel=0; delay 2ms pendiente fase −2πτ exacta; polaridad cancela −318 dB;
    highpass monótono; peak OK. El smoke c² del FEM sigue verde (no rompí nada).
  - **NO hecho (Fase 1/2/3):** parser FRD, `.room` v5, UI SourceEditDialog,
    FoM (§8), cruce modal numérico (§9). El `.room` SIGUE en v4 (Fase 0 no
    toca persistencia). Anoté la decisión opción-1 al tope de `plan_fuentes…md`.

  **(c) Re-sync de los 4 docs v2.6 → v2.12:**
  - **Fórmula FRF con `c²`** (era error factual post-v2.11): corregida en
    `EXPLICACION_TECNICA.md` §5.4 y `PROYECTO.md` (FRF + Notas de física).
  - **Ejemplos §13.2/§13.3 de `EXPLICACION_TECNICA.md` recomputados con `c²`**:
    estaban en calibración pre-c² (corridos +101.4 dB). Re-verificados contra
    el FEM real con el nuevo `verify_examples_c2.py` (sala 6×8×3 centrada,
    npm=3.0): §13.2 modo (1,0,0) = **+77.14 dB analítico / +77.15 FEM** (antes
    −24.3); §13.3 dos fuentes +76.45/+76.46, diff FEM **+5.25 dB** (antes +5.59,
    cambia con la malla). §13.1 (campo libre, 84 dB) NO cambia (monopolo directo).
  - **Audio multiplataforma** (v2.12) en los 3 stack-tables (README, PROYECTO,
    EXPLICACION): winsound/afplay/aplay·paplay·ffplay. Sellos de versión
    v2.6→v2.12 con puntero a MANUAL.md como master changelog.
  - **NO toqué MANUAL.md/.tex/.pdf** (son el master y ya estaban en v2.12; el
    usuario pidió re-sync de los OTROS docs). **NO documenté Q(f)** en ningún
    doc — es WIP, va "junto al final".

  **(d) Fase 1 del plan de fuentes — importador FRD + anclaje + `.room` v5:**
  - Nuevo `frd.py`: `load_frd(path)` parser tolerante (comentarios `*#;`, sep
    coma/espacio/tab, 2 o 3 cols, ordena+dedup) y `minimum_phase(freq, spl_db)`
    (Hilbert con reflect-pad para FRD sin fase; ~5.7° error medio mid-band vs
    el pasa-altos 1-polo, validado con su fase analítica `arctan(fc/f)`).
  - `sources.SourceResponse.from_frd(...)`: convierte SPL+fase → `g(f)` con la
    física §3.1 (`|Q|=|p|·4π/(2πf·ρ₀)`). **Dos anclajes:** `absolute`
    (`g=Q_FRD/q_base` → el nivel medido manda, sensibilidad no-op) y `relative`
    (`g=Q_FRD/|Q_FRD(f_ref)|` → `|g(f_ref)|=1`, nivel desde sensibilidad, solo
    forma+fase del FRD). Confirmado: SPL plano @S → `|Q(f)|=q_base·(f_ref/f)`
    (la consecuencia de opción-1); FRD +10 dB → absoluto lo refleja, relativo
    lo ignora. Campo `anchor` agregado al dataclass.
  - `SourceResponse.to_dict()/from_dict()`: serializa la `g(f)` horneada
    (auto-contenida, reload exacto, sin depender de la sensibilidad al cargar).
  - **`.room` v5** (`main.py`): `FILE_VERSION=4→5`, serializa
    `sources[i].response` y lo reconstruye al cargar. **Compat:** v4 sin
    `response` → `Q` constante (el loader usa `.get()`, sin gate de versión).
  - Tests en `bench_frd.py` (parser, anclaje, round-trip, fase mínima) — todos
    OK. La integración FEM ya la cubre `bench_source_response.py` (una curva
    FRD es solo otro `g(f)`; `H=g·H_base` es agnóstico al origen de la curva).
  - **Falta Fase 2** (UI `SourceEditDialog`: botón cargar/quitar FRD, preview,
    toggle de anclaje, atajo delay/polaridad), **2c** (FoM §8 + cruce modal §9)
    y **3** (data real). NO arrancar sin OK.

  **(e) Fase 2 del plan de fuentes — UI en `SourceEditDialog`:**
  - Grupo "Respuesta en frecuencia Q(f)" en `acoustic_panel.SourceEditDialog`:
    botón **Cargar FRD…** (`QFileDialog`→`frd.load_frd`; si falta fase, pregunta
    fase mínima vs cero), **Quitar**, combo de **anclaje** (absoluto/relativo),
    atajo manual **delay [ms] + invertir polaridad** (`g=±e^{-i2πfτ}`), label de
    estado (cobertura + anchor) y **preview compacto mag+fase** (matplotlib,
    best-effort con try/except).
  - **`get_source()` ahora adjunta `self._response`** (antes lo descartaba —
    bug). `_duplicate_source` también copia respuesta + sensibilidad/f_ref/power.
  - **Re-horneado del anclaje absoluto al cambiar la sensibilidad**: se guarda
    el FRD crudo (`_frd_raw`) y se re-llama `from_frd` al cambiar sens o combo.
    Curvas cargadas del `.room` (sin FRD crudo) o manuales NO se re-hornean
    (combo deshabilitado) — se preservan tal cual.
  - Verificado headless (`QT_QPA_PLATFORM=offscreen`): carga, toggle anclaje,
    delay manual (pendiente −2πτ), quitar, preservación al editar, rebake −6 dB
    al subir 6 dB de sensibilidad. **Falta test visual humano en la GUI real.**
  - **Falta Fase 2c** (FoM §8 + cruce modal §9) y **Fase 3** (data real).

  **(f) Fase 2c del plan de fuentes — figura de mérito + cruce modal:**
  - Nuevo `modal_metrics.py` (cómputo puro, sin Qt):
    - **§8 FoM** — `compute_forced_response` (H en grilla de receptores,
      (N_R,N_f)), `response_figures_of_merit` → `FoM_flat` (planitud media) +
      `FoM_espacial` (consistencia asiento-a-asiento), con ξₙ, suavizado en
      ENERGÍA por 1/N oct, sobre `default_receiver_grid` (5×5 @ z=1.2, 60%
      central, margen 0.5 m). Arregla los 4 defectos del σ de Gunawan.
    - **§9 cruce** — `modal_overlap_crossover`: `M(f)=B_HP·n(f)`,
      `B_HP=2.2/RT60` (Sabine, D5b), `n(f)` densidad NUMÉRICA por ventana 1/3
      oct (ve la forma), `f_cross` = primer cruce de M≥3. `modal_density`,
      `schroeder_frequency` helpers.
  - Oráculos en `bench_modal_metrics.py` (todos OK): FoM plano→0, invariante a
    nivel, ripple→std, var espacial→std; cruce con modos de Weyl ≈ Schroeder
    (145 vs 148 Hz, <10%); modos ralos → f_cross sube (ve la forma);
    end-to-end FEM finito.
  - **NO wireado a UI/Predicción todavía** (es el próximo paso): mostrar
    `f_cross` junto al `f_Schroeder`, FoM junto a la FRF, y alimentar
    `prediction._score_schroeder`/MODAL con el cruce numérico. La capa de
    cómputo está lista y testeada para eso.

  **Archivos nuevos:** `plot_utils.py`, `bench_source_response.py`,
  `verify_examples_c2.py`, `frd.py`, `bench_frd.py`, `modal_metrics.py`,
  `bench_modal_metrics.py`. (Fase 2 editó `acoustic_panel.py`.)

- **16 Jun 2026 — plan de 8 mejoras nuevas (`plan_mejoras_v2.13.md`).**
  Sesión de PLANIFICACIÓN (sin implementar). El usuario pidió plan para: (1) ratio
  Cox + relabel de `RATIO_LIBRARY`; (2) auditar consistencia de RT60 (hay mismatch
  real reportado); (3) altura default 3 m por uso, sin cap de 4 m; (4) geometría
  **lofteada** (dibujar corte lateral por cara, mirror con la opuesta, piso/techo
  iguales); (5) fase (ya casi cubierta por Fase 2; falta offset constante); (5.1/5.2)
  **NO sumar Q por contorno** (ya está en `φₙ(xₛ)`, sería doble conteo); (6) **SBIR**
  con 6 superficies imagen (analítico, par estéreo); (7) bafle **orientado** (frente
  = cara con los 2 círculos) + dims; (8) **optimizador de ubicación de fuentes** como
  eje de predicción separado del de geometría, combinables → 3 predicciones, objetivo
  = combo de FoM(2c)+SBIR+suavidad modal. Secuencia: T1→T3→T5→T2→T4→T6→T9(wiring 2c)→
  T8; T7(geometría) en paralelo. **5 preguntas abiertas** al final del plan. NO
  arrancar a implementar sin OK.

- **16 Jun 2026 — T7 (geometría lofteada) IMPLEMENTADA (Modelo 1).** El usuario
  pidió arrancar por T7. Hecho A+B+C; **el usuario probó el wizard visualmente y
  funciona OK**. Detalle:
  - **Modelo 1** (perfil de tope por pared, piso plano, techo que sigue los topes).
    El "techo sobre rim no-plano" se resolvió fácil: piso+techo desde el mismo
    perímetro muestreado, techo triangulado por el rim (ear-clipping) → watertight.
  - **A:** `geometry.make_lofted_room(base_polygon, wall_profiles)` +
    `bench_lofted_room.py` (regresión plano→shoebox, volumen rakeado, watertight,
    mirror, chequeo de esquina). Todos OK.
  - **B:** `geometry.build_room_geometry(params)` (dispatcher lofteado/prisma),
    wireado en `main.py` (2 puntos, path viejo idéntico), `controls` maneja
    `wall_profiles`, `.room` **v6** (perfiles en `params`; v4/v5→prisma). Headless OK.
  - **C:** `section_dialog.py` nuevo — `ProfileCanvas` + `SectionWizard` (perfil por
    pared, altura de esquina arrastrada, simetría n par). Enganchado a
    `ShapeDrawDialog` ("Cortes laterales…") → `main` → `controls.set_wall_profiles`.
    Lógica OK headless (gable por simetría → V=68.18). **Standalone para test
    visual: `python section_dialog.py`**.
  - **Gotcha:** `QMessageBox` modal bajo `QT_QPA_PLATFORM=offscreen` **segfaultea**
    (artefacto del entorno, NO bug; en GUI real anda).
  - **Limitaciones MVP:** re-abrir no pre-carga perfiles previos; simetría solo n
    par; lid del techo por rim (watertight, algo grueso). **Nuevos:**
    `bench_lofted_room.py`, `section_dialog.py`.

- **16 Jun 2026 — T1 (ratios Cox + relabel) HECHO.** `prediction.RATIO_LIBRARY`:
  corregidos los nombres cruzados → **Louden** (1:1.4:1.9), **Bolt** (1:1.26:1.59),
  **Sepmeyer** (1:1.6:2.33), **+ Cox (1:1.56:1.86)**. `generate_candidates` ahora
  genera 4 (uno por ratio) y `predict()` recorta a **top-3 por score** (`preds[:3]`)
  antes del control negativo. Verificado end-to-end (Cox suele rankear alto en
  salas chicas). El relabel no rompe `.room` (las predicciones no persisten el
  nombre del ratio). Pendiente relacionado (NO hecho, ver plan §7.6): scorear el
  criterio Bonello propio (`bonello_ok_bands` se calcula pero no se scorea).

- **16 Jun 2026 — T3 (altura por uso, sin cap 4 m) HECHO.** `prediction.USE_PRESETS`
  ahora tiene `h_default` por uso (HT/aula/estudio control = 3 m; live 3.5,
  conferencias 3.2, polivalente 5, cámara 6, sinfónica 12 — los 5 últimos
  PROPUESTOS por mí, el usuario puede ajustar). `generate_candidates` calcula
  `h_eff = inputs.height_max if set else USE_PRESETS[use]['h_default']` y lo pasa
  a `_clamp_height_constructive` (reemplaza el cap duro `_DEFAULT_HEIGHT_MAX=4.0`,
  que queda solo de fallback). `prediction_panel._on_use_changed` pre-carga
  `sp_h_max` con el default del uso (editable vía checkbox "Override altura").
  El override del usuario sigue mandando (cap real). Verificado: sinfónica 9.65 m,
  HT ≤2.92, override 3 m baja el caso grande a 3.00.

- **16 Jun 2026 — T5 (offset de fase constante) HECHO.** `SourceEditDialog`: nuevo
  spinbox "Fase (°)" (−180..180) en el atajo manual; `_apply_manual` ahora arma
  `g(f) = e^{i(φ₀ + π·invert)}·e^{-i2πfτ}` (delay + polaridad + offset). `_clear_resp`
  resetea la fase. Verificado headless (fase pura no toca |g|; combinado con delay
  da `-2πfτ+φ₀`). Junto con Fase 2, la fuente ya tiene control de fase completo.

- **16 Jun 2026 — T4 (bafle orientado + dims) HECHO** (falta confirmar render 3D).
  `OmniSource`: campos `orientation` (azimut del frente [°], None→90; acústicamente
  SIGUE omni, es visual + insumo de T8) y `baffle_size` (ancho,alto,prof; default
  0.30×0.50×0.40). `acoustic_viewer.SourceMarkers` reescrito: de `GLScatterPlotItem`
  (puntos) a **bafles** (`_baffle_geom`: caja + woofer + tweeter en el frente) como
  `GLMeshItem` combinado (`shader=None, faceColors`, patrón de FieldSliceItem).
  **Picking/drag NO se tocó**: `viewer._pick_source` usa `_source_positions`
  proyectadas, independiente del item visual. `SourceEditDialog`: grupo "Bafle
  (visual)" (orientación + An/Al/Pr); `get_source` los incluye. `.room` v6 serializa
  orientation+baffle_size. Verificado headless (geom 38v/40f, dialog, serialización);
  el render GL no se puede ver headless. Default orientación 90° (posible refinamiento:
  apuntar al centro de la sala, requiere pasar el centro a `SourceMarkers.update`).

- **18 Jun 2026 — T6 (SBIR) HECHO** (falta test visual humano). El usuario pidió
  seguir por T6. Núcleo + bench + UI, mismo patrón que Fase 0 (cómputo+oráculo
  primero, UI después).
  - **Nuevo `sbir.py`** (cómputo puro, solo numpy + `sources.C0/RHO0`): fuentes
    imagen de **1er orden**. Cada superficie es un plano (`Wall`: `point`+`normal`,
    se toman del `centroid`/`normal` del `FaceGroup`). Imagen
    `x_img = x_s − 2·((x_s−p₀)·n)·n`, presión con el **mismo monopolo** que
    `sources.free_field_pressure` (convención `e^{+ikr}`, consistente con la app),
    atenuada por `R(f)=√(1−α(f))` (`reflection_from_alpha`). Salida en **dB
    relativo al directo**: `SBIR(f)=20log₁₀(|p_dir+Σreflejadas|/|p_dir|)` → 0 dB
    anecoico, +6 dB boundary-lift en LF, peine de notches arriba. Una curva por
    fuente + la **suma compleja** (2 fuentes ≡ L/R/L+R; NO promedio de dBs).
    `SBIRResult.band_extremes` (realce/atenuación máx en banda) y `first_notches`
    (notch teórico c/(4d) por par fuente-pared). `sbir_from_sources(arr, walls,
    receiver, freq)` extrae pos/Q(f)/labels de una `SourceArray`.
  - **Decisión:** solo **1er orden** (estándar SBIR). `order` es parámetro pero
    `order!=1` lanza `NotImplementedError`; 2do orden anotado como extensión.
  - **`bench_sbir.py`** (6 oráculos, TODOS OK): notch en c/(4d) ±3% y −40 dB con
    R=1; flush-mount d→0 → sin notch + 6 dB; boundary lift = 20log₁₀(1+R) para
    varias R; absorbente (α=0.6) → notch −8.5 dB vs −35 dB rígido; shoebox 6
    paredes → 6 notches en los c/(4d) correctos; suma estéreo = suma compleja de
    p_dir.
  - **UI en `acoustic_panel.py`:** `SBIRDialog` (espejo del `FRFDialog`: matplotlib,
    eje log 20–500, grilla 1/3 oct de `plot_utils`, curva por fuente + total,
    `axvline` en cada notch, línea 0 dB, lectura realce/atenuación + distancias
    fuente-pared, export PNG/SVG/PDF/CSV/TXT, SIN audio). Botón **"Ver SBIR
    (fuente-frontera)"** en el grupo FRF. `_open_sbir` arma un `Wall` por
    `FaceGroup` con `R` del material (`_group_to_material_dict`; sin material →
    α=0.03), usa `self.receiver`, freq fija 20–500 Hz (2000 pts).
  - **Verificado headless** (`QT_QPA_PLATFORM=offscreen`): panel importa, el camino
    real shoebox→6 face groups→walls→SBIR da el notch del piso en 142.9 Hz exacto,
    `SBIRDialog` se construye con figura. El render real no se ve headless.
  - **Nuevos:** `sbir.py`, `bench_sbir.py`. (editó `acoustic_panel.py`.) NO toqué
    MANUAL/.tex/.pdf (batch v2.13 es WIP, se integra al manual al final, igual que
    T1/T3/T4/T5/T7). **Siguiente del plan:** T9 (wiring 2c) → T8.

- **18 Jun 2026 — T9 (wiring de 2c a la UI) HECHO** (falta test visual humano).
  Hace visibles/usables las métricas de `modal_metrics.py` (Fase 2c) en la
  pestaña Acústica. Editó solo `acoustic_panel.py`.
  - **f_cross junto a f_Schroeder:** label `lbl_fcross` en el grupo "Campo
    acústico 3D". `_rt60_callable()` arma un `RT60(f)` log-interp de la Sabine
    por cara (`compute_sabine_rt60_per_face` → dict banda→RT60 → np.interp en
    log-f). `_update_modal_crossover()` llama `mm.modal_overlap_crossover(freqs,
    rt_fn, f_lo=20, f_hi=min(freqs[-1], _validity_freq(h_max)))` y escribe el
    label. **Best-effort** (no rompe el solve). Se llama desde `_refresh_modes_combo`
    (tras cada solve/clip y cambio de filtro), `_on_face_materials_applied` (RT
    cambió → B_HP cambió) y `compute_and_show_schroeder`. Maneja `f_cross=None`
    → "> X Hz (no cruza en banda válida)" (pasa con malla gruesa: f_max_malla <
    f_cross teórico; subir npm lo destapa).
  - **FoM junto a la FRF:** en `_compute_frf`, tras la FRF, calcula
    `mm.compute_forced_response(locator, freqs, phis, sources,
    default_receiver_grid(nodes), fa_valid, damping)` con `fa_valid` = eje FRF
    recortado a ≤ f_max_malla, y `mm.response_figures_of_merit` → `FoM_flat`/
    `FoM_espacial`. Se pasan al `FRFDialog` (params nuevos `fom`, `fom_band`),
    que los muestra en un label con tooltip. **Best-effort** (try/except + log):
    si falla, la FRF se muestra igual. Damping = `self._xi_per_mode` (de materiales).
  - **Diferido a T8** (parte *opcional* del plan): alimentar
    `prediction._score_schroeder` con el cruce numérico. Se hace en el optimizador
    (T8), que ya consume FoM+SBIR+cruce, para no tocar el flujo de Predicción acá.
  - **Verificado headless:** shoebox 5×4×3, 40 modos → FoM 4.37/5.28 dB (finitos),
    cruce computa (None en banda válida con npm=2, esperado), panel importa,
    `FRFDialog` con FoM construye con figura. El render real no se ve headless.
  - **NO toqué** MANUAL/.tex/.pdf (batch WIP). **Siguiente del plan:** T8 (el
    grande, optimizador de ubicación; ya tiene T4+T6+2c) o T2 (necesita caso
    testigo del usuario).

- **18 Jun 2026 — T2 auditado (sin cambios de código) + T8 Fase A.**
  - **T2 (auditoría RT60), HECHA la investigación headless** (el usuario pidió
    saltear el caso testigo y seguir). Reproduje las funciones detrás de los 3
    displays de RT en la pestaña Acústica (`lbl_rt60` del panel, resumen del
    `MaterialsDialog`, curva del `RTComparisonDialog`) + la ξₙ de la simulación.
    **Todos leen de `fm.compute_sabine_rt60_per_face`** → coinciden entre sí y
    con Sabine de libro a **precisión de máquina** (recinto 6×4×3; α=0.15 uniforme
    → 0.716 s en los 4; materiales reales → match por banda a 2e-16). V/S de la
    malla = analítico exacto. `compute_sabine_rt60` (split legacy de
    `material_library`) y `classify_surface_areas` están **definidas pero NUNCA se
    llaman** (no hay 4º camino). **Veredicto: no hay bug numérico.** El "mismatch"
    que vio el usuario es una diferencia ESPERADA: (1) Sabine vs Eyring (el diálogo
    de curvas deja agregar Eyring, −8% a α=0.15), o (2) Acústica (α por cara) vs
    **Predicción** (`prediction.rt60_sabine = 0.161·V/(alpha_default·S)` con α
    uniforme=0.10, otro INPUT), o (3) "RT60 medio" (media de 8 bandas) vs "@500"
    vs una banda. Falta el caso testigo para pinpointear cuál (NO se cerró T2).
  - **T8 (optimizador de ubicación) — Fase A HECHA.** Decisiones del usuario
    (vía AskUserQuestion): **pesos por uso + ajustables**; **espacio de búsqueda
    COMPLETO** (8.1 entero). Nuevo `location_opt.py` (puro, reusa modal_metrics +
    sbir + sources): `SourceLayout` (positions/delays/inverted/mounted/baffle →
    `to_source_array` con delay/polaridad como `SourceResponse`); `LocationContext.
    from_modal` (precomputa receptores/escucha/banda/suavidad modal room-fija);
    `evaluate_layout` (FoM banda válida + SBIR en **20–200 Hz** + suavidad →
    sub-scores 0–100 → combinado con pesos); `default_location_weights(use)`;
    `seed_layouts` (mono/estéreo/ancho/subs-¼/esquina/flush) + `optimize_layout`
    (refina top-K semillas: perturbación posición + barrido delay + polaridad →
    top-N con **diversidad por familia de semilla**). `bench_location_opt.py`:
    **6 oráculos OK**. **GOTCHA importante:** `make_room` **centra el recinto en
    el origen** (x∈[−L/2,L/2], y∈[−W/2,W/2], z∈[0,H]) — las paredes SBIR se arman
    desde los face groups (centroide+normal en frame real), NO con coords [0,L].
    Mis primeros oráculos fallaron por asumir [0,L]; el core siempre usó
    `ctx.room_bbox()` así que estuvo bien. La banda SBIR del objetivo es 20–200
    (graves/modal, donde la regla soffit d≤bafle saca el notch de banda); el
    diálogo T6 sigue mostrando 20–500 al usuario.
  - **T8 Fase B HECHA** (integración en `prediction.py`): `LocationPrediction`
    (recinto + `SourceLayout` + score + FoM/SBIR + mensajes); `predict_locations`
    (FEM **completo** del recinto fijo CON locator —no el FEM-lite que lo descarta—,
    paredes desde face groups con R uniforme α=0.10, damping ξₙ=1.1/(fₙ·rt60_target),
    → `optimize_layout` top-N); `predict_combined` (top-K geometrías × su mejor
    layout, mezcla 0.5·geom+0.5·ubicación, `_COMBINED_W_GEOM` calibrable);
    `predict_axis(inputs, mode, fixed_candidate, weights)` dispatcher
    (geometry→Prediction; location/combined→LocationPrediction).
    `bench_predict_location.py`: **4 tests OK** (geometría regresión; ubicación 3
    layouts ordenados/dentro del recinto/mensajes/reconstruye SourceArray; combinado
    geom_score+mezcla; pesos cambian ranking).
  - **T8 Fase C HECHA → T8 COMPLETO.** UI en `prediction_panel.py`: grupo "5. Modo
    de predicción" (combo Geometría/Ubicación/Combinado) + sliders de pesos
    (Planitud/Espacial/SBIR/Suavidad, visibles en ubicación/combinado, default por
    uso vía `lo.default_location_weights`, ajustables). `LocationCard` (renderiza
    `LocationPrediction`; botón "Aplicar ▾" → señal `applySourcesRequested(SourceArray)`
    y, en combinado, "Aplicar geometría" reusa `applyAsParamsRequested`). `_on_predict`
    despacha a `pr.predict_axis(mode, fixed_candidate, weights)`; `_render_results`
    maneja ambos tipos de card. `main.py`: `applySourcesRequested` →
    `_on_prediction_apply_sources` (clear + add + `_refresh_sources_list` → coloca las
    fuentes en Acústica, va a la pestaña). El modo Ubicación usa el diseño actual de
    Geometría (`get_design_params`→`candidate_from_params`). Verificado headless (toggle
    de pesos con `isHidden`, LocationCard emite SourceArray, render mixto, compila).
    **Falta test visual humano** (como T4/T6/T9).
  - **Parte opcional de T9 NO hecha:** alimentar `prediction._score_schroeder` con el
    cruce numérico §9. El optimizador de UBICACIÓN ya usa el cruce vía suavidad modal,
    pero el scorer de GEOMETRÍA sigue con Schroeder analítico. Pendiente menor.
  - **Nuevos:** `location_opt.py`, `bench_location_opt.py`, `bench_predict_location.py`.
  - **ESTADO DEL BATCH v2.13:** hechos T1/T3/T4/T5/T6/T7/T8/T9. Solo queda **T2**
    (auditado headless, sin bug; el usuario lo difirió, falta su caso testigo).
    Transversal pendiente: **test visual humano** de T4 (render bafle), T6 (diálogo
    SBIR), T9 (f_cross + FoM en FRF), T8 (cards de ubicación) en la GUI real, y
    **integrar el batch al MANUAL** (.md/.tex/.pdf) cuando se cierre.

- **18 Jun 2026 — FIX render del bafle (T4): GLMeshItem(shader=None) NO renderiza.**
  El usuario: "puse dos fuentes y no se ven los parlantes". El render NO crasheaba
  (el item se creaba y se agregaba a la vista), pero **un `GLMeshItem` con
  `shader=None` + `faceColors` no se dibuja en este OpenGL** (probado: opaque y
  translucent, ninguno se vio). El patrón que SÍ funciona en este viewer es el del
  RECINTO (`viewer.IsoViewer.update_geometry`): mesh con `shader="shaded"` + color
  único, y aristas con `GLLinePlotItem(pos=float32, color=ÚNICO, mode="lines")`.
  El usuario pidió además el bafle "estilo aristas rosas como el recinto".
  **Fix (`acoustic_viewer`):** se eliminó `_baffle_geom`/el `GLMeshItem`; nuevo
  `_baffle_wireframe(center,size,yaw)` devuelve segmentos (12 aristas del prisma +
  2 círculos woofer/tweeter en la cara frontal). `SourceMarkers` ahora dibuja
  `GLLinePlotItem` (pos **float32**, color **único** rosa `(0.96,0.74,0.95,1.0)` =
  `EDGE_COLOR` del recinto; naranja `(0.98,0.55,0.05,1.0)` para la seleccionada,
  en un item aparte), `mode="lines"`, sin shader ni glOptions custom. Verificado
  headless (52 segs/fuente; 2 items con seleccion, 1 sin; clear OK). **Falta que el
  usuario re-confirme a ojo.** **GOTCHA fuerte para el futuro: en este proyecto NO
  usar `GLMeshItem(shader=None, faceColors=...)` — no renderiza. Para mallas usar
  `shader="shaded"`+color; para wireframe, `GLLinePlotItem` float32 + color único
  (patrón del recinto).**

- **18 Jun 2026 — Bafle: inclinación (pitch) + montaje en pared (durante test
  visual).** El usuario pidió rotar/inclinar/montar; rotar (azimut) ya estaba.
  Decisiones del usuario: `mounted` = one-shot informativa (no se re-pega solo);
  aplicar al OK (sin preview en vivo). **Principio (confirmado con el usuario):**
  orientación/pitch/montaje son **puramente geométricos** (dibujo 3D + insumo T8);
  NO tocan FEM/FRF/SBIR para una posición dada (el monopolo es omni, ignora el
  ángulo) — verificado headless (|p| idéntico con/sin ángulo). Montar SÍ cambia el
  SBIR pero por la POSICIÓN (acerca a la pared), no por el ángulo.
  - `sources.OmniSource`: nuevos `pitch: float=0.0` (elevación del frente, −90..90,
    0=horizontal) y `mounted: bool=False`.
  - `acoustic_viewer._baffle_wireframe(center,size,yaw,pitch)`: base local SIN roll
    (n=frente, ey=ancho horizontal nivelado, ez=n×ey inclina con pitch). pitch=0
    reproduce exacto el solo-yaw.
  - `SourceEditDialog`: spinbox "Inclinación (°)" + botón "Pegar a pared más
    cercana" (param nuevo `get_walls`); `get_source` devuelve pitch+mounted.
    `_snap_to_wall`: pared más cercana (mín |(p−c)·n|), mueve flush (d_bafle/2),
    orienta el frente hacia el interior (normal hacia el centro del recinto, robusto
    al winding), mounted=True.
  - Cableado: `AcousticPanel._get_baffle_walls` (face groups → (centroide,normal))
    pasado al diálogo desde `_add_source`/`_edit_source` y desde `main` (doble-click).
  - `.room`: `pitch`+`mounted` agregados al dict de fuente (save + load con `.get()`,
    SIN bump de versión; v6 viejo carga con pitch=0/mounted=False).
  - Verificado headless (pitch inclina, acústica invariante, snap a +X→180°,
    round-trip). **Falta test visual humano.**

- **18 Jun 2026 — Gestos directos para orientar el bafle en el viewer 3D.** El
  usuario pidió rotar/inclinar con teclado+mouse. Implementado en `viewer.IsoViewer`:
  - **Alt+Ctrl + click izq. sostenido, mov. HORIZONTAL** → **rota** (azimut).
  - **Shift+Alt+Ctrl + click izq. sostenido, mov. VERTICAL** → **inclina** (pitch;
    arrastrar arriba = inclinar arriba).
  - (Descartado el gesto de rueda: en la práctica el clic central/rueda ya orbita
    la cámara y confundía — pedido del usuario. La rueda vuelve al zoom normal.)
  - `mousePressEvent`: `is_orient = Left and Alt and Ctrl` → pick → `_orient_source_idx`
    + `_orient_mode` = "tilt" si Shift, si no "rotate". **Mover** ahora es
    `is_shift_left = Left and Shift and NOT Alt` (excluye el combo de tilt).
    `mouseMoveEvent`: emite `sourceRotateRequested(idx, diff.x·0.6)` o
    `sourceTiltRequested(idx, −diff.y·0.5)`. `mouseReleaseEvent`: resetea.
  - Señales `sourceRotateRequested(int,float)` / `sourceTiltRequested(int,float)`;
    constantes `BAFFLE_ROTATE_DEG_PER_PX=0.6` / `BAFFLE_TILT_DEG_PER_PX=0.5`
    (ajustables). NO pisa Shift+drag (mover), Shift+Ctrl (mover Z) ni Ctrl+Right (agregar).
  - `main`: `_on_source_rotate_from_viewer` / `_on_source_tilt_from_viewer` mutan
    `orientation`/`pitch` **in-place** (clamp pitch −90..90, azimut %360) y redibujan
    el marker (`set_positions`) — solo visual + T8, no toca acústica.
  - **BUG ADYACENTE ARREGLADO:** `_on_source_moved_from_viewer` (Shift+drag)
    **reconstruía** la `OmniSource` y perdía orientación/pitch/bafle/respuesta/
    sensibilidad/mounted. Ahora muta SOLO `position` in-place → preserva todo.
  - Verificado headless (señales con deltas correctos, `_pick_source` mockeado;
    compila + importa). **Falta test visual humano.**

- **18 Jun 2026 — FIX cuelgue al arrastrar (rotar/inclinar/mover) bafle + cambio de
  binding del tilt.** (a) El usuario reportó que al inclinar, la app se congela y hay
  que matarla desde el cmd (NO segfault — el proceso queda vivo → cuelgue del event
  loop). **Causa:** `SourceMarkers.update` hacía `removeItem`+`addItem` de los items
  GL en CADA frame del drag → reconstruir el scene graph a 60+ Hz cuelga pyqtgraph
  (el MISMO gotcha que el comentario de `ReceiverMarker` ya documentaba). **Fix:**
  `SourceMarkers` ahora usa **DOS items persistentes** (`_item_normal` rosa /
  `_item_sel` naranja) actualizados **in-place via `setData`** + `setVisible` (nunca
  remove/add en el drag). `clear()` sí los remueve. Verificado headless (30 frames de
  tilt → mismos 2 objetos, scene graph estable). Cura tilt, rotate y Shift+drag mover.
  **REGLA: en este viewer, NUNCA remove/add items GL por frame en un drag — usar
  `setData` in-place (como ReceiverMarker y ahora SourceMarkers).**
  (b) Cambio de binding (el clic central/rueda ya orbitaba): **tilt = Shift+Alt+Ctrl
  + Left (arrastre vertical)**; rotate = Alt+Ctrl+Left (horizontal); se descartó el
  gesto de rueda (vuelve a zoom). Mover = Shift+Left SIN Alt.

- **18 Jun 2026 — La "ventana que crashea" al inclinar era pérdida de foco por
  Shift+Alt (atajo de Windows).** El usuario pudo volver con Alt+Tab y el cmd no
  mostraba traceback → NO era crash ni cuelgue: **Shift+Alt es el hotkey de Windows
  para cambiar idioma/teclado**, robaba el foco y mandaba la ventana atrás. Rotar
  (Alt+Ctrl, sin Shift) andaba bien; solo el tilt (con Shift) fallaba. **Fix: se
  unificó en UN solo gesto SIN Shift** → **Alt+Ctrl + Left + arrastrar: horizontal =
  azimut, vertical = pitch** (ambos a la vez, tipo trackball). Se quitó el `_orient_mode`
  (ya no hay dos modos). Verificado headless (drag diagonal → azimut+pitch juntos).
  **GOTCHA: evitar combos con Shift+Alt en gestos (Windows lo usa para cambiar de
  idioma).** El fix in-place de `setData` del marcador (entrada previa) igual era
  correcto y necesario (evita el cuelgue real por reconstruir el scene graph).

- **22 Jun 2026 — wiring A6/A3 al score, Toole minado, C13/C21 COMPLETO, MANUAL v2.13
  integrado.** Sesión larga. Cinco bloques:
  1. **Wiring A6 (FSI) + A3 (Bonello) al `score_total` de geometría** (`prediction.py`):
     decisión de política del usuario = *baratas entran, caras informativas*. A6/A3 entran al
     grupo MODAL (pesos recalibrados: `0.25·Bolt + 0.15·FSI + 0.05·Bonello + 0.20·Q + 0.20·RT
     + 0.15·Sch`; Bolt+FSI+Bonello = bloque "distribución pareja" 0.45, tres lentes del mismo
     fenómeno). **D5/C8/cruce§9 quedan INFORMATIVAS**: D5 (Bass Ratio) daría 1.0 constante en
     geometría (no hay RT60 por banda sin materiales → vive en Acústica); C8/cruce§9 necesitan
     `phis` que el FEM-lite descarta. Chips FSI/Bon + lectura del ψ en la card (`prediction_panel.py`).
  2. **Libro Toole (Sound Reproduction) minado** → **no suma criterio geom/fuente nuevo**:
     relativiza los ratios (su tesis = gestión activa > proporción). Es **respaldo**: nota
     "range of validity" del ratio en A33, Geddes (absorción>forma) refuerza A36, modos LF=fase
     mínima + SFM respaldan C13/C21. Offset libro↔PDF = +19. Documentado en
     `criterios_room_geom_fuente.md` + `referencias/_indice.md`.
  3. **C13/C21 (corregibilidad EQ) COMPLETO** — era el ÚNICO pendiente del ciclo de criterios.
     Método (idea del usuario, descartó el cepstrum por frágil): **consistencia espacial +
     envolvente sin cancelación** (`H_env = Σ|término modal|` vs `H_real = |Σ|`; `cancel_depth`
     mide cancelación destructiva SIN cepstrum) + spread espacial (capta SBIR). **Plan de rigor
     de 6 niveles, TODOS hechos** (detalle en `plan_gaps_criterios.md` Fase 3): #1 loop cerrado
     (EQ global simulado mide `improvement_flat` + `fom_espacial` IRREDUCIBLE, invariante a EQ
     global); #3 convergencia (encontró 2 problemas: malla npm≥3 vía `eq_diagnosis_mesh_ok`
     ppw~15, y flag binario frágil → **grado continuo** `correctability∈[0,1]` + verdict
     3-estados); #2b ceros RHP exactos (`modal_minphase_zeros`) → midió que el proxy NO
     sobre-marca en salas reales (0%); #4 insensible a ξ (D5b no compromete); #5 separar
     fuente/sala (`flat_source`) + peor caso L+R; #6 reproduce Welti (multi-sub), #6c bloqueado
     por datos. **UI:** overlay rojo en `FRFDialog` (zonas no-ecualizables), sub-banda confiable.
     Nuevos: `modal_metrics.py` (3 funcs) + 5 benches `bench_eq_*.py`.
  4. **MANUAL v2.13 INTEGRADO** (`MANUAL.md` 11 ejes A-L + `.tex` condensado + `.pdf`
     recompilado, 32 pág). Compila **100% limpio** tras 2 fixes: `✓`→`\checkmark`, y `\%` de
     babel-spanish (`\AtBeginDocument{\def\%{\@percentchar}}` mata los "Incompatible glue units").
  5. **C9 CONFIRMADO completo** (no refinable): el paper base Fazenda 2015 (modal decay) ya está
     en `referencias/` y ya implementa C9. El "Avis 2007 Q-factor" sería un paso atrás — descartado.

  **Pendiente tras esta sesión:** **test visual humano** (T6/T8/T9 + A6/A3 card + C13/C21 overlay
  + gestos/snap bafle) — el único cuello de botella para cerrar el batch v2.13 + integrar al manual
  ya hecho. **T2** (RT60) espera el caso testigo del usuario. Opcionales/bloqueados: C13/C21 #6c
  (medición real), `build_mac.sh`. Estado vivo en memoria `[[batch-v2.13]]` y `[[criterios-research]]`.

- **26 Jun 2026 — BATCH v2.13 CERRADO (test visual humano OK).** El usuario corrió la GUI
  desde fuente y confirmó visualmente los 6 ítems que faltaban: **T6** (SBIRDialog, 6 superficies),
  **T9** (FoM_flat/FoM_espacial + f_cross junto a f_Schroeder en la FRF), **C13/C21** (overlay
  rojo/amarillo de corregibilidad EQ en `FRFDialog`), **T4** (snap = botón *"Pegar a pared más
  cercana"*; el gesto Alt+Ctrl+drag es para girar/inclinar), **A6/A3** (chips FSI + Bonello y la
  lectura del ψ en la sección MODAL de la card de Predicción), **T8** (selector de modo
  geometry/location/combined + sliders de pesos + `LocationCard` + botón aplicar fuentes →
  Acústica). **Estado del batch: TODO hecho salvo T2** (auditoría RT60, diferido por el usuario,
  espera caso testigo — NO bloquea el cierre). El MANUAL v2.13 ya estaba integrado (sin cambios
  que ameriten tocar el changelog del manual).
  - **Fix de color (esta sesión):** los dos labels de diagnóstico de la FRF (`fom_lbl`, `eq_lbl`
    en `acoustic_panel.py`) estaban en gris (`#333`) y rojo oscuro (`#7a2222`) → ilegibles sobre el
    fondo oscuro Catppuccin. Pasados a **blanco `#ffffff`**. El sombreado rojo/amarillo del plot
    (semántico) queda igual.
  - **TRABAJO NUEVO pedido por el usuario (fuera del batch, PENDIENTE DE DECISIÓN):**
    (1) **Gate de materiales + preset placeholder** — hoy Predicción NO usa materiales por cara
    (trabaja de un RT60 target tipeado, invierte Sabine); Acústica SÍ (ξ por cara) pero sin
    asignar cae a α=0.03 (casi rígido) → diagnósticos irreales. Pedido: requerir materiales o
    ofrecer un preset. **Placeholder acordado: {piso: madera, paredes: ladrillo, techo: madera}**
    (el sistema de presets completo se discute aparte). Falta decidir dónde va el gate (Acústica /
    Predicción / ambos). (2) **Undo/redo global** ctrl+z/ctrl+y, hasta 10 acciones — el ítem más
    grande (patrón command/memento transversal); falta acordar alcance antes de arrancar. El
    usuario descartó la pregunta de prioridad → esperar su próxima instrucción.

- **27 Jun 2026 — v2.14: undo/redo GLOBAL + gate de materiales en Predicción (los dos
  HECHOS y confirmados en GUI).** Las dos tareas "nuevas" de la entrada anterior, resueltas.
  1. **Undo/redo global** (`main.py`): el undo viejo solo deshacía geometría. Generalizado a
     **snapshot del estado completo** reusando la serialización `.room` (`_capture_state` /
     `_restore_state`). Un **timer de polling (~400 ms)** hace dirty-check: si el estado
     serializado cambió vs el último snapshot, lo apila → **global por construcción**, no hay
     que instrumentar cada mutación del panel gigante (el riesgo era olvidarse una). **Decisiones
     del usuario:** drag continuo = 1 acción (check de "settle" `_note_activity`/`_last_change_t`);
     snapshot = inputs, NO resultados FEM; límite 10 (`UNDO_LIMIT`). Re-entrancia con `_restoring`.
     Ctrl+Z/Y ya estaban cableados. Test: `smoke_test_undo.py` (5/5).
  2. **Gate de materiales en Predicción** (`prediction.py` + `prediction_panel.py`). **Decisión
     del usuario: va en Predicción** (Acústica es donde se retoca el material por cara). Al
     **Predecir** sin elegir absorción → **warning** con 3 caminos: (a) *que elija el programa*
     (RT por uso = comportamiento viejo, `alpha_mode="target"`); (b) *preset* {piso madera /
     paredes ladrillo / techo madera} (`PRESET_SURFACE_ALPHA=(0.10,0.044,0.095)`); (c) *coef.
     uniforme* α editable (default 0.31). **Opción A (confirmada): los materiales DETERMINAN el
     RT60 por candidato** (Sabine hacia adelante → `effective_rt60(inputs, cand)`); threadeado en
     `verify_candidates_parallel` (param `inputs`), `score_prediction`, `_build_location_context`
     y el control negativo. Botón "Materiales" en el grupo de objetivos (muestra/cambia la
     elección, `_abs_choice`). El preset da RT ~1.8 s (madera/ladrillo absorben poco → sala viva;
     es honesto). Test: `bench_prediction_materials.py` (7/7). El **sistema de presets completo
     queda pendiente de discusión** (esto es placeholder).
  3. Fix de color: labels de diagnóstico de la FRF → blanco (ya estaba, ratificado).
  4. **Editor de forma — edición numérica exacta (confirmado en GUI, "muy bien").**
     (a) **Planta** (`shape_dialog.py`): cada arista muestra su **longitud** en un chip
     clickeable; click → valor exacto, `set_edge_length` mueve el 2º vértice en la dirección
     de la arista con el 1º fijo, sin snap (`edgeLengthEditRequested`). (b) **Origen corrido**:
     el (0,0) del canvas pasó del centro a la **esquina inferior-izquierda** (ventana de mundo
     `_recompute_window`, margen negativo `ORIGIN_MARGIN_FRAC=0.12`; `_world_to_screen`/`_snap`/
     grilla reescritos) para dibujar en cuadrante positivo con una esquina en (0,0). (c) **Cortes
     laterales** (`section_dialog.py`): cada punto del perfil muestra su **altura** clickeable
     (`set_point_height`, editables los no-pinneados); y la pared opuesta pasó de checkbox a
     selector **Libre/Espejo/Igual** (`_on_opp_changed`; Espejo=(1−t), Igual=copia directa en t).
     Tests: `smoke_test_shape_edge.py` (5/5), `smoke_test_section_edit.py` (6/6).
  5. **Sistema de presets de materiales COMPLETO (Predicción + Acústica) — confirmado GUI.**
     Reemplaza el placeholder broadband (forks elegidos por el usuario: 1b armar-el-tuyo, 2b
     conectar con Acústica, 3a RT representativo). Definido UNA vez en `material_library.py`:
     `MATERIAL_PRESETS` (5: Reflectante/Estudio tratado/Home theatre/Aula/Neutra) → materiales
     reales del catálogo por superficie con α POR BANDA; `resolve_material` (match por nombre
     normalizado SIN acentos vía `unicodedata`, robusto) + `preset_surface_materials`.
     **Predicción** (`prediction_panel.py`): gate 3 caminos (programa/uniforme/materiales);
     "materiales" = combo de presets + 3 combos armar-el-tuyo (catálogo, ~430). `effective_rt60`
     modo "materials" (α por banda → RT representativo 500/1k, por candidato; **`surface_alpha`
     ahora = 3 dicts {banda:α}**, antes era tupla broadband — `PRESET_SURFACE_ALPHA` eliminado).
     Botón **"Aplicar a Acústica"** (`applyMaterialsRequested` → `main._on_prediction_apply_materials`
     → `acoustic.apply_zone_materials` asigna por `g.kind`; deshacible por el undo global).
     **Acústica** (`face_materials.py` MaterialsDialog): botón **"Preset nombrado…"** (`_named_preset_dialog`)
     con los mismos 5 presets, junto al preset manual. **Fix layout:** `main.py` `self.status` ahora
     con **word-wrap** (un mensaje largo con nombres de materiales estiraba el label, apretaba el
     panel izquierdo y cortaba el contenido de Acústica). Test `bench_prediction_materials.py` 9/9.
     Único pendiente (opcional, futuro): guardar presets PROPIOS a disco.
  **MANUAL v2.14 integrado** (MANUAL.md changelog "Cambios v2.14" A/B/C/D/E + `.tex` + `.pdf` 33 pág).

- **7-8 Jul 2026 — Feature MUEBLES + calibración con RIRs medidas + subida a GitHub.**
  Sesión larga (nota: los changelogs v2.15/v2.16 viven en la memoria persistente
  `[[batch-v2.13]]`/`[[gui-batch-v2.16]]`, no en este §13). Tres bloques:

  **1. Feature MUEBLES (nuevo, `furniture.py`).** Mobiliario en el modelo modal, 3 canales físicos:
  - **Fase A (rígido):** `carve_mesh(nodes,tets,muebles)` quita tets por centroide-adentro +
    PODA huérfanos + reindexa (evita M singular). Va ENTRE build_volume_mesh y build_KM, sin
    tocar la API estable. `Furniture` dataclass (box/cylinder + provenance + to_dict/from_dict).
    Significancia >λ_max/8. `bench_furniture.py` 13/13 (signo perturbativo textbook: obstáculo al
    centro → (1,0,0) BAJA [nodo], (2,0,0) SUBE [antinodo]; consistencia losa≡4×4×3 <0.6%).
  - **Fase B (absorción):** `furniture_boundary_faces` extrae la interfaz aire-mueble (caras
    kept-vs-removed; **GOTCHA: extraer de la malla ORIGINAL, no la tallada** — el locator evalúa
    por posición mundial) + `augment_surface_with_furniture` mete esas caras como FaceGroups al
    A36 existente. `bench_furniture_absorption.py` 5/5. Re-validación TP7: rígido EMPEORA,
    absorbente RECUPERA (+0.048 vs A) → un sillón DEBE absorber (material tesis).
  - **Fase C espina (headless):** `solve_modal_with_furniture` + `furniture_xi`; **`.room` v7**
    (holder `AcousticPanel.furniture`, serialize/restore en main.py, `FILE_VERSION 6→7`, compat).
    `bench_furniture_phaseC.py` 7/7.
  - **Canal SBIR-mueble:** rolloff de panel finito de Rindel, ADITIVO a `sbir.py` (`Wall.area`
    opcional; area=None=plano infinito=comportamiento previo). `furniture_walls`. `bench_furniture_sbir.py` 6/6.
  - **FALTA (capstone, necesita build+test visual):** UI diálogo agregar/editar muebles + wireframe
    en viewer (patrón bafle: GLLinePlotItem float32 color único, NUNCA GLMeshItem shader=None) +
    wiring del carve/xi/SBIR al camino LIVE del panel (`_compute_modes_async`, `_xi_per_mode_from_faces`).

  **2. Calibración con RIRs medidas (TP7 control room) — investigación grande.** Nuevo `rir.py`
  (load_rir, deconvolve_sweep, rir_to_frf, rt60 Schroeder T30/T20/T10 con flags, find_modal_peaks)
  + `bench_rir.py` 14/14 + `analyze_rirs.py`. **Todo el detalle en memoria `[[calibracion-rirs]]`.**
  Hallazgos que hay que saber:
  - **RIRs TP7: YA deconvolucionadas Y NORMALIZADAS POR ARCHIVO** (pico −6.02 dBFS idéntico en las
    7) → nivel absoluto y entre-posiciones NO comparable → **tabla en dB SPL IMPOSIBLE** con estos
    archivos. Lo único absoluto y confiable es el RT60. El sweep arrancó en ~70 Hz → perdió los
    modos axiales de 1er orden (43/61 Hz).
  - **Auditados TODOS los componentes del modelo** (convergencia de malla, CAD-vs-paramétrico,
    material, orden de elemento P2/P3, fuente/TRF, acople L/R/LR, frame, posición) → **TODOS
    correctos**. La corr FRF punto-a-punto baja (~0.33) NO es un defecto del software: es el
    **régimen físico M>1** (transición→f_Schroeder=164 Hz) que hace la FRF puntual *ill-posed*.
    Validación estadística correcta: **varianza espacial medida 3.43 vs simulada 3.39 dB (ratio
    0.99)**. Sala casi cuadrada (3.91×3.96) → par degenerado en 86 Hz (peor caso).
  - **Element order P2/P3 NO ayuda** (error numérico ya <0.5%; aplica D1). **Impedancia compleja
    descartada** (D5b). Para predecir en M>1 hay que desarrollar la **rama estadística** (FEM-SEA /
    SEA / varianza-vs-M / RMT), no la curva exacta. Es material fuerte del paper D de la tesis.

  **3. GitHub — el proyecto YA tiene git (ver §6 y §8, actualizados).** Repo PRIVADO
  `github.com/tomasdivididos-blip/prototipo-1`. `.gitignore` excluye dist/build/zips/referencias.
  `gh` en `C:\Program Files\GitHub CLI\gh.exe`.

  **Pendiente de MANUAL** (chico, ya shippeado sin integrar): materiales en orden **alfabético**
  (`material_library.load_folder` sort + default "Alfombra fina" pineado en acoustic_panel) +
  preview **default plana** en `SourceEditDialog`. El feature muebles + la calibración también
  esperan integración a MANUAL cuando cierren.

  **Nuevos archivos:** `furniture.py`, `rir.py`, `bench_furniture.py`, `bench_furniture_absorption.py`,
  `bench_furniture_phaseC.py`, `bench_furniture_sbir.py`, `bench_rir.py`, `analyze_rirs.py`, `.gitignore`.

- **19 Jul 2026 — Muebles: capstone visual (UI) + v2.18 + PR.** Se cerró el
  feature MUEBLES de punta a punta. El cómputo (carve/ξ/SBIR) ya estaba en `main`
  (PR #2, `006ca22`, vía agente remoto); esta sesión agregó la **UI y la
  manipulación directa**. Rama `muebles-ui` off `main` (commit `918c730` código +
  commit de docs); MANUAL v2.18 integrado (.md §6.4 + changelog A-F, .tex, .pdf 35
  pág, limpio). Test: `smoke_test_furniture_ui.py` **20/20**; benches de cómputo
  de muebles y de fuentes verdes.
  - **UI:** grupo "Muebles" en Acústica (Añadir/Editar/Quitar/Duplicar),
    `FurnitureEditDialog` (caja/cilindro, centro, tamaño, yaw, **pitch**, material,
    etiqueta), `FurnitureMarkers` (wireframe verde-azulado, patrón GLLinePlotItem
    in-place — NUNCA GLMeshItem shader=None). Material por mueble en un holder
    `_furniture_mat_names` {idx: nombre}, persistido en `.room` como
    `furniture_materials` (paralelo a `furniture`, aditivo; v7 → todos rígidos).
  - **Manipulación directa** (mismos gestos que fuentes, en `viewer.py`): Shift=mover
    XY, Ctrl+Shift=Z, Alt+Ctrl=rotar yaw (horiz) / inclinar pitch (vert), doble-click=
    editar. Señales `furnitureMove/Edit/Rotate/TiltRequested`. **Las fuentes tienen
    prioridad de picking** (`_pick_furniture` corre solo si `_pick_source`==-1). Move/
    rotate/tilt mutan in-place + `set_positions` (sin reconstruir la lista → sin cuelgue).
  - **Decisiones de diseño (importantes):**
    1. **Pitch FÍSICO**: se agregó `pitch` a `Furniture` (dataclass + `contains()` +
       to/from_dict). Afecta el CARVE (lo que inclinás es lo que se talla), no es solo
       visual como el bafle. `pitch=0` reduce EXACTO al caso solo-yaw → los benches de
       cómputo no se tocan. Ejes locales (yaw sobre z, luego pitch sobre ey) compartidos
       entre `contains`, `_furniture_wireframe` y el AABB del panel → dibujo = carve.
    2. **#2 "aparecían en el origen" era el FRAME**: el recinto vivo está CENTRADO en el
       origen (gotcha `make_room`/`build_room_geometry`); mi default asumía esquina
       (`Lx/2`). Fix: `_room_center_default()` usa el bbox real del surface (centro de
       planta, apoyado en piso) → robusto a cualquier `origin_mode`.
    3. **Colisiones por AABB** (`_furniture_conflict`): un mueble no se superpone con
       otro mueble, con el **bafle de un parlante** (`_source_baffle_aabb`), ni sale del
       **recinto** (`_room_bbox`). Colisión-STOP en el drag (revierte si conflicto);
       aviso en Añadir/Editar. Conservador para cajas rotadas/inclinadas (envolvente).
    4. **Fuentes y receptor se traban** en las paredes al arrastrar: `_clamp_to_room_bbox`
       en `_on_source_moved_from_viewer`/`_on_receiver_moved_from_viewer` (CLAMP = desliza
       pegado a la pared, no freeze — más natural para un punto; distinto del freeze de
       muebles, decisión consciente). Si el usuario pide freeze igual que muebles, cambiar ahí.
  - **Contexto de git de la sesión:** el usuario estaba en la rama `juego-quiz-acustica`
    (su WIP del juego PWA) con `juego/banco/*.js` modificados sin commitear. Para NO
    ensuciar esa rama, se hizo `git stash push` de esos 4 archivos, `git switch -c
    muebles-ui main`, se commiteó muebles, y al final `git switch juego-quiz-acustica` +
    `git stash pop` para restaurar su WIP intacto. `recinto3.room` (untracked) es del usuario.
  - **Falta:** push de `muebles-ui` + PR (el usuario dijo "commitea", no "push"; ofrecido).
    Validación limpia definitiva del efecto físico del mueble sigue siendo A/B controlado
    (ver [[calibracion-rirs]]).

- **29 Jul 2026 — Muebles: presets armados (compound) + v2.19 + PR #5.** Rama
  `muebles-presets` off main, mergeada (commit `acce53f`). MANUAL v2.19 integrado
  (.md §6.4 + changelog A-D, .tex, .pdf 36 pág). `smoke_test_furniture_ui.py` 27/27.
  - **Decisión previa (experimento de física, `scratchpad/shape_matters*.py`):** ¿la
    forma exacta de un mueble importa vs su bounding box? Resultado robusto (barrido):
    efecto-forma es **segundo orden** (0.3-1.4% en freqs, ~1-3× el ruido de malla),
    depende MUCHO de la posición (máx en esquinas = antinodos), y una forma cóncava
    (L) ya se puede componer con 2 cajas. Cilindro vs su caja = cosmético (0.8×).
    **Conclusión:** dibujar/CAD es UX, no mejora de predicción; CAD-para-predicción
    descartado. El usuario igual quiere presets "con forma" (cosmético) + CAD para
    escanear su estudio real (OBJ), que es un caso de captura, no de fidelidad.
  - **Compound (forma física):** nuevo `kind="compound"` en `Furniture` con `parts`
    (lista de sub-Furniture en frame LOCAL). `contains` = unión (transforma world→local
    por yaw/pitch del compound, OR de las partes). `aabb()` método unificado (box/
    cylinder/compound). `_local_axes()` compartido por contains/aabb/wireframe → dibujo
    = carve. box/cylinder reducen EXACTO (benches intactos). Persistencia: `parts` en
    to_dict/from_dict (el `.room` los serializa solo, sin bump de versión).
  - **27 presets** (`FURNITURE_PRESETS` + `FURNITURE_PRESET_GROUPS` + `PRESET_PLACEMENT`):
    menú agrupado General/Aula/Estudio. `make_preset(name)`→(Furniture, material).
    Placement floor/ceiling (nubes al techo, `_insert_preset` calcula z). Materiales
    sugeridos VÁLIDOS del catálogo (428 mats; usé Madera, Asientos tapizados, Panel
    acústico, Panel de madera con cámara de aire, Cielorraso lana de roca, contrachapado;
    metálicos = rígido). **Modelado honesto:** difusión (QRD) y sintonía Helmholtz NO
    se simulan (FEM LF) → geometría + material aprox; absorbentes de banda ancha sí.
  - **Fixes del test visual:**
    1. **Picking por silueta** (viewer): `_pick_furniture` agarra si el cursor cae en
       el bbox PROYECTADO en pantalla (8 esquinas), no solo a <28px del centro. El panel
       pasa `set_furniture_bboxes`. Los muebles grandes (sillón/mesa/biblioteca) tenían
       el centro en un hueco del wireframe → no se agarraban. (Headless no lo reproduce:
       la cámara iso proyecta chico; test t26 usa una caja 3 m.)
    2. **Rotación solo yaw:** Alt+Ctrl para muebles emite SOLO rotate (saqué el tilt del
       gesto). El componente vertical del arrastre acumulaba pitch (decenas de grados) →
       el mueble se "caía", su AABB crecía y se trababa. Pitch se edita por el diálogo.
    3. **El piso no atrapa** a los muebles (`_furniture_conflict` tolera z<piso;
       inofensivo para el carve). Antes, tiltear un mueble apoyado lo dejaba "hundido"
       y bloqueaba movimientos posteriores.
  - **Dialog:** `FurnitureEditDialog` maneja compound (`_compound_src`): edita posición/
    orientación/pitch/material/etiqueta, preserva `parts`. `_furn_item_text` muestra "preset".
  - **Falso susto de git:** el merge del PR #5 mostró "create mode juego/..." → parecía
    contaminar main. NO fue así: `juego/` entró a main por el **Merge del PR #3**
    (juego-quiz-acustica, commit `6a7ebe4`, mergeado en GitHub por el usuario). Mi rama
    tenía 0 juego; el merge solo tocó los 5 archivos de muebles. **main ahora incluye el
    juego (PWA) + la app acústica, todo del usuario.** Verificar con `git ls-tree` si dudás.
  - **Siguiente (acordado):** feature **CAD (OBJ)** — `kind="mesh"` vía trimesh.contains
    + pipeline CAD del recinto + embeber en `.room`. Caso de uso: escanear el estudio
    con el celu → SketchUp → separar muebles → OBJ por pieza. Ver [[calibracion-rirs]].

- **30 Jul 2026 — CAD (OBJ) para muebles + gizmo de rotación 3 ejes + roll. v2.20 + PR.**
  Rama `muebles-cad` off main. MANUAL v2.20 integrado (.md §6.4/§6.4.1 + changelog
  A-D, .tex, .pdf 36 pág, compila limpio). `smoke_test_furniture_ui.py` **36/36**,
  `bench_cad.py` nuevo (9 oráculos), los 5 benches de muebles verdes.
  - **`kind="mesh"` en `Furniture`**: `mesh_verts`/`mesh_faces` en frame LOCAL
    (centrado en su bbox), `contains` vía `trimesh.contains` con world→local por
    `to_local`. `aabb` desde `mesh_verts` directo (NO construir trimesh: corre por
    frame en el drag). Persistencia embebida en el `.room` (verts redondeados a
    0.1 mm), aditiva, sin bump de versión. La silla fixture pesa 2.3 KB.
  - **`load_furniture_mesh(path)`**: **GOTCHA CLAVE** — `trimesh.load` con el
    `process=True` default **weldea vértices y ROMPE el watertight** de un modelo
    multi-cuerpo (silla = asiento+respaldo+patas que se tocan → V pasó de 0.023 a
    0.187 y quedó no-watertight). Hay que cargar con **`process=False`**; la
    reparación (merge/fill_holes/fix_normals) se aplica SOLO si no es watertight.
  - **Fixture `silla_test.obj`** (72 caras, watertight) generada con trimesh, NO
    bajada de internet: sirve de oráculo (geometría conocida). Decisión: para
    testear `contains` conviene malla limpia propia; el caso "escaneo sucio" se
    cubre con la reparación + aviso, no con el fixture.
  - **Gizmo de rotación (`viewer.py`, autocontenido)**: 3 anillos (yaw celeste /
    pitch ámbar / roll verde), hover con Alt+Ctrl, anillo bajo el cursor en
    magenta, click+arrastre gira SOLO ese eje. **El eje se elige ANTES de mover**
    → resuelve de raíz el problema de v2.19 sin volver al trackball. Requiere
    `setMouseTracking(True)` permanente (ojo: `stop_slice_placement` lo apagaba).
    Panel pasa `set_furniture_axes([m._local_axes()])`.
  - **Roll (3er eje) — cómo se metió sin romper nada (patrón reusable):**
    1. `contains` (box) y `_furniture_wireframe` (box) **duplicaban** la cuenta de
       ejes de `_local_axes`. Primero se los hizo **delegar** (refactor no-op) y se
       corrieron los benches ANTES de tocar el roll. 2. Recién ahí se agregó el roll
       en `_local_axes` (única fuente de verdad) → se propaga solo a contains/aabb/
       to_local/wireframe/colisión. 3. `if rl:` saltea la rotación → `roll=0` reduce
       EXACTO por construcción. 4. Persistencia `.get("roll", 0.0)`.
       Convención **aviación z-y'-x''** (yaw mundo-z → pitch ey' → roll ex').
       El roll **afecta el carve** (no es cosmético): roll=90° en una caja
       1.0×0.4×0.2 intercambia exacto los semiejes y↔z.
  - **BUG FIXEADO: muebles trabados al duplicar** (lo reportó el usuario como
    "se traba y no puedo mover nada, ni borrando"). NO era cuelgue de cómputo
    (`contains` 13 ms, `aabb` 0.05 ms). Era la colisión: **el duplicado nacía en la
    posición EXACTA del original** → solape 100% → la colisión-stop revertía TODO
    movimiento de ambos, sin salida. Doble fix: (a) la copia nace **desplazada**
    (su ancho + 0.15 m, en −X si no entra); (b) **escape de solape**: solo se frena
    si el movimiento CREA un solape nuevo (`was_conflicting`), si ya estaba solapado
    se deja arrastrar para afuera. Aplica a move/rotate/tilt/roll. **No era
    exclusivo del CAD**: duplicar cualquier preset tenía el mismo trap (latente).
  - **Decisión de alcance:** CAD sirve para **capturar** un recinto real (escaneo →
    SketchUp → OBJ por pieza), NO para ganar precisión (el efecto-forma vs bbox es
    de 2º orden, ver entrada del 29 Jul). Documentado como nota en §6.4.1.
  - **Nuevos:** `silla_test.obj`, `bench_cad.py`.

- **31 Jul 2026 — Parches con espesor (prisma) + reglas de superposición. v2.21.**
  Rama `parches-prisma` off main. MANUAL v2.21 (.md §6.4/§10.5 + changelog A-F,
  .tex, .pdf 36 pág, limpio). `bench_absorption_patch.py` T9-T12,
  `smoke_test_furniture_ui.py` **38/38**.
  - **`AbsorptionPatch.depth`** (default `DEFAULT_PATCH_DEPTH=0.10`): el parche se
    dibuja como PRISMA extruido hacia el interior. **GEOMÉTRICO PURO**, no toca el
    solver (test T9: ξ y RT60 idénticos con 0 cm y 40 cm). El espesor **NO entra al
    hash de `key`** a propósito: si entrara, cambiarlo generaría clave nueva y el
    parche perdería su material.
  - **Por qué el espesor no entra a la física (discusión larga con el usuario,
    NO reabrir sin dato nuevo):** el α(f) del catálogo se midió ISO 354 CON el
    espesor de esa construcción (la norma obliga a declarar el tipo de montaje
    justamente por eso). Medido en el catálogo: misma lana 25 kg/m3, **α a 63 Hz
    cambia 15× entre 20 y 100 mm**. O sea el espesor YA afecta, vía α. Sumarlo
    como obstáculo = doble conteo. Y **mover la frontera sería PEOR**: experimento
    (`scratchpad/exp_panel_boundary.py`) → correr la pared 10 cm da +2,56 % en los
    modos con componente en ese eje, contra un ruido de malla de 1,41 % (ratio
    1,1×). O sea NO se pierde en el ruido, pero es un sesgo **que no converge**
    (el de malla sí: 2,17 % con npm=2 → 0,74 % con npm=3,5). La física decide: a
    34 Hz el panel es **λ/100** y trabaja al 4 % de su λ/4 → es transparente, la
    frontera sigue en la pared. Nuevo helper `quarter_wave_limit(d)=c/4d`.
  - **`thickness_from_material_name(name)`**: parsea la construcción del nombre del
    catálogo. **GOTCHA:** 111 de 240 nombres tienen DOS números y sumar a ciegas
    está mal: `"franjas de 12 mm a intervalos de 20 mm, absorbente de 40 mm,
    cavidad de 100 mm"` → profundidad = **140**, no 172 (franjas/intervalos son
    geometría EN-PLANO). Se clasifica cada número por su contexto previo.
    Sub-bug encontrado: tener `"abierto"` en la lista de exclusión rompía
    `"20% abierto, absorbente de 40 mm"` (el "20%" no lleva unidad, nunca matcheaba,
    solo ensuciaba el contexto del siguiente). El diálogo autocompleta el espesor
    del material y AVISA si no coincide.
  - **Aristas del prisma** (`_patch_edge_segments` + `set_patches` con 4º elemento):
    blancas ADITIVAS → siempre por encima del relleno (los colores de material
    llegan a 230/255, nunca saturan). n=contorno plano, 3n=prisma.
  - **BUG GRAVE FIXEADO: fuente/receptor DENTRO de un mueble → `FieldEvaluator`
    devuelve NaN** (medido) y contamina toda la FRF **sin lanzar error**. Bloqueo
    en los DOS sentidos: `point_inside_furniture` + `source_placement_conflict`
    (main: source/receiver move) y chequeo del receptor en `_furniture_conflict`.
    El **receptor era el más expuesto**: es un punto pelado sin bafle, y con los
    defaults (mueble al centro + receptor al centro) quedaba adentro al toque.
  - **Regla de sólidos ahora SIMÉTRICA**: el MANUAL §6.4 ya prometía que el mueble
    no ocupa el lugar del bafle, pero valía en un solo sentido (mueble→parlante sí,
    parlante→mueble no). Se mantiene el **escape** de solape en todos los casos.
  - **Aviso (no bloqueo) mueble tapando parche** (`_patches_blocked_by_furniture`):
    el prisma es dibujo y α sigue en la pared, pero el aviso tiene contenido real
    (mueble delante del absorbente → α efectivo menor que el de catálogo).
  - **FIX: muebles y parches NO se trasladaban con `origin_mode`.** `main.
    _shift_scene_objects` movía fuentes/receptor/puntos pero no ellos (arrastre
    histórico: origen v2.16, parches v2.17, muebles v2.18). Nuevo
    `AbsorptionPatch.translate(delta)` (cada componente del delta va al eje del
    marco (normal,u,v) de la cara). **Si agregás un objeto anclado al recinto,
    sumalo a `_shift_scene_objects`.**
  - **Freeze reportado por el usuario: NO reproducido.** Descartados con medición:
    `_capture_state` 0,1 ms; sin colisión bloqueando la fuente; el clamp NO atrapa
    (verificado que puede volver); cuadratura fina ~100 ms (3-6× vs A36); sin fuga
    de items GL. Con `PROTO1_WATCHDOG=1` no se colgó. Probablemente era el clamp
    contra la pared + el desconcierto visual de las cajas superpuestas.
    **Recordatorio de sintaxis:** `VAR=1 cmd` es de bash; en cmd va
    `set PROTO1_WATCHDOG=1 && ...`, en PowerShell `$env:PROTO1_WATCHDOG="1"`.

Si en una sesión futura querés actualizar este archivo (porque cambió un
patrón de trabajo, una decisión de diseño, o se descubrió un nuevo bug
histórico), editá la sección correspondiente y agregá la fecha acá.

---

*Fin del bootstrap. Buena sesión.*
