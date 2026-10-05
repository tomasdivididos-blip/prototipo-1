# Plan — Solver sparse robusto para el QEP de frontera complejo

> Objetivo: que la curva C2 del panel de decaimiento (pared trasera matcheada) y, en
> general, el QEP de frontera `qep_boundary_nodal`, corran EXACTO en salas grandes sin
> el eig denso O((2N)³). Hoy el nodal se capa en Nn≤1800 y cae a la proyección modal.
> Vara del proyecto: exactitud bajo Schroeder manda; validar todo (analítico / oráculo
> exacto / medición). Núcleo 100% numpy+scipy (D0). Ver [[frente-opuesto-admitancia]],
> `auditor_contexto.md` §v2.60.

## 0. Insight estructural (lo que hace tratable el problema)

El QEP del solver, $P(\omega)=-M\omega^2 + i c\beta C\,\omega + c^2K$, con el cambio
$s=i\omega$ (Laplace) se vuelve el **QEP viscoso clásico REAL y SIMÉTRICO**

$$s^2 M + s\,(c\beta)\,C + c^2 K = 0,$$

con $M$ SPD, $K$ SPSD (núcleo = modo DC, a deflactar), $C_d=c\beta C$ SPSD y de
**BAJO RANGO** (solo los nodos de la pared trasera: rank 3-11% de N, medido). Los
autovalores $s=-\delta\pm i\omega_d$ dan directo el decaimiento $\delta$ y la frecuencia.
Esto habilita: teoría real-simétrica (más estable), el algoritmo PAL de bajo rango, y
STOAR simétrico de SLEPc como oráculo. Con β real matcheada (=1) es un QEP; con β(ω)
compleja de `impedance.py` es un NEP (lo cubre Beyn sin cambiar de método).

## 1. Factibilidad medida (F0, 4 Oct 2026) — la memoria NO es el cuello

Factorización LU compleja desplazada $P(s)$ a f≈60 Hz (el costo dominante de A y B):

| Sala | V (m³) | npm | N | rank(C) | nnz(L+U) | LU mem | tiempo |
|---|---|---|---|---|---|---|---|
| Control Ale | ~60 | 4.0 | 5376 | 515 (9.6%) | 2.45 M | 0.039 GB | 0.28 s |
| Aula curada | 114 | 3.0 | 4002 | 130 (3.2%) | 1.07 M | 0.017 GB | 0.08 s |
| Central Hall York | ~12000 | 2.0 | 19397 | 653 (3.4%) | 13.9 M | 0.222 GB | 1.79 s |

El eig DENSO de 2N que se quiere evitar: para N=19397, matriz compleja de 38794² ≈
24 GB y minutos-horas. El sparse saca los pocos polos sub-Schroeder en segundos dentro
de 6 GB. **Conclusión: A+B es viable con holgura; el trabajo es robustez, no cómputo.**

## 2. Presupuesto y restricciones

- **Tiempo:** ≤ 10 s al abrir el panel (usuario ≈ 8 GB RAM; diseñar a 6 GB de tope).
- **D0:** motor en numpy+scipy puro (`scipy.sparse.linalg.splu` para los solves
  desplazados). **SLEPc = solo oráculo en la máquina del autor**, env conda aparte
  (`qep_oracle`); los benches que lo usan se SALTEAN si `slepc4py` no está (suite verde
  en la compu del usuario y en CI). Nunca se shippea.
- **β:** real matcheada (QEP, A/B) y compleja β(ω) (NEP, B). Ambas, según el usuario.

## 3. Métodos

- **A — PAL (Padé Approximate Linearization, bajo rango).** Lu, Huang, Bai & Su
  (2015). Reduce el pencil lineal de 2N a N+ℓm (ℓ=rank C, m=orden Padé). Motor rápido
  del caso matcheado real. `referencias/Lu Huang Bai Su - A Pad´e Approximate
  Linearization...pdf`.
- **B — Integral de contorno (Beyn).** Beyn (2012). Contorno alrededor de la banda
  sub-Schroeder; reduce a un problema lineal de dimensión k=nº de polos adentro.
  Robusto al clustering/casi-defectividad (β=1 casi-crítico) y cubre β(ω) (NEP).
  Resolvente con `splu`. `referencias/Beyn - An integral method...pdf`.
- **Oráculo C — SLEPc PEP/STOAR shift-invert.** Solo en la máquina del autor, para
  contrastar A y B. `referencias/SLEPc Users Manual.pdf`, Campos & Roman (2016).

## 4. Rigor (no negociable antes de confiar)

1. **Escalado** del QEP (si no, la linealización es inestable; ya se vio): Fan-Lin-Van
   Dooren (2004) y escalado tropical de Betcke (2008). `referencias/`.
2. **Error hacia atrás por polo** $\eta=\|P(\lambda)x\|/((|\lambda|^2\|M\|+|\lambda|\|C\|+\|K\|)\|x\|)$
   y condicionamiento: Tisseur & Meerbergen (2001); Higham, Mackey & Tisseur (2008).
3. **Backend denso del problema reducido**: `quadeig` (Hammarling, Munro & Tisseur 2013).
4. **Deflación del núcleo de K** (modo DC) para no generar polos espurios en ω≈0.
5. **Oráculos**: reproducir el QEP nodal denso actual a ~1e-10 en N chico; atadura a
   `bench_front_rear_qep` (axial analítico) y a la perturbación en β moderado; estudio
   de convergencia vs malla; SLEPc en N medio; **validación física del RT60 vs las 6
   RIRs del TP7** (`TP 7/RIRs Control Room/`).
6. Survey maestro NEP (contorno/Krylov/racional): Güttel & Tisseur (2017).

## 5. Fases

- **F0 — scaffold + oráculos + factibilidad.** Factibilidad HECHA (§1). Falta: 2-3
  shoeboxes oráculo + harness de validación (reusa el QEP denso como verdad).
- **F1 — método A (PAL). HECHO (4 Oct 2026).** `qep_sparse.pal_qep` (+ wrapper
  multi-shift `pal_boundary_xi_shift`). `bench_qep_sparse.py` 7/7: PAL denso==QEP
  denso; PAL sparse==denso (5e-15, factoriza solo Q(σ)); η_Q certifica (6.8e-14);
  el wrapper multi-shift reproduce `qep_boundary_nodal` a 0.00% en el 83% de modos.
  HALLAZGO: un shift capta su dominio de confianza (Fig 2.2) → multi-shift cubre la
  banda oscilatoria; los sobreamortiguados → método B.
- **F2 — método B (Beyn). HECHO (4 Oct 2026).** `qep_sparse.beyn_contour` (genérico,
  toma T(z) callable) + `beyn_qep`. `bench_qep_beyn.py` 5/5: encuentra TODOS los polos
  dentro de Γ (match 1.4e-7, η 4.9e-11); captura el polo más amortiguado (Re=−796,
  lejos del eje imaginario, que PAL no ve); convergencia EXPONENCIAL en n_quad
  (3.4e-6→1.5e-9); resuelve el NEP con β(z) dependiente de frecuencia (residuo 1e-8).
- **F3 — oráculo SLEPc** (pendiente; en Windows va por WSL, no hay build win-64).
- **F4 — wiring. HECHO (4 Oct 2026).** `qep_sparse.sparse_boundary_xi_shift` (PAL
  banda + relleno: proyección modal para los modos de ξ modesto, Beyn SOLO para los
  casi-críticos que PAL no cubre). `bench_qep_sparse_f4.py` 4/4: reproduce el nodal
  denso EXACTO en los 12 modos del shoebox, incluido el muy amortiguado ξ=1.2 (PAL
  solo 92% → Beyn rellena → 100%). `_rear_matched_delta_xi` ahora: nodal (Nn≤1800) →
  **sparse A+B con fallback modal (1800<Nn≤6000)** → modal (Nn>6000). Control Ale
  (Nn=5376) corre en 16 s on-demand y CORRIGE la proyección modal hasta 0.22 en ξ.
  Nota: el objetivo de 10 s no se cumple para Nm~71 (el eigs de PAL es ~2 s/shift);
  es on-demand y el norte del proyecto prioriza exactitud sobre comodidad.
- **F5 — validación física. HECHO (4 Oct 2026).** `bench_qep_f5.py` 4/4 contra el
  TP7 Control Room. **Limitación de la medición (documentada):** las 6 RIRs son de
  0.19 s → FRF con df≈5.3 Hz, y arriba de 50 Hz los modos están más juntos que eso
  (hay degenerados, M>1), así que NO se puede extraer ξ por modo sub-Schroeder de
  estas RIRs (coincide con la calibración previa). Lo validado: (T1) las frecuencias
  FEM de recinto.room == la caja analítica (<1.3%); (T2) el pico modal medido de la
  RIR (84.4 Hz) == un modo FEM (83.5 Hz); (T3) el **solver SPARSE == el modelo de
  PERTURBACIÓN** (el default ya validado contra medición, FLAIR 1.42%) sobre la
  GEOMETRÍA REAL del TP7, 0.59% medio / 1.94% máx. Combinado con que el sparse
  reproduce el QEP nodal a máquina, el solver HEREDA la validación empírica del
  modelo forward.

**ESTADO: F0-F2, F4, F5 HECHOS. Solo queda F3 (oráculo SLEPc vía WSL, opcional).**

## 6. Geometrías de prueba

- Shoeboxes oráculo: las arma el asistente (QEP denso + axial exacto = verdad).
- `PLANO AULA_curado.obj` (114 m³, watertight, con columna): caso geometría robusta.
- `Central Hall - Universiry of York.obj` (~12000 m³, no watertight): estrés de escala.

## 7. Referencias (todas en `referencias/`)

Tisseur & Meerbergen 2001 (SIAM Review 43) · Güttel & Tisseur 2017 (Acta Numerica 26) ·
Beyn 2012 (LAA 436) · Lu, Huang, Bai & Su 2015 (IJNME 103) · Betcke 2008 (SIMAX 30) ·
Fan, Lin & Van Dooren 2004 (SIMAX 26) · Hammarling, Munro & Tisseur 2013 (TOMS 39,
quadeig) · Van Beeumen, Meerbergen & Michiels 2015 (SIMAX 36, CORK) · Güttel et al.
2014 (SISC 36, NLEIGS) · SLEPc Users Manual · Campos & Roman 2016 (SISC 38) · Bai & Su
2005 (SIMAX 26, SOAR) · Higham, Mackey & Tisseur 2008 (SIMAX 29).
