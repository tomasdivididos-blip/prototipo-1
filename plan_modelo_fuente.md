# Plan — Modelo de fuente exacto (subs enfrentados / DBA-CABS)

> **Motivación:** el criterio de subs enfrentados (CABS/DBA) "no simula bien"
> (observación del profesor). Auditado el modelo de fuente actual, la causa NO
> es la directividad (bajo Schroeder `ka ≪ 1` → el sub es esencialmente omni),
> sino que la fuente es un **monopolo puntual** acoplado como valor puntual del
> modo `pₙ(xₛ)`. El DBA necesita subir un escalón: fuente **distribuida** de
> velocidad sobre la pared, acoplada por integral de superficie.
>
> **Fecha:** 2026-09-02 (plan). **Rama:** dist-exe. **Memoria:** ver
> `[[source-model-dba]]`, relacionado `[[clf-loader]]`, `[[source-filters]]`,
> `[[z-impedance-modeling]]`, `[[criterios-research]]`.
>
> **Norte (no negociable):** exactitud física bajo Schroeder. Cada fase se
> valida contra oráculo analítico o contra la implementación de referencia
> (Santillán 2001), y reduce EXACTO al comportamiento histórico con las
> features apagadas.

---

## 0. La escalera de ecuaciones (dónde estamos y adónde subimos)

Kuttruff, *Room Acoustics* (§3.6), da la jerarquía. El solver de hoy es un caso
particular.

**Hoy — Kuttruff Ec. 3.10 (fuente puntual):**

$$p(\mathbf{r}) = i\omega\rho_0 Q_0 \sum_n \frac{p_n(\mathbf{r})\,p_n(\mathbf{r}_0)}{K_n\,(k_n^2 - k^2)}$$

Es idéntica a `fem_modal.frequency_response` (línea 247) y a
`acoustic_fem.frequency_response`. El acoplamiento de la fuente es el **valor
puntual** `pₙ(r₀)`.

**Objetivo — Kuttruff Ec. 3.6-3.7 (fuente distribuida):**

$$\nabla^2 p + k^2 p = -i\omega\rho_0\, q(\mathbf{r}), \qquad
q(\mathbf{r}) = \sum_n C_n\, p_n(\mathbf{r}), \quad
C_n = \frac{1}{K_n}\int_V p_n(\mathbf{r})\,q(\mathbf{r})\,dV$$

Para un array montado en pared, `q` es una velocidad de superficie y colapsa a:

$$C_n = \frac{1}{K_n}\int_S p_n(\mathbf{r})\,v_n(\mathbf{r})\,dS$$

**Clave física:** cuando `vₙ` es uniforme sobre toda la pared `y=0`, esta
integral es no nula **solo para los modos axiales `(0,m,0)`**. Esa es, en una
línea, la razón física de que subs enfrentados funcionen, y lo que el
acoplamiento puntual de hoy no puede expresar. El fix es subir de Ec. 3.10 a
Ec. 3.7.

---

## 1. Oráculo de validación (qué mide "bien simulado")

Fuente: Santillán, JASA 110(4), 1989-1997 (2001) — implementación de referencia
(parlantes = pistones cuadrados de 0.1 m sobre la pared, modelo modal con
ξ=0.03, filtros por mínimos cuadrados multicanal, marco Nelson/Elliott) — y
Nielsen & Celestinos (CABS, Forum Acusticum 2011 + JAES 56, 915-931, 2008).

| Test | Métrica | DBA on debe dar | Fuente |
|---|---|---|---|
| **1. Colapso espacial** | desv. estándar de SPL / error LS `E(f)` sobre grilla | de >20 dB a casi plano; `E(f)<0.3` define f_max | Santillán Fig 7; CABS |
| **2. Selectividad axial** | energía en modos `(n,0,0)` vs tangenciales/oblicuos | solo axiales excitados | Santillán §III; Kuttruff `Cₙ` |
| **3. Colapso del decay** | duración de la respuesta impulsiva (IFFT de H(f) + Schroeder T30) | → "delta retardada" | Santillán §IV; CABS/JAES |
| **Límite** | `f_max = c/d` (`d` = espaciado entre subs) | aliasing espacial fija el techo | Santillán Ec. 11 |

El Test 1 ya lo mide el FoM de varianza espacial existente (MSV/VSA,
`[[criterios-research]]`). Faltan instrumentar 2 y 3.

---

## 2. Fases del build (orden decidido: S2 → S1 → S5)

Cada fase: física · cambio en código · oráculo · referencia. Riesgo creciente;
cada paso validado antes del siguiente.

### Fase S2 — Driver físico: Q(f) desde Thiele-Small

**Física.** El caudal volumétrico del driver derivado de la física. Un woofer en
caja sellada es un sistema de 2º orden; su velocidad volumétrica es

$$U(s) \propto \frac{s}{s^2 + (\omega_c/Q_{tc})\,s + \omega_c^2}, \qquad s=i\omega$$

(convención `e^{+iωt}`, igual que `filters.py`). La presión radiada de monopolo
`p = iωρ₀U ∝ s·U ∝ s²/(denom)` es el pasa-altos de 2º orden clásico de caja
sellada (plano en banda, −12 dB/oct bajo `fc`). Parámetros: `fc` (resonancia en
caja), `Q_tc` (Q total en caja), derivables de TS crudos por
`fc = fs·√(1+Vas/Vb)`, `Q_tc = Q_ts·√(1+Vas/Vb)`.

**Código.** Módulo nuevo `driver.py`: `DriverModel` (params TS) →
`.to_response(freq_pts, f_ref, anchor) -> sources.SourceResponse` (la `g(f)` que
ya existe). Se COMPONE en `OmniSource.effective_Q_spectrum`, igual que el filtro
y el delay. Sin driver → comportamiento histórico exacto. NO toca el solver.

**Oráculo** (`bench_driver.py`): (a) `|p(fc)|/|p(∞)| = Q_tc`; (b) pendiente
−12 dB/oct bajo `fc`, plano arriba; (c) fase +90° en `fc`; (d) impedancia de
radiación del pistón bafleado `Z/(ρ₀cS) = R₁(2ka)+iX₁(2ka)` coincide con Kinsler
Ch7 (límites `ka→0`: `R₁→(ka)²/2`; `ka→∞`: `R₁→1`); (e) composición en
`effective_Q_spectrum` reproduce la curva; flat → constante.

**Referencia.** Rivet, Karkar & Lissek 2018 (ecuaciones del parlante de caja
cerrada: Mms, Cms, Rms, Bl, Sd); Beranek & Mellow Ch6-7; Kinsler Ch7; MIT 13.811
Lecture 5 (pistón).

**Por qué primero:** autocontenida, oráculo analítico limpio, mejora fidelidad
ya, y es prerrequisito de S5 (el sink necesita el modelo de driver).

### Fase S1 — Fuente distribuida: el núcleo (Ec. 3.7)

**Física.** Reemplazar `pₙ(xₛ)·Q` por `Cₙ = (1/Kₙ)∫_S pₙ vₙ dS`. La FRF:

$$H(f;x_r) = i\omega\rho_0 c^2 \sum_n \frac{p_n(x_r)\,C_n}{k_n^2 - k^2}$$

**Decisión tomada — base analítica rectangular (Opción A).** Se usan los modos
exactos del paralelepípedo (`fem_modal.analytic_modes` / `rectangular_modes`),
donde `∫cos(mπy/Ly)dS` es analítica → cero error geométrico. CABS/DBA/Santillán
están definidos para cuartos rectangulares, así que esto cubre el 100% del uso
real. La base FEM sobre malla escalonada (Opción B) queda DIFERIDA (mismo
problema de la integral de superficie que difirió el gap A36 en
`[[criterios-research]]`); solo haría falta para subs enfrentados en sala
irregular (caso raro).

**Código.** Una fuente montada a pared gana modo "pistón": su huella
(`baffle_size`, `mounted`, hoy solo visuales) pasa a ser física. `Cₙ` por
integral analítica sobre la huella. El path puntual queda intacto.

**Oráculo.** (a) velocidad uniforme sobre pared entera → `Cₙ≈0` salvo axiales
(el mecanismo del DBA, chequeo numérico); (b) al achicar el pistón a un punto
`Cₙ→Q·pₙ(xₛ)` (reduce a hoy); (c) un pistón en pared coincide con el resultado
analítico de ducto 1-D para los axiales.

**Referencia.** Kuttruff Ec. 3.7; Santillán (pistones de pared); Nelson &
Elliott, *Active Control of Sound* Ch10; Scheuren (intro a control activo).

### Fase S5 — Sink / terminación anecoica

**Física.** El array trasero absorbe la onda plana. Se modelan las DOS formas y
se comparan:
- **(a) Sink manejado (CABS real):** traseras = más fuentes distribuidas (S1)
  con drive = delay + inversión resuelto por mínimos cuadrados (Santillán).
- **(b) Sink por impedancia (límite ideal):** pared trasera como impedancia
  matcheada `Z=ρ₀c` (o absorbedor electroacústico de Rivet). Entra como `β` de
  contorno → lo hace la Capa 0 (`[[z-impedance-modeling]]`).

**Oráculo.** (1) colapso del decay (IR → delta retardada, Schroeder T30);
(2) colapso de varianza espacial (MSV/VSA); (3) sink manejado con drive óptimo ≈
sink por impedancia matcheada.

**Referencia.** Santillán (filtros LS); Rivet (impedancia del absorbedor);
Kuttruff §6.8 (anecoico); CABS.

---

## 3. Transversales

- **S3 (aliasing espacial, `f_max=c/d`):** no es fase separada; sale de S1
  (varios pistones espaciados) y se verifica contra Santillán.
- **Compatibilidad hacia atrás** en toda fase (reduce exacto a hoy con features
  off), estándar del proyecto.
- **CLF (tarea ortogonal, punto 2):** generalizar el lector a otras
  versiones/exportadores; la directividad podría alimentar S3 por encima de
  Schroeder, pero para el DBA no hace falta. Se trata aparte.

---

## 4. Corpus (referencias/)

Ya en `referencias/`: Kuttruff *Room Acoustics* (§3.1-3.8, §6.2, §6.8);
Morse & Ingard *Theoretical Acoustics* (Ch9); Beranek & Mellow *Sound Fields and
Transducers*; Santillán 2001; Nelson & Elliott *Active Control of Sound* (1992);
Williams *Fourier Acoustics* (1999); Kinsler *Fundamentals of Acoustics*;
Welti & Devantier 2006; Rivet et al. 2018 (absorbedor electroacústico);
Scheuren (control activo, intro); Sakuma et al. 2000 (membranas, alternativa
pasiva + misma FoM); MIT 13.811 Lectures 2-6 (radiación, pistón bafleado);
un paper CABS (Forum Acusticum 2011); `10 - Acoplamiento Acústico.pdf` (cátedra).

Falta (opcional): CABS JAES 2008 completo (delays/decay en detalle).

---

## 5. Estado

- [x] **S4** — validación fijada (oráculo cuantificado, mecanismo Ec. 3.7,
  implementación de referencia Santillán). 2026-09-02.
- [x] **S2** — driver físico. `driver.py` (Thiele-Small caja sellada,
  impedancia de radiación del pistón). `bench_driver.py` **20/20**. 2026-09-02.
  FALTA: wiring a UI.
- [x] **S1** — fuente distribuida, base rectangular analítica exacta.
  `source_coupling.py` (`RectModalBasis`, `WallPiston`, Cₙ=∫pₙvₙdS).
  `bench_source_coupling.py` **8/8** (selectividad axial, reducción a punto,
  reciprocidad, prefactor, campo 1-D). 2026-09-02.
- [x] **S5** — sink / DBA-CABS (modelo a, manejado). `dba.py` (drive
  v_r=-v₀·e^{-iωLy/c}, cancelación polo-cero exacta a 1e-15).
  `bench_sink.py` **5/5**. Números (sala 7.8×4.1×2.8, off=frente solo):
  planitud espectral 7.4→3.2 dB, varianza espacial 6.3→2.3 dB, decay
  152→62 ms. 2026-09-02. Modelo (b) impedancia matcheada NO perturbativo
  (documentado, no implementado).
- [x] **S5 refinado — drive LS-óptimo (Santillán) + CROSS-CHECK.** `dba.py`:
  `ls_drive` (mínimos cuadrados multicanal en dominio de f: minimiza ‖Zq−d‖,
  d=onda plana viajera objetivo sobre sensores de la zona), `piston_wall_grid`,
  `coupling_matrix`, `ls_error_curve`. `bench_dba_crosscheck.py` **6/6**.
  Cross-check contra Santillán (sala 2.7×5.0×2.2, c=346.4, ξ=0.03, grillas 4×4
  front+rear, pistones 0.1 m): E_LS < 0.3 en la banda de diseño (mediana 0.16,
  con bumps en 110/165/220 Hz IGUAL que el paper); **ley f_max=c/d validada**
  (corr>0.95 variando N); cruce de E=0.3 en 369 Hz (config exacta 4×4: 352 Hz)
  vs ~300 Hz de Santillán (dentro del 17-23%, from-scratch). Refinamiento:
  LS mejora 47% sobre el retardo naive (E 0.332→0.178, 2 fuentes de pared).
  2026-09-02.

**Núcleo físico COMPLETO + validado + cross-checkeado (headless), 41 oráculos.**
Cross-check profundizado: `bench_dba_crosscheck.py` 8/8 (agrega T5/T6 = Fig 6 de
Santillán: FRF se aplana en las 4 posiciones, IR colapsa a delta retardada) +
`crosscheck_santillan_figs.py` (reproduce Fig 6 y Fig 7 como PNG).

Cola de tareas (en orden):
1. **Wiring de S1+S2+S5 al solver/GUI — HECHO (2026-09-02).**
   - **S2 (driver):** grupo "Driver físico (Thiele-Small)" en `SourceEditDialog`
     (fc/Qtc o fs/Qts/Vas/Vb → aplica DriverModel como curva Q(f), se compone en
     `effective_Q_spectrum` sin tocar el solver). `smoke_test_driver_ui.py` 8/8.
   - **S1+S5 (DBA):** herramienta autónoma `dba_dialog.DBADialog` (botón "Subs
     enfrentados (DBA/CABS)…" en la zona FRF del panel). Usa `dba.compute_dba`
     (motor analítico rectangular headless): sala AABB + arrays front/rear, drive
     LS o naive → FRF antes/después + planitud/varianza/decay. `smoke_test_dba_
     dialog.py` 7/7. **Decisión:** NO se integran fuentes distribuidas al pipeline
     FEM (reabriría la integral sobre malla escalonada, gap A36); la herramienta
     es analítica-rectangular (exacta para el caso DBA real).
2. **CLF** (punto 2): generalizar el lector — HECHO (anclaje estructural).
3. **Material → modelo de impedancia por defecto (pedido del usuario, POST-wiring).**
   Hoy, cuando se elige solo un material (α, sin construcción), la perturbación
   extendida SÍ computa ξ: convierte α→β real vía `face_materials.
   beta_from_alpha_random` (invierte Paris, reacción local + Z REAL). Pero ese
   β es REAL → solo da amortiguamiento (ξ), NO el corrimiento Δfₙ (que necesita
   Im(β)). El propio docstring lo marca como "el supuesto más débil de la
   cadena". Propuesta: que cada material cargue un modelo físico de Z(f) por
   defecto (poroso Miki/DB/JCA ajustado a su α y espesor, o Z medida), de modo
   que elegir un material dé un Z(f) COMPLEJO → ξ Y Δfₙ, sin asignar construcción
   a mano. Upgradea el eslabón débil. Ver [[z-impedance-modeling]],
   [[material-form-thirds]].
4. **Evaluar config real contra CABS — HECHO (7 Sep 2026, v2.34).** Flujo inverso
   al sintetizador: `dba_evaluate.evaluate_cabs` toma las fuentes reales del usuario
   (tipo/pos/delay/pol/curva), clasifica front/rear/other, y mide el colapso sobre
   la **respuesta TOTAL = SBIR + modos** (crossfade en f_S), comparando contra el
   ideal LS medido por el MISMO pipeline. Checklist falsable + auto-deteccion de eje
   (por coherencia de drive). Etiqueta `OmniSource.source_type` (Woofer/Sub/FR/Horn,
   inerte para la fisica). Modo "Evaluar mis fuentes" en `DBADialog`. `.room` aditivo
   (sin bump, default "generic"). `bench_dba_evaluate.py` 13/13. Decay ventaneado
   (el drive LS es no causal -> cola acausal envuelta en el IFFT; se ventanea a
   ~6*RT60 antes del T15). Ver [[source-model-dba]].

5. **Modelo de fuente fisico EXACTO (dipolo/bafle/imagenes) - DISENO, NO implementado.**
   Motivacion: al medir, la fuente sera un transductor en un bafle sobre una mesa; el
   monopolo puntual no lo simula fiel. Decisiones a tomar antes de codear:
   - **Baffle step SI es relevante** (correccion del usuario, 7 Sep): la banda modal
     del usuario llega a ~400 Hz, dentro de la subida de +6 dB del baffle step
     (f ~ c/(2*ancho)). NO queda arriba de Schroeder como se asumio en §1.1.
   - **PROBLEMA CENTRAL: doble conteo.** Un FRD/CLF ya trae el SISTEMA COMPLETO
     (bafle + transductor). Aplicar baffle-step/dipolo encima lo cuenta dos veces. El
     modelo debe saber que trae ya cada fuente: descriptor tipo
     `radiation_baked: none|driver|driver+baffle|full_system` (FRD/CLF -> full_system,
     no aplicar bafle extra; TS crudo -> driver, falta bafle -> aplicar).
   - **Radiador (segun el setup de medicion real, aun no fijado):** caja+mesa =
     monopolo + imagenes de frontera (mesa/piso), reusando `sbir.py`; bafle abierto =
     dipolo real (grad phi_n, analitico en base rectangular; grad N en FEM P1); piston
     bafleado 2pi + baffle step (`driver.piston_radiation_impedance` ya lo tiene).
   - **TS de primera clase:** hoy `DriverModel` hornea la curva y pierde los params
     crudos. Persistir fs/Qts/Vas/Vb/Sd editables, que alimenten Q(f) Y la radiacion.
   Ver [[source-model-dba]], [[clf-loader]].

   **FASE A HECHA (7 Sep 2026, v2.36).** Shaping de Q(f) + guard + TS de primera
   clase, SIN tocar el solver. `OmniSource`: campos `radiator_kind` (box/open_baffle),
   `radiation_baked` (none/driver/full_system) y `ts_fs/qts/vas/vb/sd` (aditivos,
   `.room` sin bump). `driver.baffle_step_gain/baffle_step_response`: low-shelf de
   -6 dB de MINIMA FASE, corte f_b=c/(pi*ancho), H(s)=(g_lo*w_b+s)/(w_b+s). Guard en
   `effective_Q_spectrum`: baffle step SOLO si radiation_baked=="driver" (con
   full_system NO, evita doble conteo; con none tampoco = monopolo historico). UI:
   grupo "Modelo de radiacion" en SourceEditDialog + TS releibles; auto-set del guard
   al cargar FRD/CLF (full_system) y aplicar driver (driver). `bench_source_model.py`
   12/12 (shelf, guard anti-doble-conteo, regresion con defaults bit a bit, round-trip
   TS). **FALTA FASE B:** acoplamiento DIPOLO (bafle abierto) = C_n ~ d.grad phi_n;
   rectangular analitico + `FieldEvaluator.evaluate_grad_one` en FEM (P1 grad por tet).

   **FASE B HECHA (7 Sep 2026, v2.37).** DECISION que bajo el riesgo: el dipolo se
   modela como DOS MONOPOLOS OPUESTOS en x ± (ell/2)*d (ell=ancho del bafle,
   d=orientacion/pitch) -> C_n = phi_n(x+)-phi_n(x-) (derivada direccional, figura-8)
   REUSA el point-coupling existente, NO hizo falta evaluador de gradiente en el FEM.
   `OmniSource.coupling_points()` + `sources.dipole_direction()`. Cableado: FEM
   `acoustic_fem._source_modal_coupling` (frequency_response + modal_pressure_field);
   rectangular `dba_evaluate._modal_coupling`. Shaping por tipo: caja ->
   `baffle_step_gain`, bafle abierto -> `open_baffle_gain` (pasa-altos 1er orden
   min-fase en f_D=c/(2*ancho)). SIN UI nueva (combo Radiador de Fase A +
   orientacion/pitch ya existen). `bench_dipole.py` 10/10; regresion FEM verde
   (`bench_modal_vs_impedance`, `bench_modal_metrics`: monopolos identicos).
   ITEM 5 COMPLETO (Fase A + B).

   **CAVEAT documentado (7 Sep 2026) — baffle step en el camino MODAL.** El baffle
   step se aplica en `effective_Q_spectrum`, que alimenta TANTO el acoplamiento
   modal como el SBIR. Estrictamente el baffle step es un efecto de DIRECTIVIDAD en
   eje (transicion 4pi->2pi, potencia casi constante); el acoplamiento modal depende
   de la VELOCIDAD DE VOLUMEN, no de la directividad. Aplicarlo al Q modal es un
   modelo de 1er orden DEFENDIBLE (hace que una fuente por Thiele-Small se comporte
   como una medicion FRD real, que tambien trae el baffle step), pero NO es exacto.
   Verificado que NO invierte la fisica gruesa: la caja da MAS grave que el bafle
   abierto en todas las posiciones (FRF box vs open_baffle: +9 a +40 dB en el grave).
   El reporte del usuario "caja con menos grave" fue artefacto de configuracion
   (baffle step del box) + vista normalizada, no bug. RIGOR MAXIMO futuro (opcional):
   mover el baffle step SOLO al campo directo/SBIR, fuera del Q que inyecta a modos.

6. **Discriminacion / optimizacion parcial - MINI-SPEC (diseno cerrado, 7 Sep 2026).**
   Objetivo: fijar unas fuentes y liberar otras para que el soft optimice SUS
   variables (posicion/delay/corte/filtro) segun el criterio CABS. Pedido del usuario.

   **Descomposicion (decidida):** QUIEN toca el optimizador es una propiedad POR
   FUENTE; QUE variables entran es una eleccion POR CORRIDA. Asi "reacomoda estas dos
   pero esta no, en posicion y delay" = 2 fuentes libres x conjunto {pos, delay}, sin
   necesitar una matriz fuente x variable.

   **Mecanismo elegido = OPCION C (granular por parametro)** (elegido por el usuario
   sobre A=pin por fuente y B=seleccion por corrida). Motivo: captura el caso real
   "posicion trabada por un mueble pero delay/EQ ajustables", que A (todo-o-nada por
   fuente) no da.

   **Modelo de datos:** `OmniSource.free_vars: frozenset[str]`, subset de
   {"pos","delay","fc","filter"}. Vacio = fuente FIJA (default -> comportamiento
   historico, no se optimiza nada). Persistir en `.room` ADITIVO (sin bump, como
   `source_type`). Cotas por variable: pos dentro de la sala + sin choque de muebles +
   respeta pegada-a-pared/mounted; delay 0..~L/c; fc en el rango del filtro; filter =
   familia/orden DISCRETOS del catalogo de `filters.py`.

   **UI:** grupo por fuente "Optimizar: [ ] posicion [ ] delay [ ] corte [ ] filtro"
   (en `SourceEditDialog` o en el dialogo de optimizacion). Nada tildado = fija (el
   "esta no" del usuario).

   **Optimizador:**
   - Funcion objetivo = `dba_evaluate.evaluate_cabs` (YA EXISTE, item 4): fuentes
     fijas como termino constante de la respuesta total; las libres arman el vector de
     DOF. Minimiza planitud/varianza (o maximiza el colapso CABS).
   - Variables MIXTAS (continuas pos/delay/fc + DISCRETA familia de filtro). Camino
     recomendado: ANIDADO -> bucle externo sobre las pocas combinaciones discretas de
     filtro liberadas, interno continuo con `scipy.optimize.differential_evolution`
     (acotado; respeta D0, es scipy puro). Alternativa: DE mixto en un solo vector.
   - Arrancar con {pos, delay} continuas (lo que mas mueve la aguja bajo Schroeder);
     agregar fc/filtro despues.

   **Precedente:** MSO (Multi-Sub Optimizer): por sub se marcan los parametros
   ajustables (gain/delay/PEQ), el resto fijo, y un optimizador global recorre solo
   los liberados. Welti & Devantier (JAES 54, 2006) optimizan nivel/retardo con
   posiciones fijas o variables.

   **Prerequisitos ya puestos (item 4):** `source_type` (que fuentes son subs) y el
   evaluador CABS (la funcion objetivo).

   **PRIMER CUT HECHO (7 Sep 2026, v2.35).** `cabs_optimize.py`: `optimize_cabs`
   con `differential_evolution` sobre las variables CONTINUAS (pos/delay/fc);
   `OmniSource.free_vars` (frozenset, `.room` aditivo); UI = fila "Optimizar:
   [pos][delay][corte][filtro]" en `SourceEditDialog` + boton "Optimizar fuentes
   libres" en el modo evaluar de `DBADialog` (con aplicar-a-la-sala via
   `apply_optimized`). `bench_cabs_optimize.py` 10/10. Restriccion fisica: un sub
   de pared solo libera los ejes TRANSVERSALES (no se despega de la pared); objetivo
   = flat+spatial con grilla/n_freq gruesos (rapido) + basis reusada. **FALTA:** la
   familia de filtro DISCRETA (bucle anidado), y refinamientos (respetar choque de
   muebles en pos, pesos flat vs spatial configurables).
   **Polaridad optimizable (7 Sep 2026):** "polarity" agregada a FREE_VARS como
   variable BINARIA (una inversion = fase pi constante en f, que un delay no
   reproduce). En DE via `integrality` (fallback a umbral 0.5 si scipy es viejo).
   `bench_cabs_optimize` T5: el optimizador arranca en la peor polaridad y elige la
   mejor. OJO fisico: para subs PUNTUALES la inversion NO siempre mejora flat+spatial
   (la cancelacion polo-cero del DBA es de pistones de pared, no de monopolos); el
   optimizador elige el optimo binario sin asumir el signo.
   **Pre-chequeo de factibilidad (7 Sep 2026):** `dba_evaluate.cabs_feasibility`
   (barato, estructural, sin computar respuesta) avisa ANTES de optimizar si la
   config no puede ser CABS (sin subs marcados / no hay arrays en las dos paredes /
   sub fuera de pared). Son condiciones INVARIANTES bajo la optimizacion. El aviso da
   a elegir "optimizar igual (uniformidad general) vs cancelar"; tambien se muestra
   al entrar al modo Evaluar. Motivado por un caso del usuario (2 fuentes genericas:
   optimizaba sin avisar que la config nunca iba a dar CABS).
