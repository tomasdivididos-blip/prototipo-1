# Protocolo de validación — fidelidad modal sim vs RIR medida (para JAAS)

**Estado: CONGELADO 2026-09-04** (umbrales M1-M4 §5 confirmados por el usuario). Cualquier cambio posterior va en §10 con fecha y motivo.

> **Pre-registro.** Este documento se CONGELA antes de correr ninguna comparación. Las
> métricas y umbrales se fijan acá, no después de ver los resultados. Cualquier ajuste
> posterior se registra con fecha y motivo al final. Es el mecanismo anti-sesgo del lado
> empírico (el otro es el `auditor-fisico`, lado código).

## 0. Pregunta y falsabilidad

**Pregunta:** ¿La simulación predice la respuesta modal (por debajo de f_Schroeder) de
recintos reales, con exactitud, en geometría arbitraria, SIN tunear parámetros al
resultado?

**Qué la refutaría** (criterio de fracaso, definido antes): si en la mayoría de los
recintos el error de frecuencia modal supera el umbral, o el RT60 por banda cae fuera de
tolerancia, con las α tomadas del catálogo por descripción de material (sin ajuste fino),
entonces la afirmación de "exactitud en rango modal" NO se sostiene y hay que reportarlo
así en JAAS. El objetivo NO es que dé bien; es medir cuán bien da y por qué.

## 1. Regla de oro anti-sesgo (congelada)

- Las α salen del **catálogo por descripción de material** (hormigón, durlock, vidrio...).
  **Nada se tunea para mejorar el match.** Si en algún recinto se ajusta algo (una α, una
  dimensión), se declara explícitamente en la tabla de resultados como "ajustado".
- La geometría sale del `.obj`/plano tal cual. Las posiciones fuente/mic son las medidas.
- Se corre TODO el set de recintos disponibles; no se descartan los que dan mal. Un recinto
  se excluye solo por un problema de DATO (RIR corrupta, geometría desconocida), documentado.

## 2. Datos requeridos por recinto

1. Geometría interior exacta (`.obj` o plano acotado). cm importan (fₙ ∝ 1/L).
2. Posición de la fuente (XYZ del centro acústico).
3. Posiciones de los receptores (XYZ de cada mic).
4. RIRs (`.wav`) + fs + método (sweep/MLS) + relativo o calibrado en nivel.
5. Descripción de superficies (material/construcción por cara). Sin impedancia.
6. Condiciones: vacío/amueblado (y qué/dónde), temperatura (→ c), HVAC apagado.

Fuentes: (a) datasets públicos con geometría+posiciones+RIR; (b) mediciones/planos propios.

## 3. Banda de análisis

Por recinto, banda modal = [f_min, f_S], con:
- f_S = frecuencia de Schroeder que computa el propio software (punto fijo desde V y RT).
- f_min = primer modo axial teórico (c/2·L_max) menos un margen, o el piso útil de la RIR
  (donde la SNR de la medición sigue siendo válida), lo que sea mayor.

## 4. Pipeline de comparación (usa `rir.py`, ya existente)

1. RIR → FRF: `rir.rir_to_frf` (documentar ventaneo).
2. RT60 por banda: `rir.rt60_per_band` (EDC de Schroeder, `rt_from_ir`).
3. Picos modales medidos: `rir.find_modal_peaks` sobre la FRF en la banda modal.
4. Simulación: mismo recinto (geometría real), mismas posiciones fuente/mic, α de catálogo,
   modelo de amortiguamiento = perturbación de frontera (default). Se extrae FRF simulada,
   fₙ (efectivas, con corrimiento de Capa 0), RT60ₙ.
5. Emparejamiento de modos medidos ↔ predichos: por cercanía en frecuencia dentro de una
   ventana de tolerancia (registrar el algoritmo; si hay ambigüedad, Hungarian por |Δf|).

## 5. Métricas y umbrales (CONGELADOS 2026-09-04, confirmados por el usuario)

**Primarias (criterio de PASA/FALLA):**

| # | Métrica | Definición | Umbral (congelado) |
|---|---|---|---|
| M1 | Error de frecuencia modal | mediana de \|f_pred − f_med\|/f_med sobre modos apareados | ≤ **3 %** |
| M2 | Cobertura modal | % de modos medidos apareados a un predicho dentro de tol | ≥ **80 %** |
| M3 | RT60 por banda | \|RT_sim − RT_med\| por banda de octava/tercio en la banda modal | ±**5 %** o ±**0.05 s** (el mayor) |
| M4 | Nivel/forma espacial | correlación del **promedio espacial** de la FRF (sim vs med) sobre las posiciones | ≥ **0.7** |

**Secundarias (se reportan, NO deciden PASA/FALLA):**

- Correlación punto-a-punto de la FRF. **Por física es baja bajo Schroeder** (solapamiento
  modal M>1); un valor bajo NO es fracaso. Se reporta para honestidad, no como criterio.
- Varianza espacial del nivel (sim vs med): mide si la sim reproduce la no-uniformidad
  modal del campo (lo distintivo del rango modal).

## 6. Criterio de éxito global (para JAAS)

Definir con el usuario. Propuesta: en **≥ N recintos** (fijar N según cuántos consigamos),
M1 y M3 dentro de umbral, con α de catálogo y sin tuneo. Se reporta el resultado COMPLETO
(incluidos los recintos que fallan y la hipótesis del por qué), no una selección.

## 7. Registro de resultados

Una tabla por recinto: dataset/fuente, V, f_S, nº modos comparados, M1, M2, M3, M4,
"ajustado sí/no", y una nota de interpretación. Más un resumen agregado. Se guarda en
`validation_results.md` (o CSV) generado por el pipeline, no a mano.

## 8. Interpretación (quién y cómo)

El asistente principal ayuda a interpretar, pero como es co-autor su lectura se contrasta
con: (a) los umbrales de acá (fijados antes), (b) el `auditor-fisico` (que confirma que el
pipeline `rir.py` y el núcleo no tienen un bug que fabrique un match o un fallo). Ninguna
métrica se cambia después de ver los números sin dejarlo registrado en §10.

## 9. Estado (recintos y datos)

_(se completa a medida que entran datos)_
- [ ] Datasets públicos identificados (geometría + posiciones + RIR).
- [ ] Mediciones/planos propios.

## 10. Cambios al protocolo posteriores al congelamiento

- **2026-09-04 — reactancia auto del material APAGADA por default (hallazgo M1 de
  `REVIEW-FISICO.md`).** La auditoría independiente confirmó (reproducido) que el
  corrimiento de fₙ por la Z auto derivada del α (Miki extrapolado, modelo no medido)
  sesga las fₙ hasta ~9% en salas muy tratadas. Decisión del usuario: se apaga por default
  (`_auto_material_reactance=False`, toggle opt-in en el panel). **Consecuencia para la
  validación:** la comparación primaria fₙ_sim vs fₙ_medida se corre con la reactancia auto
  OFF (β real, amortiguamiento exacto). La reactancia queda como HIPÓTESIS a testear: se
  puede correr un segundo pase con el toggle ON y medir si M1/M4 mejoran o empeoran vs las
  RIRs. Las construcciones explícitas (perforado/membrana/poroso+cámara) NO se ven
  afectadas: son modelos elegidos, no extrapolados, y aportan reactancia siempre.
- Pendiente antes de correr validación (mismo audit): C1 (acotar la FRF a la banda válida)
  y M2 (truncar el RT por piso de ruido en `rir.py`). Ver `REVIEW-FISICO.md`.
