# Plan: modelado de impedancia de superficie (Capa 0)

> Estado: **borrador de diseño** (23 Ago 2026). Aprobado en discusión: β compleja
> (Re+Im), techo poroso Miki+JCA en Etapa 1, carga de Z medida por f y por ángulo.
> Núcleo numpy+scipy puro (D0). No tocar la API pública del solver.

---

## 0. Objetivo y encuadre

Reemplazar el eslabón más débil de la cadena de amortiguamiento: hoy la absorción
colapsa en `face_materials.beta_from_alpha_random(alpha)` ([face_materials.py:600](face_materials.py:600)),
que invierte Paris asumiendo **Z real + reacción local**. Su propio docstring lo
marca como "el supuesto más débil de la cadena; para materiales con cámara de aire
es aproximado".

**Capa 0** es un módulo ortogonal (`impedance.py`) que produce la **admitancia
específica compleja** β(f) (o β(f,θ)) de una construcción de pared, desde un modelo
físico o desde una medición del usuario. Alimenta la perturbación de frontera; no
toca el ensamblaje FEM ni la forma modal (paredes siguen rígidas para φₙ, D3).

Alineado con §0 del norte: exactitud física por sobre comodidad; respetar las
condiciones de validez de cada modelo; validar contra analítico / exacto / medición;
reportar el régimen de validez.

---

## 1. Física

### 1.1 Admitancia específica y su rol en la perturbación

β = ρ₀c / Zₛ = ρ₀c · Yₛ (adimensional). La perturbación de frontera de 1er orden
(Morse & Ingard, *Theoretical Acoustics* §9.4; Kuttruff, *Room Acoustics* §3.3-3.4)
para un modo M-ortonormalizado (∫φ²dV=1) es:

$$\Delta(k_n^2) = -\,i\,k_n \oint_{\partial\Omega} \beta\,\phi_n^2\,dS$$

Descomponiendo en parte real e imaginaria de β = G + iB:

$$\delta_n = \frac{c}{2}\sum_g \mathrm{Re}(\beta_g)\oint_g \phi_n^2\,dS\quad[\text{Np/s, amortiguamiento}]$$
$$\frac{\Delta f_n}{f_n} = -\frac{c}{2\,\omega_n}\sum_g \mathrm{Im}(\beta_g)\oint_g \phi_n^2\,dS\quad[\text{corrimiento de frecuencia}]$$

El corrimiento por reactancia de pared es el efecto nuevo que Capa 0 desbloquea
(un modelo de pared rígida no lo ve). ξₙ = δₙ/ωₙ como hasta ahora.

### 1.2 Reacción local vs. extendida (el punto de "Z por ángulo")

- **Local:** Zₛ = Zₛ(f). β entra directo. Es lo que hay hoy y lo que da Kundt (normal).
- **Extendida:** Zₛ = Zₛ(f,θ). Cada modo golpea cada pared con su ángulo. En shoebox
  el ángulo del modo (l,m,n) en la pared es exacto: cosθ = k_normal/|k|. En geometría
  irregular no hay ángulo único → se estima el espectro angular local de φₙ en la
  pared (aproximación, se valida numéricamente). **Derivación original** (sin cita).

### 1.3 Modelos de material (escalera de fidelidad)

| Modelo | Entrada | Validez | Referencia |
|---|---|---|---|
| Rígido | — | β=0 (solo aire) | — |
| Resistivo real | β real | puente con Paris | face_materials actual |
| **Delany-Bazley** (1970) | σ | 0.01 < ρ₀f/σ < 1.0 | Allard&Atalla cap. 2; Miki 1990 |
| **Miki** (1990) | σ | extiende D-B a baja f, Re(Z_c)>0 | Allard&Atalla; Radičević (survey) |
| **JCA** | φ, α∞, σ, Λ, Λ' | fluido equivalente, marco rígido/limp | Allard&Atalla cap. 5; Bruneau&Potel |
| Cámara de aire | D | capa de aire (Snell + TMM) | Allard&Atalla cap. 11 (TMM) |
| Resonantes (perf/membrana/Helmholtz) | geometría | Etapa 3 | Cox&D'Antonio 6-7; Fuchs; Allard (facings) |
| **Z medida (f)** | tabla | local, patrón-oro parcial | tu Kundt |
| **Z medida (f,θ)** | tabla 2D | extendida, patrón-oro | tu medición angular |

Fórmulas empíricas (Delany-Bazley), con X = ρ₀f/σ:
$$Z_c = \rho_0 c\left[1 + 0.0571 X^{-0.754} - i\,0.087 X^{-0.732}\right],\quad k_c = \frac{\omega}{c}\left[1 + 0.0978 X^{-0.700} - i\,0.189 X^{-0.595}\right]$$
(Miki: mismos términos, otros exponentes/coeficientes; se pinchan del PDF al implementar.)

TMM: matriz de transferencia de una capa (espesor d, Z_c, k_c), componente normal k_z:
$$T = \begin{bmatrix}\cos(k_z d) & i Z_c \sin(k_z d)/\cos\theta_c \\ i \cos\theta_c \sin(k_z d)/Z_c & \cos(k_z d)\end{bmatrix}$$
Cascadeo de capas + backing rígido (v=0) → Zₛ = T₁₁/T₂₁. Para θ se arrastra Snell
sin θ_c = (k₀/k_c) sin θ. Para reacción local se fija θ=0.

---

## 2. Arquitectura

**`impedance.py`** (núcleo puro, sin GUI). Clase/estructura `SurfaceImpedance` con:
- `.Z(f)` y `.Z(f, theta)` → complejo (Pa·s/m); `.beta(f[,theta])` → ρ₀c/Z.
- `.alpha_random(f)` y `.alpha(f, theta)` → para validar contra catálogo ISO 354.
- `.is_locally_reacting` → bool (los modelos con ángulo o Z(f,θ) medida = False).

Constructores (funciones fábrica):
- `rigid()`
- `resistive(beta_real)` (puente con Paris)
- `porous(sigma, thickness, model="miki", backing="rigid", air_gap=0.0)`
- `porous_jca(phi, alpha_inf, sigma, Lambda, Lambda_p, thickness, backing=...)`
- `multilayer([layer, ...])` (TMM general)
- `measured_Zf(freqs, Z)` (local)
- `measured_Zft(freqs, thetas, Z)` (extendida)

Consumidor: `face_materials.perturbation_xi_per_mode` cambia la línea 704 por pedir
β al `SurfaceImpedance` del material (evaluada en (fₙ, θₙ) si es extendida), y
devuelve además el corrimiento Δfₙ (nuevo, opcional).

Material → construcción: campo opcional `construction` en el JSON del material y/o un
diálogo "Construcción de pared" (Etapa 5, wiring). Sin construcción → cae a α→β
(default, reproducibilidad, estilo Etapa 3 de la perturbación de frontera).

---

## 3. Escalonamiento

- **Etapa 1a [HECHA] — motor local empírico:** `impedance.py` con rigid/resistive/
  porous (Delany-Bazley + Miki) + cámara de aire + TMM + measured_Zf. β compleja
  local. `bench_impedance.py` 22/22 (rígido→β=0; resistivo→reproduce Paris bit a bit;
  poroso+cámara→pico λ/4 exacto; α(f) sana; DB no físico en graves, Miki sí).
- **Etapa 1b [HECHA] — JCA:** `jca_zc_kc` + `porous_jca` (fluido equivalente, 5
  params: φ, α∞, σ, Λ, Λ'; Cox Ec 5.15/5.16 = Johnson et al./Allard-Champoux).
  Convención i-física = -j-ingeniería (por eso NO se conjuga). `bench_impedance.py`
  T8 (28/28 total): convención coherente con Miki (Im k_c<0); fibroso ≈ Miki (Z_c
  <12%, α_random dif <0.073); físico α∈[0,1]; cámara sube graves.
- **Etapa 1c [HECHA] — perturbación compleja:** `perturbation_xi_shift_per_mode`
  (β compleja → Re=amortiguamiento ξ, Im=corrimiento de fₙ). Cuadratura de superficie
  factorizada en `_modal_surface_integrals` (fuente única). Convención: solver
  e^{+iωt}, impedance.py e^{-iωt} → conj(β) al conectar. `bench_perturbation_complex.py`
  11/11 (puente real bit a bit; vs QEP complejo exacto <3% con matching por autovector;
  corrimiento reactivo +5..+11 Hz validado).
- **Etapa 2 [HECHA] — reacción extendida:** (2a) TMM oblicuo (Snell, k_z=√(k_c²−k_t²),
  z_n=z_c·k_c/k_z) → `SurfaceImpedance.Z(f,θ)`; `measured_Zft` (Z(f,θ) bilineal);
  `is_locally_reacting` por constructor. `bench_impedance.py` 36/36. (2b)
  `_modal_incidence_angles` (θ por modo por pared = arccos√(1−k_t²/|k|²), k_t² del
  cociente de Rayleigh de la energía de Dirichlet de superficie; exacto en shoebox,
  aprox. en irregular = derivación propia) + `perturbation_xi_shift_extended`.
  `bench_extended_reaction.py` 7/7 (θ estimado vs analítico: mediana 2.4°, media 6.3°;
  puente local bit a bit; extendida ≠ normal en ξ un 47%).
- **Etapa 3 [HECHA] — resonantes (física, aislada):** facings sobre cavidad vía el
  TMM ya existente. `impedance.py`: `maa_zface` (panel (micro)perforado, Maa 1998
  Ec 2-4: r + iχ con constante de perforado x=(d/2)√(ωρ₀/η)), `membrane_zface`
  (masa-resorte, Z=ρ₀c·damping + iωm). Convención atada a la cámara de aire del
  módulo: resorte = Im(Z)<0, masa = Im(Z)>0. Constructores: `perforated`,
  `microperforated` (alias), `membrane`, `helmholtz` (cuello+cavidad concentrado
  → facing perforado equivalente), todos vía facing EN SERIE (`_facing_surface`)
  con backing por TMM (`_facing_backing`: relleno poroso opcional + cámara).
  `bench_resonant_facings.py` **21/21**: (T1) pico de α EXACTAMENTE en el cero de
  reactancia; la fórmula lumped f₀=(c/2π)√(ε/(t_ef·D)) es su límite k₀D→0 (con
  cavidad de cm, k₀D~1 → se aparta ~15%, límite conocido del Helmholtz
  concentrado). (T2) membrana f₀=60/√(m·D) exacto. (T3) Maa: r crece al achicar d
  (perforado→MPP), MPP da banda ancha sin poroso. (T4) α∈[0,1] y Re(Z)≥0
  (pasividad) en banda y ángulos. (T5) el CORRIMIENTO de fₙ CAMBIA DE SIGNO al
  cruzar la resonancia (Im(Z): resorte<0 en graves → masa>0 en agudos →
  sign(f_new−fₙ)=sign(Im(β)) se invierte). (T6) relleno poroso sube α en graves.
  (T7) helmholtz resuena en f₀ analítico. No-regresión: bench_impedance 36/36,
  extended 7/7, perturbation_complex 11/11.
- **Etapa 4 [HECHA] — auditoría integral de Capa 0 (verificación, antes de
  conectar).** `bench_capa0_audit.py` **33/33** + suite unificada `bench_capa0_all.py`
  (corre las 5 etapas en procesos aislados; **108/108 total**). (A1) geometría
  IRREGULAR (pentágono/hexágono+taper/caja+twist) sobre `_modal_incidence_angles`
  y `perturbation_xi_shift_{per_mode,extended}`: sin NaN/inf, θ∈[0,88°], ξ≥0 y
  COBERTURA completa (ninguna pared con Sg=0 → caza nan_to_num→0 y pérdida de área
  A1/A2). (A2) pasividad Re(β)≥0 (=Re(Z)≥0) y α∈[0,1] en los 11 constructores ×
  banda 20-5000 Hz × 6 ángulos + α_random. (A3) validez por modelo: DB≈Miki en
  0.01<X<1, DB no físico (α<0, no Re(Zc)<0) a X<0.01, banda modal de sala tratada
  cae en X<0.01 (por eso Miki default). (A4) convención end-to-end: con cámara cuya
  λ/4 cae en la banda modal, la ley sign(f_new−fₙ)=−sign(Im Z(fₙ)) se cumple modo
  a modo y aparecen AMBOS signos. (A5) convergencia: θ al refinar la MALLA (npm
  2.0→3.2, Δθ<6°); ξ al refinar la CUADRATURA (subdiv 1→2→3, |ξ₂−ξ₃|≪|ξ₁−ξ₃|, el
  knob real es subdiv no la malla). (A6) call-path: rígido→ξ=0; firma faltante→
  default_surf (idéntico a asignar a todas) y sin default→rígido (β=0); measured_Zf
  extrapola constante en el borde; grupos vacíos→None (guardas explícitas, sin
  padding silencioso).
- **Etapa 5 — wiring a la app (integración, SEPARADA).** Decisiones (discutidas con
  el usuario): el corrimiento de fₙ **propaga a la física** (FRF/campo/FoM usan f_new,
  la forma modal sigue rígida = perturbación de 1er orden); la construcción se ancla
  **a la cara/grupo** (mapa `construccion_por_cara` paralelo al FaceMaterialMap).
  - **Etapa 5a [HECHA] — núcleo headless.** `impedance.build_surface(spec)` +
    `spec_label` ((de)serialización JSON de toda SurfaceImpedance; el spec es la fuente
    de verdad persistible). Panel: `self._construction_map` {signature: spec},
    `_construction_surf_by_group` (construcción → SurfaceImpedance; cara sin
    construcción → `_material_surface` = resistiva del α(f), puente exacto con α→β),
    `_effective_modal_freqs`, y camino nuevo en `_compute_xi_from_materials` (si hay
    construcciones y modelo perturbación → `perturbation_xi_shift_extended`, cachea
    f_new). Propagación: `run_fem_frf(modal_freqs=...)` (param aditivo), FoM y
    marcadores del FRFDialog usan las frecuencias efectivas. Persistencia `.room` v9
    (`wall_constructions`, aditivo: <v9 sin la clave → mapa vacío → α→β,
    reproducibilidad). `bench_capa0_wiring.py` **9/9**: serialización JSON,
    reproducibilidad FRF(None)==FRF(freqs) bit a bit, puente material==α→β, la
    construcción produce corrimiento que MUEVE la FRF (dif rel 158%), mezcla
    construcción+material. Suite `bench_capa0_all.py` **117/117**. Pendiente en 5a
    (documentado): composición con parches sub-cara (por ahora construcciones tienen
    prioridad y avisan); shift en f_S/RT60/SBIR (dominados por ξ, ya correcto; el
    corrimiento de ω es refinamiento de 5c).
  - **Etapa 5b — diálogo "construcción de pared" + asignación por cara en la GUI**
    (perforado/MPP/membrana/poroso/multicapa/Helmholtz con inputs de parámetros).
  - **Etapa 5c — carga de mediciones Z(f)/Z(f,θ) + mostrar Δfₙ y ξ en FRF/Ver-RT60**
    + composición con parches + shift en el resto de consumidores.
  Default sigue α→β hasta que el usuario asigna construcción.

---

## 4. Validación (escalera, §0)

1. Rígido → recupera modos rígidos actuales (bit a bit).
2. Z resistiva real → reproduce el α→β de Paris de hoy.
3. Poroso + cámara λ/4 → pico de α(f) en la resonancia; comparar con α(f) de catálogo.
4. β compleja → contra QEP complejo (matriz C), <1% como la perturbación.
5. Z medida → tu dato (patrón-oro, protocolo §6c).

Cada etapa cierra con su `bench_*.py` verde antes de avanzar.

---

## 5. Referencias (con lo que aporta cada una)

- **Allard & Atalla**, *Propagation of Sound in Porous Media* (2ª ed): D-B, Miki, JCA/JCAL,
  Biot, TMM angular. Núcleo teórico.
- **Bruneau & Potel**, *Materials and Acoustics Handbook*: segundo respaldo riguroso JCA/Biot.
- **Bies & Hansen**, *Engineering Noise Control* (4ª ed): tablas y fórmulas de σ por densidad.
- **Fuchs**, *Applied Acoustics: Absorbers and Silencers*: resonantes/membrana/MPP (Etapa 3).
- **Cox & D'Antonio**, *Acoustic Absorbers and Diffusers* (2ª ed) cap. 6-7: devices resonantes.
- **Radičević**, *Models for Predicting Sound Absorption*: survey comparativo D-B/Miki/JCA.
- **Aygun**, *Sound absorbing materials*: props de material, valores de σ.
- **Morse & Ingard**, *Theoretical Acoustics* §9.4: perturbación de frontera (compleja).
- **Kuttruff**, *Room Acoustics* §3.3-3.4: modos con paredes amortiguadas (shoebox).
- **Desmet & Vandepitte**, *FEM for Acoustics*; **Ihlenburg**: matriz C de impedancia (validación exacta).

**Sin referencia (derivación propia, se valida numéricamente):** perturbación con
reacción extendida en geometría irregular (proyección del espectro angular de φₙ).
