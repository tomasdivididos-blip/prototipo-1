# Plan — Frente de onda opuesto y su admitancia (interacción front↔rear)

> **Estado: BORRADOR. E1 COMPLETO como prototipos de validación headless: E1a
> (oráculo 1-D, `bench_front_rear_duct.py` 4/4), E1b (campo modal real,
> `bench_front_rear_room.py` T1-T4) y E1c (admitancia β_rear extraída, T5-T6) →
> `bench_front_rear_room.py` 6/6. E1c redirige E3 al QEP (β_rear no es
> perturbativo). **E3 (opción (b), QEP exacto) HECHO: `bench_front_rear_qep.py`
> 4/4 — el RT60 del 1er axial colapsa ×1107 con la pared matcheada (C2 genuino).
> E4a/E4b (norte front↔rear = minimizar R de la pared trasera) y E5 (panel de
> decaimiento con 4º estado «pared trasera matcheada» = C2) HECHOS.** El plan está
> IMPLEMENTADO (E1-E5); quedan solo refinamientos opcionales (QEP exacto proyectado a
> los modos para la curva C2 de E5; QEP sobre FEM nodal real + β compleja de E3). Nota: el quick-win perceptual
> de Fazenda (umbral de decaimiento modal en la tabla de modos, `perceptual.py`) es
> una mejora del panel EXISTENTE, independiente de este plan, y ya está hecho.
> Vara del proyecto: exactitud por debajo de Schroeder manda; respetar las
> condiciones necesarias y suficientes de cada herramienta; todo modelo se valida
> (analítico / oráculo exacto / medición). Ver memoria [[damping-perturbation]],
> [[z-impedance-modeling]], [[source-model-dba]].

## 1. Objetivo

Modelar la interacción entre los subs **delanteros** y los **traseros** como una
**terminación de admitancia activa**: el array frontal impone un frente de onda
(onda plana viajera por debajo del primer modo transversal del eje), y el array
trasero presenta una admitancia superficial β_rear que lo **absorbe**. Con eso se
busca:

1. **Calcular** el frente de onda que imponen los subs (campo p y velocidad normal
   vₙ en el plano trasero) y su admitancia Y_inc = vₙ/p.
2. **Predecir** la interacción front↔rear traduciéndola a un cambio real de polos
   modales (Δξₙ amortiguamiento, Δfₙ corrimiento), no solo a redistribución de
   energía.
3. **Optimizar** posición/nivel/delay/polaridad del array trasero para maximizar el
   amortiguamiento de los modos axiales del eje manteniendo la respuesta plana.

Esto es la versión **rigurosa C2** del panel «Decaimiento de Subs»: hoy
`modal_decay.py` muestra el decaimiento del campo TOTAL (C1, honesto: el drive
redistribuye energía modal pero NO toca los polos). El salto es que una frontera
trasera con admitancia activa SÍ mueve los polos (la estacionaria del eje queda
amortiguada de verdad).

## 2. Marco físico (derivación)

### 2.1 El frente de onda del array frontal
Dos subs contra la pared frontal + sus imágenes especulares forman, a bajas
frecuencias, una **pared simétrica de fuentes** que radia una **onda plana** en el
eje frente↔fondo (CABS, Celestinos & Nielsen; Santillán §I-II). En una sala
rectangular, por debajo del primer modo transversal de ese eje **solo se excitan
los modos axiales**, y el campo de fuentes de pared es (Santillán, Ec. 4):

$$ p(\mathbf{r}) \propto \sum_{m} \frac{q\,\cos(m\pi y/L_y)}{(m\pi/L_y)^2 - 2ik(1/L_x+1/L_y+1/L_z) - k^2}\,\phi_m(\mathbf{r}) $$

con amortiguamiento modal ξ (Santillán usa ξ=0.03, RT≈0.2 s a ~180 Hz).

### 2.2 La admitancia del frente de onda
Sobre el plano trasero, la admitancia específica local del campo incidente es

$$ Y_\text{inc}(f) = \frac{v_n}{p}, \qquad v_n = \frac{i}{\rho_0\,\omega}\,\frac{\partial p}{\partial n} $$

Para una onda plana **normal y viajera**, Y_inc → la admitancia característica
Y₀ = 1/(ρ₀c). En general Y_inc es **compleja y dependiente de f y del ángulo** de
incidencia (el campo no es una onda plana pura a toda frecuencia).

### 2.3 Condición de absorción (admitancia adaptada)
El array trasero se maneja para que la admitancia **total** en la pared trasera
iguale a Y₀. El coeficiente de reflexión de presión

$$ R = \frac{1 - \rho_0 c\,\beta}{1 + \rho_0 c\,\beta} \;\xrightarrow{\;\beta\to 1/(\rho_0 c)\;}\; 0 $$

se anula → sin reflexión → sin onda estacionaria en ese eje.

Nelson & Elliott, cap. 5, **lo derivan exacto para el análogo 1-D** (ducto con fuente
primaria q_p en x=0 y secundaria q_s en x=L, que es la geometría front↔rear). Dos
resultados a reusar directamente:

- **Terminación absorbente (anecoica), §5.15.** Para anular la onda que viaja
  aguas-arriba (la reflejada por la pared trasera rígida), la fuente trasera debe ser
  $$ q_s = -q_p\,e^{-jkL} \quad\text{(5.15.3)}, \qquad q_s(t) = -q_p\!\left(t - \tfrac{L}{c_0}\right) \quad\text{(5.15.4)} $$
  es decir, **retardo L/c + inversión**: exactamente el drive «naive» de CABS/DBA,
  derivado de primeros principios. «In the presence of a rigid boundary a simple plane
  monopole source can act to absorb incident radiation perfectly». Esto es presentar
  una admitancia adaptada en la pared trasera (control activo de las propiedades
  acústicas de superficie, Guicking & Karcher 1984; Bobber 1962, Beatty 1964 para
  terminaciones anecoicas de calibración).
- **Fuerza óptima de mínima potencia, §5.6.** Minimizando la potencia TOTAL del par
  (cuadrática en q_s), el óptimo es
  $$ q_{s0} = -q_p\cos(kL) \quad\text{(5.6.4)}, \qquad \frac{W_0}{W_{pp}} = \sin^2(kL) \quad\text{(5.6.6)} $$
  Este es el drive **LS-óptimo** (el que resuelve `dba.ls_drive` y Santillán con sus
  FIR); coincide con el anecoico sólo donde conviene energéticamente.

**Caveat clave (§5.14-5.16):** minimizar la energía potencial total del recinto NO es
lo mismo que la terminación anecoica. La minimización de energía (§5.16) **suprime las
resonancias originales pero INTRODUCE nuevas** donde antes el campo era anti-resonante.
El objetivo limpio para el norte del proyecto es **la no-reflexión (§5.15)**, no la
mínima energía: fija β_rear → Y₀ sin crear modos nuevos.

### 2.4 Traducción a los modos (lo nuevo)
La admitancia efectiva β_rear(f) que el drive sintetiza en la pared trasera entra al
**kernel de perturbación de frontera** (Morse & Ingard 9.4.14, Kuttruff §3):

$$ \Delta\delta_n = \frac{c}{2}\,\mathrm{Re}\{\beta_\text{rear}(f_n)\}\,S_\text{rear}\,\langle\phi_n^2\rangle_\text{pared}, \qquad \Delta\xi_n = \frac{\Delta\delta_n}{\omega_n}, \qquad \Delta f_n \propto \mathrm{Im}\{\beta_\text{rear}\} $$

Es la **misma forma** que ya usa el cono del sub como absorbedor interior
(`face_materials.cone_xi_shift_per_mode`) y las paredes
(`perturbation_xi_shift_*`). Generaliza el cono (admitancia interior puntual) a una
**frontera activa de pared**.

## 3. Qué ya existe (reusar, no reinventar)

| Pieza | Archivo / símbolo | Qué aporta |
|---|---|---|
| Drive LS-óptimo de Santillán | `dba.ls_drive`, `plane_wave_target`, `coupling_matrix`, `piston_wall_grid` | Síntesis del frente y el drive del trasero óptimo. |
| Drive naive (delay+invert) | `dba.array_naive_coupling_fn`, `travel_delay`, `alias_fmax` (f_max=c/d) | CABS de libro; cota de aliasing. |
| Base modal rectangular + acople distribuido | `source_coupling` (Cₙ=∫pₙvₙ dS) | Fuente de pared ↔ modo. |
| Admitancia de un transductor | `driver.cone_specific_admittance(f,fc,Qtc,Sd,Mms)` | Plantilla de β activa de un diafragma/array. |
| Admitancia interior → Δξₙ | `face_materials.cone_xi_shift_per_mode` | Plantilla de la proyección modal de la admitancia. |
| Admitancia de pared (compleja) → ξₙ, f_new | `face_materials.perturbation_xi_shift_per_mode` / `_extended`; `absorption_patch.compute_xi_shift_with_impedance` | **El kernel donde enchufar β_rear.** |
| β(f) compleja (Re amortigua, Im corre fₙ) | `impedance.py` | Soporta β_rear(f) dependiente de frecuencia. |
| Campo FEM para salas no rectangulares | `dba_evaluate.FEMModalField` | Evaluar sobre el campo real (sin garantía de onda plana). |
| EDC / waterfall | `modal_decay.py`, `DecayWaterfallDialog` (acepta ξ por modo `_xi_per_mode`) | El panel que pasa de C1 a C2. |
| Optimizador | `cabs_optimize.optimize_cabs`, `dba_dialog` (nortes flat/spatial/sbir/cabs/dba) | Donde sumar el norte «amortiguamiento del eje». |

## 4. Etapas (por aprobar una por una)

- **E1 — Campo incidente + admitancia del frente (headless).**
  **REFINAMIENTO (hallado al prototipar):** en una pared RÍGIDA la velocidad normal
  TOTAL es 0 (BC de Neumann), así que Y_inc NO se mide sobre el campo total en la
  pared (daría 0, no 1/ρc). La admitancia del frente de onda se define sobre la
  **componente INCIDENTE** (descomposición en ondas viajeras aguas-abajo/arriba, à la
  Nelson & Elliott §5.12-5.15). La onda plana progresiva tiene u/p = 1/(ρ₀c) = Y₀.
  - **E1a — oráculo analítico 1-D: HECHO.** `bench_front_rear_duct.py` 4/4 a precisión
    de máquina: admitancia del frente u/p=Y₀ (T1), cancelación downstream con
    q_s=−q_p e^{−jkL} (T2), W₀/Wpp=sin²kL con q_s0=−q_p cos kL (T3, Ec 5.6.6), y
    terminación absorbente R→0 vs R=1 en pared rígida (T4, Ec 5.15.3). Valida las
    ecuaciones OCR-eadas del cap. 5 de Nelson & Elliott.
  - **E1b — HECHO.** `bench_front_rear_room.py` 4/4 sobre el campo modal real
    (`source_coupling.RectModalBasis` + `dba.py`, sin tocar el núcleo). Descompone
    p(y) en dos ondas viajeras (k=ω/c) sobre una ventana central del eje y extrae la
    admitancia incidente y el coef. de reflexión R. Resultados:
    - **T1:** un array de PARED ENTERA excita SOLO modos axiales (0,m,0) → el campo
      es 1-D (dos ondas planas, residuo 0.089 limitado por truncamiento modal),
      R_off≈1 (pared rígida = estacionaria), admitancia incidente = Y₀.
    - **T2:** la velocidad normal TOTAL en la pared rígida → 0 (ratio 1.2e-3):
      confirma que Y_inc NO se mide sobre el campo total (hay que descomponer).
    - **T3 (payoff):** con el trasero manejado (naive CABS, `dba.dba_coupling_fn`)
      R cae de ~1 a 0.18, MONÓTONO con la frecuencia (absorbe el frente → onda
      viajera). A 20 Hz (debajo del axial fundamental) R_on≈0.8: la onda plana aún
      no está establecida (caveat de banda, coherente con T4).
    - **T4 (banda de validez):** con una fuente OFF-CENTER, el ajuste 1-D es exacto
      en la resonancia axial (residuo 5e-4) y se ROMPE en la transversal (0.30):
      arriba del primer modo transversal el campo deja de ser una onda plana.
    **Hallazgos para E1b→E3:** (a) sólo la pared entera da el caso 1-D limpio; los
    arrays de grilla simétricos NO excitan transversales impares (se cancelan).
    (b) R se mide robusto; el residuo del ajuste es truncamiento modal, no física
    (usar ξ pequeño aísla la reflexión geométrica del amortiguamiento de pared).
  - **E1c — HECHO.** Extrae de (A₊, A₋) la admitancia específica NORMALIZADA del
    borde trasero: β = (1−r)/(1+r), r = reflexión en la pared (rígido r=1→β=0;
    matcheado A₋=0→β=1=Y₀). `bench_front_rear_room.py` T5-T6 (6/6):
    - **T5:** β_rear rígido Re≈0.003 (no absorbe); manejado Re(β) crece 0.167→1.037
      (débil→matcheado, cruza 1 cerca del tope); auto-consistencia |(1−β)/(1+β)|=R
      exacta (2.8e-16).
    - **T6 (HALLAZGO que redirige E3):** |β_rear| es de ORDEN ~1 en toda la banda
      (0.29→1.10), **nunca perturbativo** (el mínimo 0.29 ya supera el techo ~0.15
      de validez de la perturbación de `bench_cone_damping`). Re(β) va de absorción
      débil/reactiva a baja f a matcheada (~1) arriba. **Conclusión: la perturbación
      de frontera de 1er orden (Capa 0, Morse&Ingard 9.4.14, asume β≪1) NO modela el
      borde trasero CABS en ningún punto** (confirma la nota de `dba.py`).
- **E2 — Drive del trasero que adapta β_rear → Y₀.** Reusar `dba.ls_drive` (óptimo) y
  el delay+invert L/c (naive). Medir R residual y la planitud/uniformidad espacial.
- **E3 — β_rear → Δξₙ/Δfₙ por el QEP exacto (opción (b) elegida) — HECHO.**
  `bench_front_rear_qep.py` 4/4. Resuelve el QEP `c²K + i c β C_bc ω − M ω² = 0` en la
  base modal (M=I, c²K=diag(ωₙ²), C_bc = Gram de superficie de los modos en la pared
  trasera; para los axiales de una pared uniforme C_bc es **rango-1**, C_bc=(2/Ly)ssᵀ,
  sⱼ=(−1)ʲ). Mismo método que el oráculo del cono (`bench_cone_damping`).
  - **T1:** para β≤0.15 el QEP reproduce la perturbación de 1er orden δ=c·Re(β)/Ly
    (error 0.7%): atadura al modelo ya validado.
  - **T2:** a β=1 (matcheada) el QEP da amortiguamiento DEPENDIENTE DE LA FRECUENCIA
    (δ_QEP/δ_pert 1.11→1.95 en los modos bajos) que la perturbación (constante) no ve;
    ξ₁=0.35. **Matiz honesto:** para la TASA de decaimiento la perturbación es un
    promedio decente aun a β=1; lo que pierde es la estructura en frecuencia y el ξ
    exacto (y el corrimiento por Im(β), no ensayado aquí).
  - **T3 (payoff C2):** el RT60 del 1er modo axial COLAPSA de 100.7 s (rígido) a
    0.091 s (matcheado), ×1107 más rápido: el movimiento de polos genuino.
  - **T4:** δ₁ crece monótono con Re(β) (0.7→75.9 Np/s).
  **Fork resuelto por el usuario = (b)** terminación de impedancia matcheada (feedback,
  rear ∝ p local, β_rear→1): los polos se mueven (C2, decaimiento genuino), calculado
  por el QEP. La opción (a) CABS feedforward (`dba.py`, no mueve polos, C1,
  redistribución de energía en `modal_decay.py`) queda como el modelo descriptivo ya
  existente. **PENDIENTE de E3 (opcional):** QEP sobre el FEM nodal real (no solo
  modal-analítico) para salas no rectangulares, reusando `build_KM` + la C de
  superficie; y β compleja (Im(β)→Δfₙ).
- **E4 — Interacción front↔rear como norte de optimización (REDEFINIDO por E3).**
  El norte original (maximizar Σ Δξₙ) **NO aplica a fuentes reales**: el drive
  feedforward (`dba.py`) NO mueve polos (E3). El norte correcto y alcanzable por
  fuentes reales es **minimizar la reflexión R de la pared trasera** (= absorber el
  frente de onda; R→0 es el techo matcheado del QEP de E3).
  - **E4a — HECHO.** `bench_front_rear_opt.py` 4/4. Define el coste = R promedio en la
    banda axial (R vía la descomposición viajera de E1b) para una config del trasero
    (retardo, polaridad, nivel). Resultados: (T1) rígido R̄=0.998 → CABS 0.483 (el
    norte discrimina); (T2) el óptimo del retardo cae en ≈L/c (tránsito); (T3) sin
    inversión R̄=2.72 vs 0.48 (polaridad crítica); (T4) optimizar (retardo,nivel) da
    R̄=0.398, casi igual al CABS canónico (el CABS es ~óptimo). El R̄ mínimo no es 0
    porque a baja f (< axial fundamental) la onda plana no está establecida (coherente
    con E1b/E1c).
  - **E4b — HECHO (wiring núcleo + GUI).** Norte nuevo `"front_rear"` = **R̄ ponderado
    por banda (peso ~f, solo en [axial1, primer transversal] donde vale la onda plana)
    convertido a rizado en dB `20·log10((1+R̄)/(1−R̄))` + planitud + varianza espacial**
    (la elección del usuario). `dba_evaluate`: `wants_reflection`,
    `_reflection_penalty_db`, `_axis_transverse_band`, `rear_reflection` (descomposición
    viajera de E1b sobre una línea del eje), rama en `composite_cost`, gate
    `want_reflection` en `_config_metrics`, `rear_reflection_real/ideal` en
    `evaluate_cabs`. `cabs_optimize`: `want_reflection` propagado en los 3 sitios
    (`suggest_layouts`, `_cost`, `_metrics`). `dba_dialog`: ítem de combo, label,
    tooltip, y lectura en `_show_eval` (badge «frente absorbido» / «reflexión trasera
    alta» + R̄ real vs ideal + rizado dB). Verificado headless: `evaluate_cabs`
    distingue (front-only R̄=0.91/coste 35.8 → CABS con trasero L/c+invertido
    R̄=0.36/coste 16.0, elige el eje front↔rear solo); `optimize_cabs` corre sin error;
    `_show_eval` muestra el readout (R_real 0.35 vs ideal LS 0.20). **FALTA test visual
    del usuario en el diálogo real.**
- **E5 — Panel de decaimiento riguroso (C2) — HECHO.** El panel «Decaimiento con subs»
  suma un 4º estado **«pared trasera matcheada (C2)»**: ξ_total = ξ_campo + Δξ_rear, con
  Δξ_rear de una pared trasera con admitancia ADAPTADA (β=Y₀) en el eje de los subs →
  los modos axiales decaen genuinamente más rápido (polos movidos), no redistribución.
  `AcousticPanel._rear_matched_delta_xi(sources)`: identifica la pared trasera (normal
  +eje de `dba_evaluate.best_axis`) y aplica `face_materials.perturbation_xi_shift_per_mode`
  con β_provider=1 (Y₀ real) en esa pared → Δξ por modo. `_open_decay_waterfall` agrega
  el estado (`edc_d`/`csd_d`); `DecayWaterfallDialog` dibuja la curva (verde punteada) +
  waterfall + RT, con nota honesta. Verificado: el 1er axial-y recibe δ=c/Ly (69 Np/s,
  RT60≈0.10 s), los transversales la mitad; el diálogo renderiza 4 estados.
  **MATIZ (honesto, en la UI):** es perturbación de 1er orden (Re(β)=1), **CONSERVADOR**:
  el QEP exacto (E3, `bench_front_rear_qep`) da hasta ~2× más amortiguamiento en los
  modos bajos, así que la pared matcheada real decaería AÚN más rápido. A diferencia del
  norte R̄ (E4), E5 NO necesita banda de onda plana (es admitancia de frontera) → anda en
  cualquier eje/recinto, incluido Control Ale.
  **PENDIENTE (opcional):** usar el QEP exacto proyectado a los modos (no la perturbación)
  para la curva C2; requiere la Gram de superficie off-diagonal de la pared (no expuesta
  hoy). El actual es el piso conservador, declarado.

## 5. Validación y banda de validez (el norte)

- **Banda estricta:** la foto onda-plana + β única vale **solo por debajo del primer
  modo no-axial** del eje. Arriba, el campo incidente es multimodal y β_rear se vuelve
  dependiente de ángulo y frecuencia → declarar **aproximación**, nunca exactitud.
- **Oráculos:** E1 contra onda plana analítica; E3 contra QEP exacto con BC de
  admitancia; comparación cruzada con `dba.compute_dba` (ya validado, cross-check
  Santillán fig. 6-7).
- **Geometría:** rectangular = caja (onda plana limpia). Para CAD/irregular, usar
  `FEMModalField` pero advertir que no hay onda plana garantizada.

## 6. Preguntas abiertas (resolver antes de codear E3-E4)

1. **β_rear es ACTIVA, no pasiva — RESPONDIDA (E1c):** la β_rear sintetizada es de
   orden ~1 en toda la banda (|β|∈[0.29,1.10]), NO perturbativa → la perturbación de
   1er orden no aplica (ver E3 redirigido al QEP). Queda el fork feedforward (no mueve
   polos, C1) vs feedback matcheada (mueve polos, C2), detallado en E3.
2. **Causalidad del drive LS:** Santillán usa un modeling delay FIR (no causal puro).
   ¿Se puede mapear a una β_rear(f) estacionaria, o hay una parte que el waterfall
   debe ventanear? (el auditor ya marca el ventaneo del IR del drive LS).
3. **Acople inter-modal:** la perturbación es diagonal (1er orden); para absorción
   fuerte del eje o modos casi-degenerados puede degradarse → validar con QEP completo.
4. **e^{-iωt} vs e^{+iωt}:** gotcha de signo ya conocido (impedance usa e^{-iωt}, el
   solver e^{+iωt} → conj(β)); mantener la convención al enchufar β_rear.

## 7. Referencias

- **Celestinos & Nielsen**, "Low Frequency Sound Field Control... using CABS", Forum
  Acusticum 2011 (`referencias/Low frequency sound field control...CABS...pdf`):
  onda plana frontal + cancelación de la reflexión trasera, notación (N_f.N_s.N_r).
- **Santillán**, "Spatially extended sound equalization in rectangular rooms", JASA
  110(4) 2001 (`referencias/Santillán...pdf`): Ec. 4 (campo modal de pared), drive LS
  + modeling delay, onda plana viajera, solo modos axiales.
- **Nelson & Elliott**, *Active Control of Sound*, 1992 (`referencias/Active Control
  of Sound...Nelson...pdf`; PDF escaneado, OCR hecho; **offset libro = PDF − 13**).
  **Cap. 5 «Interference in Plane Wave Sound Fields»** es el marco directo del análogo
  1-D front↔rear: §5.5 absorción por una fuente plana (Ec 5.5.11, p131), **§5.6 potencia
  mínima del par y fuerza óptima** (q_s0=−q_p cos kL, Ec 5.6.4; W0/Wpp=sin²kL, p132),
  §5.12-5.14 modelo de onda viajera en recinto 1-D, **§5.15 terminación absorbente**
  (q_s=−q_p e^{−jkL}, Ec 5.15.3; q_s(t)=−q_p(t−L/c), Ec 5.15.4; control de propiedades
  de superficie, Guicking, p157), §5.16 minimización de energía (introduce nuevas
  resonancias). Cap. 2-4 (fundamentos acústicos, DSP/FIR) de respaldo.
- **Morse & Ingard**, *Theoretical Acoustics* §9.4.14 (`referencias/Theoretical
  Acoustics...pdf`): BC de admitancia β → δ modal (base del kernel de perturbación).
- **Beranek & Mellow**, *Sound Fields and Transducers*, cap. 6 (`referencias/Sound
  Fields and Transducers...pdf`): impedancia de radiación de pistón/array (base de
  `cone_specific_admittance`).
- **Williams**, *Fourier Acoustics* (`referencias/Fourier Acoustics...pdf`):
  reconstrucción de p y vₙ en un plano (espectro angular / NAH) → ruta alternativa
  para Y_inc.
- **Kuttruff**, *Room Acoustics* §3 (`referencias/Kuttruff - Room Acoustics.pdf`):
  modos, constante de decaimiento, EDC.
- **Código a reusar:** `dba.py`, `source_coupling.py`, `driver.py`,
  `face_materials.py` (`cone_xi_shift_per_mode`, `perturbation_xi_shift_*`),
  `absorption_patch.compute_xi_shift_with_impedance`, `impedance.py`,
  `modal_decay.py`, `dba_evaluate.FEMModalField`, `cabs_optimize.py`.
