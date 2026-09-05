# REVIEW-FISICO.md — Auditoría físico-numérica independiente

> Auditor externo, contexto fresco. No se tomó ningún comentario/changelog/nota/memoria
> como prueba: cada afirmación se verificó contra (a) la fuente física, (b) un oráculo
> analítico/QEP exacto, o (c) una cuenta propia reproducible. Rama `dist-exe`.
> Fecha: 2026-09-04. Alcance: `acoustic_mesh.py`, `acoustic_fem.py`, `impedance.py`,
> `face_materials.py`, `modal_metrics.py`, `prediction.py`, `rir.py` + su cableado en
> `acoustic_analysis.py` / `acoustic_panel.py`.

Contexto del juicio: el software se presenta como *la simulación más exacta posible por
debajo de la frecuencia de Schroeder en recintos arbitrarios*. Todo lo de abajo mide
contra ese estándar.

---

## Resumen ejecutivo

El **núcleo físico está bien construido y bien validado donde hay oráculo**: el ensamble
FEM P1 (K, masa consistente V/20·(1+δ)), la superposición modal con su factor c² y la
perturbación de frontera para el amortiguamiento están derivados y normalizados
correctamente, y pasan contra oráculos genuinamente independientes (QEP complejo exacto,
spread 8:10:12 del cubo, autovalores analíticos del shoebox). Verifiqué además, con un
oráculo propio, que la frontera escalonada del mallado voxel **no** degrada las
frecuencias modales de forma apreciable (un shoebox rotado 30° da el mismo error que el
axis-aligned).

Los problemas que sesgan o invalidan la afirmación de JAAS **no están en las fórmulas
sino en los bordes del régimen de validez y en lo que se muestra al usuario**:

1. **CRÍTICO** — La FRF se dibuja como una curva única y válida hasta `f máx` (default
   250 Hz) usando sólo los modos calculados (default 12, que llegan a ~100 Hz). Por encima
   del último modo es un artefacto de truncamiento del sumatorio modal: el propio
   `bench_modal_vs_impedance` (n_modes=12, cuyos modos llegan a ~100 Hz) mide **27 dB**
   de error contra la solución directa en 100–150 Hz. El gráfico no sombrea ni avisa esa
   banda.
2. **MAYOR** — El corrimiento de frecuencia por reactancia (Capa 0 automática, v2.31) está
   **ON por default** para todo material poroso-compatible, se apoya en Miki/DB
   **extrapolado muy por debajo** de su rango X∈(0.01,1), y es **modelo, no medido**
   (reconocido en el propio código). Sube TODAS las fₙ hasta ~9% (medido) cuando la
   absorción cubre la mayoría de las caras.
3. **MAYOR** — `rir.py` (pipeline de validación contra mediciones) no trunca por piso de
   ruido (Lundeby/ISO 3382 anexo) antes de la integral de Schroeder, y su estimación de
   rango dinámico sobreestima la parte útil de una RIR ruidosa → RT sesgado justo en las
   mediciones reales (truncadas, ruidosas) que son la moneda de la validación.
4. **MAYOR** — El amortiguamiento/corrimiento por perturbación sólo está validado contra
   un oráculo (QEP) en **shoebox**. Para geometría no axis-aligned (el caso que justifica
   el FEM) no hay validación contra oráculo independiente.

Ninguno de estos es un error de signo o de fórmula: son límites de validez que se cruzan
en silencio y una función (corrimiento por reactancia) encendida por default sin respaldo
de medición. Con la afirmación de "máxima exactitud" en JAAS, hay que acotarlos o apagarlos.

---

## CRÍTICO

### C1 — La FRF modal se muestra fuera de la banda de validez sin aviso (truncamiento del sumatorio)

- **Dónde:** `acoustic_analysis.py:223` (`fa = np.linspace(f_min, f_max, n_freqs)` sin
  cota por último modo ni por f_max_malla); `acoustic_fem.py:404-436`
  (`frequency_response` suma sobre TODOS los `Nm` modos que se le pasan, sin truncar);
  `acoustic_panel.py:1121` (la FRF se dibuja como una sola curva `FRF (FEM)` en todo el
  eje); defaults en `acoustic_panel.py:3548` (`sb_nmodes=12`), `:3556` (`npm=2.5`),
  `:3800` (`sb_frf_fmax=250`).
- **Supuesto físico/numérico:** la superposición modal
  `H(f)=iωρ₀c² Σₙ φₙ(r)φₙ(s)/(ωₙ²−ω²+2iξωₙω)` sólo aproxima la respuesta si el sumatorio
  incluye los modos cuyo aporte (pico + cola) es relevante a `f`. Truncar en el modo N
  deja sin sus colas a todas las resonancias por encima de N. Además, por encima de
  `f_max_malla = c/(ppw·h_max)` los modos son numéricamente sucios (dispersión). No se debe
  mostrar respuesta fuera de esa banda sin avisar.
- **Escenario que falla (inputs → salida):** defaults de fábrica. Con `n_modes=12` los
  modos de un recinto típico llegan a ~100 Hz; con `npm=2.5`, `f_max_malla ≈ 343/(6·0.4) ≈
  143 Hz`. La FRF, sin embargo, se traza hasta `f máx = 250 Hz`. La banda ~100–250 Hz es la
  cola-suma de 12 modos, indistinguible de la parte válida (143–250 está además fuera de la
  validez de la malla).
- **Medición (reproducible):**
  `PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen /c/Users/aceve/anaconda3/python.exe bench_modal_vs_impedance.py`
  → "Banda 20-100 Hz: Max |diff| 2.76 dB, RMS 1.61 dB" (bien) vs
  "Banda total 20-150 Hz: **Max |diff| 27.20 dB, RMS 10.13 dB**, Mean −5.43 dB" contra la
  solución directa con matriz C. Todo el exceso de error está en 100–150 Hz (truncamiento).
- **Impacto en JAAS:** una FRF presentada con settings de fábrica es correcta abajo de
  ~82 Hz y errónea por hasta 27 dB arriba, mostrada como una única curva "exacta". El
  `_clip_modes_to_mesh_validity` (`acoustic_panel.py:5121`) descarta modos sucios pero
  **no acota el eje de la FRF ni sombrea** `[f_max_malla, f máx]`; el plot
  (`acoustic_panel.py:1121-1141`) sólo marca líneas de modo y sombreado de EQ, nada de
  validez de malla. La guía Weyl/npm-sugerido existe pero es informativa: nada fuerza la
  coherencia n_modes ↔ f_S ↔ f máx.
- **Qué haría falta:** cortar la FRF (o sombrear/rayar) en `min(último modo válido,
  f_max_malla)`, y por robustez calcular modos hasta ~2× la f de interés para tener las
  colas antes de recortar la visualización.

---

## MAYOR

### M1 — Corrimiento de fₙ por reactancia (Capa 0 auto): ON por default, extrapolado fuera de rango, no medido

- **Dónde:** `acoustic_panel.py:6965-7003` (`_material_surface`: inyecta
  `Im(β) = Im(Z0/z_c)` de un poroso semi-infinito de Miki con σ ajustada a la α de
  catálogo, líneas 6992-6994); `acoustic_panel.py:7287-7296` (se computa el corrimiento
  `_freq_shift_per_mode` SIEMPRE que el modelo sea perturbación, aun sin construcción
  manual); `acoustic_analysis.py:216-224` (`modal_freqs` corridas entran a la FRF);
  `face_materials.py:735-786` (`perturbation_xi_shift_per_mode`, `f_new = fₙ −
  Im(δ_c)/2π`); `impedance.py:83-104` (Miki), `:404-436` (`sigma_from_alpha`).
- **Supuesto:** que la reactancia de superficie de un material real coincide con la de un
  **poroso semi-infinito de Miki** cuya σ se ajusta por mínimos cuadrados a la α de
  catálogo de incidencia aleatoria. Dos supuestos frágiles encadenados: (i) forma de la
  reactancia = poroso semi-infinito; (ii) Miki/DB válidos donde se lo usa (X∈(0.01,1)).
- **Escenario que falla (cuenta propia, reproducible):** material poroso típico
  (α = 0.15/0.35/0.65/0.85/0.95/… ) en las 6 caras de un 5×4×3:
  ```
  sigma fit ≈ 65533 ;  X(125Hz)=ρ₀f/σ=1.21·125/65533 ≈ 2.3e-3  (validez Miki: 0.01–1)
  modo 0: f_rig= 34.40 → f_eff= 37.50  (+9.0%)
  modo 2: f_rig= 55.46 → f_eff= 60.59  (+9.3%)
  modo 7: f_rig= 80.88 → f_eff= 88.88  (+9.9%)
  ```
  Corrimiento sistemático **+7…+10%** en TODAS las fₙ. Con una carpeta σ≈6.1e5,
  X≈2.5e-4 (≈40× por debajo del piso de validez de Miki). Script:
  `scratchpad/quantify_shift.py` (usa `perturbation_xi_shift_per_mode` + `_material_surface`).
- **Atenuante (también propio):** con absorción localizada (carpeta en el piso + paredes
  duras, α<0.15 → no poroso-compatible → β real → sin corrimiento) el shift cae a
  **+0.4…+0.7%** (`scratchpad/quantify2.py`). El efecto escala con la fracción de
  superficie poroso-compatible; es grave sólo en salas muy tratadas (booth, control room
  con absorción de banda ancha en casi todas las caras).
- **Impacto en JAAS:** las fₙ son el número estrella de "modal exacto bajo Schroeder". Un
  corrimiento de hasta ~9% desde una reactancia **asumida** (el propio docstring, línea
  6978: "La reactancia es MODELO (asumida a partir de alpha), no medida") y con Miki
  extrapolado ~10–40× por debajo de su rango, **empeora** el acuerdo con los picos modales
  medidos de una RIR en el caso más tratado, en lugar de mejorarlo (una pared de mampostería
  real es casi rígida: β≈0, corrimiento ≈0; el semi-infinito poroso sobreestima la
  compliancia de frontera). El signo/magnitud está bien respecto del QEP con esa β
  (bench_perturbation_complex T3, <15%), pero la β elegida no tiene respaldo de medición.
- **Nota de rango:** `sigma_from_alpha` (impedance.py:404) barre σ∈[1e3, 2e6]; en la banda
  modal (f<200) eso da X bien por debajo de 0.01 para casi cualquier material → toda la
  parte reactiva del default vive fuera del rango validado de Miki/DB. El amortiguamiento
  (Re β por inversión de Paris de la α de catálogo) NO tiene este problema: es exacto y
  reduce sin regresión al modelo α→β de siempre (verificado, ver SÓLIDO).
- **Qué haría falta:** apagar el corrimiento por default (o marcarlo explícitamente como
  hipótesis de modelo en la UI/plot), y validarlo contra al menos una RIR medida antes de
  presentarlo como exactitud.

### M2 — `rir.py`: RT sin truncado por piso de ruido (la validación contra medición se sesga)

- **Dónde:** `rir.py:164-185` (`schroeder_curve`: integra la EDC sobre TODA la IR menos el
  último 5%, sin detección de piso de ruido / Lundeby); `rir.py:205-222` (`rt_from_ir`:
  `dyn = -finite.min()` sobreestima el rango útil de una señal ruidosa; el rango de ajuste
  −5..−35 / −25 / −15 es fijo, independiente de dónde esté el piso); `rir.py:188-202`
  (`_fit_rt`).
- **Supuesto:** que la EDC de Schroeder es lineal en el rango de ajuste. En una RIR real la
  integral regresiva del **ruido de fondo** levanta la cola de la EDC (se aplana) y sesga
  la pendiente. ISO 3382 exige truncar la IR en el cruce con el piso (método de Lundeby) y
  restar el ruido antes de integrar.
- **Escenario que falla:** RIR de control room truncada (~190 ms) con piso de ruido dentro
  del rango de ajuste (p.ej. −30 dB con T30 pidiendo hasta −35). La EDC se curva; el ajuste
  lineal da una pendiente sesgada. El gate `r2>0.98` protege parcialmente (curvatura fuerte
  → r2 baja → `ok=False`), pero una curvatura suave puede pasar el gate con RT sesgado. El
  `dyn` reportado (61 dB en el propio bench t3) toma el nivel aplanado como "rango
  dinámico", sobreestimando la parte lineal disponible.
- **Reproducción / límite del bench:** `bench_rir.py` t3 sólo prueba piso a **−45 dB**, es
  decir 10 dB por debajo del rango T30 (−5..−35): por construcción no estresa un piso
  DENTRO del rango de ajuste. Correr `bench_rir.py` → 14/14 OK, pero ninguno cubre el caso
  que sesga. (grep confirmó: sin `lundeby`/`SNR`/resta de ruido en el módulo.)
- **Impacto en JAAS:** el RT medido es (a) el patrón contra el que se compara el modelo y
  (b) opcionalmente la fuente de ξₙ ("reemplaza al Sabine estimado", docstring rir.py). Un
  RT sesgado por ruido de fondo contamina las dos direcciones de la validación, que es el
  corazón de la presentación.

### M3 — Perturbación (damping + corrimiento) sin oráculo en geometría no axis-aligned

- **Dónde:** `bench_perturbation_complex.py` y `bench_perturbation_xi.py` (T5) validan
  contra el QEP exacto y el spread 8:10:12 **sólo en shoebox 5×4×3**;
  `bench_modal_vs_impedance.py` (matriz C) también shoebox. `face_materials.py:686-732`
  (`_modal_surface_integrals`: integra φ² sobre la superficie LISA de render con re-escala
  por cobertura, mientras la malla es voxel escalonada) no tiene test contra un QEP en
  malla irregular.
- **Supuesto:** que la cuadratura de superficie (φ² sobre la superficie lisa, muestreada en
  centroides que pueden caer fuera de la malla escalonada y re-escalados por área
  muestreada, `face_materials.py:719-731`) reproduce la integral de frontera del problema
  exacto también cuando frontera-lisa ≠ frontera-voxel (paredes oblicuas). En shoebox
  coinciden, por eso el bench no lo ve.
- **Escenario:** recinto con paredes splay/gable/arco (los que motivan el FEM). El
  amortiguamiento por modo y el corrimiento salen de una integral de superficie con
  re-escala heurística por cobertura de área; no hay oráculo que acote su error ahí.
- **Impacto en JAAS:** la afirmación es "recintos arbitrarios". El ξₙ (y por ende RT por
  banda, SBIR, corregibilidad-EQ) y el corrimiento en geometría arbitraria no están
  validados contra nada exacto. **Nota:** las *frecuencias* modales en geometría no
  axis-aligned SÍ las verifiqué (ver SÓLIDO, S5); esta observación es específica del
  amortiguamiento/corrimiento y de la cuadratura de superficie con cobertura.
- **Qué haría falta:** un QEP (matriz C) sobre la malla voxel de un recinto oblicuo, o un
  estudio de convergencia de ξₙ y del corrimiento con npm en geometría irregular.

---

## MENOR

### m1 — `ppw=6` por default → ~2% de error en fₙ en el tope de la banda modal

- **Dónde:** `acoustic_mesh.py:357-365` (`max_solver_frequency`, ppw=6);
  `acoustic_panel.py:5163` (`_validity_freq`, ppw=6); default `npm=2.5`
  (`acoustic_panel.py:3556`).
- **Cuenta propia (reproducible, `scratchpad/staircase.py`):** shoebox 5×4×3 vs modos
  analíticos: `npm=2.5` → maxerr 2.04%, rms 1.17%; `npm=5.0` → maxerr 0.56%, rms 0.31%
  (convergencia O(h²) limpia). ppw=6 es una regla de "ingeniería", no de alta exactitud;
  ~2% a 80 Hz son ~1.6 Hz, comparables a la resolución de picos de una RIR. Para "máxima
  exactitud" conviene documentar que hace falta npm mayor (o subir ppw) y no vender el
  default como el límite de exactitud.

### m2 — `frequency_response` zeroea en silencio fuentes/receptor fuera de la malla escalonada

- **Dónde:** `acoustic_fem.py:407-418` (`evaluate_one` → `None` → `phi = 0.0`).
- **Escenario:** fuente en esquina (típico para graves) cerca de una pared oblicua: el
  punto puede estar dentro de la superficie lisa (pasa `_validate_inside`,
  `acoustic_panel.py:5168`) pero fuera del último voxel de la malla escalonada → `phi_s=0`
  → su aporte a la FRF/campo desaparece sin aviso. Edge-case, pero silencioso.

### m3 — Cross-check aritmético del docstring de Miki mal (coeficientes OK)

- **Dónde:** `impedance.py:88-93`. El docstring afirma `826.4^-0.632 = 0.01263`; el valor
  real es ≈0.01434 (`5.50·0.01434 = 0.0789`, no 0.0699). Los **coeficientes finales**
  (0.0699/0.107/0.109/0.160 con X=ρ₀f/σ) son los canónicos de Miki y están bien
  (verificados contra la forma estándar); sólo la reconciliación numérica escrita no cierra.
  No afecta resultados, pero es un "se ve validado y no lo está" en un comentario.

### m4 — `rir_to_frf` sin ventana antes de la FFT

- **Dónde:** `rir.py:108-124`. Si la RIR viene truncada, la FFT sin ventana mete leakage
  espectral que ensancha/desplaza picos modales. Para una RIR con cola completa es
  inofensivo; para las truncadas (las reales del control room) conviene una ventana suave
  en la cola. Menor porque `find_modal_peaks` trabaja por prominencia.

---

## Qué está SÓLIDO (verificado, no asumido)

- **Ensamble FEM P1.** `acoustic_fem.py:45-98`. K = V·(∇N·∇N), masa **consistente**
  M = (V/20)(1+δ_ij) (diag V/10, off V/20) — es la consistente O(h²), no lumped.
  Simetrización defensiva correcta. `solve_modes` con eigsh shift-invert y
  `f=c√λ/2π` (λ=k²): correcto para el problema de Neumann −∇²p=k²p.
- **Superposición modal y su factor c².** `acoustic_fem.py:376-436`. Derivé la Green modal
  de Helmholtz con modos M-ortonormales (∫φ²dV=1) y da exactamente
  `H=iωρ₀c²Σ φ_r φ_s/(ωₙ²−ω²+…)`. El signo del término de amortiguamiento
  `+2iξωₙω` es el del oscilador con e^{+iωt}. Banda 20–100 Hz coincide con la solución
  directa (matriz C) a 1.6 dB RMS (`bench_modal_vs_impedance`).
- **Perturbación de frontera para el amortiguamiento.** `face_materials.py:571-575, 636-683`.
  Verifiqué la normalización: con ∫φ²dV=1, `δ=(c/2)Σ β ∫φ²dS` = `(c/2V)∮βψ²dS` con
  ∫ψ²dV=V, que es Morse & Ingard §9.4 / Kuttruff. `ξ=δ/ω`. Pasa contra el **QEP complejo
  exacto** (sla.eig 2N) a <3% (T5, α_norm≤0.3) y reproduce el spread axial:tangencial:
  oblicuo **8:10:12** del cubo (err_f<0.8%). Oráculos genuinamente independientes.
- **Convención de signo e^{±iωt} y conj(β).** `face_materials.py:855-897`,
  `bench_perturbation_complex.py` T2/T3. El QEP (oráculo) usa e^{+iωt} y la cadena aplica
  `conj(Z0/Z)` para pasar de la impedancia e^{−iωt} de impedance.py. La dirección de
  amortiguamiento (Re β>0 → decae) y de corrimiento matchean el QEP a <15%. El signo no
  está "cancelándose por casualidad": el oráculo lo fija.
- **Inversión de Paris (α→β real).** `face_materials.py:579-613`. Round-trip exacto
  (bench_perturbation_xi T1) y límite α_rand≈8β cuando β→0. Material uniforme reduce EXACTO
  a Sabine global donde debe (bench_irregular_sampling A2b).
- **Frontera escalonada del voxel NO arruina las fₙ.** Cuenta propia
  (`scratchpad/staircase.py`): un shoebox **rotado 30°** (fuerza escalera en las 4 paredes)
  da maxerr 1.95% / rms 1.24% a npm=2.5, prácticamente igual que el axis-aligned
  (2.04%/1.17%), con V preservado (59.78/60) y convergencia O(h²). Los modos bajos promedian
  la rugosidad. Esto respalda el uso del voxel en recintos arbitrarios **para frecuencias**.
- **Coeficientes DB/Miki/JCA.** `impedance.py:67-147`. DB (0.0571/0.087/0.0978/0.189) y
  Miki (0.0699/0.107/0.109/0.160) con X=ρ₀f/σ son los canónicos (Cox & D'Antonio 5.11);
  JCA (ρ_e, K_e) con la conversión j→−i coherente. TMM `Z=−i z_n cot(k_z d)` y recursión
  correctas. `bench_impedance` 36/36, `bench_capa0_all` 164/164 (corridos, verdes de verdad).
- **Métricas modales.** `modal_metrics.py:641-733`. RT por banda = T30 del decay
  multi-exponencial sintético (correcto: la pendiente de una suma de exponenciales no es la
  media de tasas; la domina el modo menos amortiguado). Overlap `M=B_HP·n`, `B_HP=2.2/RT60`,
  `f_Schroeder=2000√(RT/V)`: todas estándar y bien escritas.
- **Benches corridos y verdes (no "dicen pasar"):** voxel_mesh, perturbation_complex 11/11,
  perturbation_xi 21/21, polarity 26/26, modal_vs_impedance, default_z 8/8, capa0_all
  164/164, rir 14/14, impedance 36/36. Las tolerancias de los oráculos de perturbación
  (<3–15%) son razonables para primer orden a |β|≤0.17, no laxas a conveniencia.

## Qué NO pude verificar

- **Exactitud del amortiguamiento/corrimiento en geometría no axis-aligned** (M3): no hay
  oráculo; sólo verifiqué que las *frecuencias* aguantan la escalera.
- **La reactancia por default contra una medición real** (M1): el propio código la declara
  "asumida, no medida"; no hay RIR medida en el repo para confrontarla (validation_protocol
  y calibración con RIRs existen, pero no encontré una comparación fₙ_medida vs fₙ_corrida).
- **Comportamiento de `rir.py` con RIRs medidas reales ruidosas** (M2): sólo hay IRs
  sintéticas en los benches; no pude correr el pipeline contra una medición con piso de
  ruido dentro del rango de ajuste.
- **El path de mallado gmsh** (`mesh_router`): la auditoría se centró en el voxel (el
  default y el validado); no audité el motor gmsh ni el carve de muebles a fondo.
- **prediction.py** (RATIO_LIBRARY / scoring de diseño): es figura de mérito / ranking de
  diseño, no el campo físico bajo Schroeder; lo revisé sólo superficialmente por prioridad.

---

## Estado de remediación (post-auditoría, agregado por el asistente principal)

- **M1 — HECHO (commit 9b9f167).** Reactancia auto del material APAGADA por default
  (`_auto_material_reactance=False`, toggle opt-in). Amortiguamiento exacto intacto;
  construcciones explícitas sin cambios. `bench_default_z` 10/10, Capa 0 164/164.
- **C1 — HECHO.** La FRF ahora sombrea y dibuja punteada la banda `> min(f_max_malla,
  último modo)`; la curva sólida es solo la banda válida. Reproducido el 27 dB antes de
  arreglar. (No se cambian defaults de `n_modes`/`npm` en silencio; se respeta la palanca
  del usuario y se avisa visualmente.)
- **M2 — HECHO.** `rir.py`: truncado por piso de ruido (Lundeby iterativo) + resta de
  ruido (Chu/ISO 3382) en `schroeder_curve` (flag `noise_trunc=True`). `bench_rir_noise`
  5/5: RIR ruidosa/truncada recupera el RT dentro de 3-10% vs +312-424% sin truncar; IR
  limpia sin regresión (`bench_rir` 14/14).
- **M3 — HECHO (`bench_perturbation_oblique.py`, 3/3).** Se montó el oráculo QEP sobre
  malla voxel de recintos OBLICUOS (paredes en taper 0.35 y techo inclinado). Resultado en
  dos partes:
  - **(A) La fórmula de perturbación es exacta a 1er orden en geometría oblicua:** sobre el
    MISMO borde voxel que usa el QEP (δ = (c/2)β·φᵀCφ, φ M-ortonormal), el amortiguamiento
    coincide con el QEP a **1.4% (taper) / 0.8% (techo)**, el corrimiento a ~1.5%. La
    afirmación "recintos arbitrarios" queda respaldada para el amortiguamiento/corrimiento,
    no solo para las frecuencias.
  - **(B) Integrar sobre la superficie LISA (lo que hace la app) es lo correcto, no un bug:**
    el borde voxel del taper tiene **+34% de área** (escalera); un amortiguamiento sobre el
    borde voxel (como el QEP) sobreestimaría el del recinto real liso por ese factor. La
    integral de la app sobre la superficie lisa (con re-escala por cobertura) evita ese
    sesgo (difiere del voxel en ~22%, del orden del 34% de inflación de área). Vindica la
    decisión de diseño que el auditor había marcado como no validada.
  - **Caveat honesto:** el valor de la superficie lisa no está PROBADO exacto (para eso
    haría falta un QEP sobre malla boundary-fitted/gmsh como oráculo del recinto liso
    verdadero); corrige la mayor parte de la inflación de escalera, con incertidumbre
    residual acotada y MENOR que el ~34% que incurriría un enfoque de borde-voxel.
- Menores (m1-m4): documentados; m1 (ppw=6→~2%) y m3 (docstring Miki) pendientes de nota.

---
*Reproducción rápida:*
`PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen /c/Users/aceve/anaconda3/python.exe bench_modal_vs_impedance.py`
(C1, 27 dB), y con `PYTHONPATH` al proyecto: `scratchpad/quantify_shift.py` (M1, +9%),
`scratchpad/quantify2.py` (atenuante M1), `scratchpad/staircase.py` (S5, escalera 30°).
