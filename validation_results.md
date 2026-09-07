# Resultados de validacion

Protocolo: `validation_protocol.md` (congelado 2026-09-04, cambios en su §10). Auditoría
independiente: `REVIEW-VALIDACION.md`. Este doc es el AGREGADO mantenido a mano; cada runner
escribe su propio archivo (`validation_meshrir_m1.md`, figuras) y NO sobrescribe este.

Runners: `validate_meshrir.py` (M1), `validate_meshrir_m4.py` (M4+barrido), `validate_flair.py`
(M1+M4), `flair_geometry.py` (reconstruccion), `validate_discrimination.py` (poder discriminante).

## Lectura de una linea

La afirmacion nuclear (exactitud de FRECUENCIAS modales bajo Schroeder) SE SOSTIENE en FLAIR,
geometria arbitraria reconstruida de un escaneo laser, VALIDADA CONTRA SU LINEA BASE NULA
(percentil 1). En MeshRIR M1 no discrimina (densidad modal alta + pocos picos = azar). M4
(forma espacial) discrimina fuerte y, en FLAIR, ademas revela un sesgo de malla ~4.5%.

---

## MeshRIR S1-M3969 — M1 (frecuencia modal): PASA pero NO DISCRIMINANTE

- Cuboide 7.0×6.4×2.7 m (paper). c=347.0 m/s (T=26.3 C). 3969 mics. Reactancia auto OFF.
- Malla npm=4, f_max 231 Hz, piso numerico FEM~analitico 0.38% (O(h²)).

| f_med [Hz] | f_FEM | drel | nota |
|---|---|---|---|
| 22.0 | 24.8 | 12.85% | sub-modal (< 1er axial 24.8) |
| 52.0 | 49.7 | 4.49% | residual |
| 57.1 | 56.7 | 0.76% | apareado |
| 68.5 | 69.2 | 1.04% | apareado |
| 85.3 | 85.6 | 0.31% | apareado |
| 116.8 | 116.9 | 0.07% | apareado |

M1 = 0.76% (vs FEM) / 1.05% (vs analitico), M2 = 80% (4/5). **PERO: NO DISCRIMINA** (test de
discriminacion, C1 del auditor). M1_true (1.05%) esta en el **percentil 42** de salas aleatorias
del mismo volumen; el barrido de escala tiene su minimo en s=1.08, no en 1.0. Con 36 modos en
banda y tol 3%, casi cualquier sala aparea. **MeshRIR NO valida geometria via M1** (densidad modal
alta + pocos picos medidos resolubles). Aporta solo el chequeo de que el nucleo FEM reproduce las
autofrecuencias de caja (independiente de la medicion). M2=80% ademas esta en el limite y cuelga de
excluir el pico sub-modal de 22 Hz (fisicamente valido, pero fragil).

## MeshRIR — M4 (correlacion espacial): INCONCLUSO

MeshRIR fija el origen en el centro de la region de medicion y NO publica su ubicacion absoluta en
el cuarto (verificado: paper/repo/pagina/dataset). M4 depende de esa ubicacion. Barrido de 27
ubicaciones plausibles: M4 crudo max 0.44, destendenciado max 0.53, **0/27 ≥ 0.7**. Dos causas:
(1) ubicacion no publicada; (2) coloracion de fuente (DS) + monopolo iω. INCONCLUSO; lo carga FLAIR.

---

## FLAIR — M1 (frecuencia modal): PASA y DISCRIMINA — geometria arbitraria

- Geometria RECONSTRUIDA de la nube de 2.9M puntos (`flair_geometry.py`): alinear yaw (8.5° removido,
  rigido) + occupancy + sellar/corregir (seal="auto", guard de regimen) + marching_cubes → superficie
  cerrada → `build_volume_mesh`. Sala alineada 4.96×5.08×2.72 m, V=60.8 m3. c=344.7 (dato).
- 135 mics × 2 fuentes, posiciones EXACTAS en el marco de la nube. Malla 5090 nodos, f_max 229 Hz.

| f_med [Hz] | f_FEM | drel | nota |
|---|---|---|---|
| 26.9 | 35.1 | 30.88% | sub-modal (< 1er modo ~34) |
| 51.7 | 51.0 | 1.42% | apareado |
| 71.8 | 72.4 | 0.83% | apareado |
| 77.2 | 79.5 | 3.00% | apareado |
| 101.4 | 102.0 | 0.63% | apareado |

**M1 = 1.42% (mediana) → PASA** (umbral ≤3%), M2 = 80%. Y a diferencia de MeshRIR, **DISCRIMINA**:
M1_true (0.28% sobre picos modales) esta en el **percentil 1** de la nula (mejor que el 99% de las
salas aleatorias del mismo volumen); el barrido de escala tiene su minimo en s=1.005 (la geometria
verdadera es el optimo). **La validacion de M1 sobre geometria arbitraria reconstruida SE SOSTIENE**,
reportada con su linea base nula (no como 1.42% pelado). El pico de 26.9 Hz es sub-modal (< fundamental).

## FLAIR — M4 (correlacion espacial): MISS marginal, pero DISCRIMINANTE

Metrica ratificada (protocolo §10): DESTENDENCIADA, banda [f_min, f_S] = [45, 142] Hz. f_S =
2000√(RT/V)=142. f_min=45 = piso util de la RIR (el parlante DS no radia grave; el 62% de energia
LF de FLAIR es de 20-120, pero 20-45 es debil). Amortiguamiento xi_n=δ/ω_n, δ=3ln10/RT (input declarado).

| Metrica | Valor | Umbral | Veredicto |
|---|---|---|---|
| M4 destendenciado, fuente 0 | **0.615** | ≥0.7 | MISS marginal |
| M4 crudo, fuente 0 | 0.655 | | secundario |
| M4 destendenciado, fuente 1 | 0.539 | | secundario |

**M4 DISCRIMINA fuerte:** la curva M4 vs escala de geometria es un pico agudo (cae a −0.6 en s=0.85,
−0.2 en s=1.15). La sala verdadera (s=1.0) cae en el flanco a 0.615; el optimo (0.80, que PASA) esta
en **s=1.045**. Es decir M4 detecta que los modos del sim quedan **~4.5% ALTOS** vs la medicion — un
sesgo que M1 NO ve (M1 solo mira frecuencias de pico contra la densidad). No es el escalonado FEM
(0.4%): apunta a que la reconstruccion + doble-voxelizacion encoge la dimension acustica efectiva
~4.5%. **Hallazgo accionable**, no un fracaso: afinar malla/reconstruccion cerraria el gap 0.62→0.80.

---

## M3 (RT60 por banda): NO EVALUABLE como metric modal (bloqueo físico + de dato)

RT60 medido por banda de octava (mediana sobre mics, `rir.rt60_per_band`):

| banda | MeshRIR RT (n confiables/200) | FLAIR RT (n/135) |
|---|---|---|
| 31 Hz | 0.46 s (5) | 0.55 s (1) |
| 63 Hz | 1.24 s (4) | 0.36 s (3) |
| 125 Hz | 0.57 s (23) | 0.47 s (43) |

Dos bloqueos, ambos legítimos:
1. **Físico (refuerza la tesis del proyecto):** RT60 es una cantidad de campo DIFUSO, mal definida
   en la banda modal. Con pocos modos por octava el EDC no decae como una exponencial única (cada
   modo decae a su ritmo) → el ajuste falla para casi todos los mics (n_confiable = 1-5 de 100-200
   en 31/63 Hz; MeshRIR 63 Hz da 1.24 s, absurdo vs 0.38 s broadband). Solo 125 Hz (cerca/encima de
   f_S) tiene RT confiable. Que RT sea inestable bajo Schroeder ES el resultado esperado: la acústica
   estadística no vale ahí. Por eso el modelo valida por M1 (frecuencias) y M4 (campo), no por RT.
2. **De dato:** el sim predice RT desde los MATERIALES (α catálogo → β → ξ_n). Ni MeshRIR ni FLAIR
   los documentan. Usar el RT medido para fijar ξ (como se hace para el ancho de picos de M4) haría
   M3 circular.

**Veredicto M3: DIFERIDO** a un recinto con materiales documentados (medición propia; ya listado como
pendiente en el protocolo §2/§5). No se fuerza un M3 circular ni un RT modal mal definido.

---

## Resumen agregado

| Recinto | M1 | ¿M1 discrimina? | M4 | ¿M4 discrimina? |
|---|---|---|---|---|
| MeshRIR | 0.76% PASA | **NO** (percentil 42) | INCONCLUSO | — (ubicacion no publicada) |
| FLAIR | 1.42% PASA | **SI** (percentil 1) | 0.62 MISS marg. | **SI** (pico agudo s=1.045) |

**Conclusiones para JAAS:**
1. La exactitud de FRECUENCIAS modales bajo Schroeder se sostiene en FLAIR (geometria arbitraria
   reconstruida), validada contra su linea base nula. MeshRIR no discrimina via M1 (limitacion del
   dataset: densidad modal alta, pocos picos resolubles), pero confirma el nucleo FEM (0.38% O(h²)).
2. M4 (forma espacial completa) es el metric discriminante; queda marginalmente corto (0.62 vs 0.7)
   por un sesgo de malla ~4.5% (que M4 mismo detecta) + la coloracion de fuente residual.
3. Honestidad del pipeline: ningun numero fabricado (auditor); los INCONCLUSO/MISS se reportan como
   tales; las metricas se validan contra su nula.

4. M3 (RT60 por banda) NO es evaluable como metric modal: RT es de campo difuso, mal definido bajo
   Schroeder (dato: n_confiable 1-5 de 200 en bandas bajas), y ademas requiere materiales que los
   datasets no traen. Diferido a medicion propia con materiales documentados. Que RT sea inestable
   ahi confirma la premisa del proyecto.

**Pendiente:** M3 sobre recinto propio con materiales. Refinar malla/reconstruccion FLAIR para testear
si cierra el sesgo ~4.5% de M4. Segundo pase con reactancia auto ON (hipotesis del protocolo §10).
