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
diálogo "Construcción de pared" (Etapa 3). Sin construcción → cae a α→β (default,
reproducibilidad, estilo Etapa 3 de la perturbación).

---

## 3. Escalonamiento

- **Etapa 1a — motor local empírico:** `impedance.py` con rigid/resistive/porous
  (Delany-Bazley + Miki) + cámara de aire + TMM + measured_Zf. β compleja local.
  Bench: rígido→β=0; resistivo→reproduce Paris; poroso+cámara→pico λ/4; α(f) sana.
- **Etapa 1b — JCA:** `porous_jca` (fluido equivalente). Bench: JCA reduce a límites
  conocidos; contra figuras de Allard&Atalla; alta σ → Miki.
- **Etapa 1c — perturbación compleja:** generalizar `perturbation_xi_per_mode` a
  β compleja (Re→δ, Im→Δf). Bench: contra QEP complejo exacto (matriz C) <1%;
  β real reduce bit a bit al resultado actual.
- **Etapa 2 — reacción extendida:** `measured_Zft` + ángulo por modo (exacto shoebox,
  aprox. irregular, marcado en pantalla). Bench: oráculo shoebox.
- **Etapa 3 — resonantes + UI:** perforado/membrana/Helmholtz + diálogo construcción
  + carga de mediciones + `.room` (aditivo). Default sigue α→β hasta que el usuario
  asigna construcción.

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
