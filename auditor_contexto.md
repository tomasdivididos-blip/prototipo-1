# Contexto vivo para el auditor-fisico

> Este archivo lo actualiza el asistente principal en CADA recap, para que el
> `auditor-fisico` entre con el estado al día. **Advertencia de método (no negociable):**
> TODO lo de acá son AFIRMACIONES DEL AUTOR (co-autor sesgado), no evidencia. Verificá
> cada cosa contra la fuente física, un oráculo, o una cuenta propia. Que este archivo
> diga "resuelto/PASA" no prueba nada; es un puntero a qué mirar.

**Última actualización:** 2026-10-06 (v2.62: CIERRE de la limitación CASI-CRÍTICA del sparse `qep_sparse.py` = gate por ξ de 1er orden + Beyn TILEADO elíptico + only_if_larger, NÚCLEO EN ALCANCE; + v2.61 solver sparse PAL+Beyn; + v2.60 QEP modal/nodal; + v2.59 4º estado; + v2.58 norte front↔rear; + v2.57 exploración; + Fazenda/«?» FUERA de alcance; + v2.56 … v2.50).

## v2.61 — solver SPARSE del QEP de frontera `qep_sparse.py` (PAL + Beyn) (4 Oct 2026, EN ALCANCE — VERIFICAR)

Extiende el QEP de frontera EXACTO de la curva C2 de Nn≤1800 (eig denso de v2.60) a Nn≤6000, sin el eig denso de 2N. Plan + referencias (13 PDFs) en `plan_solver_qep_sparse.md`. TODO esto son AFIRMACIONES del autor; es NÚCLEO numérico nuevo, auditá cada pieza. Insight: con s=iω el QEP se vuelve el viscoso REAL simétrico s²M+s(cβ)C+c²K con C de bajo rango (rank 3-11% de N).

- **`pal_qep(M,C,K,sigma,k,m,mode)` (método A, PAL — Lu, Huang, Bai & Su 2015):** LEP de dim n+ℓm, factoriza SOLO Q(σ)=σ²M+σC+K (orden n) + matvec estructurado (ecs 5.2-5.3), escalado ζ del Teorema 4, Padé (m,m) de √(μ+1), recuperación λ=σ√(μ+1). A AUDITAR: (1) `bench_qep_sparse` T1/T2 afirman PAL-denso==QEP-denso y PAL-sparse==PAL-denso (5e-15) → verificar la linealización y el escalado; (2) el error-hacia-atrás `_backward_error` η_Q = ‖P(λ)x‖/((|λ|²‖M‖+|λ|‖C‖+‖K‖)‖x‖) es el certificado (Tisseur 2001) que decide qué polos se aceptan; (3) un shift σ solo capta su DOMINIO DE CONFIANZA (paper Fig 2.2) → `pal_boundary_xi_shift` usa multi-shift; ¿el espaciado `conf_hz`=18 Hz garantiza cobertura? (4) `lowrank_factor` C=EEᵀ por eigendescomposición del bloque del soporte (pared): ¿correcto para C compleja (β complejo)?
- **`beyn_contour(Tfun,z0,R,n_quad,ell)` / `beyn_qep` (método B, Beyn 2012):** integral de contorno A0=∮T⁻¹V̂, Ã1=∮(z−z0)T⁻¹V̂ por trapecio; SVD de A0 revela k=nº polos adentro; B=V0ᴴÃ1W0Σ0⁻¹ da λ. A AUDITAR: (1) `bench_qep_beyn` T1 afirma que encuentra TODOS los polos en Γ == denso (match 1.4e-7); (2) el test de RANGO del SVD (tol_rank) decide k: si k==ell hay más polos que la sonda → ¿se detecta/avisa? (3) filtro por residuo ‖T(λ)v‖/‖v‖ + dentro de Γ; (4) T4 afirma que resuelve el NEP con β(z) holomorfa → el Tfun callable es genérico, verificar que la estabilización Ã1=A1−z0A0 (Remark 3.2a) está bien.
- **`sparse_boundary_xi_shift` (wrapper A+B, el que usa el panel):** PAL banda + relleno: proyección modal (`qep_boundary_xi_shift`) para los modos de ξ modesto (donde ya es exacta, bench_front_rear_qep_modal), Beyn SOLO para los no cubiertos con ξ_fallback>`xi_crit`=0.35. Matcheo por voto POLO→MODO (cada polo vota por el modo que mejor solapa; evita mis-asignar el sobreamortiguado). ξ del sobreamortiguado desde sus DOS polos reales: ωₙ=√(s1 s2), ξ=−(s1+s2)/(2ωₙ). A AUDITAR: (1) `bench_qep_sparse_f4` afirma reproducir el nodal denso EXACTO en los 12 modos del shoebox incluido ξ=1.2 → verificar la reconstrucción del sobreamortiguado y el voto; (2) **el relleno con proyección modal mezcla un método aproximado (modal, subestima casi-críticos) con el exacto (PAL/Beyn)**: ¿el gate xi_crit captura TODOS los casi-críticos, o alguno con ξ_fallback bajo (subestimado) se escapa sin Beyn? (riesgo declarado); (3) el tope N_SPARSE_MAX=6000 y el tiempo: Control Ale 11.5 s con `couple_thr`=0.6 (default), que concentra PAL en la BANDA de los modos fuertemente acoplados (diag(G)>couple_thr·max) y deja los débiles al modal → **NO es exacto en TODA la banda**: error ≤0.03 en ξ en los modos débilmente acoplados (dentro de la precisión del modal), pero ¿el umbral 0.6 excluye algún modo que el modal SÍ subestima? (riesgo a auditar; couple_thr=0 = exacto completo, 17 s). El cuello es la convergencia de ARPACK en baja f (no la LU, 0.35 s a toda f); capar maxiter/bajar k pierde los acoplados.
- **LIMITACIÓN CASI-CRÍTICA — CERRADA en v2.62 (6 Oct 2026, EN ALCANCE — VERIFICAR).** El sparse A+B SUBESTIMABA los modos CASI-CRÍTICOS por DOS causas, ambas arregladas en `qep_sparse.py` (bench_qep_sparse_f6, regresión dedicada). TODO esto son AFIRMACIONES del autor; es núcleo numérico, auditá cada pieza.
  - **(1) Gate equivocado.** El gate de Beyn-fill miraba `ξ_fallback>xi_crit`, pero el fallback modal SUBESTIMA justo los casi-críticos (ducto 7×2.1×2.3, β=1 en X: modo axial fundamental nodal ξ=1.325, fallback ξ=0.339 < xi_crit=0.35 → NUNCA disparaba Beyn, n_beyn=0, sparse devolvía 0.339). FIX: gate por el ξ de **1er orden** `ξ_est=(c|β|/2)·diag(G)_n/ωₙ` (perturbación diagonal, Morse&Ingard 9.4.14), que es MONÓTONO y COTA INFERIOR del ξ real → el casi-crítico siempre queda flaggeado. A AUDITAR: ¿`diag(G)` crudo fallaría? SÍ (verificado: un modo de alta f con acople moderado tiene diag(G) grande pero ξ chico, ωₙ grande; por eso se divide por ωₙ). `xi_gate`=0.15 default.
  - **(2) Contorno Beyn que SATURA.** El contorno CIRCULAR único grande encierra ~2·Nm polos (densidad modal ∝ f²) → SVD sin gap, k=ell (verificado: círculo R=0.25ωₙ a 183 Hz, k=24=ell, gap=1.0, no halla el polo). FIX: **Beyn TILEADO** con una ELIPSE por cluster de frecuencia, ANCHA en Re (semieje a=1.15ωc: alcanza el polo casi-crítico, que está a −ξωₙ del eje imaginario, p.ej. s=−201+i168 para ξ≈1.2) y ANGOSTA en Im (semieje atado a la banda del cluster + margen por el corrimiento de fₙ, que crece con ξ_est). El ancho en Im controla cuántos modos se encierran; el ancho en Re casi no agrega (pocos tienen amortiguamiento grande). `beyn_contour`/`beyn_qep` extendidos a elipse (param `b`=semieje Im; círculo si b=None; normalización verificada vs bench_qep_beyn 5/5). Insight clave: todo polo del QEP nodal tiene Im(s)>1 (el nodal filtra Re(ω)>1) → NO hay polos reales puros; se descartan los no-físicos (DC, Re≥0).
  - **(3) Salvaguarda only_if_larger.** Beyn pisa el fallback SOLO si AUMENTA el ξ (su fin es corregir subestimación): si un polo se mis-asigna a un modo bien estimado y da un ξ menor, no lo daña. A AUDITAR: ¿deja escapar una SOBRE-estimación de Beyn? En el ducto, los modos no-flaggeados quedaron IDÉNTICOS al baseline (mode 14=0.226, mode 1=0.262 = mis-asignaciones PAL/truncación PRE-EXISTENTES, NO introducidas por el fix; solo cambió el modo 0: 0.339→1.325).
  - **Validación:** F4 4/4 (overdamped ξ=1.199 exacto), F6 5/5 (ducto casi-crítico ξ=1.325 exacto vs 0.339 baseline + no-regresión), qep_sparse 7/7, qep_beyn 5/5, qep_f5 4/4, front_rear_modal/nodal 9/9+9/9, front_rear_opt 4/4, capa0_all 191/191. **RIESGO RESIDUAL (no casi-crítico, PRE-EXISTENTE):** en salas DEGENERADAS (casi-cúbicas) PAL/fallback mis-asignan modos MODESTOS (ξ~0.1-0.3) por solape ambiguo entre modos casi-degenerados; el nodal mismo puede estar mal-asignado ahí. Fuera del alcance de este fix. El nodal denso sigue O((2Nn)³): ~120 s a Nn=1320.
- **THREADING (5 Oct 2026, GUI, FUERA del núcleo físico):** el cálculo del decaimiento corre en `_DecayWorker(QThread)` (numpy puro, thread-safe; caches pre-calentadas en el hilo principal) con QProgressDialog, para no congelar la UI durante el eig denso lento. No cambia la física.
- **Wiring `_rear_matched_delta_xi`:** nodal (Nn≤1800) → sparse A+B + fallback modal (1800<Nn≤6000) → modal (Nn>6000) → perturbación. Benches: `bench_qep_sparse` 7/7, `bench_qep_beyn` 5/5, `bench_qep_sparse_f4` 4/4, `bench_qep_f5` 4/4 (validación TP7, pero las RIRs NO resuelven ξ por modo: df 5.3 Hz, M>1; la validación real es sparse==perturbación sobre la geometría TP7, 0.59%). Sin regresión front_rear 9/9+9/9. **F3 — ORÁCULO SLEPc HECHO (6 Oct 2026, EN ALCANCE — VERIFICAR):** `bench_qep_slepc.py` corrió 4/4 contra SLEPc 3.26 complejo (WSL Ubuntu, env conda `qep_oracle` con petsc/slepc complejos de conda-forge; se SALTEA con exit 0 si falta slepc4py o PETSc no es complejo → suite verde en Windows). SLEPc PEP (TOAR, shift-invert) es un solver de PEP INDEPENDIENTE (otra linealización + ST) → acuerdo SLEPc==propio valida PAL/Beyn sin el mismo código. Resultados (shoebox 5×4×3, N=693): T1 SLEPc==companion denso 1.3e-10; T2 PAL certificado==SLEPc 6.3e-9; T3 cada polo SLEPc tiene polo Beyn 1.46e-9; T4 ξ(SLEPc multi-target 103 polos, matcheo por solape)==ξ(nodal) |Δξ|=0.0000 en 12 modos. A AUDITAR: T4 usa el MISMO matcheo por solape que el nodal (robusto a degeneración); el oráculo SLEPc es independiente del companion propio pero NO de la malla/K/M. NO instalable en win-64 (confirmado conda --dry-run); solo WSL/CI.


## v2.60 — curva C2 = QEP de frontera EXACTO (modal + nodal) + β compleja (3 Oct 2026, EN ALCANCE — VERIFICAR)

Reemplaza la perturbación de 1er orden de v2.59 por el QEP de frontera EXACTO (cierra E3 del plan front↔rear). CUATRO funciones nuevas en `face_materials.py` + rewire de `_rear_matched_delta_xi`. AFIRMACIONES del autor; auditá cada una, es NÚCLEO numérico nuevo.

- **`surface_gram_per_mode(phis, locator, verts, tris, groups, wall_mask, subdiv)` → G (Nm,Nm):** Gram de superficie COMPLETA G[n,m]=∫_pared φₙφₘ dS. A AUDITAR: (1) reusa EXACTO la cuadratura/validez/cobertura de `_modal_surface_integrals` (midpoint sobre tris subdivididos, re-escala A2 por cobertura) → la diagonal DEBE coincidir con el Sg de la perturbación (el bench afirma bit a bit, 2.2e-16); (2) la identidad G == φᵀ C_surf,pared φ (emparedado de la matriz de masa de superficie FEM) la verifica `bench_front_rear_qep_modal` T1a al 0.77% (error de cuadratura centroide vs integral lineal exacta) — ¿subdiv=2 del panel vs subdiv=3 del bench cambia algo?; (3) simetriza 0.5(G+Gᵀ) (ruido numérico).
- **`qep_boundary_xi_shift(freqs, G, beta, c)` → (xi, f_new):** QEP MODAL diag(ωₙ²)+i c β G ω−I ω²=0, linealización companion A=[[A0,A1],[0,I]], B=[[0,I],[I,0]] (idéntica a `bench_front_rear_qep`, validada 4/4; cf. Tisseur & Meerbergen 2001). Matcheo por Re(w) más cercano. A AUDITAR: (1) β ESCALAR (la matriz i c β G no admite β(f) por modo; para β(f) usar la perturbación) — ¿se declara bien?; (2) con base rígida (ωₙ², sin otras pérdidas) el xi devuelto ES el Δξ de la pared (la rígida no amortigua) → se SUMA a ξ_campo; ¿correcto el supuesto de superposición?; (3) el matcheo por Re más cercano puede ser many-to-one a β=1 (ver abajo).
- **`qep_boundary_nodal(K, M, C, freqs, phis, beta, c, max_dense=1800)` → (xi, f_new):** QEP NODAL EXACTO c²K+icβC ω−M ω²=0 sobre TODO el espacio (eig DENSO 2Nn), del que el modal es la proyección de Galerkin. β COMPLEJA (Re→ξ, Im→Δfₙ). Matcheo por SOLAPAMIENTO de autovector de presión (robusto). A AUDITAR: (1) **es el ORÁCULO** — mismo esquema que el `qep_solve` de `bench_perturbation_complex` (ya validado vs perturbación), pero con C restringida a la pared trasera; `bench_front_rear_qep_nodal` lo ata (T2 0.97%, T3 β compleja Δf=−0.44 Hz mismo signo que la perturbación); (2) a β=1 alcanza ξ~1.20 casi-crítico (×3.2 el modal) → **¿es físico o artefacto del matcheo?** El modo rígido se reparte en varios polos (overlap cae 0.99→0.92 a β=1); ni la suma ni el por-modo del δ son limpios (bench_modal T4b, bench_nodal T4 usan el PICO de ξ, no agregados); (3) **se DESCARTÓ el shift-invert sparse** (87% error a β~1, polos dispersos) → solo denso, Nn≤1800, si no None; ¿el tope es razonable?; (4) la Lorentziana de `frequency_response` acepta ξ>1 sin NaN (overdamped = Lorentziana ancha) → el ξ~1.2 no rompe la EDC (verificado); ¿la EDC resultante es físicamente interpretable con un modo sobreamortiguado?
- **`rear_wall_surface_mass(nodes, tets, axis, nrm_tol=0.9)` → (C csr, n):** masa de superficie de la pared trasera del VOLUMEN: caras de frontera con normal EXTERIOR·axis>0.9. A AUDITAR: (1) `_boundary_faces_with_apex` orienta la normal alejándola del ápice interior del tet → ¿robusto en mallas talladas por muebles / CAD no convexo?; (2) para un shoebox el bench confirma n_caras y suma(C)==Ly·Lz exacto; (3) la cuadratura (A/12)(1+δ) es la masa de superficie lineal exacta (= `assemble_surface_M`).
- **Wiring `_rear_matched_delta_xi`:** 3 caminos (nodal si Nn≤1800 → modal → perturbación). A AUDITAR: la pared se elige por `best_axis(criterion="cabs")` (igual que v2.59); el nodal rebuildea K,M con `acoustic_fem.build_KM(mr.nodes, mr.tets)` (misma malla del aire, tallada si hay muebles). Benches: `bench_front_rear_qep_modal` 9/9, `bench_front_rear_qep_nodal` 9/9, sin regresión `bench_perturbation_complex` 11/11, `bench_capa0_all` 191/191.

## v2.59 — panel de decaimiento: 4º estado «pared trasera matcheada» (C2) (2 Oct 2026, EN ALCANCE — VERIFICAR)

E5 del plan front↔rear. Lleva el C2 (movimiento de polos por una terminación de admitancia matcheada) al panel «Decaimiento con subs». AFIRMACIONES del autor; auditá.

- **`AcousticPanel._rear_matched_delta_xi(sources)`:** identifica la pared TRASERA (grupos con normal[axis]>0.9, axis=`dba_evaluate.best_axis(active, dims, origin, criterion="cabs")`) y calcula Δξ por modo con `face_materials.perturbation_xi_shift_per_mode` pasando un `beta_provider` que da **β=1 (Re, Im=0 → Y₀) en la trasera y 0 en el resto**. Devuelve el Δξ de esa pared. A AUDITAR: (1) **es PERTURBACIÓN de 1er orden con β=1, FUERA de su régimen de validez** (E1c/E3: β~1 no es perturbativo). Se declara CONSERVADOR porque E3-T2 mostró que la perturbación SUBESTIMA (δ_QEP/δ_pert hasta ~1.95 en modos bajos) → la curva real decaería más rápido. Verificado headless: 1er axial-y recibe δ=c/Ly=68.6 Np/s (perturbación) vs 75.9 del QEP exacto (RT60 0.10 vs 0.091 s). ¿Es aceptable mostrar el piso conservador, o debería ser el QEP exacto? (el usuario quiere el refinamiento QEP como próximo paso). (2) **β=1 real** → solo amortigua (Im=0, sin corrimiento de fₙ); OK para un absorbedor matcheado puro. (3) la pared trasera se elige por `best_axis(criterion="cabs")` = eje con subs enfrentados; si no hay subs enfrentados claros, elige por `opposed`/longitud → ¿la pared elegida es la física correcta? (4) `perturbation_xi_shift_per_mode` usa el mismo `_modal_surface_integrals` (∫φₙ²dS por grupo) ya validado; acá se le pasa g2m={} + beta_provider, camino ya existente (bench_perturbation_complex). (5) a diferencia del norte R̄ (v2.58), E5 NO depende de la banda de onda plana → anda en cualquier eje/recinto (Control Ale incluido).
- **Wiring (`_open_decay_waterfall` + `DecayWaterfallDialog`):** 4º estado `edc_d`/`csd_d` = `modal_impulse_response(..., damping=ξ_campo+Δξ_rear)`, curva verde punteada + waterfall + nota honesta. Reusa el MISMO `modal_impulse_response`/EDC/CSD de C1 (no hay derivación nueva de decaimiento). Sin cambios al solver ni a `modal_decay.py`/`perturbation_xi_shift_per_mode`.
- **PRÓXIMO (pedido del usuario): refinamiento QEP para la curva C2** — reemplazar la perturbación por el QEP exacto proyectado a los modos (necesita la Gram de superficie OFF-diagonal ∫φₘφₙdS de la pared trasera, hoy no expuesta; `_modal_surface_integrals` solo da la diagonal). El oráculo es `bench_front_rear_qep`.

## v2.58 — norte de optimización «front_rear» cableado (E4b) + readout (2 Oct 2026, EN ALCANCE — VERIFICAR)

Lleva la R̄ de E1b/E4a al optimizador/evaluador reales y a la GUI. TODO son AFIRMACIONES del autor; auditá. El QEP de E3 (opción (b), movimiento de polos) **NO** entró a la app todavía: esto es el camino (a) feedforward juzgado por la reflexión del frente de onda, no por Δξₙ.

- **`dba_evaluate.rear_reflection(basis, kappa, Q_spec, dims, origin, axis, fa, xi)`:** campo modal p(y) sobre una línea del eje (via `_modal_frf_grid`, la MISMA H del solver) descompuesto por mínimos cuadrados en 2 ondas viajeras A₊e^{−iky}+A₋e^{+iky} (k=ω/c); R(f)=|A₋|/|A₊|; R̄ = promedio PONDERADO POR f sobre la banda `_axis_transverse_band` = [c/2L_axis, min_j c/2L_j]. A AUDITAR: (1) **la banda** — es [axial fundamental, primer modo transversal]; si el eje de subs NO es el más largo, hi≤lo → banda VACÍA → R̄=NaN (reproducido con Control Ale: subs en Y=3.9 con X=4.8 más largo → f_trans 35.7 < f_ax 44 → NaN, es FÍSICO no bug). (2) **el muestreo** usa una línea al centro transversal (dims[a]/2, dims[b]/2) en coords caja; para FEM (recinto irregular) los puntos pueden caer fuera de la malla → NaN (filtrado). (3) **clamp R a 1.5** y peso ∝ f: ¿sesga? (4) la R̄ es del campo FEEDFORWARD (no mueve polos); es un DESCRIPTOR de cuán viajera es la onda, no un Δξₙ.
- **`_reflection_penalty_db(R)` = 20log10((1+R)/(1−R))** (clamp R≤0.99): rizado de onda estacionaria en dB, para sumarlo con planitud/varianza (misma unidad). A auditar: ¿es la conversión correcta R→rizado pico-a-valle? (es la fórmula del SWR en dB).
- **`composite_cost` rama "front_rear"** = `_reflection_penalty_db(R̄) + flat + spatial`. Si R̄=NaN el penalty es 0 → el coste cae a flat+spatial (el término de reflexión DESAPARECE en silencio; la GUI lo avisa en el readout, pero el OPTIMIZADOR no). A auditar: ¿debería el optimizador rechazar/avisar front_rear cuando la banda es vacía en vez de optimizar solo flat+spatial sin decirlo?
- **Wiring:** `wants_reflection`, gate `want_reflection` en `_config_metrics`, propagado en `cabs_optimize` (`_cost`/`_metrics`/`suggest_layouts`), `rear_reflection_real/ideal` en `evaluate_cabs`, y lectura en `dba_dialog._show_eval` (badge + mensaje de «no aplica» para banda vacía / «fuera de malla»). `best_axis` para front_rear (no-array) elige el eje por `opposed`=min(subs enfrentados). Benches existentes sin regresión: bench_norte_criterios 33/33, bench_cabs_criterion 14/14, bench_source_opt 29/29. Prototipo del norte: `bench_front_rear_opt.py` 4/4 (E4a). **FALTA test visual del usuario** (en Control Ale sale «no aplica», correcto; para verlo activo hay que subs en el eje más largo).

## v2.57 — frente de onda opuesto + admitancia (E1-E3) + Fazenda + «?» (2 Oct 2026)

Dos cosas FUERA de alcance físico (contexto) y una EN ALCANCE a auditar con dureza.

**FUERA de alcance (no toca solver):**
- **`perceptual.py` (umbral de Fazenda) + columnas en `ModeTableDialog`:** criterio PERCEPTUAL (umbral de decaimiento modal, Fazenda/Stephenson/Goldberg JASA 137, 2015), no física del solver. Datos digitalizados de las Figs. 4 (sine-burst 85 dB) y 5 (música) del paper; interpolación log-f, extrapolación plana. Compara el RT60ₙ (que la tabla YA calculaba) con el umbral; no cambia ningún cálculo. A mirar solo si se cuestiona la digitalización de la curva.
- **Rollout del «?» de ayuda a ~23 ventanas + reserva de franja superior en `style._HelpButtonReposition`:** puro Qt/UI.

**EN ALCANCE — EXPLORACIÓN front↔rear (subs delanteros vs traseros como admitancia activa). Son PROTOTIPOS/ORÁCULOS headless (`bench_front_rear_*.py`), NO cableados al solver ni a la GUI: no cambian ningún comportamiento de la app todavía. Plan en `plan_frente_opuesto_admitancia.md`. TODO son AFIRMACIONES del autor, auditá contra la fuente (Nelson & Elliott, _Active Control of Sound_ 1992 cap. 5; Celestinos & Nielsen CABS; Santillán JASA 110, 2001; Morse & Ingard 9.4.14).**

- **E1a `bench_front_rear_duct.py` (4/4, análogo 1-D exacto):** transcribe Nelson & Elliott cap. 5 (primario x=0, secundario x=L). A auditar: (1) ¿las Ec. 5.6.4 (q_s0=−q_p cos kL), 5.6.6 (W0/Wpp=sin²kL) y 5.15.3 (q_s=−q_p e^{−jkL}) están bien transcriptas y es el análogo correcto del eje front↔rear? (2) la potencia por Ec. 5.6.2 y la admitancia del frente u/p=Y0 (onda plana) son exactas a máquina (3.6e-16) — trivial pero verificar que no hay un error de convención de tiempo (e^{+iωt}).
- **E1b/E1c `bench_front_rear_room.py` (6/6, campo modal real):** reusa `source_coupling.RectModalBasis` + `dba.py` (ya en alcance). Descompone p(y) en 2 ondas viajeras (k=ω/c) sobre una ventana central y extrae R y β_rear=(1−r)/(1+r). A AUDITAR: (1) **la descomposición de 2 ondas**: el residuo del ajuste es ~0.089 (afirmado = truncamiento modal, NO física, porque en una resonancia axial baja a 5e-4, T4); ¿es realmente truncamiento y no un sesgo del método? (2) **pared entera excita solo axiales (0,m,0)**: cierto por la integral de superficie, pero verificar. (3) **la extracción de β_rear**: la fórmula (1−r)/(1+r) con r=(A₋e^{+jkL})/(A₊e^{−jkL}) y la auto-consistencia |(1−β)/(1+β)|=R (2.8e-16) — ¿el signo/dirección de u_n está bien? (4) **conclusión "β_rear no perturbativo" (|β|∈[0.29,1.10])**: clave, redirige E3; ¿el mínimo 0.29 es robusto o depende de la ventana/frecuencias? (5) el payoff T3 (R cae con el drive naive) usa `dba.dba_coupling_fn` (feedforward): es redistribución (C1), NO movimiento de polos — verificar que la nota NO sugiere lo contrario.
- **E3 `bench_front_rear_qep.py` (4/4, QEP exacto, opción (b) matcheada):** QEP `c²K+icβC_bc ω−Mω²=0` en base modal (M=I, c²K=diag(ωₙ²), C_bc=Gram de superficie, rango-1 para axiales de pared uniforme), MISMO método que el oráculo del cono `bench_cone_damping`. A AUDITAR CON DUREZA: (1) **el armado del QEP y la linealización companion**: ¿idéntica a `bench_cone_damping.qep_delta_cone`? ¿C_bc=(2/Ly)ssᵀ, sⱼ=(−1)ʲ es la Gram de superficie correcta? (2) **T1 QEP≈perturbación (δ=c Re(β)/Ly) a β≤0.15, 0.7%**: atadura al modelo validado — verificar que δ_pert=c Re(β)/Ly es el decaimiento 1-D correcto (δ_energía=2c Re(β)/L). (3) **T3 RT60 colapsa ×1107 (100.7 s → 0.091 s) a β=1**: ¿físico o artefacto? ξ₁=0.35 (subamortiguado, OK). (4) **T2: a β=1 δ_QEP/δ_pert tiene estructura en f (1.11→1.95 en modos bajos, <1 en altos)**: ¿el <1 de los modos altos es TRUNCAMIENTO (J=20) y no física? declararlo. (5) **fork físico (feedforward C1 vs feedback matcheada C2)**: el QEP modela (b) la terminación de impedancia PASIVA/feedback (β impuesto), no el feedforward de `dba.py`; verificar que el claim "los polos se mueven" vale para (b) y NO se confunde con el C1 de `modal_decay.py`. (6) β real aquí (Im=0): el corrimiento Δfₙ por Im(β) NO se ensayó.

## v2.56 — export tras optimizar + «?» de ayuda + sacar X/Y/Z del visor (2 Oct 2026, FUERA DE ALCANCE FÍSICO)

Nada de esto toca el solver, el ensamblaje FEM, la perturbación, la impedancia ni las métricas. Es UI/IO; no requiere auditoría física. Para contexto:
- **`dba_dialog.DBADialog._export`:** antes solo exportaba el modo diseño (`_last`); ahora exporta el gráfico actual según `_last_plot_kind` ("calc"|"eval") — imagen siempre, CSV con columnas por modo. El CSV de evaluación sale de `_last_eval` (`freq`, `total_db_mean_real`, `total_db_mean_ideal`), que son los MISMOS arrays que ya dibujaba `_draw_eval` y que produce `dba_evaluate.evaluate_cabs` (núcleo YA en alcance desde PR #19, sin cambios acá). No se recomputa nada nuevo: solo se serializa lo ya calculado. Único efecto de cálculo: al APLICAR una optimización se re-llama `_calc_eval()` (re-evalúa la config optimizada con la misma `evaluate_cabs`, sin lógica nueva).
- **`style.add_help_button` / `show_help_popup`:** botón «?» + popup de texto. Puro Qt.
- **`viewer.py`:** se quitó el widget `AxisIndicator` (cuadrados X/Y/Z). El bloqueo de eje (rotación restringida) sigue por teclado; la matemática de rotación no cambió.

## v2.55 — material no resuelto → α=0.03 (no rígido) + modelo de impedancia por forma del α + ajuste (1 Oct 2026, EN ALCANCE — VERIFICAR)

Todo son AFIRMACIONES del autor; auditá contra la física y los oráculos. Dos cosas con impacto directo en el amortiguamiento (y por ende RT60/f_S/decay), que son tu alcance.

- **Fallback α=0.03 en el camino UNIFICADO (arreglo del BUG de v2.54).** Antes, una cara con material no resuelto caía a `default_surf=None` → β=0 (rígida) en `absorption_patch.compute_xi_shift_with_impedance`, inconsistente con el camino simple (`face_materials._alpha_for`, default 0.03). Fix: `AcousticPanel._default_alpha_surface()` = `imp.resistive(beta_from_alpha_random(0.03))` (β REAL, sin reactancia) pasado como `default_surf`. A auditar: (1) ¿`imp.resistive(β).alpha_random == Paris(β)`? (el puente que hace α=0.03 consistente entre los dos caminos; `bench_material_fallback.py` A1 lo mide ~0.03). (2) β real → Im=0 → NO introduce corrimiento de fₙ espurio en las caras sin resolver/asignar (igual que `_material_surface` con reactancia apagada). (3) ¿el fallback cambia resultados de `.room` CON construcciones y caras sin material? sí: esas caras pasan de rígidas (β=0) a α=0.03 — es el fix buscado (consistencia), no regresión, pero verificá que para un `.room` donde TODO está asignado/resuelto no cambia ni un dígito. `bench_material_fallback.py` A2 mide xi_rígido/xi_default=0.000 (reproduce el bug) y default==camino simple 2.1%.

- **Feature 1-2 etapa 2: el modelo de impedancia sugerido se elige por la FORMA del α y se AJUSTA para reproducir el α de catálogo (NÚCLEO NUEVO EN ALCANCE).** Reemplaza la etapa-1 (keyword fija tipo + params del nombre), que producía modelos cuyo α contradecía el catálogo (membrana con Re(β)≈0 en paredes → al aplicar sugerencias el amortiguamiento colapsaba → Control Ale f_S 1135 vs 215 correcto). En `impedance_defaults.py`: `_alpha_shape` (flat/low_peak/mid_peak/rising) propone el TIPO; `_fit_spec_to_alpha` (scipy `least_squares` multi-start) ajusta los params minimizando, EN ESPACIO β, el residuo `w·(Re(β_modelo(f,θ=0)) − beta_from_alpha_random(α_cat(f)))` con peso `w=√(f₀/f)` a graves; se acepta el de menor residuo bajo `_fit_is_acceptable` (umbral 0.40×RMS(β_target)); si ninguno pasa, o α plano (cv<0.30), cae a β real (α exacto). A AUDITAR CON DUREZA: (1) **¿el objetivo correcto es Re(β) a θ=0?** el claim es que el kernel de perturbación unificado usa β(θ=0) y que `beta_from_alpha_random(α_cat)` es el amortiguamiento del camino de material — verificar que minimizar ese residuo es EXACTAMENTE lo que alinea el RT/f_S (no un proxy). (2) **el peso a graves `√(f₀/f)`** sesga el ajuste a la banda sub-Schroeder: ¿deja mal el amortiguamiento en medios (p.ej. Techo residβ 0.016 pero Re(β) a 250 Hz 0.008 vs objetivo 0.038, sub-amortiguado)? ¿importa para el f_S? (3) **el umbral 0.40×RMS es arbitrario** (calibrado con 4 materiales del profe: Techo membrana 0.016 pasa, Emplacado 0.019 no): ¿defendible? ¿falsos aceptados/rechazados en el catálogo de 428? (4) **el pico del Techo se corre 63→125 Hz** (membrana simple vs compuesto machimbre+lana+chapa): el β en graves matchea pero fₙ se corre por la reactancia de un modelo que NO es el físico real → ¿el corrimiento de fₙ resultante es defendible o es un artefacto del ajuste? (5) **selección por forma vs evidencia textual:** la etapa-1 exigía evidencia textual para la reactancia (anti-M1); ahora la forma puede elegir membrana para un α con pico grave aunque el keyword diga poroso — ¿reintroduce algo del sesgo M1 (reactancia de un modelo extrapolado)? El autor afirma que NO porque el Re(β) se ajusta al α medido y el fallback β-real cubre lo que no reproduce. (6) `_fit_spec_to_alpha` multi-start con grillas chicas + early-exit (perf): ¿el óptimo encontrado es estable (no cae en mínimos locales distintos entre corridas)? Oráculo: `bench_impedance_defaults.py` REESCRITO 32/32 (recuperación: α generado de un modelo conocido → recupera tipo + damping-match; selección por forma; INVARIANTE anti-colapso para los 4 materiales reales). No-regresión: wiring 14/14, `bench_capa0_all` 190/190. El solver/ensamblaje FEM NO se tocó; esto es wiring + criterio de modelado + ajuste numérico.

## v2.54 — impedancia por default por material + BUG de f_S con material no resuelto (1 Oct 2026)

- **BUG EN ALCANCE (importante, NO arreglado — VERIFICAR y corregir):** una cara con material que NO resuelve en el catálogo se vuelve RÍGIDA (β=0) en el camino de perturbación UNIFICADO (`absorption_patch.compute_xi_shift_with_impedance`, el que corre con modelo=perturbación), porque `_construction_surfaces` no agrega esa cara a `surf_g` y el kernel usa `default_surf=None` → β=0. El camino SIMPLE (`face_materials.perturbation_xi_per_mode`/`_alpha_for`) usa α=0.03 para lo no resuelto → los dos caminos son INCONSISTENTES. Impacto medido (Control Ale.room, gable 4.8×3.9×3.1, V=69): con 2 materiales custom sin cargar, paredes+techo quedan rígidas → RT explota → **f_S ~1100 Hz (falso)**; el f_S correcto con materiales resueltos es **~180 Hz** (Sabine 174 / perturbación 182, coinciden). A auditar/arreglar: (A) material no resuelto debe caer al default del mapa (o α=0.03) y AVISAR, no volverse rígido en silencio; (B) el guardado del `.room` debe embeber los materiales usados (`embedded_materials` salió vacío). Ver [[bug-material-no-resuelto-rigido]] en memoria.
- **Material→impedancia por default (FUERA del solver — es wiring + criterio):** `impedance_defaults.classify_material` propone un spec por material (keyword-driven); los specs entran a la física solo si el usuario los APLICA (pasan a `_construction_map` → `build_surface`, el camino ya auditado). Re(β)=α del material sigue intacto para lo no aplicado. Criterio del usuario: modelo solo con evidencia textual; inespecíficos sin modelo. A auditar si se vuelve default-ON algún día: la estimación de σ (de `sigma_from_alpha` o típica) y que la reactancia estimada no reintroduzca el sesgo M1. `bench_impedance_defaults` 52/52, `bench_impedance_defaults_wiring` 14/14. El hover-3D y las sugerencias son GUI.

## v2.53 — composición parche↔impedancia, renombre y editor de parches (30 Sep 2026, un punto físico, resto GUI)

- **Composición parche↔impedancia de cara (EN ALCANCE pero SIN cambio de solver — VERIFICAR el claim):** el autor afirma que la física YA componía correctamente y que solo se removió una política de UI. A auditar contra `absorption_patch.compute_xi_shift_with_impedance`: cada punto del teselado se asigna a UN solo slot (huella del parche → Z del parche; resto de la cara → Z de la cara), con peso `area·φ²·cover`. (1) ¿la partición es realmente disjunta (ningún punto cuenta dos veces, ninguna área se pierde)? el bench W8 mide, con solo el host wall aportando Im(β), que Im(δ_compone)/Im(δ_full) ∈ [0,1] por modo y que override(parche hereda)==pared-entera |Δf|=0 (partición exacta), pero eso NO prueba el caso multi-pared con varias Im simultáneas. (2) el camino unificado sigue a incidencia NORMAL (θ=0), como desde 5b. (3) se quitó `_resolve_patch_finish_conflicts` (forzaba herencia); ahora un parche-material sobre cara-impedancia compone por default → el resultado por default de un .room viejo con esa combinación CAMBIA (el parche ya no se descarta). Verificar que eso es lo deseado y no una regresión silenciosa para proyectos previos.
- **Renombre «Construcción de pared» → «Impedancias»:** solo strings de UI; `_construction_map` y el wiring intactos. Fuera de alcance físico.
- **Editor de parches (mover + hover α):** `patch_dialog` geométrico/IO (clamp al bbox de la cara + rechazo de solape via `polys_overlap`, traslación por `AbsorptionPatch.translate`) y de presentación (mini-α con `plot_utils.draw_alpha_curve`). NO toca la física; el α que entra al modelo no cambia por mover el parche (misma geometría u-v, solo trasladada). `bench_patch_move_hover` 15/15, `bench_capa0_all` 190/190.
- **Planeado (NO implementado):** `plan_impedancias_default.md` (material→impedancia por default, keyword-driven, inespecíficos sin modelo). Cuando se implemente, el punto caliente para el auditor será la ESTIMACIÓN de parámetros (espesor/σ/densidad) y que la reactancia resultante NO reintroduzca el sesgo M1 (solo con evidencia textual, etiquetada, editable; Re(β)=α exacto).

## v2.52 — Helmholtz y multicapa expuestos en la GUI (30 Sep 2026, FUERA DE ALCANCE DE SOLVER, un punto físico a mirar)

Solo se tocó `ConstructionEditorDialog` (acoustic_panel.py): se agregaron al editor de «Construcciones de pared…» dos modelos que YA existían en `impedance.py` y ya estaban dentro del alcance de auditoría (`helmholtz(...)`, `multilayer(specs)`). El solver, el ensamblaje FEM, la perturbación y `build_surface` NO cambiaron. La GUI solo produce el `spec` dict; la física lo consume por el único punto `imp.build_surface(spec)` (sin whitelist), igual que perforado/membrana/poroso. Puntos para el auditor:

- **Helmholtz distribuido sobre `wall_area` (afirmación del autor, verificar):** el editor pide área de cuello S, largo l, volumen V y **área de pared A**, y mapea al facing perforado equivalente con `ratio=S/A`, `D=V/A` (impedance.helmholtz). La resonancia f₀=(c/2π)√(S/(l_ef·V)) es **independiente de A** (correcto para un Helmholtz concentrado), pero la MAGNITUD de la admitancia superficial sí escala con 1/A: el modelo reparte un dispositivo concentrado como impedancia uniforme sobre A. A auditar: (1) ¿es física esa uniformización cuando el resonador es chico frente a A y frente a la longitud de onda modal? es la misma hipótesis del panel perforado, pero acá el «orificio» es un solo cuello; (2) el bench nuevo mide el pico de α cerca de f₀ (117 vs 113 Hz), NO valida el nivel de absorción contra un Helmholtz medido (no hay oráculo de dato propio).
- **Multicapa (pila TMM):** el editor arma `layers` (poroso/aire, superficie→fondo) que van a `multilayer()` → `_surface_Z_tmm` (Cox 5.24-5.25, YA auditado en Etapa 1a/2a). El bench nuevo verifica que una multicapa de **1 sola capa porosa ≡ `porous()`** (max|Δβ|=0, atadura al camino validado) y que α∈[0,1]. A auditar: el ORDEN de las capas (la UI dice «superficie→fondo»; `_surface_Z_tmm` procesa `reversed(layers)` con la más profunda viendo el backing rígido) → confirmar que «capa 1 en la lista» = la que da a la sala.
- **Bench `bench_capa0_5d.py` (22/22)** integrado a `bench_capa0_all` (Etapa 5d); total Capa 0 **186/186**. Es GUI-level (QApplication offscreen), no reemplaza la auditoría física de `helmholtz`/`multilayer` contra la fuente, que sigue siendo la de Etapa 1a/2a/3.

## v2.51 — batch de UI/UX (29 Sep 2026, MAYORÍA FUERA DE ALCANCE FÍSICO; un punto a mirar)

Casi todo es interfaz (botones, ventanas, arrastre en Z, grillas de coordenadas XZ/YZ como referencia visual, todo `viewer.py`/`style.py`). NO toca el solver, ni la FRF, ni el campo, ni los modos. El único punto con relevancia para el auditor:

- **`acoustic_panel._snap_source_into_domain` ganó un FALLBACK por superficie.** Antes: si no había `modal_result` (FEM), devolvía la posición sin tocar. Ahora: sin FEM cae a `points_inside_surface` (rayo 1-dirección) para frenar que una fuente arrastrada se vaya lejos del recinto. A auditar: (1) `points_inside_surface` da FALSOS "adentro" en techo NO-convexo (es la causa raíz del bug -500, ver v2.48) → el fallback NO clampa bien la cáscara del alero; solo el camino FEM (con modos) lo hace. Está declarado en el docstring y en el MANUAL. (2) El snap solo se dispara en el DRAG interactivo del visor (`main._on_source_moved_from_viewer`), no en el optimizador ni en el cálculo de FRF/campo (esos usan el `inside_fn` de tets de v2.48, intacto). Así que este fallback no puede reintroducir la recta -500 en la FRF (esa sigue guardada por A1/A3). (3) el `centroid` del march en el caso superficie es la media de vértices de superficie, que para un recinto muy no-convexo podría caer fuera; el march igual solo devuelve un punto que pasa el test `_in`, así que no empeora respecto de no clampar.

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
