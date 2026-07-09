# Plan — Respuesta en frecuencia + fase por fuente

> **Estado:** Fases 0, 1, 2 y 2c IMPLEMENTADAS (16 Jun 2026). Falta wiring
> a UI/Predicción de las métricas 2c, y Fase 3 (data real).
> **Fecha:** 12 Jun 2026 (plan) · 16 Jun 2026 (Fases 0-2c).

> ## ⚠️ DECISIÓN DE IMPLEMENTACIÓN (16 Jun 2026) — leer antes que §2/§3.1
>
> **La respuesta de fuente se implementó como GANANCIA compleja `g(f)`
> relativa al Q baseline (opción 1), NO como SPL absoluto.**
>
> `effective_Q_spectrum(f) = effective_Q() · g(f)`, con `g` adimensional.
> "Sin curva" ≡ `g ≡ 1` → FRF baseline bit a bit.
>
> **Por qué (corrige una inconsistencia de este plan):** §2 y §3.1 afirman que
> "curva SPL plana = sensibilidad constante de hoy → FRF idéntica". **Es
> falso.** Hoy el código usa `q_from_sensitivity` → **Q constante** en `f`
> (lo que implica SPL subiendo +6 dB/oct, porque `|p| ∝ ω·|Q|`). Un SPL
> plano daría `Q(f) ∝ 1/f`, que NO es el comportamiento de hoy. Por eso el
> oráculo de regresión y el modelo interno se anclan a `g(f)` sobre el Q
> actual, no a SPL absoluto. El **SPL absoluto del FRD real entra en Fase 1**
> como `g(f) = Q_FRD(f)/Q_base` con el toggle de anclaje (§6). El mapeo
> SPL→Q de §3.1 sigue siendo correcto para esa conversión; sólo se aclara
> que NO se usa como "curva plana = hoy".
>
> **Implementado en Fase 0:** `sources.SourceResponse` (g(f) como
> gain_db+phase_rad), `synth_response` (5 oráculos), `OmniSource.response`,
> `effective_Q_spectrum`, `SourceArray.amplitudes_spectrum`; integración en
> `acoustic_fem.frequency_response`/`modal_pressure_field`. Oráculos en
> `bench_source_response.py` (todos pasan).
>
> **Implementado en Fase 1:** `frd.py` (`load_frd` parser tolerante +
> `minimum_phase` Hilbert con reflect-pad), `SourceResponse.from_frd` con
> anclaje **absoluto** (`g=Q_FRD/q_base`) y **relativo** (`g=Q_FRD/|Q_FRD(f_ref)|`),
> `to_dict`/`from_dict`, y persistencia **`.room` v5** (`main.py`: serializa y
> reconstruye `sources[i].response`; v4 sin `response` → Q constante). Tests en
> `bench_frd.py`.
>
> **Implementado en Fase 2 (UI):** grupo "Respuesta en frecuencia Q(f)" en
> `acoustic_panel.SourceEditDialog` — botón Cargar FRD… / Quitar, combo de
> anclaje (absoluto/relativo), atajo manual delay+polaridad, preview mag+fase,
> y `get_source()` que preserva la curva. Re-horneado del anclaje absoluto al
> cambiar la sensibilidad (guarda el FRD crudo). `_duplicate_source` copia la
> curva. Verificado headless (offscreen); **falta test visual humano**.
>
> **Implementado en Fase 2c:** `modal_metrics.py` — §8 FoM (`FoM_flat` +
> `FoM_espacial`, con ξₙ + suavizado energía 1/N oct + grilla de receptores) y
> §9 cruce modal numérico (`modal_overlap_crossover`, densidad numérica que ve
> la forma; recupera Schroeder con densidad de Weyl). Oráculos en
> `bench_modal_metrics.py`. **Capa de cómputo lista, SIN wirear a UI/Predicción**
> (próximo paso: mostrar f_cross junto a f_Schroeder, FoM junto a la FRF,
> alimentar `_score_schroeder`). Pendiente además **Fase 3** (data real).
> **Objetivo del usuario:** simular cada vez más la situación real de un
> recinto para el estudio de su distribución modal, incorporando **fuentes
> reales** medidas (respuesta en frecuencia + fase). Mediciones a obtener de
> colegas; mientras tanto se valida con curvas sintéticas.

---

## 1. Evaluaciones previas (rationale de las decisiones)

Esta sección documenta el razonamiento que llevó al alcance del plan. Se
conserva para no re-discutir.

### 1.1 Directividad (patrón polar) — DESCARTADA

**Decisión:** no se implementa directividad de fuentes.

**Por qué:** el régimen modal es baja frecuencia, justo donde los parlantes
son **casi omnidireccionales**. Para una sala típica (V≈100 m³, RT≈0,5 s),
`f_Schroeder ≈ 2000·√(0,5/100) ≈ 141 Hz`. El FEM es válido por debajo de eso
(y de `f_max_malla`). A 140 Hz, λ≈2,45 m; un parlante recién se vuelve
direccional cuando su baffle/cono ~ λ/2 (un woofer de 30 cm: arriba de
~570 Hz). En la banda donde el FEM es la herramienta correcta, el patrón
polar medido es prácticamente plano (±1–2 dB frente/atrás, por baffle step /
difracción de bordes, no por beaming real).

**Conclusión clave:** el dominio donde la directividad importa (cientos de Hz)
y el dominio de validez del FEM (≤ Schroeder) **casi no se solapan**.
Modelar directividad sería gastar cómputo y complejidad de UX sin sumar
rigurosidad en la banda de interés.

*(Si en el futuro se quisiera de todos modos: el camino sería multipolo de
bajo orden — monopolo + dipolo = cardioide — acoplando el dipolo al gradiente
del modo `∇φₙ(xₛ)`, que es casi gratis porque sale de `self.A_inv` del
`FieldEvaluator`. Pero NO es parte de este plan.)*

### 1.2 Distinción rigurosa: distribución modal vs respuesta forzada

| Objeto | ¿Depende de la fuente? | ¿Lo toca `Q(f)`? |
|---|---|---|
| **Distribución modal** (`fₙ`, `φₙ`) | **No** — sale de `K φ = λ M φ`, propiedad pura del recinto + bordes | **No** |
| **Respuesta forzada** (FRF, campo \|p\|, audio) | **Sí** — producto (sala) × (fuente) | **Sí** |

- Los modos (dónde están, qué forma tienen) **no cambian** con la fuente.
- El efecto "distancia a las paredes" **ya está capturado** y es exacto hoy:
  es `φₙ(xₛ)`, el valor de la forma modal en la fuente.
- Lo que `Q(f)` hace más real es la **respuesta forzada**: qué respuesta
  mediría el usuario (sweep tipo REW), qué se escucha, y **cómo interfieren
  varias fuentes**.

### 1.3 Cost-benefit de `Q(f)` + fase (4 ejes)

| Eje | Veredicto | Detalle |
|---|---|---|
| **Cómputo** | Casi nulo | `num` pasa de `(Nm,)` constante a evaluarse por frecuencia: matvec `(Ns,)@(Ns,Nm)` con `Ns`=1–4. Sobre 1000 frecuencias y `Nm`=500 son ~μs. FRF sigue <5 ms. |
| **Lectura/escritura** | Trivial | FRD = ASCII de KB. Curva embebida en `.room` v5 (~pocos KB de JSON). `.room` viejo → fallback a `Q` constante de hoy. |
| **UX** | Costo real, dial-able | Único eje con costo no despreciable. Ver tiers en §1.4. |
| **Rigor científico** | Sí, real | Reemplaza una **suposición arbitraria** (Q plano, fase 0) por **dato medido**. Información **nueva e independiente** (pasa el test de D5b: no es el mismo dato reempaquetado). No degrada nada: se multiplica en el numerador, no toca damping modal ni calibración c². |

**Argumento de rigor más fuerte — multi-fuente:** el acople es
`Σₛ Qₛ·φₙ(xₛ)`. Con `Qₛ` reales constantes solo se simula "perfectamente en
fase". La interferencia modal entre subs (constructiva donde `φₙ` tiene igual
signo, destructiva donde opuesto) vive **enteramente en la fase relativa**.
Caso hoy imposible: **alinear dos subs en tiempo** (un delay `τ` es
`Q(f)=e^{-i2πfτ}`, fase lineal; con `Q` constante no se puede representar).

### 1.4 Decisión de alcance

- **Directividad:** fuera.
- **`Q(f)` + fase:** se implementa. Compute y storage gratis; rigor real en la
  respuesta forzada; costo concentrado en UX.
- **Tier elegido:** **B — FRD completo (magnitud + fase) por fuente**, porque
  el usuario quiere cargar mediciones reales de fase y respuesta. (El Tier A
  —delay+polaridad— queda subsumido: un delay/polaridad es un caso particular
  de `Q(f)`, así que se puede ofrecer también como atajo manual sin archivo.)

---

## 2. Estrategia de validación con datos sintéticos

La "respuesta de mentira" no es solo placeholder de UX: si se elige con
**comportamiento analítico conocido**, es el **oráculo de validación**
permanente. La data real entra por el mismo camino.

| Curva sintética | Definición | Verificación esperada |
|---|---|---|
| Plana 0 dB / 0° | `Q(f)=cte` (= sensibilidad actual) | FRF **idéntica a la de hoy** (`rtol<1e-10`). Invariante de regresión. |
| Delay puro | `Q(f)=e^{-i2πfτ}`, \|Q\|=1 | 1 fuente: \|H\| sin cambios, fase rota `-2πfτ` exacto. Fija el signo de la convención `e^{+iωt}`. |
| Polaridad −1 | fase = π constante | 2 fuentes opuestas: cancela/refuerza modos según signo de `φₙ` (§13.3 del doc técnico). |
| Pasa-altos 1 polo | \|Q(f)\|=`f/√(f²+fc²)` + fase mínima asociada | Modos debajo de `fc` reciben menos excitación (predecible). Simula rolloff de sub. |
| Pico resonante | bump gaussiano en \|Q\| | Respuesta no monótona; testea interpolación. |

Estas curvas se generan programáticamente (helper `synth_response(...)`) y
sirven como smoke tests en `__main__` y/o un `bench_*.py`.

---

## 3. Diseño técnico

### 3.1 Modelo de datos (la "variable a ingresar")

Una respuesta de fuente es una **función de transferencia compleja** `H(f)`.
Representación interna por fuente:

```
freq_pts : (Nf,) float   — frecuencias del archivo [Hz]
spl_db   : (Nf,) float   — magnitud [dB SPL @ 1 m] (o relativa, ver anclaje)
phase    : (Nf,) float   — fase [grados en archivo → radianes internos]
```

Mapeo a caudal volumétrico `Q(f)` reusando la física del monopolo que ya
existe (`q_from_sensitivity`), generalizada a por-frecuencia:

```
|p(f,1m)| = 20µPa · 10^(spl_db(f)/20)
|Q(f)|    = |p(f,1m)| · 4π / (2π f · ρ₀)        ← misma inversión, f_ref → f
Q(f)      = |Q(f)| · exp( i · phase_rad(f) )
```

> **Consistencia:** el SPL medido en campo libre a 1 m ya incluye el factor
> ω del monopolo; al invertir a `Q` recuperamos la **velocidad de volumen
> equivalente** del transductor, que es la cantidad correcta para inyectar
> en la suma modal (la Green modal del recinto vuelve a aplicar la respuesta
> de la sala). No hay doble conteo. El caso "sensibilidad constante" de hoy
> es el caso particular de una curva SPL plana → continuidad total.

### 3.2 Formato de archivo a ingerir: FRD

FRD (Frequency Response Data), el formato nativo de VituixCAD:

```
* comentarios opcionales con *
freq_hz   spl_db   phase_deg
20.00     78.3     -145.2
20.50     78.6     -144.8
...
```

- Separador: whitespace (a veces coma/tab según exporter) → parser tolerante.
- 2 columnas (sin fase) o 3 columnas (con fase). Si falta fase: opción de
  sintetizar **fase mínima** (Hilbert) o asumir 0.
- Frecuencias arbitrarias (log o lineal) → `np.interp` sobre `freq_axis` de
  la FRF. Fuera de cobertura: hold-flat en los bordes (documentar).

### 3.3 Puntos de integración en el código

**`sources.py`:**
- Extender `OmniSource` con campo opcional `response` (la curva, o `None`).
- `effective_Q_spectrum(freq_axis) -> (Nf,) complex`: muestrea `Q(f)` sobre
  el eje. Fallback (sin curva) = `effective_Q()` broadcasteado (comportamiento
  actual).
- `SourceArray.amplitudes_spectrum(freq_axis) -> (Nf, Ns) complex`.
- Mantener `effective_Q()` / `amplitudes()` para compat y el path de f única.

**`acoustic_fem.frequency_response`:**
- Reemplazar `src_arr = sources.amplitudes()` `(Ns,)` por
  `src_spec = sources.amplitudes_spectrum(freq_axis)` `(Nf, Ns)`.
- El acople pasa a depender de f: `coupling = src_spec @ phi_s` `(Nf, Nm)`.
- `num` por frecuencia: `num_i = phi_r * coupling[i]`. (Vectorizable a
  `(Nf, Nm)` y eliminar el loop Python, opcional.)

**`acoustic_fem.modal_pressure_field`:**
- A f fija: `src_arr = sources.amplitudes_spectrum(np.array([f]))[0]`.
  Cambio de una línea.

**Persistencia `.room` v5:**
- Serializar la curva por fuente bajo `acoustic.sources[i].response`.
- Bump de versión; loader retrocompatible (sin campo → `Q` constante).

**UI (`acoustic_panel.SourceEditDialog`):**
- Botón **"Cargar respuesta (FRD)…"** + preview chico (mag+fase) + botón
  "Quitar" para volver a sensibilidad plana.
- Mostrar cobertura ("FR: 20–200 Hz, 312 pts") e indicador de fuente con/sin
  curva.
- Decisión de **anclaje de nivel**: toggle "FRD fija nivel absoluto" vs
  "FRD solo da la forma; nivel desde sensibilidad".
- Atajo manual (sin archivo): campos **delay [ms]** y **polaridad [+/−]** que
  generan `Q(f)=±e^{-i2πfτ}` (caso particular, cubre alineación de subs).

### 3.4 Visualización — grilla de 1/3 de octava (ISO 266) en la FRF

**Objetivo:** que el gráfico de FRF muestre como **xticks las frecuencias
límite de las bandas de tercio de octava** (los bordes entre bandas), para
leer en qué banda cae cada pico modal. Consistente con las Tablas ISO 266 del
análisis modal (Gunawan 2018) y con los criterios tipo Bonello.

**Definición de los límites de banda:**

- Centros nominales ISO 266 [Hz]: 20, 25, 31.5, 40, 50, 63, 80, 100, 125,
  160, 200, 250, …
- Límite entre bandas adyacentes = **media geométrica de los centros**:
  `f_edge(i) = sqrt(fc_i · fc_{i+1})`. Garantiza bordes compartidos (el borde
  superior de una banda = el inferior de la siguiente). Equivale a `fc·2^(1/6)`
  con centros base-2.
- Bordes en rango modal [Hz]: 22.4, 28.1, 35.5, 44.7, 56.1, 71.0, 89.4,
  111.8, 141.4, 178.9, 223.6 …

**Implementación (`acoustic_panel.FRFDialog`):**

- `ax.set_xscale('log')` — el tercio de octava es log-equiespaciado; la grilla
  queda pareja visualmente.
- xticks fijos en los bordes dentro de `[f_min, f_max]`:
  `ax.xaxis.set_major_locator(FixedLocator(edges))`.
- Etiquetas en Hz enteros con `FuncFormatter` (evitar la notación `10^x` por
  defecto del eje log).
- Apagar minor ticks automáticos del log (`set_minor_locator(NullLocator())`)
  para no ensuciar.
- Grilla vertical tenue en los bordes (`ax.grid(True, which='major',
  axis='x', alpha=0.3)`) — el look "1/3 oct" tipo REW.
- Las líneas naranjas de modos se siguen dibujando encima; ahora se lee en qué
  banda cae cada modo.

**Helper reutilizable:** `third_octave_edges(f_min, f_max) -> np.ndarray` en un
módulo de utilidades (ej. `audio_utils` o nuevo `plot_utils`), para reusar en
otros gráficos si se quiere consistencia.

**Alcance:** objetivo primario la FRF. Opcional extender al diálogo de RT60
(ya es por bandas). No aplica al heatmap de slice (es espacial, no en f).

**Independencia:** este ítem NO depende de `Q(f)`; se puede implementar y
shippear antes que las Fases 0–3.

---

## 4. Fases de implementación

| Fase | Alcance | Entregable | Depende de |
|---|---|---|---|
| **0** | Núcleo + sintéticos (sin UI) | Modelo de datos, `synth_response`, `q_from_spl_curve`, integración en `frequency_response` y `modal_pressure_field`, smoke tests con las 5 curvas oráculo | — |
| **1** | Importador FRD + persistencia | Parser FRD tolerante, interpolación, anclaje de nivel, `.room` v5 embebido | Fase 0 |
| **2** | UI | Botón cargar/quitar en `SourceEditDialog`, preview, indicador, atajo delay/polaridad | Fase 1 |
| **2b** | Grilla 1/3 oct en FRF | xticks en límites de banda ISO 266 en `FRFDialog` (§3.4) | **Independiente** — puede ir antes |
| **2c** | Figura de mérito + cruce numérico | σ_SPL amortiguado/espacial (§8) y cruce por solapamiento modal (§9) | Necesita modos + ξₙ (ya existen) |
| **3** | Validación con data real | Cargar mediciones de los colegas; sanity checks; (opcional) comparar sim vs medición en sala real | Fase 2 + mediciones |

**El usuario pidió arrancar por la Fase 0** (sintéticos) para ver el efecto
antes de tener mediciones reales.

---

## 5. Métricas de éxito

- **Regresión:** curva plana sintética → FRF idéntica a la actual,
  `rtol < 1e-10`.
- **Delay:** `τ` en una fuente → \|H\| sin cambios, pendiente de fase
  `-2πτ` exacta (signo correcto).
- **Multi-fuente:** dos fuentes con Δτ → corrimiento verificable de la
  interferencia modal; polaridad opuesta → cancelación según §13.3.
- **Rolloff:** pasa-altos `fc` → caída predecible de la excitación de modos
  bajo `fc`.
- **Cómputo:** `frequency_response` < 10 ms para `Nm`=500, `Nf`=1000.
- **Carga FRD:** parse + interp < 50 ms.

---

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Ambigüedad de anclaje de nivel (FRD calibrado vs relativo) | Toggle explícito en UI; default = anclar a sensibilidad en `f_ref`. |
| Cobertura de banda incompleta (FRD no cubre todo el eje FRF) | Hold-flat en bordes, documentado; avisar cobertura en UI. |
| Convención de signo de fase (`e^{+iωt}` del proyecto) | Validar con delay sintético (pendiente de fase con signo conocido). |
| Fase ausente en mediciones magnitude-only | Opción de fase mínima (Hilbert) o 0; avisar al usuario. |
| Dialectos de FRD según exporter | Parser tolerante; testear con header real de VituixCAD. |

---

## 7. Preguntas abiertas (a resolver antes de Fase 1)

1. **Header exacto del FRD de VituixCAD** — pegar las primeras ~5 líneas de
   un archivo real (separador, comentarios, si trae columna de fase).
2. **Calibración** — ¿las mediciones son SPL absoluto (dB @ distancia/drive
   conocidos) o relativas? Define el default de anclaje.
3. Confirmado: una sola curva on-axis por fuente (directividad fuera).

### Decisiones pendientes — extensiones motivadas por Gunawan 2018

(Discutidas el 12 Jun 2026; ver crítica del paper en el hilo. No aprobadas aún.)

4. **Figura de mérito mejorada.** El paper usa σ_SPL de **un punto** en sala
   **sin pérdidas** — frágil (su propia Tabla 6 muestra que mover el probe
   cambia σ en 1.3–1.9 dB, mientras el ranking se decide por 0.34 dB).
   Propuesta: σ_SPL **con damping de materiales** (ξₙ que ya tenemos),
   **promediado espacialmente** sobre una zona de receptores, y **suavizado
   en 1/6–1/3 octava**. Refina la "adición #1" del análisis del paper.
   *Formalizada en §8 (12 Jun 2026).*
5. **Relabel de ratios + agregar Cox.** `RATIO_LIBRARY` tiene los nombres
   cruzados vs la literatura del paper: "Bolt"=1:1.4:1.9 (es **Louden**),
   "Bonello"=1:1.26:1.59 (es **Bolt**), "Louden"=1:1.6:2.33 (es **Sepmeyer**).
   Falta **Cox** (1:1.56:1.86). Propuesta: corregir etiquetas y agregar Cox.
   *Aprobado como enfoque (12 Jun 2026). Se aplica editando `prediction.py`
   en la fase de implementación (no en planning). Requiere nota de
   compatibilidad: los `.room` viejos con el nombre antiguo siguen abriendo.*
6. **Criterio Bonello propio** (densidad 1/3 oct no-decreciente) y opcional
   **figura de Louden** (stdev del espaciado intermodal) y **modal overlap M**
   (Schroeder/Kuttruff). Hoy `bonello_ok_bands` se calcula pero no se scorea.

---

## 8. Figura de mérito — calidad modal de la respuesta

> Reemplaza/mejora el σ_SPL del paper (Gunawan 2018). Uso doble: rankeo en el
> módulo de **Predicción** y lectura en la pestaña **Acústica** (junto a la FRF).

### 8.1 Qué arregla respecto al paper

| Defecto del paper | Cómo lo arregla esta FoM |
|---|---|
| Paredes sin pérdidas (Q→∞, σ = artefacto numérico) | Usa **ξₙ de materiales** (RT60 → amortiguamiento real por modo) |
| σ en **un solo punto** (esquina = peor caso) | **Promedia y mide varianza sobre una zona de receptores** |
| σ del dB crudo (sobre-pesa los nulos) | **Suavizado en energía por 1/N de octava** (doma los nulos) |
| Banda hasta 200 Hz con malla inválida (2 ppw) | Calcula **solo hasta `f_max_malla`** (regla de la app) |
| Volúmenes distintos confundidos | Candidatos a igual `V_target`; si V difiere, documentarlo |

### 8.2 Definición formal

Dados los modos `fₙ, φₙ`, el amortiguamiento `ξₙ`, fuentes con `Qₛ(f)`, una
grilla de receptores `R = {x_r}` (r = 1..N_R) en la zona de escucha, y un eje
de frecuencias `f` en la banda válida `[f_lo, min(f_hi, f_max_malla)]`:

**(1) Función de transferencia compleja en cada receptor** (misma superposición
modal que `frequency_response`, ahora CON damping y en muchos puntos):

```
H(x_r, f) = i·ω·ρ₀·c² · Σₙ φₙ(x_r)·[Σₛ Qₛ(f)·φₙ(xₛ)]
                        ────────────────────────────────────
                          ωₙ² − ω² + 2i·ξₙ·ωₙ·ω
```
Shape: `H` es `(N_R, N_f)` complejo.

**(2) Suavizado en energía por 1/N de octava** (N = 3 o 6). Para cada `f`,
promedia la POTENCIA en la sub-banda `[f·2^(−1/2N), f·2^(+1/2N)]`:

```
Ŝ(x_r, f) = 10·log10( ⟨ |H(x_r, f')|² ⟩_{f' ∈ banda(f)} / p_ref² )
```
Suavizar en **energía** (no en dB) evita que los nulos profundos dominen.
`p_ref = 20 µPa`. Shape `(N_R, N_f)` en dB.

**(3) Respuesta media espacial** (energía promediada sobre receptores, luego
suavizada `→ L̄ˢ(f)`):

```
L̄(f) = 10·log10( ⟨ |H(x_r, f)|² ⟩_r / p_ref² )
```

**(4) Dispersión espacial** (variación asiento-a-asiento) a cada `f`:

```
σ_esp(f) = std_r [ Ŝ(x_r, f) ]      [dB]
```

**(5) Dos números complementarios (NO uno solo):**

```
FoM_flat     = std_f [ L̄ˢ(f) ]       ← planitud de la respuesta media [dB]
FoM_espacial = ⟨ σ_esp(f) ⟩_f         ← consistencia entre asientos [dB]
```

- `FoM_flat ↓` = timbre más plano (la versión corregida del σ del paper:
  amortiguado + espacial + suavizado).
- `FoM_espacial ↓` = la sala suena parecido en toda la zona (varianza espacial
  tipo Welti/Devantier, base del diseño multi-sub).

**Por qué dos:** una sala puede ser plana en promedio pero variar mucho
asiento-a-asiento, o al revés. El paper los confundía en un solo σ de un punto.

**Variante opcional pesada a picos** (los picos se oyen más que los nulos): en
(5) usar la dispersión de **solo las desviaciones positivas** sobre la
tendencia, `⟨ max(0, L − L̄ˢ) ⟩`, en vez del std simétrico.

### 8.3 Cómputo con la malla y los ξₙ

- `φₙ(x_r)`: el `FieldEvaluator` ya evalúa modos en puntos arbitrarios,
  vectorizado → matriz `(N_R, N_m)`.
- `ξₙ`: de materiales vía RT60 (`ξₙ = 1.1/(fₙ·RT60(fₙ))`), igual que la FRF. En
  el FEM-lite de Predicción se usa `alpha_default → RT60`.
- `H = (N_R, N_f)` por `einsum` sobre modos. Costo `~ N_R·N_f·N_m`:
  N_R=50, N_f=200, N_m=100 → ~10⁶, trivial (ms).
- **Solo banda válida:** truncar `f ≤ f_max_malla` (no repetir el error del
  paper de medir donde la malla no resuelve).
- Integración: `verify_candidate_fem` hoy solo hace stats modales; hay que
  agregarle el cómputo de respuesta forzada sobre la grilla (reusa
  `frequency_response` / `modal_pressure_field`).

### 8.4 De métrica a sub-score (0–100)

Mapeo lineal con umbrales calibrables (TBD con corridas de referencia):

```
score_flat = clamp( 100·(σ_techo − FoM_flat)/(σ_techo − σ_piso), 0, 100 )
```
con `σ_piso ≈ 2 dB` (excelente) y `σ_techo ≈ 12 dB` (pobre). Ídem
`FoM_espacial`. Calibrar corriendo las salas del paper (sirven de cruce).

En el grupo MODAL, `score_flat` y `score_espacial` **complementan** (no
reemplazan) a Bolt-spacing: el paper mostró que distribución pareja y
respuesta plana pueden discrepar, así que conviene tener ambas señales.

### 8.5 Zona de receptores por defecto

Sin geometría de butacas: grilla (ej. 5×5) a **altura de oído z ≈ 1.2 m**,
sobre el **60 % central de la planta**, excluyendo ~0.5 m de cada pared (para
NO caer en el peor caso de esquina del paper). En la pestaña Acústica el
usuario podría definir su propia zona/altura más adelante.

---

## 9. Cruce por solapamiento modal numérico (estilo MDCF)

> Motivado por Wang, Du & Yu (2026), *Archives of Acoustics* 51(1). El
> `f_Schroeder` analítico es **ciego a la forma** (solo V y T60). Como la app ya
> resuelve los modos FEM con ξₙ, se puede calcular un cruce que **sí ve la
> forma**, casi gratis — evitando los defectos del paper (ver crítica en el hilo).

### 9.1 Idea

El solapamiento modal es `M(f) = B_HP(f)·n(f)` (ancho de banda de media potencia
× densidad modal local). Criterio de Schroeder: régimen denso cuando `M ≥ 3`.
El cruce es la `f` donde `M` cruza 3.

- `f_Schroeder` usa la densidad de **Weyl** (solo volumen) → ciego a la forma.
- El **cruce numérico** usa la densidad **real** `n(f)` de los modos resueltos
  → ve la forma (splay / taper / arco, que la app soporta).

### 9.2 Definición formal

Ancho de banda de media potencia por modo (resonancia de 2º orden):

```
B_HP,n = 2·ξₙ·fₙ = fₙ/Qₙ        [Hz],   Qₙ = 1/(2ξₙ)
```

Con `ξₙ = 1.1/(fₙ·RT60(fₙ))` queda `B_HP,n = 2.2/RT60(fₙ)` — constante en `f` e
igual al analítico `B̄_HP = 3·ln(10)/(π·RT60) ≈ 2.20/RT60`. (Ver §9.3: con el
modelo Sabine el aporte numérico viene de la densidad, no del ancho.)

Densidad modal local (suavizada, robusta):

```
n(f) ≈ ΔN / Δf   en una ventana de 1/3 de octava centrada en f
```

(`N(f)` = conteo acumulado de modos; derivada por ventana, **no** `1/(fₙ−fₙ₋₁)`
crudo.)

Solapamiento y cruce:

```
M(f)    = B_HP(f) · n(f)
f_cross = min { f : M̄(f) ≥ 3 }      con M̄ suavizado
```

**Continuidad con SF (chequeo lindo):** metiendo la densidad de Weyl
`n_Weyl = 4πV·f²/c³` se recupera Schroeder exacto: `M=3 → f ≈ 2066·√(RT60/V)`.
Reemplazando `n_Weyl` por la densidad numérica se obtiene el cruce que ve la
forma. Mismo patrón que "Q(f) plano reproduce la FRF de hoy".

### 9.3 Qué SÍ podemos y qué NO

| | |
|---|---|
| ✅ Densidad numérica `n(f)` | De los `fₙ` resueltos. Incluye el término de superficie (Maa) que SF descarta (crítica #1 al paper). Captura la **forma**. Gratis. |
| ❌ Ancho de banda **por modo** real | Necesitaría autovalores **complejos** (impedancia ensamblada en matriz `C`). **Descartado por D5b.** Con ξₙ de Sabine, `B_HP` es constante → el aporte numérico es solo la densidad. |

O sea: nuestro cruce = **"Schroeder con la densidad modal real (consciente de la
forma)"**, no el MDCF completo. Es el ~80 % del valor del paper (la forma) sin
reabrir D5b.

### 9.4 Evitar los pozos del paper

- **Umbral robusto:** `M̄(f)` suavizada (mediana / ventana 1/3 oct), NO "el más
  bajo y todos los subsiguientes" — en el paper eso lo decide un outlier (su
  "modelo C" es artefacto de definición, crítica #3).
- **Solo banda válida:** `f ≤ f_max_malla`.

### 9.5 Cómputo e integración

- Helper `modal_overlap_crossover(freqs, xi, rt60_func, ...) -> (f_cross, M_curve)`
  en `acoustic_analysis` (o nuevo módulo de métricas).
- UI: junto al `f_Schroeder` actual, mostrar `f_cross (M≥3, numérico) ≈ X Hz`.
  Opcional: graficar `M(f)` con la **misma grilla de 1/3 octava de §3.4**.
- Predicción: puede alimentar `_score_schroeder` con el cruce numérico en vez
  del analítico.

### 9.6 Caveats honestos

- Sigue siendo un **proxy** (convención `M≥3`); NO validado contra la
  convergencia real FEM↔acústica geométrica (mismo límite que el paper).
- `ξₙ` viene de Sabine (fórmula de campo difuso) aplicada **debajo** de
  Schroeder — aproximación aceptable, pero es la inconsistencia #5 del paper.
  Anotarla, no esconderla.

---

*Discusión: 12 Jun 2026. Pendiente de aprobación para arrancar Fase 0.*
