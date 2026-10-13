# Plan — hallazgos M1-M4 del auditor sobre el QEP sparse (`qep_sparse.py`)

> Origen: auditoría independiente del `auditor-fisico` (12 Oct 2026) sobre el solver
> sparse del QEP de frontera (v2.61-2.62), tras cerrar el bug CRÍTICO C1 (definición
> de ξ, ver [[bug-xi-definicion-qep-c1]] en memoria + `auditor_contexto.md`). Estos
> cuatro son los MAYOR/MENOR que quedaron abiertos. Todo es NÚCLEO numérico: cada fix
> se valida contra un oráculo (nodal denso, SLEPc o cuenta propia) y un bench dedicado.
> NO se codea sin OK del usuario.

Orden acordado: **M4 → M3 → M2 → M1**.

---

## M4 — Beyn pierde polos en silencio al saturar el SVD  [HECHO 12 Oct 2026]

> Implementado y validado. `beyn_contour`/`beyn_qep` exponen `{k, ell, saturated}`
> (param `return_info`); `ell` se provisiona por la densidad REAL de la banda; el
> tiling usa `_beyn_band` recursivo que bisecta en Im al saturar (`BEYN_MAX_DEPTH=3`);
> `n_saturated` en el dict del wrapper. Bench `bench_qep_sparse_m4.py` 9/9 (flag dispara,
> bisección recupera 40/40 polos, integración sparse==nodal 0.0% en el ducto). Sin
> regresión: beyn 5/5, sparse 7/7, f4 4/4, f6 5/5, f5 4/4, front_rear qep/modal/nodal
> 4/4·9/9·9/9. Diagnóstico y diseño originales abajo.


**Diagnóstico.** `beyn_contour:267` hace `k = sum(s > tol_rank·s[0])`. Si una elipse
encierra ≥ `ellp` polos (`:627`, `ellp=max(2·nmc+12,18)`), no hay hueco en el espectro
singular, k satura en ell, los polos de más se pierden; `only_if_larger` deja entonces
el fallback subestimado. No hay guarda en runtime (el docstring `:242` dice «si k==ell
conviene subirlo» pero no lo hace). La densidad modal ∝ f² hace que `nmc` (nº de modos
FLAGGEADOS del cluster) subestime los polos TOTALES en la banda del contorno.

**Fix.**
1. `beyn_contour` y `beyn_qep`: param `return_info` que expone `{k, ell, saturated=(k>=ell)}`.
2. Provisionar `ell` por la densidad REAL de la banda (todos los modos `freqs_ref` dentro
   del semieje Im de la elipse), no por los flaggeados.
3. Tiling (`sparse_boundary_xi_shift`): helper recursivo `_beyn_band(fa,fbb,xg,depth)` que,
   si el contorno SATURA, bisecta la banda en Im y recursa (hasta `BEYN_MAX_DEPTH=3` o
   banda < conf_hz/2) → reduce modos-por-contorno a la mitad por nivel.
4. Instrumentar `n_saturated` en el dict `return_info` del wrapper (ya no es silencioso).

**Oráculo/bench.** `bench_qep_sparse_m4.py`: (a) unidad: `beyn_qep` con `ell` chico sobre
un contorno denso → `info["saturated"]==True` (el flag dispara); (b) integración: sala de
alta densidad modal (casi-cúbica), β=1 → el sparse recupera los polos casi-críticos que
el nodal denso (Nn≤1800) confirma, y ningún casi-crítico queda en el fallback subestimado.

**Ref.** Beyn 2012, *Linear Algebra Appl.* 436, §3 (elección de ℓ y remedio k==ℓ).

---

## M3 — `only_if_larger` permite sobre-inflar un modo por mis-asignación  [HECHO 12 Oct 2026]

> Implementado y validado. El voto guarda el MARGEN de solape sobre el 2do modo;
> `_put`, en el relleno Beyn (only_if_larger), solo pisa si solape ≥ `overlap_strong`
> (0.5) y margen ≥ `overlap_margin` (0.1) (params nuevos del wrapper; el 1er pase PAL
> es baseline sin guarda). NO se agregó la guarda de proximidad en |w| del plan: el
> matcheo corre |w| hasta 35% (fix C1), una banda ajustada rechazaría casi-críticos
> genuinos; el solape es el discriminador robusto. Bench `bench_qep_sparse_m3.py` 3/3
> (ducto: estricta rechaza el overwrite de Beyn del casi-crítico 0.339↔0.790, default
> lo deja pasar == nodal; no-harm ON==OFF a 9e-16 en sala near-degenerada). Sin
> regresión. **ALCANCE:** protege el camino de relleno Beyn. Las inflaciones OBSERVADAS
> en degeneración EXACTA (cubo: modo inflado por el 1er pase PAL, o sobre-estimado por
> el fallback modal) son el RESIDUAL pre-existente que el auditor dejó fuera (ahí la
> «verdad» nodal también es ambigua). Esta guarda NO las ataca. Diagnóstico abajo.


**Diagnóstico.** `_put:524` escribe si `newxi > xi[nm]`. Un polo de Beyn mal asignado con
ξ mayor INFLA un modo modesto; F6-T2 solo chequea ξ_sparse ≥ ξ_fallback, que una inflación
espuria PASA. El voto (`:534-538`) acepta el mejor solape sin exigir margen ni proximidad
en frecuencia.

**Fix.** Condicionar la escritura a una asignación inequívoca y consistente en frecuencia:
(a) guarda de proximidad: aceptar el polo para el modo nm solo si `|w_polo|` cae en la banda
esperada del modo (ωₙ ± corrimiento del cluster); (b) margen de voto: el solape ganador debe
superar al segundo por un margen (rechazar empates, el caso degenerado); (c) mantener
`only_if_larger` tras esas guardas.

**Oráculo/bench.** Par casi-degenerado donde Beyn podría cruzar asignaciones; assertar que
ningún modo modesto se infla (ξ dentro de tolerancia del nodal Nn≤1800).

**Ref.** Tisseur & Meerbergen 2001 (certificado η por polo) + criterio de solape de `_assign`.

---

## M2 — el gate `xi_est>0.15` no es cota probada  [HECHO 12 Oct 2026]

> Implementado y validado. El certificado η con la forma RÍGIDA φ_n NO sirve de gate
> (medido: no separa el error del ξ; el casi-crítico, el peor subestimado, tiene η de
> los más BAJOS). En su lugar: (1) `xi_gate` 0.15→0.08, calibrado por el audit (ratio
> ξ_est/ξ_nodal ∈ [0.40,0.43] sobre una familia de shoeboxes → 0.08 < 0.40·xi_crit=0.14,
> margen hasta ξ_real≈0.20); (2) red de SOSPECHA: si el fallback modal < ξ_est (con
> ξ_est no despreciable) ⇒ subestimación por truncamiento ⇒ flag. Bench
> `bench_qep_sparse_m2.py` 5/5 (audit del margen; recuperación end-to-end 0.0% de los
> modos subestimados 0/2/9 del ducto; η no separa). Es empíricamente calibrado, NO una
> cota demostrada (declarado). Sin regresión. Diagnóstico abajo.


**Diagnóstico.** `:574` `xi_est=(c|β|/2)·diag(G)_n/ωₙ` (perturbación diagonal 1er orden).
El claim «cota inferior monótona → ningún casi-crítico se escapa» es empírico (ratio
ξ_true/ξ_est≈3.9-4.4 medido, no teorema). Un modo con ξ_est apenas <0.15 y ξ_true moderado
por acople off-diagonal se escaparía a Beyn con el fallback subestimado.

**Fix.** Gate por CERTIFICADO: tras PAL+relleno modal, para cada modo no cubierto calcular el
η (`_backward_error`, ya existe) del valor de fallback como polo del QEP; si el fallback NO
satisface el QEP a tolerancia, flaggear para Beyn independiente de `xi_est`. Respaldo: tabla
empírica ξ_true/ξ_est sobre muchas geometrías (donde corre el nodal) para fijar
`xi_gate = ξ_objetivo/min_ratio` con margen, y bajarlo (Beyn es barato sobre pocos modos).

**Oráculo/bench.** Modo con ξ_est<0.15 pero ξ_true moderado (acople off-diagonal fuerte): el
gate por certificado lo captura, el gate viejo lo deja escapar.

**Ref.** Tisseur 2000, *SIAM J. Matrix Anal.* (backward error); Morse & Ingard 9.4.14.

---

## M1 — sin oráculo exacto a escala real (Nn=5376)  [HECHO 12 Oct 2026 — con HALLAZGO]

> **El oráculo SLEPc a escala expuso un problema real.** SLEPc (PEP/TOAR, sparse,
> independiente) corre en WSL (`~/miniforge3`, env `qep_oracle`, SLEPc 3.26 complejo).
> Baseline N=693: 4/4 (y el fix C1 valida contra SLEPc, |Δξ|=0.0000, tras corregir la
> convención ξ=δ/|s| también en `bench_qep_slepc.py`). **A escala (Nn~2660) el sparse
> A+B DISCREPA de SLEPc en |Δξ|~0.30 en los casi-críticos y tarda ~45× más (192 vs 4 s).**
> La «exactitud a Nn≤6000» de v2.62 era inferencia FALSA (el auditor tenía razón). Causa:
> a Nn≳2600 PAL/ARPACK pierde el fundamental de f baja y el polo de Beyn da ~0.55 (no el
> ~0.82 convergido); no es banding (couple_thr=0 igual falla).
>
> **Resolución (1+3 y DESPUÉS el arreglo del solver, decisión del usuario «arregla el
> sparse»):**
> 1. (provisional) se bajó el cap a 1800 mientras se diagnosticaba.
> 3. SLEPc como ORÁCULO de CI: `bench_qep_slepc.py` (N=693, 4/4, valida C1 vs SLEPc) +
>    `bench_qep_slepc_scale.py` (Nn>1800) + `bench_qep_sparse_m1.py` (win-native).
>
> **ARREGLO DEL SOLVER (hecho, validado).** Causa raíz precisa (no era ARPACK ni
> banding): el polo de un modo fuertemente matcheado tiene δ=Re GRANDE Y su fₙ se corre
> HACIA ARRIBA (|s|~1.4-1.7·wc, p.ej. fundamental del ducto Nn=2430: rígido 24.5 Hz →
> |s| 35 Hz, polo s=−181+124i), quedando lejos del eje imaginario; la elipse de Beyn
> (a=1.15wc, z0=−0.1wc) NO lo alcanzaba (test adentro=1.006) → Beyn 0 polos → sparse caía
> al fallback. FIX en `_beyn_band`: ensanchar en Re (a=1.5wc, z0=−0.35wc); ensanchar en
> Re NO agrega modos (se diferencian en Im) → no satura. **Validado: sparse == nodal
> EXACTO a 0.0000 en los 16 modos a Nn=2660** (antes 0.30 de error), fundamental
> recuperado también a Nn=4301 (sparse==SLEPc 0.816), 24× más rápido (21-80 s vs 505 s).
> `SPARSE_NN_MAX` RESTAURADO a 6000 (cubre Control Ale 5376). El residuo sparse-vs-SLEPc
> en pares near-degenerados (≤0.10) es ambigüedad ENTRE oráculos (sparse==nodal exacto),
> NO defecto del sparse; el bench compara casi-críticos AISLADOS. Diagnóstico abajo.


**Diagnóstico.** `qep_boundary_nodal` corta en Nn≤1800 (eig denso O((2N)³)); Control Ale corre
por el sparse a Nn=5376 sin comparación exacta (solo vs perturbación, que subestima el
casi-crítico). La exactitud a esa escala es INFERENCIA (álgebra invariante de escala), no
medición.

**Cierre de validación** (no es «fix» de código):
(a) extender el oráculo SLEPc (`bench_qep_slepc.py`, ya 4/4 a N=693 en WSL) a Nn≈5376 sobre
   la malla real: volcar K/M/C_rear, resolver SLEPc PEP (TOAR, shift-invert, sparse) en
   WSL/CI, comparar ξ (clásico post-C1) polo a polo (solver exacto INDEPENDIENTE a escala real);
(b) complemento win-native: oráculo de convergencia (sparse `couple_thr=0` == default +
   refinamiento de malla → ξ del casi-crítico converge, cota por Richardson);
(c) barato: subir `max_dense` 1800→~3000 donde RAM/tiempo del eig denso lo permitan.

**Ref.** Hernández, Roman & Vidal, *ACM TOMS* 31 (SLEPc), manual PEP/TOAR; Beyn 2012.
