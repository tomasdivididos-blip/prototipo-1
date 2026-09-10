# Contexto vivo para el auditor-fisico

> Este archivo lo actualiza el asistente principal en CADA recap, para que el
> `auditor-fisico` entre con el estado al día. **Advertencia de método (no negociable):**
> TODO lo de acá son AFIRMACIONES DEL AUTOR (co-autor sesgado), no evidencia. Verificá
> cada cosa contra la fuente física, un oráculo, o una cuenta propia. Que este archivo
> diga "resuelto/PASA" no prueba nada; es un puntero a qué mirar.

**Última actualización:** 2026-09-10.

## Estado del proyecto

Simulador modal acústico < Schroeder (numpy/scipy). Fase actual: **validación empírica**
contra RIRs medidas (para JAAS) y diseño de la campaña de medición propia.

## Pipeline de validación (auditá con el mismo rigor que el núcleo)

Un bug acá sesga TODA la comparación contra mediciones (corazón de JAAS):

- `rir.py` — lado medido: `rir_to_frf` (FFT + zero-pad, SIN ventana → leakage de sinc),
  `rt_from_ir`/`schroeder_curve` (Lundeby + Chu + ISO 3382), `rt60_per_band`, `find_modal_peaks`.
- `validate_meshrir.py` — M1 sobre MeshRIR (cuboide 7×6.4×2.7). Escribe `validation_meshrir_m1.md`
  (NO `validation_results.md`: ese lo sobrescribía, bug corregido 2026-09-06).
- `validate_meshrir_m4.py` — M4 con barrido de ubicación (MeshRIR no publica el placement).
- `flair_geometry.py` — reconstrucción de la nube FLAIR (2.9M pts): alinear yaw + occupancy +
  sellar/corregir + marching_cubes. `seal="auto"` con guard de régimen (no toca borde de grilla).
- `validate_flair.py` — M1+M4 sobre FLAIR (geometría reconstruida).
- `validate_discrimination.py` — línea base nula + barrido de escala (poder discriminante).

## Resultados afirmados (VERIFICAR, no creer)

- **MeshRIR M1 = 0.76%** pero **NO discrimina** (percentil 42 de la nula; barrido min en s=1.08).
- **FLAIR M1 = 1.42%** y **SÍ discrimina** (percentil 1; barrido min en s=1.005).
- **M4 crudo casi 0** por coloración de fuente; destendenciado FLAIR = 0.615 (MISS marginal);
  M4 discrimina (pico agudo en s=1.045 → afirma sesgo de malla ~4.5%).
- **M3 no evaluable** (RT mal definido < Schroeder + sin materiales).

Detalle en `validation_results.md`; auditoría previa + resolución en `REVIEW-VALIDACION.md`;
protocolo congelado en `validation_protocol.md` (§10 = cambios post-congelamiento).

## Dónde desconfiar primero (candidatos a bug/sesgo, según el autor)

1. `rir_to_frf` sin ventana: ¿algún pico medido es un sidelobe de sinc, no un modo?
2. Apareo "pico → modo más cercano": ¿infla el match? (ya se midió: no discrimina en MeshRIR).
3. `sim_spatial_avg` (en validate_*_m4/flair): ¿reproduce `frequency_response` exacto? factor c²,
   ξ_n=δ/ω_n, δ=3ln10/RT, `evaluate_many` con NaN fuera de malla.
4. `flair_geometry`: ¿la reconstrucción encoge la dimensión acústica efectiva ~4.5%? (M4 lo sugiere).
5. Bandas y detrend de M4: ¿elegidos por física o para acercarse a 0.7? (ratificado en protocolo §10).

## Campaña de medición propia (en diseño)

`protocolo_medicion.md` — para destrabar M3/M4 con datos completos (fuente FRD, Z(f) de
materiales, posiciones exactas, WAV de RIRs). Normas de adquisición citadas ahí (ISO 3382/18233,
ISO 10534-2, IEC 60268-21/61260/60942). El análisis modal queda fuera del ámbito de esas normas.

## Núcleo nuevo EN ALCANCE (mergeado a main 7-8 Sep 2026 — VERIFICAR, no creer)

El modelo de fuente exacto para subs enfrentados (DBA/CABS) se mergeó a `main` (PR #19,
commit ac6cd94). Suma núcleo físico/numérico que ENTRA en tu alcance de auditoría:

- `dba.py` — motor analítico rectangular (arrays front/rear, drive naive y LS de Santillán,
  cancelación polo-cero Cₘ(kₘ)=0, ley de aliasing f_max=c/d).
- `source_coupling.py` — base modal rectangular ortonormal + acople por integral de superficie
  Cₙ=∫_S pₙvₙ dS (fuente distribuida, Kuttruff Ec.3.6-3.7).
- `driver.py` — driver Thiele-Small + baffle step + open-baffle gain.
- `dba_evaluate.py` — evalúa una config real contra el ideal CABS sobre la respuesta TOTAL
  (SBIR + modos, crossfade en f_S).
- `cabs_optimize.py` — optimización parcial (differential_evolution + polaridad binaria).
- Dipolo = dos monopolos opuestos acoplado a d·∇φₙ en `acoustic_fem._source_modal_coupling`.

Dónde desconfiar primero: (1) el crossfade SBIR+modos en f_S ¿doble-cuenta reflexiones?;
(2) el drive LS es no causal → se ventanea la IR antes del Schroeder (¿sesga el decay?);
(3) el acople dipolar por diferencia de monopolos ¿reproduce d·∇φₙ a la resolución de malla usada?

**Columnas (cilíndricas/prismáticas):** PLANEADO, sin implementar (`plan_columnas.md`). El motor
de carve rígido de `furniture.py` es el que se reusaría; lo nuevo a validar sería el agujero
pasante piso-techo (topología de túnel).

**Respuesta compuesta + criterio CABS/DBA (9 Sep 2026, headless, sin commitear a UI todavía —
VERIFICAR):**
- `composed_response.py` — función canónica `composed_response(...)` → curva modal ⊕ SBIR
  (crossfade en f_S) en SPL absoluto dBSPL (P_REF=20e-6). Reusa `acoustic_fem.frequency_response`
  (modal, c²) y `sbir.sbir_from_sources` (imágenes). A auditar: ¿modal y SBIR están realmente en
  la MISMA escala absoluta de Pa para el mismo Q? (el crossfade asume que sí; `bench_composed_
  response.py` C4 lo chequea contra el monopolo analítico). ¿Hay escalón de nivel en f_S?
- **Fase 2 (v2.39): la respuesta compuesta YA está cableada a la GUI en los tres.** La FRF suma la
  curva compuesta (extendida hasta ~500 Hz, opción B); el SBIR pasó a dBSPL absoluto (`_open_sbir` +
  `SBIRDialog` con `to_spl(p_total)`); el overlay de corregibilidad EQ (C13/C21) vive en
  `plot_utils.draw_correctability_overlay` y el cómputo en `AcousticPanel._modal_fom_eqc` (grilla de
  receptores, `mm.eq_correctability`). A auditar: (1) verificado headless que la «Total híbrido» del
  SBIR == la «Total» de la FRF (max|dif|=0.0), pero ¿coincide también con lo que muestra la GUI real?
  (2) el overlay usa el mismo `eqc` en los tres: ¿es correcto asumir que el veredicto EQ es
  independiente de la config de fuentes (es propiedad de la sala)? (3) la compuesta debajo de f_S usa
  modal aunque el mesh no valga hasta f_S (si f_valid < f_S) → zona modal poco confiable en el cruce.
- `dba_evaluate.evaluate_cabs(criterion=...)` y `cabs_optimize.optimize_cabs(criterion=...)` —
  bajo "dba" el drive del array (front 0/+1, rear L/c/−1) lo fija el criterio y sale de los DOFs;
  bajo "cabs" queda libre. **Ya cableado a la GUI (v2.38): selector «Criterio» en `DBADialog`.**
  Reglas de array (spec del usuario): DBA = ≥2 subs adelante y ≥2 atrás; CABS = ≥2 subs atrás +
  fuente adelante de cualquier tipo (Full Range OK). `SourceRole.at_front/at_rear` = membresía de
  pared para cualquier tipo. A auditar: (1) ¿`tau_ideal=L/c` es el delay DBA correcto cuando los
  subs están inset de la pared (vs distancia frente→trasero real)? El tol_rel 0.35 lo tapa, pero es
  aproximación. (2) ¿El gate front/rear por `wall_tol=0.6 m` clasifica bien en salas chicas?
  `bench_cabs_criterion.py` 14/14 (incluye las reglas de array por criterio).

**Optimizador v2.42 (10 Sep 2026, en alcance — VERIFICAR):** `cabs_optimize.optimize_cabs`
sumó (1) restricción dura al recinto real: `_cost` penaliza +100 dB por fuente movida fuera
del polígono (`inside_fn` = `points_inside_surface`), porque el bound de caja es el AABB y en
recinto irregular el AABB > planta; (2) DOF de NIVEL: varía `sensitivity_dB` en `[sens−12,
sens+12]` acotado a `[40,130]`, recomputando Q. A auditar: (a) ¿la penalización discontinua de
100 dB distorsiona el `differential_evolution` (mínimos espurios en el borde del polígono) o el
polish local?; (b) el nivel por fuente es un grado de libertad legítimo del MSO, pero ¿el
objetivo `flat+spatial` con nivel libre puede degenerar (subir todas las fuentes al tope)? El
resto del batch (remapeo de firmas de material por traslación, portabilidad/embebido de
materiales, seguimiento de objetos al re-anclar) es IO/GUI, fuera del núcleo físico.
