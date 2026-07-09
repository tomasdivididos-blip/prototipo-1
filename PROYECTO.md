# Prototipo 1 — Modelador de Recintos 3D con Simulación Acústica FEM

## Resumen

Aplicación de escritorio (Windows 11, Python 3.12 + Anaconda) para diseñar
recintos acústicos en 3D, visualizarlos en vista isométrica, calcular su
comportamiento modal por FEM (Método de Elementos Finitos), e invertir el
flujo: describir un uso y obtener dimensiones óptimas scoreadas.

---

## Stack tecnológico

| Capa | Librería |
|---|---|
| GUI | PyQt5 (Qt en C++) |
| Visor 3D | pyqtgraph 0.14 + PyOpenGL |
| Álgebra / mallas | NumPy, SciPy (eigsh, cKDTree, fftconvolve) |
| Geometría CAD | trimesh + gmsh (kernel OpenCASCADE) |
| Gráficos científicos | matplotlib (embebido en Qt5) |
| Audio | winsound (Win) / afplay (Mac) / aplay·paplay·ffplay (Linux) + scipy.io.wavfile |
| Lenguaje | Python 3.12 (Anaconda base) |

> **PyQt6 / PySide6 descartados**: las DLLs de MSVC de Anaconda son incompatibles
> con Qt 6.x en Windows. Se usa PyQt5 directamente.

> **sounddevice descartado**: requiere `libportaudio64bit.dll` no disponible en
> algunas instalaciones de Anaconda. `audio_utils.py` es multiplataforma
> (v2.12): `winsound` en Windows, `afplay` en macOS, `aplay`/`paplay`/`ffplay`
> en Linux. Todos built-in del SO, sin dependencias pip.

---

## Estructura de archivos

```
prototipo 1/
├── main.py                  # Ventana principal, orquestador de señales
├── viewer.py                # IsoViewer — visor 3D (pyqtgraph GLViewWidget)
├── controls.py              # ControlPanel — sliders de geometría
├── geometry.py              # Motor geométrico paramétrico 3D
├── shape_dialog.py          # Diálogo de dibujo de polígono personalizado
├── style.py                 # QSS dark theme (Catppuccin Mocha)
├── timed_button.py          # Helper "Último: X.XX s" bajo botones pesados
├── app_settings.py          # Persistencia cross-OS (%APPDATA%/Prototipo1/)
│
├── sources.py               # OmniSource (Q directo o por sensibilidad), SourceArray
├── acoustic_analysis.py     # Orquestador FEM: pipelines, slices, campos 3D
├── acoustic_fem.py          # Ensamblaje K/M, eigsh, FRF, FieldEvaluator (cKDTree)
├── acoustic_mesh.py         # Malla tet volumétrica (voxel) + subdivide_surface
├── acoustic_viewer.py       # Overlays 3D: SourceMarkers, ReceiverMarker,
│                            #   FieldSliceItem, PressureField3D, SlicePlanePreview
├── acoustic_panel.py        # AcousticPanel, SourceEditDialog, FRFDialog,
│                            #   RT60PlotDialog, SliceHeatmapDialog
├── audio_utils.py           # Ruido rosa, FRF→IR, soft-clip, anti-pop, playback
├── material_library.py      # MaterialLibrary: carga JSON, Sabine, ξ por modo
├── face_materials.py        # Agrupación planar por cara (estilo EASE) + MaterialsDialog
│
├── mesh_router.py           # Router voxel↔gmsh, auto-tuner densidad por budget
├── mesh_gmsh.py             # Wrapper gmsh boundary-fitted con auto-clean
│
├── geom_import.py           # Loaders STL/OBJ/PLY/glTF/STEP/IGES/BREP + diagnose/repair
├── geom_repair_dialog.py    # MeshImportDialog con preview 3D + reparación guiada
├── geom_scale_dialog.py     # Diálogo escala + orientación (Y-up ↔ Z-up)
│
├── prediction.py            # Motor: 8 presets de uso, ratios Bolt/Bonello/Louden,
│                            #   FEM-lite paralelo, 13 sub-scores en 5 grupos
├── prediction_panel.py      # Pestaña Predicción con cards scoreadas
│
├── fem_modal.py             # Solver FEM shoebox-only (referencia analítica)
├── benchmark_v2.py          # Suite headless: 7 bloques, BENCHMARK_RESULTS.md
│
├── check_materials_coverage.py  # Matching difuso es/en contra catálogo Cox
├── verify_setup.py          # Verificación de dependencias + OpenGL
│
├── materials/               # Archivos JSON de materiales acústicos (19 archivos)
│   ├── hormigon_visto.json
│   ├── yeso_pintado.json / yeso.json
│   ├── madera.json / madera_dura.json
│   ├── alfombras.json / alfombra_fina.json / alfombra_gruesa.json
│   ├── vidrio.json / ventanas.json
│   ├── ladrillo.json / cortinas.json
│   ├── panel_acustico.json / paneles_perforados.json
│   ├── porosos.json / rigidos.json
│   ├── materiales_naturales.json / mobiliario.json / otros.json
│   └── README de formato en EXPLICACION_TECNICA.md
│
├── run.bat                  # Lanzador (detecta Anaconda automáticamente)
├── build.bat                # Empaqueta a dist/Prototipo1/ con PyInstaller
├── build_installer.bat      # Genera Prototipo1_Installer.exe con NSIS
├── build_installer.py       # Pipeline Python para PyInstaller + NSIS
├── installer.nsi            # Script NSIS
├── setup.py                 # Setup pip (legacy, no usado para distribuir)
├── Prototipo 1.spec         # Spec PyInstaller
│
├── MANUAL.md / MANUAL.tex / MANUAL.pdf     # Manual de usuario v2.6
├── EXPLICACION_TECNICA.md                  # Walkthrough técnico
├── BENCHMARK_RESULTS.md                    # Benchmarks reproducibles
├── MATERIALS_COVERAGE.md                   # Cobertura vs catálogo Cox
├── INSTALACION.md / README.md              # Guías de instalación y uso
├── PROYECTO.md                             # Este documento
└── signal_flow.tex                         # Doc LaTeX del flujo de señales
```

---

## Pestañas de la app

### Pestaña Geometría

Modelar el recinto con sliders (`controls.py`) o dibujar un polígono base
(`shape_dialog.py`).

| Parámetro | Descripción |
|---|---|
| `width`, `length`, `height` | Dimensiones base en metros |
| `n_walls` | Número de lados del polígono base (3–32) |
| `taper` | Factor de estrechamiento hacia arriba [0–1] |
| `twist` | Ángulo de rotación del techo [°] |
| `wall_inclinations` | Array de inclinaciones por pared [°] |
| `arch_height` | Altura del arco de bóveda (si > 0, activa bóveda) |
| `roof_type` | `"flat"` / `"arch"` / `"gable"` / `"shed"` |
| `ridge_offset` | Posición del caballete en techo a dos aguas [−0.9, 0.9] |
| `base_polygon` | Polígono 2D personalizado (lista de [x,y]) |

Tipos de techo:
- **Plano**: sin deformación vertical.
- **Arco (bóveda de cañón)**: perfil circular `R = (W²/4 + h²)/(2h)`. Solo vértices
  interiores (`boundary_mask` evita gaps con las paredes).
- **Dos aguas (gable)**: caballete con `_triangulate_with_ridge`. `ridge_offset`
  permite descentrarlo.
- **Inclinado (shed)**: techo inclinado en una dirección.

### Pestaña Acústica

Calcular modos, visualizar campos, escuchar la sala.

**Flujo recomendado**:
```
1. Diseñar recinto (pestaña Geometría) — o importar CAD con Ctrl+I
2. Asignar materiales por cara (botón Materiales… abre MaterialsDialog)
3. Posicionar fuentes (Ctrl+Click derecho en visor o desde panel)
   → configurar por sensibilidad de altavoz (dB/W/m)
4. Posicionar receptor (Shift+drag o spinboxes)
5. Elegir Nº de modos → "Calcular modos (FEM)"
   (motor voxel/gmsh elegido automáticamente por mesh_router)
6. Visualizar campo:
   a. Nube 3D: "Forma modal" (Signed Vivid) o "Presión |p|" (Rainbow 7)
   b. Slice 2D: plano XY/XZ/YZ con "Activar plano interactivo" → click en
      recinto → heatmap matplotlib con barra de color en dB SPL
7. Calcular FRF (FEM) → gráfico matplotlib + "🔊 Escuchar" (ruido rosa filtrado)
8. Ver RT60(f) calculado: diálogo comparativo Sabine vs Eyring
```

### Pestaña Predicción (v2.6)

Flujo inverso: describir el uso y obtener candidatos.

**Inputs** (`PredictInputs`):
- Uso (8 presets: conferencias, aula, control room, live room, home theater,
  sala de cámara, sala sinfónica, sala polivalente)
- Capacidad, m²/persona, prioridad inteligibilidad↔envoltura
- Restricciones de planta y altura, paredes paralelas, forma de techo
- Objetivos: RT60 @ 500 Hz, V/persona

**Pipeline**:
1. Calcular `V_target = capacidad × V/persona`
2. Generar 3 candidatos con ratios Bolt (1,9:1,4:1), Bonello (1,59:1,26:1),
   Louden (2,33:1,6:1), escalados a `V_target` respetando restricciones
3. Correr FEM lite en paralelo (`ThreadPoolExecutor`, 3 workers, malla coarse, 40 modos)
4. Computar 13 sub-scores en 5 grupos:
   - **MODAL**: RT60 feasibility, Bolt-spacing, Modal Q audibility, Schroeder coverage
   - **VOZ**: STI (Bradley), %Alcons (Peutz), distancia crítica
   - **MÚSICA**: Bass support proxy (geométrico)
   - **PRÁCTICO**: Forma (L/W, H/W), aprovechamiento de planta, constructabilidad
   - **ROBUSTEZ**: margen del α requerido respecto a [0,08; 0,30]
5. Combinar con pesos condicionales por uso (voz / música / mixto)
6. Si los 3 candidatos quedan dentro de ±5 puntos, agregar 4ª card "Control negativo"
   (cubo 1:1:1) con border rojo para enseñar visualmente qué NO usar
7. Botón **Aplicar ▾**: "Como parámetros" (mueve sliders de Geometría) o
   "Como CAD" (inyecta malla como geometría externa)

Además: **Evaluar mi diseño actual** corre el mismo pipeline sobre la geometría
de la pestaña Geometría para validar diseños propios contra los 13 criterios.

---

## Visor 3D (IsoViewer)

### Controles de cámara

| Acción | Efecto |
|---|---|
| Botón central (arrastrar) | Órbita |
| Botón derecho (arrastrar) | Pan |
| Rueda del mouse | Zoom |
| Shift + botón central | Órbita restringida (sólo yaw) |
| Tecla `0` | Reset cámara a vista isométrica |

### Indicador de ejes (v2.2)

Esquina inferior derecha: cuadrados clicables `X` / `Y` / `Z` (también
`Ctrl+Shift+Alt+X/Y/Z`). Fijar un eje hace que la rueda del mouse rote el
recinto solo alrededor de ese eje mundial.

### Modos de visualización

- **Aristas**: mesh traslúcido + aristas.
- **Externa**: mesh opaco.
- **Contorno**: solo aristas.

### Interacciones acústicas en el visor

| Acción | Efecto |
|---|---|
| `Ctrl + Click derecho` | Colocar fuente acústica (z=1 m desde el piso) |
| `Shift + Click izquierdo` (arrastrar) | Mover fuente o receptor |
| Doble-click sobre fuente | Editar fuente |
| Click derecho + arrastrar sobre pared | Inclinar esa pared en vivo |

---

## Fuentes acústicas

### Configuración por sensibilidad de altavoz

Ingresá los datos de la ficha técnica del parlante:

| Campo | Descripción |
|---|---|
| Sensibilidad | dB SPL @ 1W/1m (p.ej. 90 dB) |
| Frecuencia de referencia | Hz a la que se mide (default: 1000 Hz) |

Conversión al modelo de monopolo:
```
p₀ = 20 µPa · 10^(S/20)
|Q| = p₀ · 4π / (2π·f_ref·ρ₀)
```

Al cambiar sensibilidad, FRF / modos / campo 3D se recalculan automáticamente
(porque `SourceArray.amplitudes()` llama `effective_Q()` en cada evaluación).

---

## FEM Modal

**Formulación**: tetraedros lineales P1, ensamblaje K/M vectorizado,
`eigsh` Lanczos shift-invert.

**Condición de borde**: Neumann homogénea (paredes rígidas, impuesta
naturalmente).

**Frecuencia de validez**: `f_max = c / (ppw · h_max)`, ppw=6.

**Superposición modal (FRF)**:
```
H(f) = iωρ₀·c² · Σₙ φₙ(xᵣ)[Σₛ Qₛ·φₙ(xₛ)] / (ωₙ²−ω² + 2i·ξₙ·ωₙ·ω)
```
`ξₙ` es un array `(Nm,)` calculado por modo desde los materiales. El factor
`c²` (v2.11) sale de la Green function modal de Helmholtz (`ωₙ²=c²·λₙ`,
`k²=ω²/c²`); sin él el SPL absoluto queda ~101 dB bajo (ver tabla de bugs).

### Auto-tuner de densidad (v2.6)

Cuando el motor está en "Automático", `mesh_router.auto_density` calcula la
densidad necesaria para cubrir hasta `f_Schroeder` en un budget de tiempo
(5 s para shoebox simple, 10 s para CAD o curvas). Si no entra, aparece un
diálogo "Cobertura parcial / Cobertura completa (~Y s) / Cancelar".
Prioridad: validez antes que velocidad.

### FieldEvaluator vectorizado (v2.3)

`FieldEvaluator.evaluate_many` usa `scipy.spatial.cKDTree` + `numpy.einsum`
para buscar el tetraedro contenedor por punto. Speedup medido: **50–170×**
sobre el bucle Python anterior, diferencia numérica `< 1e-15`. Resolución 50
(62 500 puntos): antes 15–25 s, ahora ~280 ms.

### Voxel mesher vectorizado (post-v2.6)

`acoustic_mesh.points_inside_surface` ahora procesa todos los centroides
contra todos los triángulos en una sola expresión broadcasted (chunking de
memoria con `_CHUNK_PAIRS = 10M`). El bucle triple de `cand_tets` se
reemplazó por `np.meshgrid` + indexación con `HEX_TO_TETS`. Speedup mediana
**44×** (mín 1,3× para CAD con Nt > 1000, máx 85× para shoebox simple).
Verificación bit-exact en 14 casos (paramétrico, no-convexo, gable, shed,
OBJ roundtrip) en `verify_voxel_equivalence.py`. Detalle en
[BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md) sección B8.

---

## Materiales por cara (v2.3, estilo EASE)

A diferencia del esquema clásico piso/techo/paredes, `face_materials.py`
descompone la malla en regiones planares conexas:

1. **Cluster por normal** de cara (tolerancia ±15°).
2. **Componentes conexas** dentro de cada cluster.

Cada grupo recibe un label automático ("Piso", "Techo", "Pared N (+X)",
"Cara inclinada N (…)") y una **firma estable** (hash de normal/centroide/área
redondeados) que sobrevive recompilaciones y cambios menores de geometría.

El usuario asigna un material por grupo via `MaterialsDialog`. Las
asignaciones se serializan en `.room` v4 (`acoustic.face_materials.assignments`)
como `{signature: material_name}`.

### Cálculo de RT60

**Sabine** (por banda):
```
RT60(f) = 0.161·V / Σᵢ αᵢ(f)·Sᵢ
```

**Eyring (Norris-Eyring)**:
```
RT60(f) = 0.161·V / [-S·ln(1 − ᾱ(f))]
```

Diálogo comparativo multi-curva: azul = Sabine, rojo = Eyring. Fitzroy
existe en código pero se removió de la UI en v2.5.

Amortiguamiento modal:
```
ξₙ = 1.1 / (fₙ · RT60(fₙ))
```

---

## Import CAD (v2.0)

**Formatos soportados**:

| Familia | Formatos | Loader |
|---|---|---|
| Mallas triangulares | `.stl`, `.obj`, `.ply`, `.glb`, `.gltf`, `.3mf`, `.dae`, `.off`, `.xyz` | trimesh |
| B-rep paramétrico | `.step`, `.stp`, `.iges`, `.igs`, `.brep` | gmsh (kernel OpenCASCADE) |

**Pipeline** (`geom_import.load_geometry`):
1. Cargar malla.
2. **Diálogo de escala y orientación** (`geom_scale_dialog`): heurística por
   diagonal AABB + sugerencia Y-up por extensión (OBJ/glTF/Blender = Y-up).
3. `diagnose()`: watertight? normales consistentes? huecos? volumen?
4. Si hay problemas → **diálogo de reparación guiada** (`geom_repair_dialog`)
   con preview 3D: cerrar hueco (fan triangulation), soldar a vecinos
   (snap KD-tree), mover vértice, "Reparar TODO automáticamente".
5. La malla queda **embebida** en el `.room` v3+ — proyecto portable.

---

## Router de mallado (v2.1)

`mesh_router.build_mesh` decide automáticamente:

| Geometría | Motor | Badge |
|---|---|---|
| Shoebox / polígono axis-aligned techo plano | voxel directo | 🟢 verde "voxel · exacto" |
| Paramétrica con `arch_height > 0` | voxel directo (gmsh falla por T-junctions) | 🟢 verde |
| Paramétrica `twist`/`taper`/curva o CAD importado | intenta gmsh primero | 🔵 azul "gmsh · boundary-fitted" |
| Gmsh falla (T-junctions, PLC error) | fallback a voxel | 🟡 amarillo "voxel · fallback" |
| Override usuario | respeta elección | 🟠 naranja si forzaste el no-óptimo |

Override se persiste por proyecto (`.room`) y como default global
(`%APPDATA%/Prototipo1/settings.json`).

---

## Visualización del campo acústico

### Nube de puntos 3D

| `combo_field` | Cómputo | Colormap (v2.6) |
|---|---|---|
| Forma modal | `mode_shape_field_3d` — φₙ(x), sin fuente | Signed Vivid (azul → gris medio → rojo) |
| Presión \|p\| | `pressure_field_3d` — \|p(x,f)\| con fuentes | Rainbow 7 paradas |

**Resolución campo 3D**: spinner independiente (8–80 pts/eje). No confundir
con "Densidad de malla" (que controla la precisión FEM, no la visualización).

**Auto-actualización**: debounce de 350 ms al mover fuentes en modo "Presión |p|".

### Plano de corte 2D interactivo

Tres orientaciones: **XY** (z=cte), **XZ** (y=cte), **YZ** (x=cte).

1. Elegir plano en el combo.
2. Presionar "⊕ Activar plano interactivo".
3. Mover cursor sobre el recinto → plano celeste translúcido sigue al cursor.
4. **Click izquierdo** → confirma y abre heatmap.
5. **Click derecho** → cancela.

**Heatmap** (`SliceHeatmapDialog`):
- Ventana no-modal, reutilizable.
- Forma modal: colormap divergente RdBu_r.
- Presión |p|: colormap inferno, leyenda en **dB SPL (re 20 µPa)**.
- Export PNG / SVG / PDF.

---

## FRF (Respuesta en frecuencia)

- Gráfico matplotlib con toolbar interactiva.
- Eje Y: dB SPL = 20·log₁₀(|H| / 20 µPa).
- Líneas naranjas: modos FEM.
- Botón **"🔊 Escuchar"**: ruido rosa filtrado con H(f) por convolución en
  frecuencia → playback `winsound`.
- Anti-pop al finalizar (v2.5): fade-in 10 ms + fade-out 50 ms + 100 ms de
  silencio + soft-clipping tanh (drive=2.5).
- Formato de audio: **16 bits, 44 100 Hz, estéreo** (L=R, mono acústico).

---

## Persistencia

| Llave | Lugar |
|---|---|
| Geometría + acústica + fuentes + materiales por cara | `.room` v4 (JSON portable) |
| Preferencias globales (motor default, último dir CAD, files recientes) | `%APPDATA%/Prototipo1/settings.json` |

### `.room` v4

```jsonc
{
  "format": "prototipo1.room",
  "version": 4,
  "params": { /* sliders de Geometría */ },
  "acoustic": {
    "mesh_engine": "auto",        // "auto" | "voxel" | "gmsh"
    "h_target": 0.40,
    "n_per_meter": 2.5,
    "n_modes": 12,
    "sources": [...],
    "receiver": [...],
    "face_materials": {           // v2.3+
      "assignments": { "<signature>": "<material_name>", ... }
    }
  },
  "external_geometry": {          // v2.0+ si hay CAD importado
    "kind": "embedded_mesh",
    "format": "trimesh-json-v1",
    "vertices": [...],
    "faces":    [...]
  }
}
```

Los `.room` v2/v3 antiguos siguen abriéndose sin problema (campos nuevos son
opcionales).

---

## Atajos

| Atajo | Acción |
|---|---|
| `Ctrl+Z` / `Ctrl+Y` / `Ctrl+Shift+Z` | Deshacer / Rehacer |
| `Ctrl+S` / `Ctrl+Shift+S` | Guardar / Guardar como |
| `Ctrl+O` | Abrir `.room` |
| `Ctrl+I` | Importar CAD |
| `Enter` (pestaña Acústica) | Actualizar campo 3D |
| `Enter` (pestaña Predicción) | Disparar Predecir |
| `0` | Reset cámara vista isométrica |
| `Ctrl+Shift+Alt+X/Y/Z` | Fijar / liberar eje |

---

## Bugs resueltos (registro histórico)

| Bug | Causa | Fix |
|---|---|---|
| PyQt6 DLL load failed | DLLs MSVC de Anaconda incompatibles con Qt6 | Migrar a PyQt5 |
| `run.bat` encuentra Python de MS Store | PATH prioriza WindowsApps | Hardcodear ruta Anaconda |
| `projectionMatrix()` rota en pyqtgraph 0.14 | Cambio de firma | Cálculo manual con `QMatrix4x4` |
| Gap pared-techo arco | Subdivisión aplicaba arco en bordes | `boundary_mask` excluye borde |
| Gable triangula mal | Ear-clipping no respeta arista de caballete | `_triangulate_with_ridge` |
| Esferas de fuente no visibles | `shader="shaded"` falla; orden render | `GLScatterPlotItem` |
| Receptor no arrastra 2ª vez | `mouseReleaseEvent` chequeaba `>= 0` | Cambiar a `!= -1` |
| Campo no cambia al mover fuente | `_update_field_3d` ignoraba `combo_field` | Rama modo/presión + debounce 350 ms |
| Slice sangra fuera del recinto | Condición `or` en quad mask | Cambiar a `and` |
| "Modo" y "Presión" lucen igual | Siempre computaba presión en nube 3D | `update_signed` para modo, `update` para presión |
| QGroupBox borde derecho cortado | Sin margen en CSS | `margin-right: 4px` en QSS |
| Botones no expanden | `QPushButton` sin `Expanding` | `setSizePolicy(Expanding, Fixed)` |
| Densidad de malla no agrega puntos 3D | Controla FEM, no la rejilla visual | Spinner "Resolución campo 3D" independiente |
| Colorbar duplicada en heatmap | `ax.clear()` no borra axes de colorbar | `fig.clf()` + `add_subplot(111)` |
| sounddevice falla (PortAudio DLL) | `libportaudio64bit.dll` no carga en Anaconda | Reemplazar por `winsound` (built-in Windows) |
| Pop al finalizar reproducción (v2.5) | DAC corta seco al EOF | Fade 50 ms + 100 ms cola de silencio |
| Variable local `fm = QFormLayout(...)` sombrea import `face_materials as fm` (v2.5) | `UnboundLocalError` en `acoustic_panel._build_ui` | Renombrar local a `fmode` |
| Warning "Unknown property font-variant-numeric" (v2.5) | Propiedad CSS no soportada por Qt5 | Removida de `controls.py` y `shape_dialog.py` |
| Slice plane invisible para shoebox (v2.6) | Z-fighting con aristas wireframe rosa | Shrink 2 % + borde wireframe cian + opacidad 0,40 |
| Auto-tuner rompe fallback gmsh→voxel (v2.6) | `override="gmsh"` desactiva fallback | Mantener `override="auto"` cuando tuner elige gmsh |
| FRF y `modal_pressure_field` ~101 dB bajos en SPL absoluto (v2.11) | Factor `c²` ausente en `frequency_response` y `modal_pressure_field` (`acoustic_fem.py`) y `frequency_response` (`fem_modal.py`). La derivación canónica de la Green function modal de Helmholtz da `iωρ₀·c²·Σφ(xr)φ(xs)/(ωn²−ω²)` (porque ωn²=c²·λn y k²=ω²/c²); el código omitía el `c²` | Multiplicar prefactor por `c**2`. Validado contra C-matrix de impedancia (`bench_modal_vs_impedance.py`, RMS 1.6 dB en banda modal) y contra cálculo analítico (74.2 dB calculados vs 74.8 dB esperados). Smoke test en `acoustic_fem.__main__`. Auralización inafectada (normaliza a peak antes del DAC). Detalle en `acoustic_fem_explicado.md` §16.8 |
| Modos por encima de `f_max_malla` numéricamente sucios pero entregados al usuario (v2.12) | `solve_modes(K, M, n_modes=N)` devuelve los N modos más bajos sin chequear contra el techo de validez de la malla (`f_max_malla = c/(ppw·h_max)`). Al pedir N alto (cosa frecuente con la sugerencia Weyl) los últimos modos quedaban arriba de ese techo, con dispersión del esquema FEM y plegado de onda. Eigsh los devolvía sin error pero eran basura física | Post-clip en el panel (`_clip_modes_to_mesh_validity`) tras cada solve: descartar los modos con `f > f_max_malla` y avisar al log (`"pediste 256 modos, 210 son válidos, 46 excedían f_max_malla = 59 Hz"`). El picker, la FRF y el campo de presión sólo ven modos físicamente válidos |
| Botones del diálogo CAD/reparación clipeaban primer carácter (v2.12) | Texto centrado por default + sizeHint() subestimado por la métrica irregular del Unicode al inicio (`✓ ⛒ ✎ →`) hacían que Qt clipee el primer carácter del label. "✓  Cerrar este hueco (auto)" aparecía como "✓ errar este hueco (auto)" | Triple defensa: `setMinimumWidth(440)` en el panel izquierdo del splitter, `setMinimumWidth(380)` por botón, y `text-align: left; padding-left: 16px` vía styleSheet local |
| Botones `Exportar PNG/SVG/PDF/CSV/TXT` cortados en FRF/RT60/Slice heatmap (v2.12) | `setMinimumWidth(100)` o `setMaximumWidth(120)` no daban espacio suficiente para el texto + padding QSS Catppuccin (~135 px requerido) | Bumpeados a `setMinimumWidth(140)` con `sizePolicy(Preferred, Fixed)` |

---

## Notas de física

### Modo vs. Presión en resonancia

En `f = fₙ`:
```
p(x) ≈ [ρ₀·c²/(2·ξₙ·ωₙ)] · φₙ(xₛ) · φₙ(x)
```
La distribución espacial de `|p|` **es la forma modal** escalada por la
posición de la fuente. Solo difieren en signo (± en modo, ≥0 en presión).
Al mover la fuente a un nodo `φₙ(xₛ)=0`, ese modo se desexcita y el patrón
cambia significativamente.

### Sensibilidad de altavoz → monopolo

```
p₀ [Pa] = 20 µPa · 10^(S_dB / 20)         (presión a 1W/1m)
|Q|     = p₀ · 4π / (2π·f_ref·ρ₀)         (caudal monopolo)
```
Para S = 90 dB/W/m, f_ref = 1 kHz: |Q| ≈ 1,05 × 10⁻³ m³/s.

### Escucha: cadena de procesamiento

```
pink_noise(4s) → apply_frf_filter(H(f)) → soft-clip tanh (drive=2.5)
              → fade-in 10 ms + fade-out 50 ms
              → +100 ms silencio (anti-pop EOF)
              → int16 stereo WAV → winsound.PlaySound
```

### Frecuencia de Schroeder

```
f_s = 2000·√(RT60/V)
```
Por debajo de `f_s`: régimen modal (FEM es preciso). Por encima: campo
estadístico (energía uniforme; FEM pierde validez).

---

## Dependencias

Ver [requirements.txt](requirements.txt). Mínimo:
```
PyQt5>=5.15
pyqtgraph>=0.13.3
PyOpenGL>=3.1.6
numpy>=1.24
scipy>=1.10
gmsh>=4.13
trimesh>=4.0
matplotlib>=3.7
```
`winsound` viene built-in con Python para Windows.

Instalación:
```bash
conda activate base
pip install -r requirements.txt
```

---

*Última actualización: re-sincronizado a v2.12 el 16 de junio de 2026
(changelog maestro en MANUAL.md).*
