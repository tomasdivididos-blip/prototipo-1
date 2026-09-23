# Contexto vivo para el auditor-fisico

> Este archivo lo actualiza el asistente principal en CADA recap, para que el
> `auditor-fisico` entre con el estado al día. **Advertencia de método (no negociable):**
> TODO lo de acá son AFIRMACIONES DEL AUTOR (co-autor sesgado), no evidencia. Verificá
> cada cosa contra la fuente física, un oráculo, o una cuenta propia. Que este archivo
> diga "resuelto/PASA" no prueba nada; es un puntero a qué mirar.

**Última actualización:** 2026-09-23 (v2.50: el amplificador en la admitancia del sub, estado de bornes; + v2.49 + v2.48).

## v2.50 — el amplificador en la admitancia del cono: estado eléctrico de los bornes (23 Sep 2026, NÚCLEO NUEVO EN ALCANCE — VERIFICAR)

Refina v2.49: el Q de la caja (que fija β_cono y el Δξ_n) ahora depende del estado de bornes en vez de suponer
amp ideal. Cierra el punto (1) de la auditoría de C2a ("para bornes abiertos habría que usar Q_mc; NO
implementado"). Todo son AFIRMACIONES del autor, auditá.

**Refs de auditoría:** modelo electro-mecánico y efecto de la resistencia de salida del ampli sobre Q_es =
**Small, JAES 20 (1972)** ("Direct-Radiator Loudspeaker System Analysis" y "Closed-Box Loudspeaker Systems");
**Beranek & Mellow, _Sound Fields and Transducers_, cap. 6** (impedancia motional (Bl)²/(R_E+R_g) reflejada a
lo mecánico). Contexto del sub que controla el campo/decaimiento modal (por qué esto importa): **Hill & Hawksford,
AES 129 (2010), Convention Paper 8313** (CSA, corrección de modos); **Backman, AES 137 (2014), CP 9145**
(condiciones de frontera del sub fuertemente dependientes de f); **JAES 64(5), May 2016** (low-freq calibration
+ modelado de diafragma). Los tres YA en `referencias/`.

- **Física `driver.box_terminal_Q(fc, fs, Qms, Qes, state, DF)`:** trabaja en espacio de Q. Equivalencia a
  auditar: es el término motional (Bl)²/(R_E+iωL_E+R_g) reescrito como Q_ec(DF)=Q_es(fc/fs)(1+1/DF), con
  DF=R_E/R_g. **Aproximación declarada:** se DESPRECIA ωL_E (inductancia de bobina) → válido abajo de Schroeder
  (ωL_E≪R_E) pero NO arriba; alcance acordado = solo el waterfall < f_S, así que no toca la FRF de banda ancha.
  A auditar: (1) ¿1/Qtc=1/Qmc+1/Qec es el combinado correcto (pérdidas en paralelo) y Q_mc=Qms·(fc/fs),
  Q_ec=Qes·(fc/fs) el escalado de caja sellada? (2) límite "short" (DF→∞) == sealed_box_params EXACTO (bench
  lo mide <1e-9 → sin regresión); "open" (DF→0) = Q_mc. (3) monotonía Q(DF) decreciente. bench C3 7/7.
- **`driver.qms_qes_from_qts`:** completa (Qms,Qes) desde Qts si falta uno; **lanza ValueError sin ninguno**
  (decisión de norte: no repartir amortiguamiento sin dato). A auditar: la identidad 1/Qts=1/Qms+1/Qes y que el
  fallback en el wiring caiga a "short" (que solo usa Qts) y avise, en vez de asumir un Qms típico.
- **Wiring `acoustic_panel._cone_delta_xi`:** Q_eff por sub según ts_amp_state; β=cone_specific_admittance con
  ese Q. A auditar: (1) el knob físico es Re(β(f_n)): open (Q alto) da β MÁS alto y MÁS angosto en fc → más
  amortiguamiento SOLO cerca de fc, menos en las colas (correcto para un resonador poco amortiguado, pero puede
  sorprender: "abiertos" no siempre amortigua más un modo lejos de fc). (2) sigue siendo SOLO Re(β) (Im(β)/shift
  de fₙ no se aplica, igual que v2.49). (3) el estado "con subs (drive)" del waterfall sigue sin carga de cono
  (modelo parcial declarado, v2.49).
- **UI/persistencia:** Sd ahora se carga desde la GUI (antes ts_sd solo se copiaba al duplicar → la carga del
  cono era inalcanzable sin editar el .room a mano). ts_qms/ts_qes/ts_amp_state/ts_df en OmniSource + dict "ts"
  del .room (aditivo, loader con defaults históricos). Round-trip verificado headless; default = "short"/None.
  **Test visual PASÓ (23 Sep 2026, T1-T8):** UI/enable-disable/persistencia/waterfall verificados por el usuario.
  Esto valida el WIRING/UI, NO la física (el auditor debe seguir verificando box_terminal_Q y el knob Re(β) contra
  la fuente y el QEP; la etiqueta "VERIFICAR" sigue vigente para el núcleo).

## v2.49 — C2: el cono del sub como parche de impedancia → Δξ_n modal (23 Sep 2026, NÚCLEO NUEVO EN ALCANCE — VERIFICAR)

Física NUEVA (la versión rigurosa del punto 3). AFIRMACIONES del autor, auditá contra la fuente.

**Refs de auditoría:** Z_mech del driver = **Small, JAES 20 (1972)**; **Beranek & Mellow, _Sound Fields and
Transducers_, cap. 6**. Perturbación de frontera = **Morse & Ingard 9.4.14**, **Kuttruff 3.34**. DSP del IR/
decaimiento (C1: IFFT de H, ventaneo, causalidad, leakage, CSD) = **Oppenheim & Schafer, _Discrete-Time
Signal Processing_** y **Pohlmann, _Principles of Digital Audio_** (ambos YA en `referencias/`). El hueco DSP
de v2.48 quedó cubierto.

- **C2a `driver.cone_specific_admittance`:** β_cono(f)=ρ₀c·Sd/Z_mech, Z_mech(ω)=Mms[ωc/Qtc+i(ω−ωc²/ω)].
  `moving_mass_from_ts`: Mms=1/((2πfs)²·Cms), Cms=Vas/(ρ₀c²Sd²). A auditar: (1) ¿Z_mech de caja sellada con
  Q_tc TOTAL es la carga correcta para un sub CONECTADO al amplificador (bornes en corto, amortiguamiento
  eléctrico Bl²/Re incluido en Q_tc)? Para bornes abiertos habría que usar Q_mc (mecánico); NO implementado.
  (2) β adimensional, e^{−iωt} (Im Z>0 arriba de ωc → Im β<0); el consumidor de perturbación usa e^{+iωt} y
  ya conjuga para las paredes, pero C2b usa SOLO Re(β) (invariante al conj) para el amortiguamiento → el
  corrimiento de fₙ por Im(β) NO se aplica (secundario, declarado). (3) se ignora la resistencia de radiación
  del cono (2º orden). bench_cone_damping 7/7 (C2a).
- **C2b `face_materials.cone_xi_shift_per_mode`:** Δδ_n=(c/2)Re(β(f_n))·Sd·φ_n²(x_s), Δξ_n=Δδ_n/ω_n. El cono
  es un absorbedor INTERIOR (no de pared); la derivación (proyección modal de la admitancia puntual,
  (k_n²−k²)a_n=−iω ρ₀ Y φ_n²(x_s) a_n con Y=βSd/(ρ₀c)) da la MISMA forma que la perturbación de frontera. A
  auditar con dureza: (1) **1er orden para un absorbedor CONCENTRADO** — el acople inter-modal (off-diagonal)
  se desprecia; el bench mide <0.11% vs el QEP exacto (C_cono=Sd·e_j e_jᵀ en el nodo) hasta β=0.15, pero
  para β grande o modos casi-degenerados podría degradarse. (2) el oráculo pone el cono EXACTAMENTE en un
  nodo de la malla (para que C_cono sea rango-1 limpio); una posición arbitraria interpola φ vía el locator
  (mismo κ que la fuente) → el bench NO cubre el error de interpolación fuera de nodo. (3) φ_n²(x_s) usa el
  MISMO locator que el acople de fuente (validado). Aditividad ξ_total=ξ_pared+Δξ_cono a 1er orden. bench 10/10.
- **C2c (UI, `acoustic_panel`):** tercer estado del waterfall «con carga cono» = IR modal con ξ_walls+Δξ_cono.
  A auditar: (1) el estado «con subs (drive)» usa ξ_walls (sin la carga del cono) → es un modelo PARCIAL
  (mientras el sub suena, el cono TAMBIÉN carga); se muestra a propósito para AISLAR el efecto C2, la nota lo
  aclara. (2) damping puede ser escalar (0.03) o array por modo (_xi_per_mode); ξ_total=damping+Δξ_cono por
  broadcast. (3) requiere TS completos por sub; sin ellos no grafica el 3er estado (Control Ale los tiene en
  null → se usaron TS de prueba para el render). El núcleo de C1 (IR por IFFT, EDC, CSD) intacto.

## v2.48 — dominio del optimizador, parches y decaimiento con subs (22 Sep 2026, EN ALCANCE — VERIFICAR)

Tres cambios sobre `Control Ale.room` (recinto con techo a dos aguas = NO convexo). Auditá contra la
física, son AFIRMACIONES del autor.

**Referencias de auditoría (en `referencias/`, verificá cada afirmación contra la fuente):**
- Serie modal / Green del recinto y acople κₙ = φₙ(x_s): **Kuttruff, _Room Acoustics_** §3 (`Kuttruf - Room
  Acoustics.pdf`) y **Morse & Ingard, _Theoretical Acoustics_** cap. 9 (normal modes of rooms). El factor c²
  de `frequency_response` ya está validado en `bench_modal_vs_impedance.py`.
- Amortiguamiento modal ξₙ desde la frontera (y por qué el drive NO lo cambia): **Morse & Ingard 9.4.14**;
  **Kuttruff** §3 (δ del decaimiento modal). La versión C2 (impedancia del cono → Δξₙ) extendería ESTO.
- Decaimiento / EDC: **Schroeder, JASA 37 (1965)**; **ISO 3382-1** (T20/T30); el ajuste vive en `rir.py`.
- Waterfall (CSD): **Berman & Fincham, JAES 25 (1977)** (citado en `modal_decay.py`).
- Validez numérica del FEM (banda ≤ f_valid, dispersión/pollution de Helmholtz): **Ihlenburg, _Finite
  Element Analysis of Acoustic Scattering_** + `FEM for Acoustics.pdf`.
- HUECO conocido de referencias (no bloquea): falta un texto de **DSP** (p.ej. Oppenheim & Schafer,
  _Discrete-Time Signal Processing_) para citar con rigor el IR-por-IFFT, ventaneo, causalidad y leakage del
  waterfall; hoy eso se deriva de primeros principios + `_scrape.py` sobre el canon acústico.

- **Bug de la «recta −500» (A1/A2/A3), root cause reproducido:** en un techo no-convexo,
  `acoustic_mesh.points_inside_surface` (paridad de rayo 1-dir) da FALSOS «adentro» en una cáscara sobre
  las aguas (sobre el cielorraso inclinado). Ese test era el `inside_fn` del optimizador CABS; ahí el campo
  FEM está indefinido y `acoustic_fem._source_modal_coupling` devuelve 0 → `run_fem_frf` H=0 → recta a
  ≈−506 dB (FRF y SBIR comparten `run_fem_frf`). **A1:** `acoustic_panel._open_dba._inside_fn` ahora usa el
  dominio de los TETS (`locator.evaluate_many(ones)≠NaN`) cuando hay modos, el MISMO que evalúa la FRF; sin
  malla FEM cae al polígono. A auditar: (1) ¿el test de tets (KDTree de centroides + contención, con
  fallback K) coincide EXACTO con el dominio donde `_source_modal_coupling` da κ≠0? el bench asume que sí
  (cerró la cáscara a 0 falsos-positivos). (2) para un recinto CAD no-estanco (aula EASE) el locator de tets
  puede tener huecos propios → ¿el `inside_fn` se vuelve demasiado restrictivo y el optimizador se queda sin
  región? (conservador = seguro, pero verificar). **A2:** `_snap_source_into_domain` (marcha pos→centroide,
  primer punto en tets) reubica lo que el clamp al AABB dejó afuera; el nudge a centroide asume dominio
  estrellado respecto al centroide (cierto para caja/gable, NO garantizado para un recinto muy cóncavo o
  con columna). **A3:** `_decoupled_active_sources` (‖κ‖<1e-12) + guardas en `_compute_frf`/`_open_sbir`
  para no dibujar la recta. `bench_source_domain_guard.py` 18/18. NO toca el núcleo de `frequency_response`.

- **`modal_decay.py` (C1) — NÚCLEO NUEVO EN ALCANCE:** decaimiento del campo manejado en el receptor.
  `modal_impulse_response` = IFFT de `acoustic_fem.frequency_response` (la MISMA H validada, factor c²) →
  EDC de Schroeder (vía `rir.schroeder_curve`, `noise_trunc=False` para IR sintético) + `cumulative_spectral_
  decay` (waterfall CSD). A auditar con dureza: (1) **honestidad del claim** — se muestra como decaimiento
  del CAMPO TOTAL (el drive del array redistribuye energía modal), NO como cambio de ξₙ; verificar que el
  texto de UI (`DecayWaterfallDialog`) no sugiera que cambian los polos. (2) **consistencia IR↔FRF**:
  `bench_modal_decay.py` mide err 2e-16 (FFT(IR) vs H banda-limitada), pero la ventana de banda es REAL
  (fase cero) → introduce pre-ring que envuelve la cola: por eso el IR para RT usa `bandlimit=False` (banda
  completa causal). Verificar que ningún camino de RT use `bandlimit=True`. (3) **T30 de un modo aislado** =
  6.908/(ξ·ωₙ): medido 1.6% de error (bench). ¿Se sostiene con ξ por modo (array) y con `modal_freqs`
  efectivas de Capa 0? (4) el A/B «sin subs / con subs» clasifica por `source_type=='subwoofer'`: ¿es la
  partición correcta para todos los casos (p.ej. mains full-range que también bajan)? `bench_modal_decay.py`
  9/9. **C2 (rigurosa: impedancia del cono → Δξₙ) NO implementada.**

- **Reconciliación de parches (B):** `absorption_patch.reconcile_patch_signatures` re-ancla parches
  huérfanos por deriva de firma (mismo eje de normal + plano ≤0.75 m). Geométrico/IO, fuera del núcleo
  físico, PERO afecta qué α entra al modelo (los parches mueven ξ por A36): verificar que re-anclar la firma
  NO cambia la geometría u-v del parche (son coords de mundo) ni su material → el amortiguamiento resultante
  debe ser idéntico, solo se corrige la visibilidad/edición. `bench_absorption_patch.py` T13.

## Mallado de CAD con columnas y superficies curvas (13 Sep 2026 — EN ALCANCE, VERIFICAR)

Cadena de fixes al FEM sobre CAD importado (auditá contra la física del dominio):
- `mesh_gmsh._auto_clean_mesh`: quita caras degeneradas (área ~0) SOLO si la malla sigue
  estanca (borrarlas abría huecos → gmsh "overlapping facets"). A auditar: ¿alguna cara
  "degenerada" real (no sliver) se pierde y cambia el dominio?
- **Columna (hueco interior) → resta booleana:** `mesh_router._subtract_interior_bodies`
  resta los cuerpos interiores del recinto (`trimesh.boolean.difference`, backend
  **manifold3d** nuevo) → superficie con TÚNEL → gmsh single-loop boundary-fitted.
  Verificado headless: caja 6×8×3 + columna prismática → gmsh, f1=21.4=c/2·8; 0 nodos dentro
  del footprint de la columna (túnel tallado). A auditar: ¿el boolean preserva el volumen
  acústico exacto (V_sala − V_columna) y las normales/áreas de cara para el amortiguamiento?
- **Multi-loop gmsh** (`mesh_gmsh._build_volumes_with_voids`): para huecos FLOTANTES
  (rodeados), `addVolume([ext, hueco…])`. Verificado con caja-en-caja.
- **Superficies CURVAS / CAD sucio (techo en arco importado) — IMPLEMENTADO 13 Sep 2026,
  VERIFICAR:** cuando la reparametrización de gmsh falla ("overlapping facets"), el router
  ahora intenta REMESH ISOTRÓPICO (pymeshlab) + MALLADO DISCRETO antes de caer a voxel.
  Receta: pymeshlab isotropic remesh → `trimesh(process=True)` (suelda duplicados →
  watertight) → gmsh `createTopology` (frontera discreta fija, sin reparametrizar). Código:
  `mesh_gmsh._remesh_isotropic` + `mesh_with_gmsh(remesh_target_len=...)` (path discreto);
  cadena en `mesh_router.build_mesh` reparam→remesh+discreto→voxel. `bench_remesh_curved.py`
  18/18. A auditar con dureza (afirmaciones del autor, no evidencia):
  (1) **¿el remesh CAMBIA la geometría acústica?** pymeshlab mueve los vértices a una malla
  uniforme; el volumen se conserva <0.2% (afirmado) pero la FRONTERA se re-muestrea. ¿Los
  modos del recinto remallado son los del recinto REAL o los de una versión suavizada?
  Oráculo usado = voxel (que para el aula axis-aligned es near-exacto): coincidencia <0.34%
  en 5 modos de una caja, pero eso NO prueba el caso curvo genuino (ahí no hay oráculo
  analítico, ver §5 del plan). (2) **hallazgo clave del spike:** el aula testigo es
  axis-aligned FACETADO (todas las normales ±x/±y/±z), NO curvo → voxel ya converge <1% y
  <0.15% en volumen; la escalera $O(h)$ que motivaba el remesh casi no aplica ahí. El pago
  del boundary-fitted es real solo para CAD genuinamente inclinado/curvo. (3) convergencia
  O(h²) afirmada (err volumen 0.07%→0.03% al refinar) pero medida sobre pocos puntos.
  (4) el remesh puede NO cerrar a h grueso (arco chico a h=0.40 dio "sin tets" → router cae
  a voxel): verificar que el fallback nunca deja resultado inválido. (5) GOTCHA determinista:
  pre-limpiar (remove_duplicate_vertices) ANTES del remesh rompe gmsh; se suelda DESPUÉS.
- **Hallazgo lateral SIN corregir (tarea pendiente, con OK):** gmsh reparam sobre malla NO
  watertight puede completar sin excepción pero con volumen ~21% incorrecto (arco paramétrico
  como CAD: V=72 vs 91). El router solo prueba remesh si reparam LEVANTA excepción → este
  caso pasa silencioso. Propuesto: gate de plausibilidad de volumen. Viola exactitud (norte).
- Fallback SIEMPRE a voxel: el usuario nunca queda sin cálculo.

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

**CUALQUIER PAR OPUESTO + OPTIMIZADOR NO-FREEZE (16 Sep 2026, en alcance — VERIFICAR):**
pedido del profesor. (1) `dba_evaluate.best_axis` ahora es CRITERION-AWARE: elige el eje del par
de paredes opuestas que CUMPLE el criterio (cabs=≥2 subs en una pared + ≥1 fuente en la opuesta,
simétrico; dba=2+2), y la longitud del eje pasa a último desempate. Antes desempataba por la
dimensión más larga → con subs enfrentados en el eje corto elegía el eje largo y fallaba. A
auditar: (a) ¿`_axis_satisfies` puede dar un falso positivo (dos subs "en una pared" que en
realidad no están enfrentados a la fuente opuesta por estar en esquinas)? el `wall_tol=0.6 m`
define "en la pared"; en salas chicas dos paredes opuestas quedan a <1.2 m y un sub podría contar
en ambas. (b) el combo "Auto" pasa axis=None → `evaluate_cabs`/`cabs_feasibility`/`optimize_cabs`
resuelven con best_axis(criterion): ¿coincide el eje elegido para evaluar con el usado para
optimizar? (deberían, mismo criterio). (2) `cabs_optimize.optimize_cabs` sumó `progress_cb`/
`should_cancel` y **polish=False** + popsize adaptativo (180/D). A auditar: ¿polish=False degrada
el óptimo? (medido: mejora ~igual, 4.86→4.68 en un caso; el L-BFGS-B aportaba poco sobre este
objetivo ruidoso, pero verificar en configs con muchos DOFs). El threading (`_OptimizeWorker`
QThread en `dba_dialog`) es GUI, fuera del núcleo físico, pero opera sobre COPIAS (`replace`) de
las fuentes sin tocar Qt → sin data race. `bench_source_opt.py` 11/11.

**CABS/DBA NO BLOQUEAN, se juzgan por planitud (16 Sep 2026, 2da tanda — SOLO GUI, VERIFICAR que el
núcleo no cambió):** spec del profesor. El diálogo ya no rechaza/bloquea una config que no sea un
array de libro (p.ej. 1 sub por pared enfrentados): evalúa/optimiza SIEMPRE por planitud + varianza
espacial de la respuesta total (modos+SBIR). CAMBIOS SOLO EN `dba_dialog.py` + un flag en
`acoustic_panel`; **`dba_evaluate.evaluate_cabs`, su `passed` y el checklist estructural quedan
IDÉNTICOS** (benches 14/14+13/13 sin tocar). A auditar: (1) el nuevo veredicto de UI usa
`flat_real<=flat_ideal+1.5 and spatial_real<=spatial_ideal+1.5` como "respuesta plana" — ¿el margen
1.5 dB es defendible o arbitrario? es cosmético (badge), las métricas crudas se muestran igual.
(2) `is_rectangular` = `mesh_router.is_axis_aligned_box(params)` (False para CAD/polígono/arco):
¿describe bien "paralelepípedo"? para un recinto rotado no-axis-aligned da False aunque sea una caja
(conservador: muestra la nota de más, no de menos). (3) la evaluación sobre AABB de un recinto
irregular ya existía (el diálogo siempre trabajó sobre la caja); lo único nuevo es AVISARLO. El
núcleo físico no se tocó.

**CABS/DBA SOBRE EL CAMPO FEM REAL (16 Sep 2026, EN ALCANCE — VERIFICAR):** para salas no
rectangulares, evaluar/optimizar CABS/DBA sobre la base analitica rectangular es la geometria
equivocada. `dba_evaluate.FEMModalField` adapta la solucion modal FEM a la interfaz de
`RectModalBasis` (mapeo caja<->mundo por `origin`), y `evaluate_cabs`/`optimize_cabs` la usan via
`fem=`. A auditar con dureza: (1) **FRAMES** — el FEM vive en frame mundo (mismo que las fuentes) y
`_config_metrics` trabaja en coords caja; el adaptador suma `origin` para volver a mundo. Verificar
que el panel pasa origin=vmin CONSISTENTE con el frame de `modal_result.nodes` (si difieren, phi se
evalua en el lugar equivocado y todo el metric miente; el oraculo en caja lo detecta: FEM debe
coincidir con el analitico). (2) **ENMASCARADO** `FEMModalField.inside_mask`: los pts de grilla
fuera de la malla real se excluyen; ¿el criterio de "adentro" (evaluate_many de campo=1 -> NaN
afuera) coincide con el dominio acustico real, o el voxel/gmsh deja pts de borde ambiguos? (3)
**n_modes**: la evaluacion usa los modos que resolvio el panel; si son pocos (default n_modes=12),
la planitud hasta 200 Hz queda subrepresentada -> el veredicto puede ser optimista. (4) el decay se
saltea sobre FEM (no entra en el veredicto, OK). Oraculo `bench_source_opt.py` 16/16 (en caja
FEM~analitico <1.5 dB). El adaptador es matematica pura (superposicion modal como
`acoustic_fem.frequency_response`, factor c^2), reusa la Green modal ya validada
(`bench_modal_vs_impedance`). Rutas alternativas (perturbacion de forma de Slater; DtN no local) en
`plan_optimizacion_fuentes_unificada.md` §8, NO implementadas.

**v2.46 (17 Sep 2026, en alcance — VERIFICAR):** (a) los criterios CABS/DBA se volvieron
SIMETRICOS entre las dos paredes de un eje (sin "adelante/atras"): CABS = par de subs en una
pared + >=1 fuente en la opuesta; DBA = par de subs en cada pared. El checklist `ok_arr` de CABS
(que alimenta `passed`) era asimetrico y quedo consistente con `_axis_satisfies` (ambos simetricos).
Verificar que la simetria no habilite falsos positivos fisicos: 2 subs en una pared + 2 full-range
enfrente ahora "pasa CABS" estructuralmente, pero el VEREDICTO sigue siendo planitud+transferencia
(no bloquea ni por estructura). (b) nuevo flag `evaluate_cabs(...)["field"]` = "fem"|"aabb": solo
rotula sobre que volumen se midio (no cambia la fisica). (c) boton "todas" = azucar de UI para los
free_vars (no toca el nucleo).

**Panel unificado "Optimización de fuentes" (18-20 Sep 2026, en alcance — VERIFICAR):** la
herramienta CABS/DBA pasa a ser un panel con selector de NORTE: `flat` (planitud compuesta,
default), `spatial` (varianza espacial), `sbir` (peine de bordes en el receptor,
`_sbir_span` via sbir.band_extremes 20-200), `combined` (score 0..100 con umbrales `_lin_score`
y pesos `default_location_weights` de Predicción por caso de uso), `cabs`, `dba`. Función-objetivo
UNICA `dba_evaluate.composite_cost(metrics, criterion, weights)` que usan optimizar Y evaluar
(coherencia). Uniformidad modal Bolt = INFORMATIVA (no objetivo: invariante bajo el layout).
PUNTOS A AUDITAR: (1) el peine SBIR y el score combinado reusan `location_opt` (misma escala que
Predicción) -> chequear que los umbrales `_lin_score` (flat/esp 2..12, sbir 2..24) son defendibles
y no arbitrarios; (2) `composite_cost` mezcla dB (flat/spatial) con dB (sbir) sumando con pesos:
validar que la escala es comparable; (3) el "ideal" de referencia (array LS) se recomputa por
norte -> verificar que sigue siendo un techo alcanzable. Solo reorganiza que se minimiza; el
nucleo fisico (base modal, SBIR, respuesta compuesta) intacto. bench_norte_criterios 29/29.

**Fix frame ubicación v2.44 (12 Sep 2026, en alcance — VERIFICAR):** el optimizador/
evaluador de ubicación de la pestaña Predicción ponía fuentes AFUERA del recinto (y daba
falso "afuera") con `origin_mode=corner` en CAD y recinto paramétrico. Causa afirmada: el
FEM de ubicación se reconstruía centrado (`make_room`, ignora `origin_mode`) cuando no se
pasaba la malla real (solo se pasaba si `is_irregular_shape`); las fuentes viven en el frame
de render. Fix: pasar SIEMPRE la malla real → FEM, `inside_fn` (polígono real) y fuentes en
un mismo frame; guarda dura "nunca afuera" en `location_opt.optimize_layout`. A auditar:
(1) ¿el FEM sobre la malla real en frame `corner` da los MISMOS modos/ξ que en `center`
(invariancia por traslación del solver)? verificar que trasladar el recinto no mueve fₙ;
(2) `points_inside_surface` como `inside_fn` es el mismo test ray-parity 1-dir de v2.43:
para el recinto DIBUJADO no convexo dio DENTRO en el repro, pero para un CAD curado
apenas-estanco puede tener falsos "adentro" (la guarda solo garantiza lo que ese test
afirma); (3) `evaluate_design`/`fixed_room_from_design` ahora toman dims del AABB de la
malla real (no de sliders) → para un N-gono el RT60 usa `_shoebox_areas` del AABB (área
sobrestimada). Repro headless en scratchpad; `bench_predict_location.py` +2 tests.

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

**Curado de CAD + validez del dominio (v2.43, 12 Sep 2026 — RELEVANTE para el auditor):**
El hallazgo importante NO es una feature sino un LÍMITE del pipeline: los CAD del aula
(`PLANO AULA*.obj`) NO son sólidos cerrados (decenas/miles de componentes disconexos), y
`acoustic_mesh.points_inside_surface` (ray-parity, 1 dirección) da ~96% del AABB «adentro».
Como `build_volume_mesh` usa ese mismo test para decidir las celdas interiores, sobre un CAD
no estanco el DOMINIO SIMULADO degenera al AABB entero (no al recinto real), en silencio. A
auditar: (1) ¿cuánto se aparta el dominio voxelizado del recinto real cuando la malla no es
watertight?; (2) el nuevo `acoustic_panel._confirm_nonsolid_cad` avisa antes del FEM si
`is_watertight` es False, pero NO cuantifica el error del dominio; (3) para un recinto con
COLUMNA interior (dos sólidos cerrados anidados, tras curar), el voxelizador debería tallar
la columna por paridad de rayos — VERIFICAR que el interior resultante = recinto menos columna
(no incluye el interior de la columna). Las herramientas de curado (`geom_import`) son
geométricas (trimesh), fuera del núcleo físico, pero que la malla llegue estanca es CONDICIÓN
NECESARIA para que el modelo modal valga.
