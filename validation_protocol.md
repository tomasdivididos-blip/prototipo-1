# Protocolo de validación — fidelidad modal sim vs RIR medida (para JAAS)

**Estado: CONGELADO 2026-09-04** (umbrales M1-M4 §5 confirmados por el usuario). Cualquier cambio posterior va en §10 con fecha y motivo.

> **Pre-registro.** Este documento se CONGELA antes de correr ninguna comparación. Las
> métricas y umbrales se fijan acá, no después de ver los resultados. Cualquier ajuste
> posterior se registra con fecha y motivo al final. Es el mecanismo anti-sesgo del lado
> empírico (el otro es el `auditor-fisico`, lado código).

## 0. Pregunta y falsabilidad

**Pregunta:** ¿La simulación predice la respuesta modal (por debajo de f_Schroeder) de
recintos reales, con exactitud, en geometría arbitraria, SIN tunear parámetros al
resultado?

**Qué la refutaría** (criterio de fracaso, definido antes): si en la mayoría de los
recintos el error de frecuencia modal supera el umbral, o el RT60 por banda cae fuera de
tolerancia, con las α tomadas del catálogo por descripción de material (sin ajuste fino),
entonces la afirmación de "exactitud en rango modal" NO se sostiene y hay que reportarlo
así en JAAS. El objetivo NO es que dé bien; es medir cuán bien da y por qué.

## 1. Regla de oro anti-sesgo (congelada)

- Las α salen del **catálogo por descripción de material** (hormigón, durlock, vidrio...).
  **Nada se tunea para mejorar el match.** Si en algún recinto se ajusta algo (una α, una
  dimensión), se declara explícitamente en la tabla de resultados como "ajustado".
- La geometría sale del `.obj`/plano tal cual. Las posiciones fuente/mic son las medidas.
- Se corre TODO el set de recintos disponibles; no se descartan los que dan mal. Un recinto
  se excluye solo por un problema de DATO (RIR corrupta, geometría desconocida), documentado.

## 2. Datos requeridos por recinto

1. Geometría interior exacta (`.obj` o plano acotado). cm importan (fₙ ∝ 1/L).
2. Posición de la fuente (XYZ del centro acústico).
3. Posiciones de los receptores (XYZ de cada mic).
4. RIRs (`.wav`) + fs + método (sweep/MLS) + relativo o calibrado en nivel.
5. Descripción de superficies (material/construcción por cara). Sin impedancia.
6. Condiciones: vacío/amueblado (y qué/dónde), temperatura (→ c), HVAC apagado.

Fuentes: (a) datasets públicos con geometría+posiciones+RIR; (b) mediciones/planos propios.

## 3. Banda de análisis

Por recinto, banda modal = [f_min, f_S], con:
- f_S = frecuencia de Schroeder que computa el propio software (punto fijo desde V y RT).
- f_min = primer modo axial teórico (c/2·L_max) menos un margen, o el piso útil de la RIR
  (donde la SNR de la medición sigue siendo válida), lo que sea mayor.

## 4. Pipeline de comparación (usa `rir.py`, ya existente)

1. RIR → FRF: `rir.rir_to_frf` (documentar ventaneo).
2. RT60 por banda: `rir.rt60_per_band` (EDC de Schroeder, `rt_from_ir`).
3. Picos modales medidos: `rir.find_modal_peaks` sobre la FRF en la banda modal.
4. Simulación: mismo recinto (geometría real), mismas posiciones fuente/mic, α de catálogo,
   modelo de amortiguamiento = perturbación de frontera (default). Se extrae FRF simulada,
   fₙ (efectivas, con corrimiento de Capa 0), RT60ₙ.
5. Emparejamiento de modos medidos ↔ predichos: por cercanía en frecuencia dentro de una
   ventana de tolerancia (registrar el algoritmo; si hay ambigüedad, Hungarian por |Δf|).

## 5. Métricas y umbrales (CONGELADOS 2026-09-04, confirmados por el usuario)

**Primarias (criterio de PASA/FALLA):**

| # | Métrica | Definición | Umbral (congelado) |
|---|---|---|---|
| M1 | Error de frecuencia modal | mediana de \|f_pred − f_med\|/f_med sobre modos apareados | ≤ **3 %** |
| M2 | Cobertura modal | % de modos medidos apareados a un predicho dentro de tol | ≥ **80 %** |
| M3 | RT60 por banda | \|RT_sim − RT_med\| por banda de octava/tercio en la banda modal | ±**5 %** o ±**0.05 s** (el mayor) |
| M4 | Nivel/forma espacial | correlación del **promedio espacial** de la FRF (sim vs med) sobre las posiciones | ≥ **0.7** |

**Secundarias (se reportan, NO deciden PASA/FALLA):**

- Correlación punto-a-punto de la FRF. **Por física es baja bajo Schroeder** (solapamiento
  modal M>1); un valor bajo NO es fracaso. Se reporta para honestidad, no como criterio.
- Varianza espacial del nivel (sim vs med): mide si la sim reproduce la no-uniformidad
  modal del campo (lo distintivo del rango modal).

## 6. Criterio de éxito global (para JAAS)

Definir con el usuario. Propuesta: en **≥ N recintos** (fijar N según cuántos consigamos),
M1 y M3 dentro de umbral, con α de catálogo y sin tuneo. Se reporta el resultado COMPLETO
(incluidos los recintos que fallan y la hipótesis del por qué), no una selección.

## 7. Registro de resultados

Una tabla por recinto: dataset/fuente, V, f_S, nº modos comparados, M1, M2, M3, M4,
"ajustado sí/no", y una nota de interpretación. Más un resumen agregado. Se guarda en
`validation_results.md` (o CSV) generado por el pipeline, no a mano.

## 8. Interpretación (quién y cómo)

El asistente principal ayuda a interpretar, pero como es co-autor su lectura se contrasta
con: (a) los umbrales de acá (fijados antes), (b) el `auditor-fisico` (que confirma que el
pipeline `rir.py` y el núcleo no tienen un bug que fabrique un match o un fallo). Ninguna
métrica se cambia después de ver los números sin dejarlo registrado en §10.

## 9. Estado (recintos y datos)

**Datasets públicos identificados (2026-09-04).** Gate crítico para rango modal =
contenido de BAJA FRECUENCIA (sweep/parlante que baje de ~40 Hz); si no, no excita los
modos. A confirmar antes de comprometer cada uno.

| Dataset | Recinto | V, f_S aprox | Geometría | Posiciones | Baja frec | Uso |
|---|---|---|---|---|---|---|
| **MeshRIR** | cuboide 7.0×6.4×2.7 | ~121 m³, f_S~112 Hz (RT 0.38) | cuboide conocido | **3969** mics (grilla 5 cm) desde 1 fuente + 441 desde 32 | a confirmar (parlante 3 vías con woofer) | M1 (forma modal), **M4 (varianza espacial, ideal por densidad)**. CC BY 4.0, Zenodo |
| **FLAIR (2025)** | 1 recinto, geometría láser | a confirmar (paper) | **nube de puntos 3D mm** → construíble a .obj | 270 RIR, mics calibradas láser | a confirmar (paper) | **el mejor para "geometría arbitraria"** (geometría exacta no trivial). CC BY 4.0, Zenodo 17037517 |
| dEchorate | cuboide 6×6×2.4 | 86.4 m³, f_S~118 Hz | cuboide, pos ±2 cm | 30 mics × 6 fuentes × 11 config | **NO: sweep 100 Hz–14 kHz** (se pierde 28–100 Hz) | marginal para modal (banda 100–118 Hz muy angosta); su config "totalmente absorbente" sirve de caso límite del damping. Zenodo+GitHub |

Descartado para validación: `facebookresearch/AcousticRooms` (RIR SIMULADAS, no medición → no es ground truth). Secundarios a mirar: MIRaGe, Arni (Aalto), Univ. Rochester RIR.

- [x] Datasets públicos identificados.
- [x] **Runner M1 corrido sobre MeshRIR (`validate_meshrir.py` → `validation_results.md`), 2026-09-05.**
  Caja 7.0×6.4×2.7, c=347.0 m/s (T=26.3°C), 3969 mics promediados, reactancia auto OFF.
  Resultado: **M1 (vs FEM) = 0.76% → PASA** (umbral ≤3%), **M2 = 80% (4/5) → PASA** (umbral ≥80%).
  M1 vs analítico = 1.11% (el desacuerdo es FÍSICO: piso numérico del FEM ~0.38% a npm=4, converge O(h²)).
  Pico medido de 22.0 Hz excluido por sub-modal (< 1er axial 24.8 Hz = c/2Lx): no es resonancia de sala.
  Único residual >tol: modo medido a 52.0 Hz (4.5%), en región modal densa (analíticos 54.2 y 56.5 a <5 Hz →
  el peak-pick sobre el promedio espacial se corre). M1 (mediana) es robusto a esto.
- [x] **M4 sobre MeshRIR corrido (`validate_meshrir_m4.py`), 2026-09-05 → INCONCLUSO.**
  MeshRIR NO publica la ubicación absoluta del rig en el cuarto (verificado en paper/repo/página/dataset).
  Barrido de 27 ubicaciones plausibles: M4 crudo máx 0.44, destendenciado máx 0.53, **0/27 ≥ 0.7**.
  Dos causas: (1) ubicación no publicada → patrón de amplitudes modales no fijable; (2) coloración de
  fuente (DS-7) + monopolo iω domina la M4 cruda. Los picos SÍ coinciden en frecuencia (M1 <1%).
  **M4 autoritativo → FLAIR.** MeshRIR aporta solo M1.
- [x] **FLAIR: M1 + M4 corrido (`validate_flair.py` + `flair_geometry.py`), 2026-09-06.**
  Geometría RECONSTRUIDA de la nube de 2.9M puntos (alinear yaw 8.5° + occupancy + sellar/corregir +
  marching_cubes → superficie cerrada → build_volume_mesh). Sala 4.96×5.08×2.72, V=60.8 m³, posiciones exactas.
  **M1 = 1.42% → PASA** (M2 80%), sobre geometría arbitraria: resultado fuerte para JAAS.
  **M4 (destendenciado, banda [45, f_S=142]) = 0.615 → MISS marginal**; crudo 0.655; fuente 1: 0.539.
  Limitante de M4: rolloff LF del parlante + discrepancia cerca de f_S + reconstrucción ±1.6%; las fₙ SÍ coinciden.
- [x] **Auditoría independiente (`auditor-fisico`) + test de discriminación, 2026-09-06.** Reporte en
  `REVIEW-VALIDACION.md`. Hallazgo crítico C1 (M1/M2 pueden pasar con sala equivocada) → se implementó
  `validate_discrimination.py` (línea base nula + barrido de escala): **MeshRIR M1 NO discrimina**
  (percentil 42, azar); **FLAIR M1 SÍ discrimina** (percentil 1). **M4 FLAIR discrimina fuerte** (pico
  agudo en s=1.045) y revela un sesgo de malla ~4.5% (modos sim altos). Fixes: guard de sellado
  (`seal="auto"` en flair_geometry), docstring, y bug de clobber de validation_results.md (el runner
  ahora escribe `validation_meshrir_m1.md`). Ningún número fabricado (auditor).
- [x] **M3 (RT60 por banda): NO EVALUABLE sobre estos datasets, 2026-09-06.** Doble bloqueo: (1) físico,
  RT es de campo difuso, mal definido bajo Schroeder (medido: n_confiable 1-5 de 200 mics en 31/63 Hz;
  MeshRIR 63 Hz da 1.24 s absurdo); solo 125 Hz (≈f_S) es confiable. Refuerza la tesis (la estadística de
  sala no vale ahí). (2) De dato: el sim predice RT desde materiales que los datasets no documentan; usar
  el RT medido sería circular. **DIFERIDO a medición propia con materiales.** Ver `validation_results.md`.
- [ ] **Refinar malla/reconstrucción FLAIR** para testear si cierra el sesgo ~4.5% de M4. FUTURO.
- [x] **Descargados y baja frecuencia CONFIRMADA sobre datos reales (2026-09-05)** en `datasets/`:
  - **FLAIR** (`datasets/flair/data_FLAIR.mat`, 116 MB, MD5 OK): fs 48 kHz, c 344.7,
    270 RIRs (135 mics × 2 fuentes, XYZ exactas), **nube de 2.9M puntos de contorno +
    normales** (geometría exacta → construíble). bbox 5.78×5.62×3.35 m. **Baja frecuencia
    FUERTE: 62% de la energía 20-2000 Hz está en 20-120 Hz.** Ideal para modal + geometría
    arbitraria. PRIMARIO.
  - **MeshRIR S1-M3969** (`datasets/meshrir/S1-M3969_npy/`, 1.0 GB, ZIP íntegro): fs 48 kHz,
    T 26.3°C, cuboide 7.0×6.4×2.7, fuente (2.0,1.5,0.0), **3969 mics en grilla de 5 cm**
    (región ±0.5×±0.5×±0.2 m). LF más débil (1.5% de energía <120 Hz) pero **los modos son
    resolubles**: picos del promedio espacial a 23.4/52.7/57.1/68.8/79.1/117 Hz (axiales
    teóricos 24.5/26.8/63.5). Usable para M1 y sobre todo **M4 (varianza espacial, densidad
    única)**; M3 con cuidado en las bandas bajas. COMPLEMENTO.
  - dEchorate NO descargado (sweep desde 100 Hz, descartado para modal).
- [ ] Mediciones/planos propios.

## 10. Cambios al protocolo posteriores al congelamiento

- **2026-09-04 — reactancia auto del material APAGADA por default (hallazgo M1 de
  `REVIEW-FISICO.md`).** La auditoría independiente confirmó (reproducido) que el
  corrimiento de fₙ por la Z auto derivada del α (Miki extrapolado, modelo no medido)
  sesga las fₙ hasta ~9% en salas muy tratadas. Decisión del usuario: se apaga por default
  (`_auto_material_reactance=False`, toggle opt-in en el panel). **Consecuencia para la
  validación:** la comparación primaria fₙ_sim vs fₙ_medida se corre con la reactancia auto
  OFF (β real, amortiguamiento exacto). La reactancia queda como HIPÓTESIS a testear: se
  puede correr un segundo pase con el toggle ON y medir si M1/M4 mejoran o empeoran vs las
  RIRs. Las construcciones explícitas (perforado/membrana/poroso+cámara) NO se ven
  afectadas: son modelos elegidos, no extrapolados, y aportan reactancia siempre.
- Pendiente antes de correr validación (mismo audit): C1 (acotar la FRF a la banda válida)
  y M2 (truncar el RT por piso de ruido en `rir.py`). Ver `REVIEW-FISICO.md`. **[HECHO, commit 3785f3f]**
- **2026-09-05 — M4 quedó SUB-ESPECIFICADA frente a la coloración de fuente (hallazgo del run MeshRIR).**
  La definición congelada ("correlación del promedio espacial de la FRF") no dice cómo tratar la coloración
  del parlante ni el modelo de fuente. Al correrla cruda sobre MeshRIR, la correlación la domina la
  diferencia de banda ancha (parlante DS-7 real vs monopolo ideal iω), no la estructura modal, dando ~0
  aun cuando los picos coinciden (M1 <1%). **Decisión pendiente (a fijar CON el usuario antes de correr M4
  sobre FLAIR, para no ajustar la métrica al resultado):** o bien (a) destendenciar/blanquear ambos
  espectros de forma simétrica (comparar estructura modal, no coloración), o (b) comparar sobre picos
  modales apareados, o (c) modelar la respuesta de fuente medida si el dataset la trae. Se elige el criterio
  ANTES de ver el número de FLAIR y se registra acá. El umbral M4 ≥ 0.7 NO se toca.
- **2026-09-06 — RATIFICADO (con el usuario): M4 = correlación DESTENDENCIADA** (baseline suavizada en
  log-f restada simétricamente a sim y medido) sobre la banda [f_min, f_S]. f_min = piso útil de la RIR
  (protocolo §3; para FLAIR = 45 Hz, el parlante DS no radia por debajo). f_S = 2000·√(RT/V). La banda NO
  se elige para pasar; el umbral 0.7 no se toca. Resultado FLAIR bajo esta definición: M4 = 0.615 (MISS
  marginal), reportado como tal. La opción (c) (modelar la respuesta de fuente del dato) queda como
  refinamiento futuro si se quiere cerrar el gap 0.62→0.7.
