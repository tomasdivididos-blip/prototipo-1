# REVIEW-VALIDACION.md — Auditoría adversarial del pipeline de validación empírica

Auditor externo (`auditor-fisico`), entrada en frío, 2026-09-06. Reprodujo los tres runs
(MeshRIR M1, FLAIR M1+M4) con Anaconda: los números de `validation_results.md` reproducen
exactamente. El problema no es reproducibilidad, sino el **poder discriminante** de las métricas.

Cada hallazgo lleva su **estado de resolución** (agregado por el autor tras el test de
discriminación `validate_discrimination.py` y los fixes del 2026-09-06).

## CRÍTICO

### C1 — M1/M2 no discriminan: una sala equivocada también "PASA"
**Auditor.** Apareo "pico medido → modo predicho más cercano" con tol 3% y 4-5 picos contra
22-35 modos: casi cualquier frecuencia aparea. Reprodujo: en MeshRIR una frecuencia aleatoria
tiene 95% de caer ≤3% de algún modo; una sala inventada 6×4×3 dio M1=0.18% en FLAIR (mejor que
la correcta 0.28%). Concluye: el PASA de M1 no valida la geometría; el claim JAAS está sobre-vendido.

**Resolución (PARCIALMENTE CONFIRMADO, matizado).** Se implementó el test que el auditor pidió
(línea base nula + barrido de escala), `validate_discrimination.py`:
- **MeshRIR: CONFIRMADO.** M1_true (1.05%) está en el percentil 42 de la nula; mínimo del barrido
  en s=1.08, no en 1.0. M1 sobre MeshRIR NO discrimina; su PASA es azar. Se reporta como tal.
- **FLAIR: REFUTADO.** M1_true (0.28%) está en el percentil **1** de la nula (mejor que el 99% de
  las salas aleatorias del mismo volumen); mínimo del barrido en s=1.005. La sala 6×4×3 del auditor
  era una muestra afortunada de la cola (~1% la supera). M1 sobre FLAIR SÍ discrimina y SÍ valida
  la geometría reconstruida. Se reporta CON la línea base nula, no como número pelado.

## ALTO

### A1 — MeshRIR: los rasgos dominantes del espectro (22, 52 Hz) son los que NO aparean
**Auditor.** El pico global medido (22 Hz) se descarta como sub-modal; el 2º (52 Hz) es el residual
que falla la tolerancia. Los apareos limpios son picos secundarios en la región densa (donde C1 no
discrimina). **Resolución: MOOT.** Dado C1 (MeshRIR M1 no discrimina), el punto queda absorbido:
MeshRIR ya no se presenta como validación de M1, solo como caso de baja resolución modal.

### A2 — M2 MeshRIR = 80% exacto, colgado de excluir el 22 Hz
**Auditor.** Con el 22 Hz contando, M2=67% FALLA. La exclusión es físicamente defendible (< 1er axial
24.8) pero decisiva. **Resolución: ACEPTADO.** Se reporta M2 MeshRIR como "en el límite, condicionado
a la exclusión sub-modal", y dado C1 no se le da peso inferencial.

## MEDIO

### M1 — Reconstrucción FLAIR biestable; "converge estable en s" era falso
**Auditor.** seal=2 → V=100.9 (fuga), seal=3 → V=60.8 (correcto). La docstring afirmaba convergencia;
es la transición fallo→éxito del sellado. seal=3 hardcodeado sin guard. Verificó por su cuenta que
seal=3 da la geometría correcta (ajuste de planos: Lx≈5.0, Ly≈5.1, Lz≈2.72).
**Resolución: CORREGIDO.** (a) Docstring arreglada (era falso). (b) Se agregó `seal="auto"` con guard
de régimen: sube el seal hasta que el interior deja de tocar el borde de la grilla (deja de fugar);
si no sella con seal≤8, levanta error. `validate_flair.py` usa auto + `assert not leaked`. Verificado:
auto elige seal=3, seal=2 se marca leaked=True.

### M2 — f_min=45 vs "baja frecuencia FUERTE" del protocolo
**Auditor.** M4 usa f_min=45 (el parlante no radia grave), pero el protocolo §9 dice "LF FUERTE 62%
de energía en 20-120". Inconsistente sin precisar que 20-45 es débil. **Resolución: ACLARADO.** El 62%
es de FLAIR global (20-120); la caída fuerte del promedio espacial es <45 Hz (visible en la figura,
−25 dB). Ambas cosas conviven: hay energía en 45-120, poca en 20-45. Documentado en resultados.

## BAJO

- **B1 — RT60 MeshRIR 0.38 s.** CONFIRMADO correcto: el paper (Table 1, arXiv 2106.10801) reporta 0.38 s
  para S1. El "~300 ms" que dudó el auditor no aplica a S1. Sin cambio.
- **B2 — 26.9 Hz FLAIR contado en `cov`.** ACEPTADO menor: la narrativa decía "excluido por física" pero
  el código lo cuenta como miss (4/5=80%). M1 (mediana) es robusto al outlier. Se aclara en resultados.
- **B3 — `rir_to_frf` sin ventana.** ACEPTADO como limitación conocida: solo zero-pad (leakage de sinc),
  mitigado por promedio de potencia + umbral de prominencia. Los picos inspeccionados son reales.

## SÓLIDO (verificado por el auditor)

c de temperatura (347.0 m/s, Kuttruff); dimensiones MeshRIR no tuneadas (paper); núcleo FEM (0.38%
O(h²)); geometría FLAIR reconstruida correcta (coincide con ajuste de planos); `sim_spatial_avg`
reproduce `frequency_response` (factor c², ξ_n=δ/ω_n correctos); 0/135 mics fuera de malla; M4
reportado honestamente como MISS (banda/detrend no elegidos para pasar); `rt_from_ir` Lundeby+Chu+ISO.

## Hallazgo adicional del autor (test de discriminación, va más allá del pedido del auditor)

**M4 SÍ discrimina, y detectó un sesgo sistemático que M1 no ve.** La curva M4(s) vs escala de
geometría es un pico agudo (cae a −0.6 en s=0.85). La sala verdadera (s=1.0) da 0.615 en el flanco;
el óptimo (0.80) está en s=1.045. O sea los modos del sim quedan ~4.5% ALTOS respecto de la medición
FLAIR. No es el escalonado FEM (0.4%): apunta a que la reconstrucción + doble-voxelización encoge la
dimensión acústica efectiva ~4.5%. M4 es el metric discriminante de verdad; M1 es ciego a este sesgo
porque solo mira frecuencias de pico contra la densidad. Hallazgo accionable (afinar malla/reconstrucción).

## Veredicto (autor, tras resolución)

El auditor tenía razón en el MECANISMO (C1) pero generalizó de más: M1 no discrimina en MeshRIR
(azar) pero SÍ en FLAIR (percentil 1). La validación fuerte para JAAS es FLAIR M1 (con línea base
nula) + M4 discriminante. El sesgo de malla ~4.5% que reveló M4 es lo más valioso: muestra que el
pipeline es sensible y honesto. Fixes aplicados: guard de sellado, docstring, y el bug de clobber de
`validation_results.md` (el runner lo sobrescribía; ahora escribe `validation_meshrir_m1.md`).
