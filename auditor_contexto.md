# Contexto vivo para el auditor-fisico

> Este archivo lo actualiza el asistente principal en CADA recap, para que el
> `auditor-fisico` entre con el estado al día. **Advertencia de método (no negociable):**
> TODO lo de acá son AFIRMACIONES DEL AUTOR (co-autor sesgado), no evidencia. Verificá
> cada cosa contra la fuente física, un oráculo, o una cuenta propia. Que este archivo
> diga "resuelto/PASA" no prueba nada; es un puntero a qué mirar.

**Última actualización:** 2026-09-08.

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
- `dba_evaluate.evaluate_cabs(criterion=...)` y `cabs_optimize.optimize_cabs(criterion=...)` —
  bajo "dba" el drive del array (front 0/+1, rear L/c/−1) lo fija el criterio y sale de los DOFs;
  bajo "cabs" queda libre. A auditar: ¿`tau_ideal=L/c` es el delay DBA correcto cuando los subs
  están inset de la pared (vs distancia frente→trasero real)? El tol_rel 0.35 lo tapa, pero es una
  aproximación. `bench_cabs_criterion.py` 8/8.
