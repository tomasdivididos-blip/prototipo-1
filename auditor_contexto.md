# Contexto vivo para el auditor-fisico

> Este archivo lo actualiza el asistente principal en CADA recap, para que el
> `auditor-fisico` entre con el estado al día. **Advertencia de método (no negociable):**
> TODO lo de acá son AFIRMACIONES DEL AUTOR (co-autor sesgado), no evidencia. Verificá
> cada cosa contra la fuente física, un oráculo, o una cuenta propia. Que este archivo
> diga "resuelto/PASA" no prueba nada; es un puntero a qué mirar.

**Última actualización:** 2026-09-06.

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
