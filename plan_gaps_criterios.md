# Plan de implementación — gaps de cobertura de criterios

> Cierra los **6 gaps in-scope** identificados en `cobertura_criterios_en_soft.md` (la
> matriz criterio×código). Estado: **PLAN (no implementado)** — escrito 2026-06-21.
> Es la continuación natural de `plan_integracion_criterios_T8.md` (donde A33/A36/B27 ya
> están ✅). Punteros de código verificados sobre el repo.
>
> **Fases por esfuerzo/valor.** Los 3 de Fase 1 son métricas puras sobre datos que la app
> YA tiene (frecuencias modales / H) → baratos y sin riesgo. Fase 2 necesita RT por banda
> (existe en el flujo de materiales). Fase 3 es cara o está bloqueada por datos.

---

# FASE 1 — métricas puras, bajo esfuerzo (recomendado empezar acá)

## A6 · Rindel FSI ψ(25) — ✅ HECHO (2026-06-21) · esfuerzo BAJO · valor ALTO

> **Implementado:** `modal_fsi(freqs, n=25)` en `modal_metrics.py` (§8b). Validado en
> `bench_modal_metrics.py::test_fsi_rindel`: cubo ψ=3.71 (peor), BBC/Rindel ψ=1.43 (mejor) <
> Louden 1.52 < cubo. Falta solo el wiring al scorer (opción b) si se decide reemplazar la
> suavidad modal — por ahora es métrica disponible. Resto = registro histórico.

**Criterio:** `ψ(n) = (1/(n−1))·Σ(δᵢ/δ̄)²` sobre los intervalos de los primeros 25 modos.
Ideal `ψ=1`, mejor real ≈1.3, **evitar ψ>1.6**. `l/w` domina (Rindel 2021).

**Dónde:** función nueva en `modal_metrics.py` (al lado de `modal_overlap_crossover`):
```
def modal_fsi(freqs, n=25):
    f = np.sort(np.asarray(freqs, float))[:n]
    d = np.diff(f)                      # intervalos δᵢ
    dbar = d.mean()
    return float(np.mean((d / dbar) ** 2))   # ψ
```
Las `freqs` salen de `modal_result.freqs` (panel Acústica) o `FemLiteResult.freqs` (Predicción).

**Wiring (2 opciones, hacer la conservadora primero):**
- (a) **Mostrar** ψ como métrica nueva en el panel + en `Prediction` (un campo `fsi: float`).
- (b) Más adelante: **sub-score** `score_fsi` (target ψ∈[1.0,1.4]→100, ψ>1.6→0) y, si convence,
  reemplazar `score_uniformity` (el doc proponía exactamente esto). NO reemplazar de una.

**Validación:** bench nuevo / extender `bench_modal_metrics.py`: cubo → ψ alto (malo);
Bolt/Louden/Rindel → ψ≈1.2-1.4. Confirmar que `l/w` mueve ψ más que `w/h`.

**Caveat:** ψ pide ≥25 modos; en salas muy chicas puede haber menos en la banda válida →
usar `n=min(25, len(freqs))` y avisar si n<~15 (poco robusto).

## A3 · Bonello completo (densidad monótona) — ✅ HECHO (2026-06-21) · esfuerzo BAJO

> **Implementado:** chequeo no-decreciente en `prediction.py` (bloque Bonello) + campos
> `bonello_monotonic: bool` y `bonello_score: float` en `FemLiteResult`. Validado vía
> `predict()`: ratios buenos → monotonic=True/100%; **cubo → False/40%**. Expuesto como
> referencia (no scoreado aún, igual que `bonello_ok_bands`). Resto = registro histórico.

**Criterio:** la cantidad de modos por **⅓ de octava** debe ser **no-decreciente** al subir de
banda (horizontal permitido), y ningún modo coincidente salvo banda con ≥5 modos.

**Estado:** `prediction.py:481` ya computa `counts` por ⅓-oct y `bonello_ok_bands` (bandas con
≥5 modos) pero **solo como referencia, no se scorea**, y **falta la parte monótona**.

**Cambio:** en ese mismo bloque, agregar el chequeo no-decreciente sobre `counts` (la lista de
modos por banda ya está implícita en el loop) y exponer:
- `bonello_monotonic: bool` (o un `score_bonello` = fracción de transiciones no-decrecientes).
- Opcional: integrarlo a `score_uniformity` o dejarlo como flag/aviso.

**Validación:** sala con densidad que cae al subir → `bonello_monotonic=False`; sala bien
proporcionada → True. (El cubo debería fallar también acá.)

## C8 · Asimetría pico/nulo en FoM_flat — ✅ HECHO (2026-06-21) · esfuerzo BAJO

> **Implementado:** campo `FoM_flat_asym` en `FoMResult` + cálculo en
> `response_figures_of_merit` (RMS pesado, `asym_weight=3.0` default; picos pesan 3×).
> Validado en `bench_modal_metrics.py::test_fom_asymmetry`: pico +6 dB (asym=1.64) >
> nulo −6 dB (asym=0.61); `asym_weight=1` ⇒ asym==FoM_flat (reducción). `FoM_flat` original
> intacto (no rompe los tests). Resto = registro histórico.

**Criterio:** los **picos** se oyen más que los nulos → pesar más las desviaciones **positivas**
sobre la tendencia (plan §8.2). Ya hay **prototipo en `bench_location_opt.py`**.

**Dónde:** `modal_metrics.py` `response_figures_of_merit` (cálculo de `FoM_flat` = σ del |H|
suavizado en dB). Agregar una variante con peso asimétrico de `S_hat - L_mean` (positivos pesan
más).

**Cambio:** **NO reemplazar** `FoM_flat` (los tests de `bench_modal_metrics.py` asertan su
comportamiento exacto con H sintético). Agregar `FoM_flat_asym` (o un parámetro `asym_weight`),
tomando la fórmula del prototipo del bench.

**Validación:** H con un pico de +X dB debe scorear peor que H con un nulo de −X dB equivalente.

---

# FASE 2 — necesita RT por banda (existe en el flujo de materiales)

## D5 · Bass Ratio real — ✅ HECHO (2026-06-21) · esfuerzo MEDIO

> **Implementado:** `bass_ratio(rt60_bands)` en `face_materials.py` (`(RT125+RT250)/(RT500+RT1000)`,
> Beranek) + display en el panel (`_refresh_materials_summary`: "BR: X.XX (fría/cálida/boomy)").
> Validado: cálido→1.30, frío→0.62, banda faltante→nan, sala toda-alfombra→3.82 (boomy, correcto).
> `score_bass` (densidad) se mantiene SEPARADO. Resto = registro histórico.

**Criterio:** `BR = (RT125+RT250)/(RT500+RT1000)` (Beranek); calidez. Target ~1.1-1.45 (ata A24,
"bass rise"). Hoy `score_bass` mide **densidad de modos bajos**, que es OTRA cosa.

**Estado:** el RT60 **por banda** ya existe: `compute_sabine_rt60_per_face(V, groups, g2m)` →
`{banda: RT60}` (`face_materials.py:362`). El flujo de **Predicción** usa un `rt60_target` único
(no por banda) → BR encaja mejor en el panel **Acústica/materiales**, no en la predicción.

**Cambio:**
- `def bass_ratio(rt60_bands)` en `face_materials.py` (o `material_library.py`).
- Mostrarlo en el resumen de materiales del panel (al lado del RT60 medio).
- Opcional: un `score_warmth` comparando BR contra el target por uso (música ~1.2-1.45;
  voz ~1.0-1.1) — reemplaza/complementa `score_bass` como criterio de **calidez** (≠ soporte).

**Validación:** sala con materiales que absorben más en agudos → BR>1 (calidez alta); con bass
trap fuerte → BR<1. Comparar contra la curva A24.

**Caveat:** mantener `score_bass` (soporte modal de graves) como métrica SEPARADA — son cosas
distintas (abundancia de modos vs balance de reverberación). No fusionarlas.

---

# FASE 3 — caro o bloqueado

## C13/C21 · Diagnóstico de corregibilidad EQ (fase mín/no-mín) — 🔨 EN CURSO · esfuerzo ALTO

**Criterio:** clasificar regiones de la respuesta de sala en **fase mínima** (corregibles con EQ)
vs **NO mínima** (nulos SBIR/modales → exigen acústica). Es lo que decide qué delegar al DSP.

### Método elegido (2026-06-22): consistencia espacial + fase mínima estructural (SIN cepstrum)
El usuario descartó el excess-phase cepstral (frágil: `log(~0)` en nulos) y pidió "como la consistencia
espacial pero teniendo en cuenta la fase mínima sin el error numérico". Solución diseñada:
- **Envolvente sin cancelación** como referencia min-phase: `H_env = Σ|término modal|` (cada modo en
  MAGNITUD) vs `H_real = |Σ término|`. Por desigualdad triangular `cancel_depth = 20log10(H_env/H_real)
  ≥ 0` mide la **cancelación destructiva** (nulos por interferencia entre modos). Construida de los
  propios modos (φₙ, ξₙ, residuos) → cero cepstrum. (`forced_response_with_envelope` en `modal_metrics.py`.)
- **Spread espacial** sobre la grilla de receptores = parte posicional (captura SBIR, que la cancelación
  modal no ve). No corregible si `cancel_depth` profundo **o** `spread` alto **o** el EQ necesitaría
  boost > headroom.

### Plan de rigor (6 niveles, el usuario quiere TODOS; orden por DEPENDENCIA, no por valor marginal)
1. **✅ HECHO (2026-06-22) — cerrar el loop.** `eq_correctability(H, f, H_env)` en `modal_metrics.py`:
   simula un **EQ global de fase mínima** (invierte la media espacial, con `max_boost_db`), lo aplica
   y MIDE: `improvement_flat` (lo que el EQ gana) + `fom_espacial` (cota IRREDUCIBLE — el EQ global es
   ganancia común → varianza espacial **invariante**, probado a 3.5e-15). `bench_eq_correctability.py`:
   7 oráculos OK (modo aislado→cancel 0; cancelación→11.7 dB @ entre modos; posicional→spread alto +
   EQ no ayuda; invariancia; loop cerrado FoM_flat 1.91→0.25; mixto; end-to-end FEM 5x4x3 → 5% corregible).
2. **✅ HECHO (2026-06-22) — convergencia + banda válida.** `bench_eq_convergence.py` corre el FEM
   5x4x3 a npm=2/3/4. **Encontró 2 problemas reales y se mitigaron:**
   - **P1 (malla):** `cancel_depth` SUBE al refinar (5.33→6.62→6.91 dB) — la malla gruesa "redondea"
     los nodos modales → subestima las cancelaciones → la sala **parece más corregible de lo que es**
     (confirma el riesgo D3: el método vive de signos de φₙ cerca de nodos). **Mitigación:**
     `eq_diagnosis_mesh_ok(h_max, f_band, ppw=15)` exige más resolución que el solver (ppw~6); marca
     npm=2 insuficiente, npm≥3 OK. El caller debe validar antes de diagnosticar.
   - **P2 (diseño):** el flag binario `correctable` era frágil cerca del umbral (frac 0.147/0.017/0.003
     parecía divergir aunque la física convergía). **Mitigación:** reemplazado por **grado continuo**
     `correctability∈[0,1]` (rampas suaves `_ramp_down` con banda `uncertainty_db`) + `verdict` 3-estados.
     El grado converge: RMS npm3↔npm4 = **0.026** (vs binario que saltaba). Escalares robustos
     `improvement_flat`≈3.5 dB y `fom_espacial`≈4.3 dB estables en las 3 mallas.
3. **✅ MÉTODO HECHO (2026-06-22) — ceros RHP exactos** (`modal_minphase_zeros` en `modal_metrics.py`).
   Fase mínima EXACTA: `np.roots` del numerador modal `N(s)=Σrₙ·Π_{k≠n}(s²+2ξₖωₖs+ωₖ²)`, **normalizado
   por ω_ref** (sin esto los coef escalan ~ω^(2M)~10^100 y `np.roots` da basura). Ceros con Re>0 = no-mínima.
   Oráculos O8/O9/O11 en `bench_eq_correctability.py`. **HALLAZGO (reproduce teoría):**
   - Driving-point (residuos `φ_s²≥0`, mismo signo) → **siempre min-phase** (pasividad). 2 modos → siempre
     min-phase. No-minimidad recién con ≥3 modos y residuos de signo mezclado (receptor/fuente en lados
     opuestos de nodos).
   - **El proxy `cancel_depth` SOBRE-marca:** un nulo profundo de 2 modos mismo signo da `cancel_depth=11 dB`
     (parece no-corregible) pero es **min-phase / corregible** (`n_rhp=0`). El proxy confunde antiresonancia
     min-phase con cancelación genuina. **Consecuencia:** `cancel_depth` es conservador (marca de más); el
     lado seguro (recomienda acústica de más, nunca EQ que no funciona), pero no exacto.
   **DECISIÓN (2026-06-22): opción (c), validada con dato.** Cuantifiqué el sobre-marcado en la shoebox
   real (npm=3, 40 modos, 36 receptores): **0%** — los 36 receptores son genuinamente no-mínima (ceros RHP)
   Y el proxy los marca a todos → **proxy y exacto coinciden 100% en salas reales**. El sobre-marcado de O8
   era artefacto de pocos modos/mismo-signo (driving-point), irrelevante en la práctica. Conclusiones:
   (1) reemplazar el proxy por el exacto NO cambiaría nada → no vale el costo; (2) como TODA RTF real es
   no-mínima, el flag binario min/no-mín no discrimina — lo que importa es **cuánto/dónde** (`cancel_depth`)
   y la **variabilidad espacial** (`spread`), que es C21, lo que el grado ya captura. **Resultado:** el grado
   queda con el proxy (validado); `modal_minphase_zeros` queda como **diagnóstico exacto disponible** (confirma
   teoría + detecta el caso raro min-phase de salas muy amortiguadas/pocos modos). Nada que cambiar en el grado.
4. **✅ HECHO (2026-06-22) — ξ de A36 + sensibilidad** (`bench_eq_xi_sensitivity.py`). A36 (ξ per-modo
   per-cara) se enchufa como array `damping` (ya soportado por `_modal_terms`). **Resultado tranquilizador:**
   las escalares robustas son casi insensibles a ξ — `improvement_flat` span **0.00 dB**, `fom_espacial`
   span **0.24 dB** bajo ±40% de incertidumbre en ξ; forma (uniforme vs per-modo) mueve 0.11 dB. **La
   incertidumbre irreducible de D5b (sin Z(ω)) NO compromete el diagnóstico:** `improvement_flat`/`fom_espacial`
   dependen de la geometría modal (φₙ, posiciones), no del damping (ξ afecta la profundidad de picos, pero el
   suavizado en energía 1/3-oct + el promedio espacial lo lavan). El grado por-frecuencia es algo más sensible
   (indicador blando), los escalares de cabecera son sólidos.
5. **✅ HECHO (2026-06-22) — separar fuente/sala + peor caso L+R** (`bench_eq_source_room.py`). Nuevo
   parámetro `flat_source` en `_modal_terms`/`forced_response_with_envelope`: con Q plano da la transferencia
   de SALA SOLA (sin la fase de fuente). **Demostrado:** (1) la sala-sola es **idéntica** con/sin polaridad
   invertida (la fase de fuente no contamina el diagnóstico de sala — un delay/polaridad es all-pass de la
   FUENTE, corregible desde el drive); (2) la interferencia L+R en contrafase **duplica** `fom_espacial`
   (4.90→11.60) pero es problema de SETUP, distinguible; (3) peor caso sobre {L, R, L+R} = L+R contrafase
   (one-toothed comb de Toole). Para una fuente sola el delay es invariante (todo es magnitud); la fase de
   fuente solo importa en la **interferencia entre canales**.
6. **✅ PARCIAL (2026-06-22) — validación externa + umbrales.** 
   - **6a HECHO** (`bench_eq_multisub.py`): el diagnóstico **reproduce Welti & Devantier 2003** — multi-sub
     midwall baja `fom_espacial` (5.57 dB 1-sub-esquina → 4.0-4.6 multi-sub). Validación contra resultado
     publicado, sin medición propia. (Que 4 salga ≈ 2 es geometría-dependiente, consistente con que Welti
     dice que la config óptima es sala-dependiente; la tendencia multi<single es robusta.)
   - **6b HECHO** (docstring de `eq_correctability`): umbrales anclados a audibilidad — spread ~3 dB
     (variación seat-to-seat perceptible, Welti/Toole), cancel ~6 dB (dips audibles, Toole cap 4/19),
     uncertainty 2 dB (orden de la incertidumbre del modelo). Ajustables.
   - **6c BLOQUEADO (como D5b/C9):** validación CUANTITATIVA contra respuesta medida real con EQ aplicado
     requiere datos que no están en el corpus. Queda como limitación documentada. Anclaje fino de umbrales
     a curvas de audibilidad (Olive/Toole cap 19) requiere subir esos datos a `referencias/`.

### UI/overlay — HECHA (2026-06-22), falta test visual humano
`acoustic_panel.FRFDialog` muestra el diagnóstico: `_compute_frf` computa `eq_correctability` sobre la
**sub-banda confiable** (ppw≥15 vía `f_eq_max = c/(15·h_max)`; más angosta que la banda válida del FoM ppw≥6 —
npm=3→≤69 Hz, npm=4→≤91 Hz; si la malla es muy gruesa se omite con aviso). El `FRFDialog` (params nuevos `eqc`,
`eqc_band`) **sombrea en rojo** las zonas no-ecualizables (`verdict==0`) y **amarillo** las inciertas
(`verdict==1`) con `axvspan` (helper `_contiguous_runs`), + label con `improvement_flat`/`fom_espacial` y la
banda + aviso "subí npm" si la banda del diagnóstico < la del FoM. Verificado headless (npm=3 y 4). **FALTA:
test visual humano** (junto a T4/T6/T8/T9 del batch v2.13) + integrar al MANUAL al cerrar el batch.

### Registro histórico del plan original (excess-phase cepstral — DESCARTADO como método primario)

**Dónde:** diagnóstico nuevo sobre el `H(f)` complejo de un receptor (ya disponible de
`compute_forced_response`). `frd.minimum_phase(freq, spl_db)` **ya existe** (computa la fase
mínima a partir de la magnitud) → se puede reusar:
```
phi_actual  = np.unwrap(np.angle(H))
phi_minphase = minimum_phase(f, 20*log10(|H|))   # referencia min-fase
excess = phi_actual - phi_minphase               # exceso de fase
# regiones con |excess| grande / saltos = NO mínima (no ecualizable)
```

**Cambio:** una función `eq_correctability(f, H)` que devuelva, por frecuencia, un flag
mín/no-mín (o el exceso de fase), y un overlay en el plot de respuesta del panel marcando las
zonas "no ecualizables" (típicamente los nulos profundos por SBIR).

**Validación:** un nulo SBIR profundo debe salir NO-mínima; un pico modal suave, mínima.

**Caveat:** la fase mínima por cepstrum es sensible a la resolución y a los nulos profundos
(log de ~0). Requiere cuidado numérico. Es la de mayor esfuerzo del backlog.

## C9 · Umbral perceptual de Fazenda — ✅ HECHO (2026-06-21, desbloqueado)

> **Desbloqueado:** el usuario cargó el paper `Fazenda, Stephenson & Goldberg (2015)...` a
> `referencias/`. **Implementado:** `fazenda_modal_threshold(f)` en `modal_metrics.py` (§8c) —
> curva de umbral de decaimiento T60_thr(f) leída de la Fig. 4 (estímulos artificiales/absolutos):
> `0.90 s @32 Hz · 0.30 s @63 Hz (rodilla) · 0.20 @100 · 0.17 @200`, interp en log-f, clamp fuera
> de [32,200]. Un modo colorea si `T60_modo > thr(f)`.
> **Wiring:** campo `n_audible_fazenda` en `FemLiteResult` (`prediction.py`) + **`_score_modal_q`
> ahora usa Fazenda** (el Q>30 fijo se conserva como `n_audible_modes` de referencia).
> Validado en `bench_modal_metrics.py::test_fazenda_threshold`.
>
> **DOS CURVAS + selección por programa (RESUELTO 2026-06-21).** `fazenda_modal_threshold(f,
> stimulus)` expone ambas: **"artificial"** (sine bursts, umbral absoluto/sin enmascaramiento =
> PEOR CASO, más estricto) y **"music"** (muestras musicales, con enmascaramiento = ESCUCHA REAL,
> más permisivo). Fig. 4 vs Fig. 5: @63 Hz 0.30 vs 0.51 s; @100 Hz 0.20 vs 0.37 s. Campos
> `n_audible_fazenda` (art) y `n_audible_fazenda_music` (mus) en `FemLiteResult`.
>
> **Wiring resuelto sin toggle manual** (idea del usuario): la curva la elige el **programa** de la
> sala — `_fazenda_stimulus_for(program)`: música/cine → "music", voz → "artificial".
> `_score_modal_q(fem, stimulus)` usa la curva correspondiente. Resultado: sala de **música** →
> score_modal_q ≈ **48** (realista, masking); sala de **voz** → ≈ **10** (peor caso, conservador).
> El score ya no es catastrófico uniforme: se **calibra por uso**, automáticamente. Validado en
> `bench_modal_metrics.py::test_fazenda_threshold` (ambas curvas) + `predict()` (selección por uso).
> El `Q>30` queda como `n_audible_modes` de referencia. Resto = registro histórico.

**Criterio:** un modo es audible según su **decaimiento** (τ_e) contra un **umbral perceptual
dependiente de f y nivel** (Fazenda, Stephenson & Goldberg, JASA 137(3), 2015). Hoy la app usa
un **Q>30 FIJO** (`prediction.py:537-544`) como proxy crudo.

**Bloqueo:** **no tenemos los valores de la curva umbral** (el paper de Fazenda NO está en el
corpus `referencias/`). Sin esos datos no se puede implementar fielmente.

**Opciones:**
- (a) **Interim sin el paper:** reemplazar el `Q>30` fijo por un **umbral de Q dependiente de la
  frecuencia** (los modos graves toleran menos Q antes de colorear) — mejora sobre el fijo, no
  es Fazenda. Bajo esfuerzo.
- (b) Conseguir el paper de Fazenda 2015 → extraer la curva → implementar fiel. **Requiere acción
  del usuario** (subir el PDF a `referencias/`).

**Recomendación:** dejar C9 para el final; hacer (a) solo si se quiere un quick-win, o esperar
el paper para (b).

---

## Orden sugerido y dependencias

1. **Fase 1 entera** (A6 → A3 → C8): independientes, baratos, sin riesgo, sobre datos existentes.
2. **D5** (Bass Ratio) cuando se quiera cerrar la calidez correctamente.
3. **C13/C21** si se quiere el diagnóstico EQ (es el feature más grande).
4. **C9** al final / cuando aparezca el paper de Fazenda.

> Menores no incluidos arriba (ver `cobertura_criterios_en_soft.md`): A29 (flag pressure zone),
> A34 (tolerancias EBU + doble-pendiente), B19 (aviso posición del oyente), B7/B29/B30
> (constraints de layout). Son one-liners/avisos; se pueden colgar de Fase 1 si interesan.
