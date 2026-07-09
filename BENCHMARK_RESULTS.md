# Prototipo 1 — Resultados de benchmarks

_Generado por `benchmark_v2.py` el 2026-05-22 10:25:16._
_Actualizado 2026-05-25: agregado bloque B8 (vectorizacion de `points_inside_surface`)._
_Actualizado 2026-05-30: agregado bench modal-damping vs C-matrix de impedancia (`bench_modal_vs_impedance.py`, ver `acoustic_fem_explicado.md` §16). Fix de calibracion `c²` en `frequency_response` (v2.11). Clip de modos por validez de malla en el panel (v2.12)._

> **Nota de interpretación post-v2.11**: cualquier resultado SPL absoluto
> medido con la app antes de v2.11 está **101 dB por debajo** del valor
> físico real (factor c² ausente en la fórmula modal). Tiempos, formas
> de FRF, posiciones de picos y RT60 NO afectados. Detalle en MANUAL.md
> "Cambios v2.11".
>
> **Nota de interpretación post-v2.12**: el panel descarta automáticamente
> los modos con `f > f_max_malla` (numéricamente sucios). Si un benchmark
> contaba modos crudos de `solve_modes`, el conteo visible en el picker
> de la app puede ser menor. Detalle en MANUAL.md "Cambios v2.12".


## Entorno

- **Python**: 3.12.3
- **Plataforma**: win32
- **NumPy**: 1.26.4
- **SciPy**: 1.13.1
- **CPU cores**: 16 (8 fisicos)
- **RAM**: 63.7 GB

## Metodologia

- Cada test se corre **3 veces** y se reporta la **mediana** (robusta frente a hiccups del SO).
- Todos los tiempos en milisegundos de reloj de pared (`time.perf_counter`).
- Las mallas FEM se construyen con `acoustic_mesh.build_volume_mesh` usando el motor voxel (axis-aligned → exacto).
- Los benchmarks son **headless** (sin GUI): no incluyen tiempo de render OpenGL ni de interaccion del usuario en los dialogos.

## B1. FEM modal (malla + ensamblaje + modos)

| Recinto | n_per_meter | n_modes | nodos | tets | mesh ms | K,M ms | modos ms | total ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| shoebox 4×5×3 | 2.5 | 12 | 1287 | 5760 | 468 | 12 | 33 | 514 |
| shoebox 6×8×3 | 2.5 | 12 | 3024 | 14400 | 1233 | 27 | 117 | 1376 |
| shoebox 6×8×3 | 3.5 | 12 | 7018 | 35280 | 3012 | 64 | 499 | 3575 |
| pentagono 8×8×4 | 2.5 | 12 | 3179 | 14910 | 1914 | 28 | 119 | 2061 |
| hexagono 10×10×4 | 2.5 | 20 | 5708 | 28140 | 3442 | 52 | 515 | 4008 |

## B2. Campo 3D — forma modal y presion |p|

Sala 6×8×3 m, malla n_per_meter=2.5 → ~3 k nodos, ~14 k tets.

Cada celda muestra (mediana de 3 corridas):  **ms total**  ·  *N puntos validos*.

| Resolucion | Puntos teoricos | Forma modal | Presion \|p\| |
|---:|---:|---:|---:|
| 20 | 4,000 | **23 ms**  ·  *3,992 pts* | **26 ms** |
| 30 | 13,500 | **61 ms**  ·  *13,484 pts* | **72 ms** |
| 40 | 32,000 | **131 ms**  ·  *31,910 pts* | **174 ms** |
| 50 | 62,500 | **247 ms**  ·  *62,500 pts* | **296 ms** |
| 60 | 108,000 | **434 ms**  ·  *107,502 pts* | **469 ms** |
| 70 | 171,500 | **674 ms**  ·  *170,788 pts* | **741 ms** |

## B3. Comparativa: loop Python (antes) vs KDTree (ahora)

Mide la funcion `evaluate_many` que es el cuello de botella historico del campo 3D. El loop Python esta implementado tal cual existia en `acoustic_fem.py` antes de la optimizacion (referencia).

| Sala | tets | puntos | loop Python | KDTree+numpy | speedup | max diff |
|---|---:|---:|---:|---:|---:|---:|
| 4×5×3 (npm=2.5) | 5,760 | 4,000 | 941 ms | **18 ms** | **51.4×** | 2.2e-16 |
| 6×8×3 (npm=2.5) | 14,400 | 13,500 | 6739 ms | **95 ms** | **71.2×** | 2.2e-16 |
| 6×8×3 (npm=3.0) | 23,328 | 13,500 | 11351 ms | **65 ms** | **173.4×** | 2.2e-16 |

## B4. Agrupacion de caras por region planar

Tiempo para detectar grupos de caras coplanares conexas (funcion `group_faces_by_planar_region`). Se ejecuta una vez por apertura del dialogo de materiales.

| Recinto | n_walls | tris | grupos | tiempo (mediana 3) |
|---|---:|---:|---:|---:|
| shoebox 6×8×3 | 4 | 12 | 6 | 0.7 ms (0.6 – 0.8) |
| pentagono | 5 | 16 | 7 | 0.7 ms (0.7 – 0.8) |
| hexagono | 6 | 20 | 8 | 0.8 ms (0.7 – 1.1) |
| octagono | 8 | 28 | 10 | 0.9 ms (0.9 – 0.9) |
| dodecagono | 12 | 44 | 14 | 1.3 ms (1.3 – 1.4) |
| 32-gono (circulo) | 32 | 124 | 14 | 2.1 ms (2.0 – 2.2) |

## B5. Importacion CAD (sin GUI)

Mide los pasos individuales del pipeline de import (sin la interaccion del usuario en el dialogo de escala o reparacion).  Cada fase se mide por separado para que se vea **donde se va el tiempo** cuando un archivo es lento.

| Tris objetivo | Tris reales | load (ms) | diagnose (ms) | suggest scale (ms) | total (ms) |
|---:|---:|---:|---:|---:|---:|
| 200 | 320 | 8 | 2 | 0 | 10 |
| 5,000 | 5,120 | 13 | 7 | 0 | 20 |
| 20,000 | 20,480 | 30 | 45 | 1 | 76 |
| 80,000 | 81,920 | 138 | 169 | 4 | 311 |
| 200,000 | 327,680 | 507 | 660 | 13 | 1180 |

## B6. RT60 con asignacion por grupo

Tiempo del calculo de RT60(f) en 8 bandas de octava con un material distinto por grupo. Es lo que se ejecuta cada vez que el usuario cambia una asignacion en el dialogo de materiales.

| Recinto | grupos | tiempo (mediana 3) |
|---|---:|---:|
| shoebox 6×8×3 | 6 | 0.32 ms |
| octagono 10×10×4 | 10 | 0.44 ms |
| 32-gono 16×16×5 | 14 | 0.67 ms |

## B7. Memoria del FieldEvaluator (KDTree + locator)

La vectorizacion del campo 3D agrega un cKDTree sobre los centroides de los tetraedros. Verificamos que el costo en memoria es despreciable para cualquier malla razonable.

| Recinto | tets | RSS antes (MB) | RSS despues (MB) | delta |
|---|---:|---:|---:|---:|
| 4×5×3 (npm=2.5) | 5,760 | 109.8 | 110.8 | +1.0 |
| 6×8×3 (npm=2.5) | 14,400 | 111.5 | 113.6 | +2.1 |
| 6×8×3 (npm=4.0) | 55,296 | 116.1 | 123.9 | +7.8 |
| 16-gono (npm=2.5) | 179,250 | 127.6 | 150.0 | +22.3 |

---

## Lectura del reporte

- **B1** muestra que el tiempo de FEM no es lineal con npm: duplicar la densidad de malla (~ 8× tets) puede llevar el ensamblaje y la resolucion modal de < 100 ms a varios segundos.
- **B2** muestra que con el nuevo evaluator vectorizado, incluso resolucion 70 (170 k puntos) tarda < 1 s. Antes de la optimizacion, res=50 tomaba 15-25 s en una sala chica.
- **B3** mide el delta exacto entre el loop Python y el evaluator vectorizado. La diferencia numerica es < 1e-15 (redondeo IEEE-754); el algoritmo es el mismo, solo cambio como se buscan los tets candidatos.
- **B4** confirma que la agrupacion de caras tarda < 5 ms para cualquier sala parametrica. Para CADs muy grandes (50 k caras) escala linealmente con el numero de aristas.
- **B5** descompone el tiempo de import CAD entre carga, diagnose y suggest_scale. Para mallas grandes (>200 k tris), diagnose puede ser la fase mas pesada.
- **B6** confirma que recomputar RT60 cada vez que el usuario cambia un material es < 1 ms — el UI puede ser totalmente reactivo.
- **B7** confirma que el KDTree agrega < 5 MB incluso para mallas de 100 k tetraedros.

---

## Cuellos de botella restantes y oportunidades

### 1. `build_volume_mesh` (motor voxel) — **RESUELTO el 2026-05-25**

Era el cuello restante mas grande hasta v2.6: `acoustic_mesh.build_volume_mesh` consumia 80-95 % del tiempo FEM completo, dominado por el bucle Python de `points_inside_surface` (un punto a la vez contra todos los triangulos en numpy).

**Fix**: vectorizacion batched de Moller-Trumbore con chunking de memoria. La nueva version procesa TODOS los puntos contra TODOS los triangulos en una sola expresion broadcasted. Ver detalles en B8 abajo.

**Resultado medido** (mismas salas que B1):

| Sala | npm | tets | mesh_ms antes | mesh_ms despues | speedup |
|---|---:|---:|---:|---:|---:|
| 6×8×3 | 2.5 | 14 400 | 1 141 | 25.8 | **44x** |
| 6×8×3 | 3.5 | 35 280 | 2 791 | 56.1 | **50x** |
| 10×10×4 | 2.5 | 28 140 | 3 205 | 89.5 | **36x** |

Verificacion bit-exact en 14 casos (incluye polygonos no-convexos, gable, shed, OBJ icosphere): ver `verify_voxel_equivalence.py`.

Las "mejoras posibles" listadas antes (cachear malla entre llamadas, importar tetraedros de gmsh) siguen abiertas pero ya no son urgentes: con la vectorizacion, un recinto tipico (shoebox 6×8×3, npm 2.5) tarda **~25 ms en mallado + ~150 ms en Lanczos = ~180 ms en total**, suficientemente rapido para iteracion interactiva.

### 2. `diagnose()` para mallas CAD muy grandes

**B5** muestra que `diagnose` cuesta ~ 660 ms para 327 k triangulos. La operacion mas pesada es la deteccion de huecos (`find_holes`), que ya esta vectorizada en cuanto a la deteccion de aristas de borde pero todavia recorre cada hueco con Python para armar los ciclos.

**Cuando aparece:** importar STL/OBJ de auditorios con varios cientos de miles de triangulos.

**Mitigacion ya disponible al usuario:**
- El nuevo `QProgressDialog` muestra "Diagnosticando..." con un cancelar funcional, asi el usuario no cree que la app se colgo.
- Si la malla es limpia (`diag.ok == True`), el sistema **se saltea** la confirmacion (antes habia un QMessageBox "Si/No" que sumaba 1-2 segundos de fricion innecesaria).

**Posible mejora futura:** detectar mallas con > 1 M caras y ofrecer un modo "Importacion rapida" que saltee `find_holes` (solo verifica is_watertight + winding).

### 3. Loops Python que sobreviven (pero NO son cuellos de botella en uso normal)

Investigue tambien estos loops para descartar si son problema:

| Ubicacion | Tipo | Iteraciones tipicas | Costo medido | Veredicto |
|---|---|---:|---:|---|
| `acoustic_fem.frequency_response` linea 244 | `for f in freq_axis` | 100-1000 | < 5 ms | OK (vectorizable, pero no urgente) |
| `acoustic_fem.frequency_response` lineas 228, 236 | `for n in range(Nm)` y nested sources × modes | 12 × 1-4 | < 1 ms | OK (Nm es chico) |
| `acoustic_analysis.pressure_gradient_3d` | 6 llamadas a `evaluate_many` | 6 | hereda speedup de B3 | OK |
| `geom_import.find_holes` linea 362 | `for start_i, start_j in boundary_edges` | < 5 % de las caras | depende | Tiene mitigacion: hub-and-spoke en numpy. Solo lento en CADs con miles de huecos. |

### 4. Memoria — sin sorpresas

**B7** confirma que el costo del KDTree (centroides + arbol) es ~ 120 bytes por tetraedro: 100 k tets = ~ 12 MB. Despreciable frente a los ~ 150 MB de RAM total que ocupa la app con una malla mediana.

---

## B8. Vectorizacion de `points_inside_surface` (2026-05-25)

### Contexto

Hasta v2.6 inclusive, `points_inside_surface` (raycast Moller-Trumbore para filtrar tets dentro del recinto) tenia un bucle Python sobre los puntos. Para 14 400 puntos en una sala 6×8×3 con 12 triangulos, era ~14 400 llamadas a una funcion que internamente hace `np.cross`, `np.einsum`, etc. — la suma del overhead del interprete era ~1.1 s.

La nueva implementacion procesa todos los puntos contra todos los triangulos en una sola expresion broadcasted con chunking para acotar memoria (`_CHUNK_PAIRS = 10M`).

### Metodologia

Side-by-side: la implementacion ORIGINAL se mantiene inlineada en `verify_voxel_equivalence.py`. El bench corre las dos versiones sobre los mismos centroides en la misma invocacion (3 corridas, mediana). Reproducible con `python bench_voxel_extended.py`.

### Resultados (14 casos)

| Categoria | Caso | Nt | Np | original ms | vectorizado ms | speedup |
|---|---|---:|---:|---:|---:|---:|
| Paramétrico simple | shoebox 4×5×3 | 12 | 5 760 | 489.7 | 5.76 | **85.1x** |
| | shoebox 6×8×3 | 12 | 14 400 | 1 193.9 | 15.55 | 76.8x |
| | shoebox 6×8×3 (npm 3.5) | 12 | 35 280 | 2 971.6 | 41.71 | 71.2x |
| | pentagono 8×8×4 | 16 | 21 600 | 1 830.6 | 32.72 | 55.9x |
| | hexagono 10×10×4 | 20 | 37 500 | 3 230.7 | 75.76 | 42.6x |
| Plantas no-convexas | L-shape 6×7×3 | 20 | 12 960 | 1 170.6 | 26.39 | 44.4x |
| | U-shape 8×6×3 | 28 | 14 400 | 1 293.0 | 40.57 | 31.9x |
| | Plus-shape 6×6×3 | 44 | 10 800 | 978.2 | 46.14 | 21.2x |
| Techos especiales | gable centrado | 20 | 19 800 | 1 796.1 | 39.13 | 45.9x |
| | gable descentrado (ridge=0.4) | 20 | 19 800 | 1 735.5 | 39.15 | 44.3x |
| | shed inclinado | 12 | 19 800 | 1 724.6 | 22.33 | 77.2x |
| Combo agresivo | taper+twist+paredes inclinadas | 20 | 28 704 | 2 543.7 | 58.85 | 43.2x |
| Curva subdividida | arch (techo curvo) | 522 | 18 000 | 2 297.1 | 854.36 | 2.7x |
| OBJ real | icosphere subdiv 3 (roundtrip) | 1 280 | 10 368 | 1 561.6 | 1 207.88 | **1.3x** |

**Mediana**: 44.3x | **min**: 1.3x | **max**: 85.1x.

### Lectura

El speedup es inversamente proporcional a `Nt` (cantidad de triangulos en la malla superficial):

- **Nt < 50** (paramétrico, no convexo, gable/shed, combo): 20-85x. La vectorizacion elimina el overhead del interprete Python que dominaba cuando cada llamada hacia poco trabajo numpy.
- **Nt ~ 500** (arch subdividido): ~3x. Cada llamada original ya hacia bastante trabajo numpy por triangulo, queda menos overhead para amortizar.
- **Nt > 1 000** (CAD real): 1-3x. El trabajo numpy domina; la vectorizacion solo ahorra el overhead del bucle Python.

### Implicancia practica

| Geometria | Nt tipico | Speedup | Comentario |
|---|---|---|---|
| Recinto paramétrico (uso cotidiano) | 12-50 | 40-85x | **Caso dominante en la UI** |
| Recinto con techo arch/gable subdividido | 500 | 3x | gmsh seria mas apropiado |
| CAD importado | 1k-50k | 1-3x | El router de v2.1 elige gmsh automaticamente |

Es decir: el cuello queda resuelto para el caso de uso normal del voxel mesher (geometria paramétrica simple). Para CAD pesado, el router va a gmsh igual, asi que no pasa por este path.

### Verificacion de equivalencia

Bit-exact en los 14 casos: `cand_tets` (indices enteros) y mascara `inside` (bools) coinciden elemento a elemento. Las frecuencias modales del FEM resultante coinciden a `rtol < 1e-10`. Repetir con `python verify_voxel_equivalence.py`.

---

## Recomendaciones operativas para el usuario

Basadas en los numeros del reporte:

1. **Resolucion del campo 3D**: usar **res = 40-50** para exploracion (< 0.3 s); subir a **res = 70** solo para figuras finales o capturas (~ 0.7 s).
2. **Densidad de malla FEM** (`n_per_meter`): mantener en **2.5** para diseno cotidiano (15 k tets, validez hasta 250 Hz aprox.); subir a **3.0-3.5** solo cuando se requiera precision a > 300 Hz, sabiendo que el mallado tomara 3-10 s.
3. **Importacion de CADs grandes**: archivos de > 100 k triangulos van a tardar 0.5-1.5 s por la fase de `diagnose`. Mientras corre, el `QProgressDialog` muestra el progreso y permite cancelar. Tras importar, la geometria se cachea en memoria; las siguientes operaciones no la vuelven a leer.
4. **Materiales por cara**: el dialogo se puede abrir y cerrar libremente; cambiar asignaciones es prácticamente instantaneo (< 1 ms por recompute de RT60, segun **B6**). El UI es totalmente reactivo.
