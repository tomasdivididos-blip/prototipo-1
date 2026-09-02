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
1. **Wiring de S1+S2+S5 al solver/GUI** (única tarea grande del modelo de fuente).
2. **CLF** (tarea ortogonal, punto 2): generalizar el lector a otras versiones.
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
