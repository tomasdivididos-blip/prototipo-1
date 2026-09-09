# Plan: respuesta compuesta única (SBIR + FRF + CABS coherentes) — grupo A

> Estado: **PLANIFICADO, sin implementar** (8 Sep 2026). No escribir código hasta OK
> explícito. Cubre los ítems i, ii, vii del backlog de la charla ([[backlog-charla-sep]])
> más el **bug confirmado del delay 2×**. El ítem iii (pesos a 100) es grupo C aparte.

---

## 0. Objetivo y motivación

Motivación del usuario: **cada parámetro tiene que tener en cuenta a todos los demás.**
- El SBIR debe ver la respuesta modal.
- La FRF debe ver el SBIR y la respuesta modal.
- El DBA/CABS debe ver el SBIR y la transferencia modal.

Traducción de ingeniería: hoy hay **tres cómputos distintos y parcialmente solapados** de
"la respuesta en el receptor". El objetivo es una **única respuesta compuesta canónica**
(modal FEM debajo de f_S ⊕ imágenes SBIR arriba, crossfade en f_S) que alimente a los tres
diálogos y al optimizador de ubicación, todos mostrando **las mismas curvas** con el mismo
overlay de corregibilidad EQ.

## 1. Estado actual (lo que hay que unificar)

| Lugar | Función | Qué compone hoy | Qué le falta |
|---|---|---|---|
| **FRF** | `acoustic_panel._compute_frf` → `aa.run_fem_frf` | **Modal puro** (superposición de Green, c²). Calcula FoM + corregibilidad (`mm.eq_correctability`) sobre grilla | NO ve el SBIR |
| **SBIR** | `acoustic_panel._open_sbir` → `sbir.sbir_from_sources` + `sbir.modal_sbir_crossfade` | SBIR (directo + imágenes 1er orden) **+ modal híbrido** (normalizado al directo) | NO tiene overlay de corregibilidad |
| **CABS** | `_open_dba` / `dba_evaluate.evaluate_cabs` → `_config_metrics` | SBIR + modal sobre **puntos objetivo**, vs ideal LS | Pipeline propio, no comparte curva/overlay; criterio único (ver §4) |
| **Ubicación** | `location_opt` (`default_location_weights`, `LocationContext.from_modal`) | flat + espacial + SBIR + smoothness como **sub-scores separados** | Los combina con pesos, no como una FRF compuesta |

**Primitiva ya existente:** `sbir.modal_sbir_crossfade(freq, sbir_db, modal_db, f_s, transition_oct=0.5)`
(peso lineal en log₂f, ±0.5 oct). Es el núcleo de la composición; el plan la envuelve, no la
reescribe.

## 2. Decisión de fondo: una función canónica de respuesta compuesta

Crear en un módulo nuevo `composed_response.py` (núcleo, sin Qt, numpy+scipy, D0):

```
composed_response(sources, receiver(s), freq, *, modal_result, walls, f_s,
                  damping, ref="direct") -> ComposedResponse
```

- Devuelve la curva **modal ⊕ SBIR** (dB) en el/los receptor(es), más las curvas de
  componentes (modal sola, SBIR sola) para graficar, y la banda de validez.
- **Un solo receptor** → la curva que hoy dibuja cada diálogo.
- **Grilla de receptores** → alimenta `mm.eq_correctability` y el FoM (corregibilidad y
  varianza espacial necesitan grilla, no un punto).
- Reúsa `run_fem_frf` (modal), `sbir.sbir_from_sources` (imágenes) y `modal_sbir_crossfade`
  (mezcla). No duplica física.

### D1 — referencia común (0 dB): RESUELTA = **SPL absoluto (dBSPL)**

Decisión del usuario (8-9 Sep 2026): la curva única va en **SPL absoluto (dBSPL)**, NO relativo
al directo de campo libre. Razón física: es el nivel que graba un **micrófono calibrado**
(calibrador de sonómetro a 94/114 dBSPL, referencia del usuario 90 dBSPL) → es lo comparable
contra medición, que es el norte de la validación. Además la **FRF ya está en dBSPL**, así que
la FRF no cambia; el que se adapta es el SBIR.

**Implicación (lo que hay que implementar):**
- La FRF modal (`run_fem_frf`, con el factor c² de B5) ya es SPL absoluto → queda igual.
- El SBIR hoy es **relativo al directo de campo libre** (`20log10(|H|/|p_dir|)`, 0 dB = anecoico).
  Para llevarlo a absoluto hay que **sumarle el SPL absoluto del campo directo** en el receptor:
  $$L_\text{dir}(f) = L_\text{sens}(f) - 20\log_{10}(r) - 11\ \text{dB}$$
  con `L_sens` = sensibilidad de la fuente (dB @1W/1m, de CLF/FRD/TRF) y `r` = distancia
  fuente-receptor (ley inverso-cuadrado desde 1 m). Así SBIR_abs = SBIR_rel + L_dir.
- **Caveat honesto:** una fuente sin sensibilidad calibrada (monopolo con Q arbitrario, sin
  FRD/CLF/TRF) NO tiene nivel absoluto físico → en ese caso el absoluto queda referido a un Q=1
  nominal y hay que rotularlo como "nivel relativo a fuente nominal", no como dBSPL medible. El
  crossfade se hace entre dos curvas ya en la misma escala absoluta.
- Consistencia con el offset de calibración histórico (B5, ~101 dB / factor c²): el mismo
  `L_sens` y la misma referencia tienen que valer para FRF y para el directo del SBIR (si no,
  hay un escalón en f_S). Bench de continuidad en f_S obligatorio.

## 3. Fases (ítems i + ii)

**Fase 1 — núcleo `composed_response.py` + benches.**
- La función canónica (single + grilla), reference según D1.
- Benches: (a) sin SBIR (walls=[]) → reduce EXACTO a la FRF modal actual; (b) sin modos →
  reduce EXACTO al SBIR actual; (c) crossfade continuo en f_S (sin salto); (d) regresión
  contra las curvas que hoy dibujan `_open_sbir` y `_compute_frf`.

**Fase 2 — rutear los tres diálogos por el núcleo.**
- `_compute_frf`: la curva pasa a ser la compuesta (modal ⊕ SBIR). El FoM y la corregibilidad
  se computan sobre la compuesta en grilla (hoy son modal-solo).
- `_open_sbir`: ya es híbrido; ahora además dibuja el **overlay de corregibilidad** (extraer
  el helper de dibujo de `FRFDialog`, líneas ~1241/1307, a un módulo compartido).
- `_open_dba` / `evaluate_cabs`: usar la misma curva compuesta para el reporte real vs ideal.

**Fase 3 — Predicción usa la FRF compuesta (ítem ii).**
- `location_opt`: que el sub-score de respuesta se calcule sobre la **compuesta** (modal ⊕
  SBIR) en vez de FoM-modal y SBIR por separado. Mantener smoothness (propiedad del recinto).
  Revisar si el peso `sbir` se funde en `flat/espacial` de la compuesta (probablemente sí).

## 4. Discriminación por criterio DBA vs CABS (ítem vii) + fix del bug del delay

### El bug (confirmado)

- `dba_evaluate._make_checklist` usa `tau_ideal = L/c` con **L = dimensión completa del eje**;
  `dba.build_dba_sources` (naive) usa `delay = L/c`. Es el drive **DBA canónico** (Santillán/
  Celestinos: trasero retardado L/c e invertido, absorbe en la pared trasera). Físicamente OK.
- `cabs_optimize` tiene cota de delay `(0, 1.5·max(dims)/c)` (puede alcanzar L/c) pero **no se
  restringe a esa forma**: minimiza planitud/varianza espacial y converge a **~L/(2c)** →
  `_check_rear_drive` (tol_rel 0.35) lo rechaza. Duplicar a L/c hace pasar la evaluación.
- Raíz: **dos criterios distintos** (planitud listener-óptima vs drive DBA canónico). El 2× es
  referencia de distancia media-sala vs sala completa (intuición del usuario correcta).

### La solución (unifica el bug con el ítem vii)

Un **selector de criterio** en el panel CABS/DBA (botón/combo), y cada criterio define (a) qué
config es válida, (b) sobre qué **puntos objetivo** se evalúa, (c) cuál es el drive ideal:

- **DBA (subs adelante + atrás):** drive canónico, trasero retardado por la distancia
  **frente→trasero real** (no la dimensión completa si los subs están despegados de la pared)
  e invertido. `tau_ideal` pasa a ser distancia-entre-arrays/c, no `L/c` a secas.
- **CABS (puede ser solo atrás / manejado):** criterio distinto (control activo de la reflexión
  trasera; Celestinos & Nielsen). Puntos objetivo y validación propios.
- **Reconciliación optimizador↔evaluar:** o el optimizador se **restringe** al drive del
  criterio elegido (búsqueda con la forma del drive fija, solo amplitud/fase), o `evaluate`
  **acepta** el delay listener-óptimo cuando el criterio es "planitud". Ambas rutas quedan
  explícitas por criterio, así deja de haber el desacuerdo silencioso del 2×.

### D2 — RESUELTA: un selector de criterio gobierna optimizar Y evaluar

Decisión del usuario (9 Sep 2026): hoy el problema es que **no se puede elegir** optimizar por
DBA o por CABS, así que el optimizador hace una cosa y el evaluador otra. Solución: un **selector
de criterio (CABS | DBA)** único que gobierna **los dos caminos**:
- Elegís **DBA** → se optimiza con el criterio DBA y se evalúa con el criterio DBA.
- Elegís **CABS** → se optimiza con el criterio CABS y se evalúa con el criterio CABS.

El criterio define el drive ideal (y por lo tanto el `tau` esperado), los puntos objetivo y la
validación. Como optimizar y evaluar leen el MISMO criterio, concuerdan por construcción → el
bug del delay 2× desaparece (deja de haber "el optimizador puso L/(2c), evaluar quería L/c").
`cabs_optimize` deja de tener el delay como variable libre sin forma: queda atado al drive del
criterio (optimiza posición y amplitud/fase relativa dentro de esa forma).

**Detalle estético (item vii, bug reportado 9 Sep):** el cartel/checklist del `DBADialog` NO
muestra la **polaridad** como parámetro, aunque el cálculo SÍ la usa. Agregar la polaridad a la
tabla de parámetros mostrados (solo display, la física ya la contempla).

## 5. Métricas de éxito

- **Regresión exacta:** `composed_response` con walls=[] ≡ FRF modal actual; sin modos ≡ SBIR
  actual (bit a bit / ruido ARPACK).
- **Coherencia visual:** para una misma sala+fuentes+receptor, la curva compuesta que muestran
  FRF, SBIR y CABS es **la misma** (mismo eje, misma referencia, mismo f_S de crossfade).
- **Bug del delay cerrado:** optimizar y después evaluar da **PASA** sin tener que duplicar el
  delay a mano, en los mismos recintos donde hoy falla (caso testigo: 4 subs espejados en un
  eje). Bench `bench_cabs_criterion.py` que reproduzca el caso y verifique consistencia.
- **Corregibilidad en los tres:** el overlay C13/C21 aparece en SBIR y CABS, no solo en FRF.

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Costo: SBIR sobre grilla de receptores (para corregibilidad) multiplica el cómputo | La grilla del FoM ya existe (`mm.default_receiver_grid`); SBIR por punto es barato (imágenes analíticas). Cachear la base modal |
| Referencia mal elegida rompe la lectura de niveles | D1 explícita; regresión contra las curvas actuales |
| Cambiar `tau_ideal` regresiona el cross-check de Santillán (`bench_dba_crosscheck` 6/6) | El cross-check usa subs en las paredes → distancia-entre-arrays ≈ L; debe seguir verde. Correrlo como gate |
| Tocar `location_opt` cambia los scores de ubicación históricos | Bench de regresión de `bench_location_opt`; documentar el cambio de semántica |

## 7. Orden sugerido de ejecución

1. Fase 1 (núcleo + benches de reducción) — es la base, sin riesgo de UI.
2. Fix del delay + criterio (§4) — cierra el bug que ya te molesta, con caso testigo.
3. Fase 2 (rutear diálogos + overlay de corregibilidad en SBIR/CABS).
4. Fase 3 (Predicción sobre la compuesta).

## 8. Decisiones (estado al 9 Sep 2026)

- **D1 — RESUELTA: SPL absoluto (dBSPL).** Ver §2. El SBIR se lleva a absoluto sumando el
  directo; la FRF queda igual. Caveat: fuentes sin sensibilidad calibrada → "nivel nominal".
- **D2 — RESUELTA: un selector de criterio (CABS | DBA) gobierna optimizar Y evaluar.** Ver §4.
  El criterio elegido fija el drive/tau/puntos objetivo para los dos caminos → concuerdan por
  construcción y el bug del delay 2× se cierra. Más: agregar la polaridad al display del `DBADialog`
  (hoy no la muestra aunque el cálculo la usa; estético).
- **Corregibilidad en CABS — RESUELTA: solo capa visual.** CABS mantiene sus métricas propias
  (flat/espacial/decay); el overlay C13/C21 se dibuja encima como capa visual, no reemplaza las
  métricas del pipeline CABS.

## 9. Referencias

- Crossfade modal↔imágenes: `sbir.modal_sbir_crossfade`; pedido original del profesor en
  [[profesor-sbir-rt60]].
- Corregibilidad EQ (fase mínima/no-mínima, 6 niveles): `modal_metrics.eq_correctability`,
  C13/C21 en [[criterios-research]].
- Drive DBA canónico: Santillán JASA 2001; CABS: Celestinos & Nielsen (Forum Acusticum 2011,
  JAES 56). Motor: `dba.py`, `dba_evaluate.py`, `cabs_optimize.py`; ver [[source-model-dba]].
- Superposición modal forzada (c²): `acoustic_fem.frequency_response`, D5b.
