# Cobertura de criterios en el software — matriz exhaustiva

> Cada criterio de `criterios_room_geom_fuente.md` (A/B/C/D) y de `numerica_fem_validez.md`
> (E) contra **cómo se aplica (o no) en el código**. Auditado 2026-06-21 sobre el repo
> (no de memoria): `prediction.py`, `modal_metrics.py`, `location_opt.py`, `sbir.py`,
> `face_materials.py`, `acoustic_fem.py`, `material_library.py`.
>
> **Naturaleza de la app** (define qué es in/out of scope): predictor **modal de baja
> frecuencia** (FEM, banda ~20–200 Hz / ≤ Schroeder) + **optimizador de ubicación de
> fuentes** (T8), para recintos **shoebox-ish de reproducción**. NO tiene respuesta
> impulsiva, ray-tracing, ni acústica geométrica → todo lo temporal/early-reflection/
> mid-high es fuera de alcance por construcción.

**Leyenda:** ✅ implementado · 🟡 parcial / proxy (con la salvedad) · ❌ **gap in-scope**
(falta y aplicaría) · ⊘ fuera de alcance (con motivo).

---

## §A — Geometría

| # | Criterio | Cómo se aplica en el soft | Estado |
|---|---|---|---|
| A1 | Bolt area | Ratio "Bolt" en `RATIO_LIBRARY` + bins de spacing | ✅ |
| A2 | Louden | Ratio "Louden" en `RATIO_LIBRARY` | ✅ |
| A3 | Bonello | ✅ (2026-06-21) `bonello_monotonic`/`bonello_score` en `FemLiteResult` (densidad no-decreciente); cubo→False/40%, buenos→True/100% | ✅ |
| A4 | Gilford (modos aislados) | Aproximado por bins de 5 Hz "hueco" (`prediction.py:497`); no el umbral exacto >20 Hz | 🟡 |
| A5 | Cubo / ratios enteros | **Control negativo = cubo 1:1:1** (`_generate_negative_control`) | ✅ |
| A6 | Rindel FSI ψ(25) | ✅ (2026-06-21) `modal_fsi(freqs)` en `modal_metrics.py`; cubo ψ=3.71, Rindel ψ=1.43. Falta solo wiring al scorer | ✅ |
| A7 | Cox peor-caso fuente/receptor | `d_worst = √(L²+W²)/2` es un receptor de peor caso; la optimización |H| esquina↔esquina de Cox no | 🟡 |
| A8 | Meissner suavidad |H| | ≈ `FoM_flat` (suavidad de |H|), aunque no el ajuste polinómico de Meissner | 🟡 |
| A9 | Walker índice + región | La **región** (ratio) está en A33; el "mean-square quality index" como métrica no se computa | 🟡 |
| A10 | Librería de ratios | `RATIO_LIBRARY` (5 ratios) | ✅ |
| A11 | Volumen por uso | `v_per_person`, `h_default` por uso; `score_volume` | ✅ |
| A12 | Schroeder | `schroeder_frequency` (`modal_metrics`) | ✅ |
| A13 | MDCF crossover | `modal_overlap_crossover` | ✅ |
| A14 | Densidad modal de Maa | (MDCF usa densidad real) | ⊘ |
| A15 | Splay / no-shoebox | `parallel_walls`, `roof_shape` (taper/loft) + FEM no-shoebox | ✅ |
| A16 | Params ortogonales salas grandes | — | ⊘ salas grandes |
| A17 | Energía por tipo de modo | **A36** (xi per-cara) pesa por forma modal → captura el espíritu; etiquetas axial/tang/obl no se computan en FEM | 🟡 |
| A18 | `B_HP = 2.2/RT60` | `modal_metrics:207` | ✅ |
| A19 | Excitabilidad `φₙ(xₛ)` | `compute_forced_response` / `location_opt` | ✅ |
| A20 | VSA | = `FoM_flat` (σ del |H| promedio espacial) | ✅ |
| A21 | Coloración spacing >20 Hz | Bins de 5 Hz grumo/hueco (no el umbral exacto) | 🟡 |
| A22-A25 | Volumen/RT óptimos (salas grandes) | — | ⊘ salas grandes |
| A26 | Volumen mínimo (~42 m³) | `score_volume`/`score_bass` penalizan salas chicas; la cota dura no es explícita | 🟡 |
| A27 | Umbral ~300 Hz cavidad/rayos | Lo maneja Schroeder/MDCF/f_max | ✅(equiv) |
| A28 | Procedimiento modos axiales | La app computa **todos** los modos FEM (no solo axiales 565/L) | ✅(superset) |
| A29 | **Pressure zone `f_pz` / 4 zonas** | La app **no flaggea** la pressure zone (banda < modo más bajo); arranca en 20 Hz | ❌ menor |
| A30 | Ensanchamiento modal ±10 Hz | Vía xi/B_HP (los picos tienen ancho por damping) | ✅ |
| A31 | Flutter echo | Opción `parallel_walls="evitar"` (taper); el flutter como tal no se computa (es HF/temporal) | 🟡 |
| A33 | Ratio BBC/Rindel | `RATIO_LIBRARY` (agregado esta sesión) | ✅ |
| A34 | RT objetivo + tolerancias + doble pendiente | `score_rt60` + `rt60_target`; **las bandas EBU R22 y el chequeo de doble-pendiente NO** | 🟡 |
| A35 | Fórmula de Rayleigh | El solver FEM computa los modos (Rayleigh = shoebox; FEM generaliza) | ✅ |
| A36 | Decay modal per-cara | `compute_xi_per_mode_per_face` (agregado esta sesión) | ✅ |
| A37 | Frec. crítica = overlap 3 | `modal_overlap_crossover` (M≥3) | ✅ |

---

## §B — Fuentes

| # | Criterio | Cómo se aplica en el soft | Estado |
|---|---|---|---|
| B1 | Excitación modal `φₙ(xₛ)` | `location_opt` / `compute_forced_response` | ✅ |
| B2 | Fuente en esquina | Semilla "esquina" en `location_opt` | ✅ |
| B3 | SBIR notch `c/4d` | `sbir.py:257` | ✅ |
| B4 | Flush/soffit 2π | Semilla flush/mounted en `location_opt` + lift +6 dB en `sbir` | ✅ |
| B5 | Zonas de distancia a pared | `sbir` computa el notch por `d`; las zonas (bien/evitar/bien) son interpretación, no un aviso discreto | 🟡 |
| B6 | Welti MSV (multi-sub) | `location_opt` (semillas midwall/¼) + `FoM_espacial` | ✅ |
| B7 | Estrategias de subs (DBA/Geddes) | Semillas esquina/midwall/¼ sí; **DBA (arrays con delay) / Geddes (aleatorio) no explícitos** | 🟡 |
| B8 | Delay / fase entre fuentes | Barrido de delay/polaridad (`_delay_polarity_response`) | ✅ |
| B9 | Simetría estéreo | Semilla estéreo-simétrica | ✅ |
| B10 | ¼ de onda oyente-pared trasera | El oyente no se optimiza (solo la fuente) | ⊘/❌ |
| B11 | Altura fuente / oído | `z_ear=1.2` en la grilla; altura de fuente en la búsqueda | ✅ |
| B12 | Directividad de fuente | Omni en banda modal (deliberado; **B32/Meyer lo valida**) | ⊘ |
| B13 | Absorción en máx. de presión | **A36** captura DÓNDE ayuda la absorción + **B27** avisa; no hay optimizador de colocación | 🟡 |
| B14 | Simetría de patología L/R | Semilla simétrica; no hay chequeo explícito de simetría del campo | 🟡 |
| B15 | Distancias asimétricas (anti-pile-up) | `sbir` da notches por pared (pile-up visible); `location_opt` podría evitarlo, no se scorea explícito | 🟡 |
| B16 | Regla soffit `d ≤ baffle` | Flush mount en `location_opt` | ✅ |
| B17 | Absorber radiación trasera | — (detalle de montaje) | ⊘ |
| B18 | Absorbente por frecuencia | Librería con `α(f)` por material + **B27** | ✅ |
| B19 | **Oyente vs nulos modales** | El soft **no aconseja** la posición del oyente (evitar el centro) | ❌ |
| B20 | Trampas de graves en esquinas | **B27** avisa; no hay recomendador explícito de trampa de esquina | 🟡 |
| B21 | Tratamiento 1ª reflexión | — | ⊘ temporal |
| B22 | Reflexión lateral (espaciosidad) | — | ⊘ temporal |
| B23 | Carga de frontera +3/+6/+9 dB | Lift +6 dB en `sbir`; la excitación modal captura la carga de esquina | ✅ |
| B24 | Difusor pared trasera | — | ⊘ difusión HF |
| B25 | Flush = fase mínima | Flush en `location_opt`; la distinción fase-mín **no se diagnostica** (= C13) | 🟡 |
| B26 | Dipolo vs monopolo | La app usa fuentes omni/monopolo (sin modelo dipolar) | ⊘ |
| B27 | Advisory de absorbente | `lf_modal_absorption_hints` (agregado esta sesión) | ✅ |
| B28 | Difusión no controla modos | Implícito (no modela difusores para LF; B27 manda absorción) | ✅(equiv) |
| B29 | Triángulo estéreo 2–2.5 m | Semilla estéreo; el triángulo 2–2.5 m exacto no se impone como constraint | 🟡 |
| B30 | Monitor free-standing (reglas) | `location_opt` barre distancias; las reglas (≥200 mm esquina, etc.) no como constraint | 🟡 |
| B31 | Carga = fuente + imagen | Modelo de imágenes en `sbir.py` | ✅ |
| B32 | Directividad de instrumentos | Validación (omni < 500 Hz); no cambia código | ⊘(valida) |

---

## §C — Combinado

| # | Criterio | Cómo se aplica en el soft | Estado |
|---|---|---|---|
| C1 | Cox opt conjunta dim+pos | `location_opt` hace dim(candidatos)+fuente; no el método exacto de Cox | 🟡 |
| C2 | Harman multi-objetivo | **Es la arquitectura de T8** (objetivo ponderado) | ✅ |
| C3 | FoM_flat | `response_figures_of_merit.FoM_flat` | ✅ |
| C4 | FoM_espacial | `response_figures_of_merit.FoM_espacial` | ✅ |
| C5 | MDCF M≥3 | `modal_overlap_crossover` | ✅ |
| C6 | Trade-off del par (principio) | Arquitectura: geometría fija modos, ubicación optimiza | ✅ |
| C7 | Ponderación por uso | `default_location_weights` / scoring por uso | ✅ |
| C8 | Asimetría pico/nulo | ✅ (2026-06-21) `FoM_flat_asym` en `response_figures_of_merit` (picos pesan 3×); pico+6 > nulo−6 | ✅ |
| C9 | Umbral perceptual Fazenda | ✅ (2026-06-21) `fazenda_modal_threshold(f, stimulus)` — 2 curvas (artificial/peor caso + music/escucha real, Fig.4/5 2015). `_score_modal_q` elige la curva por **programa** (música→music, voz→artificial) vía `_fazenda_stimulus_for`. Q>30 queda de referencia | ✅ |
| C10 | Límite del control pasivo | Base conceptual del multi-sub (location_opt sobre absorción) | ✅(concepto) |
| C11 | No-shoebox → FEM | **La app ES FEM** | ✅ |
| C12 | Marco VSA/MSV/SDMFS | FoM_flat + FoM_espacial + uniformity bins ≈ los 3 | ✅ |
| C13 | **Fase mín/no-mín (corregibilidad EQ)** | `frd.minimum_phase` existe pero es para la **FRD de la fuente**, no para diagnosticar la **respuesta de sala** | ❌ |
| C14 | Multipunto | `default_receiver_grid` (grilla de receptores) | ✅ |
| C15 | Taxonomía de distorsión | Ataca SBIR/modal/L-R pero no como checklist explícito | 🟡 |
| C16 | ITDG | — | ⊘ temporal |
| C17 | LEDE | — | ⊘ temporal |
| C18 | RFZ | — | ⊘ temporal |
| C19 | Sala de modos amortiguados | Soportado vía materiales/A36; no como "modo" de diseño | 🟡 |
| C20 | Non-Environment | — | ⊘ tratamiento CR |
| C21 | Regla corregibilidad EQ | = C13 (mismo gap) | ❌ |
| C22 | Reproducción = neutral | Implícito (la app apunta a recintos de reproducción) | ✅(implícito) |
| C23 | Difusor vs absorbente | B27 manda absorción; la elección de difusor | ⊘ parcial |
| C24 | LF no-difuso → FEM | La app ES FEM (lo valida) | ✅ |
| C25 | No simetrizar 1ª reflexión | — | ⊘ temporal |
| C26 | Geometría de la consola | — | ⊘ temporal |

---

## §D — Perceptuales / ISO 3382

| # | Criterio | Cómo se aplica en el soft | Estado |
|---|---|---|---|
| D1 | Intimidad / ITDG | — | ⊘ temporal |
| D2 | Reverberación / EDT | RT60 sí (`score_rt60`); **EDT no** | 🟡 |
| D3 | Claridad C50/C80 | **No** (requieren respuesta impulsiva). Inteligibilidad de voz **sí**: `score_sti` (Bradley), `score_alcons` (Peutz) | 🟡 |
| D4 | Riqueza del tono | — | ⊘ |
| D5 | Calidez / Bass Ratio | ✅ (2026-06-21) `bass_ratio(rt60_bands)` en `face_materials.py` + display panel (fría/cálida/boomy). `score_bass` (densidad) queda separado | ✅ |
| D6-D7 | Brillo / Sonoridad G | — | ⊘ |
| D8-D12 | Balance/Blend/Ensemble/Ataque/Textura | — | ⊘ salas grandes/temporal |
| D13 | Ruido de fondo NC/RC | — | ⊘ (HVAC/aislamiento) |
| D14 | Acoustic glare | — | ⊘ |
| D15 | Uniformidad espacial | = `FoM_espacial` | ✅ |
| D16 | IACC / BQI | — | ⊘ binaural |
| D17 | Seat-dip | — | ⊘ salas grandes |

---

## §E — FEM / numérica

| # | Criterio | Cómo se aplica en el soft | Estado |
|---|---|---|---|
| E1 | Orden O(h²) | P1 hat functions (decisión D1) | ✅ |
| E2 | Regla `ppw` | `ppw=6`, `f_max_malla = c/(ppw·h)` | ✅ |
| E3 | Costo ∝ k | Razón de trabajar ≤ Schroeder | ✅ |
| E4 | Pollution `C₂k³h²` | Razón física del **clip B6** | ✅ |
| E5 | Matriz C de impedancia | **NO se ensambla** por diseño (D5b, usa ξₙ modal; evidenciado en `bench_modal_vs_impedance.py`) | ⊘ por diseño |
| E6 | Error geométrico de discretización | Es la **malla escalonada** (voxelización Freudenthal), decisión asumida | ✅(asumido) |
| E7 | PG multiescala pollution-free | Alternativa **NO usada** (la app clipea, no corrige) | ⊘ por diseño |

---

## Resumen: estado de los gaps in-scope

**✅ Cerrados (2026-06-21)** — Fase 1 + Fase 2 del `plan_gaps_criterios.md`:
1. **A6 · FSI ψ(25)** — `modal_fsi` (`modal_metrics.py`). Falta solo wiring opcional al scorer.
2. **A3 · Bonello completo** — `bonello_monotonic`/`bonello_score` (`prediction.py`).
3. **C8 · asimetría pico/nulo** — `FoM_flat_asym` (`modal_metrics.py`).
4. **D5 · Bass Ratio real** — `bass_ratio` (`face_materials.py`) + display panel.

**✅ C9 cerrado (2026-06-21)** — desbloqueado al cargar el paper de Fazenda; `fazenda_modal_threshold`
implementado y wired a `_score_modal_q` (⚠️ baja mucho ese sub-score — decisión de wiring pendiente).

**⏳ Pendiente** (único gap in-scope sin cerrar):
- **C13/C21 · corrigibilidad EQ (fase mín/no-mín)** — diagnóstico de qué exige acústica vs EQ. *Alto esfuerzo (análisis de fase de la respuesta de sala; reusar `frd.minimum_phase`).*

Menores/discutibles: **A29** (flag de pressure zone), **A34** (tolerancias EBU + doble-pendiente),
**B19** (aviso de posición del oyente vs nulos), **B7/B29/B30** (constraints de layout más explícitos).

**Fuera de alcance por construcción** (no son gaps): todo lo temporal/early-reflection
(C16-C18, C25-C26, B21-B22, B24, D1), mid-high/IR (D3 C50/C80, D4-D14, D16), salas grandes
(A16, A22-A25, D17), y E5/E7 (decisiones FEM deliberadas).
