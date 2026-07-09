# Criterios de diseño acústico de recintos — geometría ↔ fuentes

> Lista exhaustiva de criterios para elegir/diseñar las características acústicas
> de un recinto, considerando **geometría** y/o **fuentes**. Cada criterio:
> nombre · qué mide (FoM/fórmula) · rango/umbral · fuente · mapeo a la app (T8).
>
> Estado: **v2 (cerrado) — 2026-06-20.** Minado del corpus de salas chicas/estudio **completo**
> (papers T1 + web + decks de cátedra + libros: Everest, Newell, Cox&D'Antonio, BBC/Rose,
> Beranek&Mellow, Carrión, Howard&Angus, Meyer). **~107 criterios.** Diferido por bajo valor:
> trío de salas grandes (Beranek Concert Halls / Ando / Barron — ya cubierto en §D) y los textos
> FEM (van al doc aparte de numérica). Ver progreso al pie y `referencias/_indice.md`.
> Síntesis accionable para el scorer T8: ver **§E** al final.
> Convención: `l ≥ w ≥ h` (largo, ancho, alto); banda modal = 20–200 Hz.

---

# §A — Criterios de GEOMETRÍA (forma/dimensiones del recinto)

Propios del recinto: salen de la lista de modos `fₙ` (y a veces de `|H|` con un
par fuente/receptor fijo). En su mayoría **independientes de la fuente**.

## A.1 · Distribución de modos (spacing) — la familia histórica

**A1. Bolt (1946) — "Bolt area".**
Dispersión estadística del intervalo entre modos en baja frecuencia. Define una
**región de ratios buenos** (la "mancha de Bolt") en el plano `w/h`–`l/h`.
Ratios citados: **3:4:5 = 1:1.33:1.67** y **1:1.25:1.6**. → FoM: varianza del spacing.

**A2. Louden (1971) — desvío estándar del espaciado modal.**
Mejor ratio **1:1.4:1.9**; peor **1:1.41:2.8** (y el cubo). FoM: `std(Δfₙ)` mínima.

**A3. Bonello (1981) — densidad modal no-decreciente.** [Everest p347-349]
Criterio doble: (a) la cantidad de modos por **1/3 de octava** (elegidas porque
**aproximan las bandas críticas del oído**) debe ser **no decreciente** al subir de
banda, hasta 200 Hz (horizontal permitido); (b) **ningún modo coincidente** salvo que
la banda ya tenga **≥5 modos**. Apto para cómputo (Bonello lo pensó así). Es el criterio
que la app calcula como `bonello_ok_bands`. → robusto, fácil de chequear.
**Control de un modo problemático** (Everest): ajustar dimensiones (sala nueva) o
**resonador Helmholtz de alto Q** (sala existente) — alto Q exige cavidad rígida
(hormigón/cerámica; la madera flexiona y baja el Q), sintonizado y bien ubicado.

**A4. Gilford (1959) — modos aislados / agrupados.** ✓ cubierto por A28 (Everest: spacing axial ≥25 Hz)
Evitar modos axiales separados >~20 Hz de su vecino (se oyen como coloración) y
evitar cúmulos. Prioriza modos **axiales** (los más energéticos).

**A5. Evitar degeneraciones (cubo / ratios enteros).**
Cubo `1:1:1` y ratios enteros (`1:2`, `2:3:5`...) hacen **coincidir** modos →
picos fuertes y huecos. El cubo es el peor caso en casi todas las FoM.

## A.2 · Optimización numérica de la respuesta (ya acopla algo de fuente)

**A6. Rindel FSI ψ(25) (2021) — varianza relativa de intervalos.** ✅ leído
`ψ(n) = (1/(n−1))·Σ(δᵢ/δ̄)²` sobre los primeros 25 modos. Ideal `ψ=1`
(equiespaciado perfecto), **mejor real ≈ 1.3**, **evitar ψ>1.6**.
**Hallazgo clave:** `l/w` **domina**, `w/h` casi no importa → diseñar con
**`1.15 < l/w < 1.45`** (y `l/h` en rango similar). Óptimo `1:1.20:1.45`.
Independiente de V y absorción. → candidato a reemplazar la "suavidad modal" de T8.

**A7. Cox & D'Antonio (2001/2004) — |H| más plano, peor caso de posición.**
Modelo de fuentes imagen con **fuente en una esquina + receptor en la esquina
opuesta**; optimizan dimensiones para el `|H|` más plano 20–200 Hz. Ratio
peor-caso `1:1.075:1.868`. **Aporte metodológico:** evaluar el ratio bajo el par
de posiciones de **peor caso** lo hace robusto a dónde caiga la fuente. ✓ minado: Cox&D'Antonio
(2ª ed.) **NO** trae esta optimización de sizing LF (es libro de devices); queda como está, vía web/Cox2004.

**A8. Meissner (2018) — suavidad de |H| (polinomio + correlación).**
FoM: ajuste de `|H|` a polinomio de 2° orden + coef. de correlación normalizado.
Depende de V, **absorción** y ratio. Óptimos: **A 1:1.20:1.45 · B 1:1.40:1.89 ·
C 1:1.48:2.12**. (A coincide con el óptimo de Rindel.)

**A9. Walker (1993, BBC) — índice de calidad + región admisible.** ✓ ampliado en A33 (caja BBC `1:1.14:1.4` ± tol)
"Mean square room quality index" sobre los modos hasta 120 Hz. Criterio de
proporciones admisibles: **`1.1·(w/h) ≤ l/h ≤ 4.5·(w/h) − 4`**. Óptimos por
altura (ej. 200 m³: `1:1.19:1.40` alto, `1:1.75:2.2` práctico).

## A.3 · Librería de ratios estándar (valores)

**A10. Ratios recomendados** (para `generate_candidates` de Predicción):

| Nombre | Ratio `1 : w : l` | Origen |
|---|---|---|
| Sepmeyer | 1 : 1.14 : 1.39 / 1 : 1.28 : 1.54 / 1 : 1.6 : 2.33 | Sepmeyer 1965 |
| Louden | 1 : 1.4 : 1.9 | Louden 1971 |
| Bolt | 1 : 1.25 : 1.6 (≈3:4:5) | Bolt 1946 |
| Cox & D'Antonio | 1 : 1.56 : 1.86 | Cox 2004 |
| Rindel/Meissner A | 1 : 1.20 : 1.45 | Meissner 2018 / Rindel 2021 |
| (evitar) Golden | 1 : 1.62 : 2.62 | — (queda bajo en ranking) |
| (evitar) Cubo / doble cubo | 1:1:1 / 1:1:2 | peor caso |

> Nota: coincide con el relabel hecho en T1 (la "Louden" 1:1.6:2.33 de la vieja
> librería era **Sepmeyer**; "Bolt" 1:1.4:1.9 era **Louden**; etc.).

## A.4 · Volumen, banda válida y crossover

**A11. Volumen por uso / por persona.**
Define la densidad modal (más V → modos más juntos → menos problema modal). En
salas chicas (< ~300 m³) la banda modal 20–200 Hz es problemática (modos
escasos). Rindel: el análisis modal vale hasta donde la dimensión mayor no
exceda ~8.6 m (≈300 m³). → la app ya tiene `v_per_person` / `h_default` por uso.

**A12. Frecuencia de Schroeder `f_s = 2000·√(RT₆₀/V)`.**
Frontera modal/difuso. Debajo: campo modal (FEM); arriba: difuso (acústica
geométrica). Ciega a la forma (sólo V, RT). → la app la muestra y la usa de techo.

**A13. MDCF — crossover por densidad modal numérica (Wang, Du & Yu 2026).** ✅ leído
`M(f) = B_HP(f)·n(f)`, régimen denso cuando `M ≥ 3`; el cruce usa la **densidad
modal real** `n(f)` de los modos resueltos (ve la forma), no la de Weyl. En
cabinas poco absorbentes el MDCF da **70–150 Hz menor** que Schroeder, y **varía
con la forma** a V constante. → es el `f_cross` numérico del plan §9 (ya en
`modal_metrics.modal_overlap_crossover`).

**A14. Densidad modal con término de superficie (Maa).** ⊘ diferido (fuera de alcance; el MDCF A13 ya usa densidad real)
`n(f) ≈ 4πV·f²/c³ + (πS·f)/(2c²) + L/(8c)` — Weyl + superficie + aristas.
Schroeder descarta el término de superficie; MDCF lo captura vía la densidad real.

## A.5 · Forma (no-shoebox) y salas grandes

**A15. Paredes no paralelas (splay) / forma irregular.** ✓ ampliado: A31 (splay 10°, BBC/Cox) + C11 (no-shoebox→FEM)
Reduce flutter echo y **suaviza** la distribución modal (rompe degeneraciones),
pero a baja frecuencia los modos siguen dominados por las dimensiones globales.
La app soporta lofteado/splay → MDCF y FSI numérica capturan el efecto.

**A16. Parámetros ortogonales de salas grandes (Beranek / Ando).** ⊘ diferido (salas grandes; ya en §D D1-D16)
Para auditorios/salas de concierto (fuera de la banda modal pura):
- **Beranek:** RT, EDT, G (fuerza), ITDG (initial-time-delay gap), BQI/IACC
  (binaural), C80 (claridad), BR (bass ratio), SDI.
- **Ando (4 ortogonales):** nivel de escucha, ITDG, T_subsequent (RT), **IACC**.
Diseño por **preferencia subjetiva**. → no aplican al régimen modal chico, pero
entran si la app escala a salas grandes.

## A.6 · Adiciones del deck de control room (Bidondo, UNTREF 2024)

**A17. Energía relativa por tipo de modo.** [deck S45]
Axial **0 dB** > tangencial **−3 dB** > oblicuo **−6 dB**. Los **axiales** dominan
la coloración (consistente con Gilford A4: priorizar axiales).

**A18. Ancho de banda modal `B_HP ≈ 2.2 / RT60`.** [deck S46]
Tabla: RT 0.2 s → 11 Hz · 0.5 s → 4.4 Hz · 1.0 s → 2.2 Hz. **Sustenta** `M(f)=B_HP·n(f)`
del MDCF (A13) y el `ξₙ = 1.1/(fₙ·RT60)` de la app. En estudios es común `B_HP ≈ 5 Hz`.

**A19. Excitabilidad según posición del modo.** [deck S52] (puente a §B)
**7/8** de los modos tienen un **contorno de presión nula que pasa por el centro**
del recinto; sólo los modos con `nx, ny, nz` **todos pares** tienen presión ≠0 en
el centro. Un modo se excita a pleno **sólo** con fuente en su **máximo de presión**.

**A20. VSA — Variance of Spatial Average.** [deck S61]
Varianza del **promedio espacial** de `|H|` en 20–100 Hz: planitud de la respuesta
promedio. ≈ `FoM_flat` de la app (complementaria).

**A21. Coloración por spacing > 20 Hz o solapamiento.** [deck S54] (refina A4)
Coloración audible cuando el espaciado entre modos supera ~**20 Hz** (hueco) o hay
**solapamiento/degeneración** (cúmulo). El cubo y los ratios enteros son el peor caso.

## A.7 · Volumen y RT óptimos (del deck de Acoplamiento — salas medianas/grandes)

**A22. Volumen óptimo de sala (Cerdá et al. 2014; Ando-Beranek + Barron).** [Acopl S10-11]
Región **V–RT** acotada por contornos de **LFC** (Lateral Fraction, 0.12–0.26). Salas
con **V muy grande a RT bajo** caen fuera de la región buena (mala acústica reportada).

**A23. RT óptimo (Barron 2002).** [Acopl S12-13]
`T_r,opt = a + 2.3026·b·log V`, con `a, b` por **tipo de uso**:
iglesia/órgano (a=+0.098, b=1/5) · concierto/sinagoga (−0.162, 1/5) · estudio/ópera
(−0.352, 1/5) · conferencia/cine (−0.101, 2/15) · voz/broadcast (−0.192, 1/9).

**A24. Curva RT vs frecuencia (target de calidez).** [Acopl S13]
Ratio del RT respecto a 500 Hz: **31.5 Hz → 2.40 · 63 → 1.93 · 125 → 1.46 ·
250 → 1.13 · 500–1k → 1.00 · 2k–8k → 1.05**. Define el "bass rise" deseado (warmth, D5).

**A25. Volúmenes acoplados / decay de doble pendiente (Ermann 2005).** [Acopl S1-9]
Apertura de acople **~5% de la superficie** del hall principal → **acople máximo** →
**claridad alta** (decay inicial rápido) **+ reverberancia alta** (decay lento) a la
vez. `Coupling constant = RT*/T15`. Herramienta de diseño geométrico para lograr dos
objetivos normalmente en conflicto. La pendiente **varía con la posición del asiento**
(cerca de aperturas vs centro) → variación espacial.

## A.8 · Del Master Handbook (Everest, cap. 15/19)

**A26. Volumen mínimo (Gilford / Everest).** [Everest p401] (refina A11)
Salas < ~**1500 ft³ (~42 m³)** → modos escasos con **espaciado exagerado** → coloración
impráctica. Cota dura inferior por debajo de la cual ninguna proporción salva la sala.

**A27. Umbral ~300 Hz cavidad/rayos.** [Everest p401] (refina A12)
Debajo de ~300 Hz el recinto es **cavidad resonante** (es el aire confinado el que
resuena, no la estructura); arriba, el sonido se trata como **rayos** (especular).
Complementa Schroeder (que depende de V, RT).

**A28. Procedimiento de modos axiales + criterio de coloración.** [Everest p402-403]
Calcular los **modos axiales** (`f₁ = 565/L` [ft], `565/W`, `565/H` y armónicos) hasta
300 Hz, ordenarlos ascendente y examinar el **spacing**. Coloración si: (a) **coincidencias**
(2+ modos a la misma f) o (b) **modos aislados ≥ 25 Hz** de su vecino. Los **axiales
dominan** (tangenciales/oblicuos se desprecian). Ejemplo de Everest: sala 1:1.65:2.15
(dentro del Bolt area) → spacing medio 11.7 Hz, σ=6.9 Hz. (Nota: Everest usa 25 Hz; el
deck de Bidondo, 20 Hz — refina A21.)

## A.9 · Del Recording Studio Design (Newell, 3ª ed.)

**A29. Pressure zone `f_pz` y diagrama de 4 zonas (Bolt-Beranek-Newman).** [Newell p168-169, p213-214, fig 6.10]
Por **debajo del modo axial más bajo** (media longitud de onda no entra en la dimensión
mayor) **no existen modos**: la sala entra en la **"pressure zone"** — todo el volumen sube
y baja de presión **al unísono**, sin soporte resonante → los graves **decaen muy rápido** y la
respuesta es **inherentemente plana**. Diagrama de 4 zonas del estado estacionario:
**A** pressure zone (`<f_pz`) · **B** normal-modes-controlled (`f_pz→f_L`) · **C** difusión/
difracción (`f_L→4f_L`) · **D** reflexión especular + absorción (`>4f_L`). Complementa
Schroeder (A12) y el umbral ~300 Hz de Everest (A27). **Consecuencia para la fuente:** en la
pressure zone el recinto **no realza** los graves (sin boost modal) → un parlante que excite esa
banda necesita **gran output LF**. Salas **muy chicas** pueden tener LF **muy plano** justo
porque operan en pressure zone (sin modos). → cota inferior dual de A26.

**A30. Ensanchamiento modal ≈ ±10 Hz (modo parcialmente amortiguado).** [Newell p100, fig 4.16]
Un modo típico parcialmente amortiguado está "activo" **~10 Hz a cada lado** de su frecuencia
nominal (no es una línea espectral). **Sustenta** el ancho de banda modal `B_HP` (A18) y el
criterio de solapamiento del MDCF (A13/C5): los modos se pisan cuando su spacing < su ancho.

**A31. Flutter echo — umbral temporal ~30 ms / camino > 8–10 m.** [Newell p106; Cox&D'Antonio §1.4 p17]
Entre dos superficies paralelas duras, el flutter sólo se oye como **eco discreto** si el camino
da repeticiones de **≥ ~30 ms** (separación > ~8–10 m). Por debajo de eso (la mayoría de salas
chicas) el mismo par de paredes paralelas produce **coloración tímbrica modal**, no flutter
audible. Tratar con absorción **en al menos UNA** de las dos paredes (basta poroso fino: es
tratamiento de medios/altos), **geometría (splay / no-paralelismo)** o difusión. Cox prefiere el
**difusor**: controla el flutter **y** dispersa para mejor cobertura/inteligibilidad. Refina A15/A21.
**Receta BBC** [Rose §3.3-3.4 p91]: mínimo para que una sala no tenga flutter = alfombra **o**
cielo con tiles + absorción en **dos paredes ADYACENTES (no opuestas)**. El flutter es casi seguro
en rectangulares con **gran diferencia de absorción por dirección** (p. ej. alfombra absorbe lo
vertical y sólo un par de paredes tratado). Alternativa geométrica: **angular** una superficie
**10° total** (una a 10° o ambas 5°) para sacarla del paralelismo; o difusor en vez de una cara dura.

## A.10 · Del BBC Guide to Acoustic Practice (Rose, 2ª ed. 1990)

> *(Nota de numeración: **A32 no se usa** — la serie A salta de A31 a A33. Se deja el hueco a
> propósito para no renumerar las referencias cruzadas a A33-A37.)*

**A33. Ratio recomendado BBC + "Golden Ratio" — refina A9.** [Rose §3.3 p90-91]
Dos reglas BBC para proporciones de estudio/control room:
- **Evitar el cubo / cuadrado "a toda costa"** y que cualquier par `largo:ancho`, `largo:alto`,
  `ancho:alto` caiga en (o muy cerca de) **enteros pequeños** → si no, las resonancias coinciden y
  colorean (= A5). Vale **aun si la sala está sólo ligeramente angulada**.
- **"Golden Ratio" BBC** = `1 : 2^⅓ : 2^⅔ ≈ 1 : 1.26 : 1.6` (ojo: **no** es el φ=1.618; choca con el
  "Golden 1:1.62:2.62" que en A10 está *a evitar* — son cosas distintas). Multiplicar factores por
  enteros es válido (p. ej. `1 : 1.6 : 2.52`).
- **Rango de buena distribución modal LF (Walker/BBC)**, relativo al alto: **`w/h = 1.14 ± 0.1`,
  `l/h = 1.4 ± 0.14`** → caja de tolerancia ≈ `1 : 1.14 : 1.4` (`w/h∈[1.04,1.24]`, `l/h∈[1.26,1.54]`).
  Es la versión simple (1990) del índice de calidad Walker de A9; útil como **constraint directo**
  en `generate_candidates`. Coincide casi con el óptimo Rindel/Meissner A (1:1.20:1.45).
- **Ventana de utilidad del ratio ("range of validity" de Bolt).** [Toole §13.2.1 p205-207]
  El beneficio de un ratio óptimo está **acotado a una banda angosta** (~40-120 Hz en sala de
  85 m³, según el gráfico "range of validity" de Bolt que casi nunca se reproduce): debajo hay
  muy pocos modos para que el ratio importe; arriba la densidad modal ya alcanza. Toole **relativiza**
  el peso del ratio frente a la **gestión activa** (posición + multi-sub + EQ + absorción distribuida)
  y cuestiona dos asunciones del "cuarto óptimo": que axial/tangencial/oblicuo pesan igual (falso,
  los axiales dominan — ata A36) y que las paredes son rígidas perfectas. **No agrega un ratio nuevo**:
  confirma el régimen de la app (la geometría es UN eje; T8/ubicación + A36/damping son los otros).
  Geddes (en Toole p223): *"la distribución de absorción importa más que la forma"* → respaldo de A36.

**A34. RT objetivo y tolerancias BBC + prohibición de decay doble-pendiente.** [Rose §3.2 p89-90] (refina A24/D2)
Para talks studios y **todos los control rooms**: RT global (200 Hz–3.15 kHz) **0.20–0.25 s**.
Banda media (200 Hz–3.15 kHz) dentro de **0.8–1.2·Tm**; LF (50–200 Hz) entre `0.8·Tm` y una recta
de `1.2·Tm @200Hz` a `2.5·Tm @50Hz` (**bass rise** permitido, calidez — ata A24); HF (3.15–10 kHz)
de `1.2·Tm` a `0.6·Tm`. **Debajo de 50 Hz el RT carece de sentido** (λ > sala — dual de A29/pressure
zone). **Decay de doble pendiente NO permitido:** si el RT en `−20…−35 dB` difiere del de `−5…−20 dB`
en **más de 2:1**, la sala es inaceptable (en salas chicas el doble-decay es defecto, ≠ del recurso
de diseño de A25 en salas acopladas grandes). Norma base: **EBU R22-1985**.

## A.11 · Del Diseño Acústico de Espacios Arquitectónicos (Carrión Isbert, 1998)

**A35. Fórmula de Rayleigh de los modos propios (ancla del cálculo modal).** [Carrión §1.15.5 p49-51]
Para caja paralelepipédica de superficies totalmente reflectantes, las frecuencias propias son
`f_{k,m,n} = (c/2)·√((k/Lx)² + (m/Ly)² + (n/Lz)²)` = **`172.5·√(…)`** con `c=345 m/s`; `k,m,n` enteros
≥0. Es la base que el solver discretiza para shoebox (y que el FEM generaliza a no-shoebox). Carrión
**confirma** tres cosas ya en el doc: (a) la **región `largo/ancho` recomendada** (fig 1.42, alto=1)
para distribución uniforme = la mancha de Bolt (A1); (b) la coloración modal **sólo importa
debajo de ~200 Hz y en salas chicas** (locutorios, salas de control) — nula en salas grandes
(refuerza A11/A26/A27); (c) se **minimiza con EQ o resonadores** (ata C13/B18 — EQ válido sólo
para lo de fase mínima). Sin criterios nuevos de geometría↔fuente: es un texto de teatros/salas
de conciertos.

## A.12 · Del Acoustics and Psychoacoustics (Howard & Angus, 4ª ed.)

**A36. Tiempo de decaimiento MODAL por tipo de modo — formaliza A17/A18/A30.** [H&A §6.2.6-6.2.8 p329-335]
Un modo **no decae como el campo difuso**: visita **menos superficies** (e incidencia no aleatoria)
→ **menos absorción → decae más lento** en su frecuencia. El decay de la sala tiene varias constantes:
la corta es el campo difuso; las largas, los modos. Fórmula tipo Sabine pero **1-D**, con la
**longitud del modo** en vez del camino libre medio: **`T60_modal = 0.04·L_mode / (−ln(1−α_mode))`**
(0.04 = ln10⁶/c).
- **Axial:** `L_mode` = la dimensión relevante de la sala → caminos cortos, pocos rebotes.
- **Tangencial / oblicuo:** caminos entre rebotes más largos.
- Energía/ancho por tipo (fig 6.38, **even absorption**): **axial 0 dB > tangencial −3 dB > oblicuo
  −6 dB** (= A17). El **ancho de banda** del modo **depende sólo de su `T60_modal`** (independiente de
  la frecuencia si α es constante) → sustenta `ξₙ` / `B_HP` (A18, A30). Si `L_mode >` camino libre
  medio, el modo **resuena más** que el difuso (axiales largos = los que más colorean).

**A37. Frecuencia crítica ≡ solapamiento modal = 3 — corrobora el MDCF (A13/C5).** [H&A §6.2.9-6.2.11 p334-338]
La frontera modal↔difuso ("**critical frequency**" = Schroeder = "large-room frequency") H&A la define
**exactamente como el MDCF**: el punto donde se excitan **≥3 modos** por una frecuencia dada (sus
anchos solapan), porque con **>3 modos sumados** la variación frecuencial **y** espacial cae.
Corroboración independiente del umbral `M ≥ 3` de la app (A13, Wang-Du-Yu 2026). Estimador rápido
**`f_crit = 2102·√(T60/V)`** (≈ Schroeder 2000·√); la definición rigurosa usa el **ancho modal real**
(huevo-gallina en diseño → se usa el estimador). Define **sala acústicamente "grande" vs "chica"**:
grande si `f_crit` < la menor frecuencia emitida (auditorios, catedrales); **chica** si `f_crit` cae
dentro de la banda útil (dormitorios, salas de control — el caso de la app). Tabla 6.4 de ratios
favorables (A 1:1.14:1.39 … C 1:1.60) y **criterio Bonello** (modos/⅓-oct monótono creciente)
**confirman** A10/A3. Dual espacial: **distancia crítica** `r_c` (directo = reverberante en el espacio,
§6.1.8) — análogo espacial de `f_crit`.

---

# §B — Criterios de FUENTES (ubicación / montaje dado el recinto)

La geometría fija `fₙ` y `φₙ`; la **fuente decide qué modos excita**, la
consistencia entre asientos y el peine de frontera.

**B1. Excitación modal `φₙ(xₛ)`.**
Una fuente en un **antinodo** de presión excita ese modo al máximo; en un **nodo**
no lo excita. Es exacto en el modelo modal (ya está en la app vía `φₙ(xₛ)`).

**B2. Fuente en esquina → excitación máxima y pareja.**
La esquina es antinodo de **todos** los modos → los excita a todos por igual
(máxima salida en graves, peor caso de coloración pero uniforme). Es la semilla
`esquina` y el baseline de Cox.

**B3. SBIR — notch de frontera `f_c = c/(4·d)`.** ✅ (arqen)
Por cada pared cercana, primer nulo en `f_c = c/(4·d)`, `d` = distancia
fuente-pared. → es el cómputo de `sbir.py` (T6).

**B4. Flush / soffit mount → carga 2π.** ✓ ampliado: B25 (Newell), B31 (Beranek: fuente+imagen), B16/B23
Montar la fuente **al ras** de la pared elimina la reflexión frontal: radiación
en **medio espacio (2π)**, **+6 dB** en graves, **sin notch SBIR**. Estándar en
control rooms. → en la app es `mounted=True` (empuja `d→0`).

**B5. Zonas de distancia a pared (regla práctica).** (arqen)
**Bien:** flush o `<0.2 m`. **Aceptable:** hasta ~1 m. **Evitar:** 1–2.2 m
(notch en banda audible grave). **Bien:** `>2.2 m` (notch < cutoff del parlante).

**B6. Welti & Devantier (2003) — MSV (varianza espacial asiento-a-asiento).** ✅
Minimizar la variación de SPL entre asientos con **múltiples subs**. Resultado
canónico: **4 subs en el medio de las paredes baten a 4 en esquinas** por 1–2 dB;
simetría reduce la varianza. Simularon 36.000 salas. → es la FoM_espacial de T8.

**B7. Estrategias de ubicación de subs.** ⊘ diferido (Welti completo; B6 ya tiene el resultado canónico)
- **Esquinas:** máxima salida, mayor varianza.
- **Mid-wall simétrico (Welti):** mínima varianza.
- **Geddes:** asimétrico, posiciones "aleatorias" descorrelacionadas.
- **DBA (Double Bass Array):** arrays opuestos con delay → cancela el modo axial
  longitudinal (onda plana viajera). → encaja en el espacio de búsqueda 8.1.

**B8. Alineación temporal / fase entre fuentes.**
Delay `τ` (fase lineal `e^{-i2πfτ}`) + polaridad (`π`) controlan la interferencia
modal constructiva/destructiva (`Σ Qₛ·φₙ(xₛ)`). → ya en T5/Fase-2 de la app.

**B9. Simetría fuente-oyente (estéreo).** ✓ ampliado en B29 (triángulo BBC 2–2.5 m) + C25 (simetría modal ≠ temprana)
Par estéreo + oyente en **triángulo equilátero**, simétrico respecto al eje de la
sala (ITU-R BS.1116 / EBU 3276: ±30°, distancias iguales) → imagen + respuesta
LF simétrica.

**B10. Regla del cuarto de onda oyente-pared trasera.** (arqen)
Oyente a `≥3 m` de la pared de atrás → el notch del cuarto de onda cae `<30 Hz`.

**B11. Altura de la fuente / del oído.**
Excitación del modo vertical (1 axial en z) según la altura; oído a `z≈1.2 m`
(sentado). → la grilla de receptores de FoM usa `z_ear=1.2`.

**B12. Directividad de fuente (menor en banda modal).** → **ampliado/cuantificado en B32 (Meyer)**
Parlantes/instrumentos son casi omni debajo de Schroeder (descartado en la app,
ver plan §1.1). Importa arriba de ~cientos de Hz (baffle step, difracción).

## B.2 · Adiciones del deck de control room (Bidondo, UNTREF 2024)

**B13. Colocación de absorción en máximos de presión modal.** [deck S53]
Para controlar un modo, poner el absorbente **donde ese modo desarrolla máxima
presión** (esquinas para los axiales/oblicuos; según el modo). Acopla geometría +
materiales + control modal.

**B14. Simetría de "patología" entre altavoces.** [deck S38]
Si el campo modal es **asimétrico** (iso-superficies curvadas en sala irregular),
L y R trabajan en campos distintos → patologías distintas. Preferible colocarlos
**simétricos respecto al eje** para que ambos tengan la **misma** patología
(complementa B9: simetría fuente-oyente).

**B15. Distancias fuente-frontera NO simétricas (anti-pile-up de notches).** [deck S94]
Posicionar el monitor con distancias **distintas** a cada pared para que los notches
SBIR (`c/4d`) **no se apilen** en la misma frecuencia. Refina B3/B5.

**B16. Regla soffit `d ≤ mín(dimensión del baffle)`.** [deck S94]
Empotrar de modo que la distancia fuente-pared sea ≤ la **menor dimensión del
baffle** → el notch SBIR cae fuera de banda. **Confirma la constraint flush de T8.**

**B17. Empotrado: absorber radiación trasera/lateral.** [deck S88]
Al hacer flush/soffit, es fundamental **absorber la radiación trasera y lateral**
del monitor (si no, reaparece por otro camino).

**B18. Selección de absorbente por frecuencia objetivo.** [05-Absorción S4]
Poroso/fibroso (espumas, lanas) → **medios/altos**. Membrana/panel → **graves**.
Resonador Helmholtz → **banda angosta grave**. Para **control modal** (graves) usar
membrana/Helmholtz **en los máximos de presión del modo** (ata con B13). Nota: la
absorción que ve la app es α de incidencia aleatoria (Sabine/ISO 354); Eyring/Millington
son alternativas para α alto / RT bajo (relevante al audit T2 de RT60).

## B.3 · Del Master Handbook (Everest, cap. 19)

**B19. Posición del oyente vs nulos modales.** [Everest p404-405]
El **centro de la sala** intercepta los **nulos de todo modo axial impar** → evitarlo.
Los nulos son "sheets" (planos) ubicables; **mover el asiento** para esquivarlos
(impresiones estilizadas de Toole). Es el dual de B1 para el receptor.

**B20. Trampas de graves en esquinas cerca de los parlantes.** [Everest p406-408]
Absorción LF en las **dos esquinas frontales** (junto a los parlantes) mejora la
**imagen estéreo**; las esquinas son **máximos de presión de todos los modos**. f de
diseño ~100 Hz (Helmholtz/diafragmático/Tube Trap/Korner Killer). Refina B13.

**B21. Tratamiento de puntos de primera reflexión.** [Everest p409-410, Olive & Toole]
Reducir las **reflexiones tempranas** (piso F, techo C, paredes laterales W, difracción
del borde del cabinet D) que generan **comb-filter** y emborronan la imagen del directo.
Identificar y tratar los puntos espejo fuente↔oyente.

**B22. Excepción: reflexión lateral para espaciosidad.** [Everest p410]
A diferencia de B21, **conservar/ajustar** la reflexión lateral de las paredes laterales
controla la **espaciosidad e imagen**. Es la base del **RFZ/LEDE** (matar tempranas
salvo las laterales). Ata con D15/IACC.

**B23. Carga de frontera CUANTIFICADA (+3 / +6 / +9 dB).** [Everest p438] (refina B4/B16)
Fuente cerca de **1** superficie → **+3 dB** (medio espacio, 2π). Cerca de la
intersección de **2** → **+6 dB** (¼ espacio). En **esquina trihedral (3 superficies)**
→ **+9 dB** (⅛ espacio). Es el efecto "fuente en esquina" en términos de carga (≠ de la
excitación modal de B2). Si las distancias son apreciables vs λ, aparece el comb de B3.

**B24. Difusión de pared trasera → ensancha el sweet spot.** [Everest p432-434]
Un difusor de fase (phase-grating / RPG) en la pared trasera dispersa la energía
reflejada en **tiempo Y espacio** → en vez de un único punto especular que vuelve al
operador, **cada elemento** del difusor le manda energía → muchas más posiciones de
escucha buenas (mata el "sweet spot" único). Mejor que absorber (no pierde energía).

## B.4 · Del Recording Studio Design (Newell, 3ª ed.)

**B25. Flush mount: elimina la reflexión trasera de LF (y su boost es fase mínima).** [Newell p91, p347-348]
Un parlante **dentro** de la sala radia graves **también hacia la pared de atrás**, que se suman a
las reflexiones del recinto ("confusión" en graves); montado **al ras** no hay esa radiación
trasera → menos reflexiones LF. Además, el **boost de graves** que aporta el empotrado es de
**fase mínima** (mismo cociente de niveles en **toda** la sala) → **corregible por EQ** del drive.
Refina B4/B23 y ata con C21.

**B26. Dipolos vs monopolos: siting LF crítico.** [Newell p337]
Una fuente **dipolar** (p. ej. electrostáticos) excita **menos** modos pero los que excita, **más
fuerte**; carece del **boost por acoplamiento mutuo** (mutual coupling) en graves de los
monopolos y **no puede excitar la pressure zone** (A29) → tendencia a sonar **"bass-light"** aun
con respuesta anecoica plana. Exige **cuidado extra** en la distancia a las fronteras y la
distribución modal. Refina/excepciona B12 (la directividad LF **sí** importa para dipolos).

## B.5 · Del Acoustic Absorbers and Diffusers (Cox & D'Antonio, 2ª ed.)

**B27. Colocación de absorbente: VELOCIDAD vs PRESIÓN — corrige B13/B18/B20.** [Cox&D'Antonio §1.3 p15]
Distinción clave que mis criterios previos colapsaban en "absorber donde hay máxima presión":
- **Absorbente poroso/fibroso** opera sobre la **velocidad de partícula** → es máximo a **λ/4 de
  la frontera** (~1 m para 100 Hz), y **≈0 sobre la pared y en las esquinas** (allí la velocidad
  es mínima aunque la presión sea máxima). **Poner espuma/lana en las esquinas para domar
  modos es INEFICAZ.** Refina/corrige B20 (las "trampas en esquina" sólo sirven si son del tipo
  correcto).
- **Absorbente resonante** (Helmholtz / membrana) opera sobre la **presión** → **sí** va en
  esquinas / máximos de presión modal, y con **poca profundidad**. Por eso es el preferido para
  graves cuando el espacio es limitado.
- → Reconcilia B13/B18: "en el máximo de presión" vale **sólo para resonantes**; el poroso va a
  **λ/4** del límite. Implicación de modelado: la app usa α de incidencia aleatoria, ciega a esta
  dependencia de posición (ata con C24).

**B28. La difusión NO controla modos (graves siempre con absorción).** [Cox&D'Antonio §1.3 p15]
A baja frecuencia un difusor tendría que ser **prohibitivamente grande** (λ enorme) → los modos
problemáticos se tratan con **bass traps** (absorción), no con difusores. La difusión entra de
medios hacia arriba (dispersión espacial/temporal). Acota el alcance de B24/D14.

## B.6 · Del BBC Guide to Acoustic Practice (Rose, 2ª ed. 1990)

**B29. Triángulo estéreo 2.0–2.5 m + simetría no compensable.** [Rose §4.2 p124, fig 47] (refina B9)
Base del layout de monitoreo estéreo: **triángulo** parlantes-operador, idealmente **equilátero de
~2.0–2.5 m** de lado; productor a **≥1.8 m** detrás del operador. **Simetría esencial:** ambos
parlantes **equidistantes** del operador, y la diferencia de distancia **NO se compensa**
desbalanceando niveles (arruina la imagen). En salas chicas se acorta el frente-fondo (parlantes
siguen a 2.0–2.5 m, operador más cerca). Altura de cielo **igual sobre ambos** parlantes.

**B30. Monitor free-standing: lejos de pared/esquina y de objetos resonantes.** [Rose §4.5 p125] (refina B5/B16)
La mayoría de los monitores (no los grandes de empotrar) son **free-standing** → idealmente **no
muy cerca de pared ni en esquina**. Si el espacio obliga a arrimarlo: tratar la pared para bajar
reflexiones; si va cerca de **esquina**, dejar `≥200 mm` de tratamiento profundo en **ambas**
superficies. El parlante **no debe estar junto a nada que resuene/vibre/zumbe** (puerta, rejilla de
ventilación, rack) — el SPL ahí es mucho mayor. **Cielo plano**; si hay bulkhead de ventilación,
al **fondo** de la sala, no sobre los parlantes ni a un lado. Monitores en pared/escritorio →
**montaje resiliente** (evita transmitir al cuarto vecino y excitar resonancias del mueble).

## B.7 · Del Sound Fields and Transducers (Beranek & Mellow, 2012) — base física

**B31. Carga de frontera = fuente + imagen (deriva B2/B3/B4/B23 de un mismo modelo).** [B&M §4.9-4.12 p137-144]
Una fuente simple (monopolo, `R < λ/6`) frente a un **plano rígido** equivale, por el **método de
imágenes**, a **dos fuentes en fase** separadas `b = 2d` (`d` = distancia a la pared). El campo es la
suma vectorial de ambas (Huygens):
- **`b ≪ λ`** (fuente pegada a la pared, graves): las dos se **funden** y la presión **se duplica**
  → **+6 dB** y radiación en **medio espacio (2π)**. Es la **carga de frontera** formal de B4/B23.
- **`b` comparable a `λ`** (la fuente se aleja): la suma alterna refuerzo/cancelación con el ángulo
  → es el **peine SBIR** de B3 (`f_c = c/4d`). ⇒ B4 y B3 son **el mismo fenómeno** en dos límites.
- **N fronteras** ⇒ N imágenes: **1 plano +6 dB (2π), 2 planos +9, esquina trihedral +9 dB extra
  (⅛ espacio, 8 imágenes en total)**. Generaliza B23 y la "fuente en esquina" de B2. En términos de
  **ángulo sólido** `Ω`: ganancia `= 10·log(4π/Ω)` (Q de directividad).
- **Acoplamiento mutuo:** dos fuentes reales en fase a `b ≪ λ` también duplican presión → **+6 dB**
  de graves (base del boost multi-sub y del déficit de los **dipolos** de B26: sin par en fase, sin boost).
Nota física asociada (B&M §4.10-4.11): un radiador chico tiene **resistencia de radiación → 0** en
graves (impedancia reactiva) → cuesta radiar LF (por eso los subs necesitan gran desplazamiento).

## B.8 · Del Acoustics and the Performance of Music (Meyer) — amplía B12

**B32. Directividad de instrumentos: omni < ~500 Hz, crece con la frecuencia (resuelve B12).** [Meyer Ch 4 §4.1-4.2 p129-136, fig 4.1]
Cuantifica B12 para **fuentes acústicas** (no sólo altavoces): una fuente radia **omni** cuando es
chica frente a `λ` → **mayormente sólo los fundamentales de la octava más grave**; Meyer mide que
**ningún instrumento de orquesta radia omni por encima de ~500 Hz** (fig 4.1). ⇒ **En la banda
modal (20–200 Hz) TODA fuente natural es omnidireccional** → valida de lleno la hipótesis omni de
la app (plan §1.1), también para instrumentos, no sólo parlantes.
- La directividad **crece monótonamente con la frecuencia** (dimensión de la fuente / boca vs `λ`).
  **Índice de directividad** (dB sobre una omni de igual potencia) del **metal**: trompeta ~**7 dB
  @2 kHz → ~16 dB @15 kHz**; dipolo ideal ≈ +4.6 dB (factor 1.7).
- Arriba de Schroeder importa la **dirección principal de radiación** (p. ej. eje de la campana del
  metal; rotacionalmente simétrica) → define **qué tempranas se excitan** y el **aim** de la fuente.
- El **timbre** también depende de la dirección (no sólo el nivel) → relevante para captación/colocación.
Implicación para la app: refuerza descartar directividad en el régimen modal; sólo entraría si el
scorer se extendiera arriba de `f_cross` (geometría/tempranas), donde el aim de la fuente sí pesa.

---

# §C — Criterios COMBINADOS (geometría × fuentes, optimización conjunta)

**C1. Cox & D'Antonio — optimización conjunta dim + posición.** ✓ minado: la 2ª ed. no detalla esta
optimización (es libro de devices); el criterio queda vía Cox-D'Antonio-Avis 2004 (JAES) ya citado.
Optimizan **dimensiones** evaluando el `|H|` con un **par fuente/receptor fijo
de peor caso** (esquina↔esquina). Es el ejemplo canónico del par geometría↔fuente.

**C2. Harman — optimización iterativa multi-objetivo.** (patente US 12501231)
Optimiza **geometría + posición de parlantes + posición de oyente** juntas, con
objetivos múltiples (respuesta LF + variación espacial). Confirma el enfoque de
T8 (ejes geometría/ubicación/combinado).

**C3. FoM_flat — planitud de la respuesta media (Gunawan mejorado).** plan §8
σ del `|H|` **promediado en el espacio**, **con damping** (ξₙ de materiales) y
**suavizado 1/N-oct**. Corrige el σ de un punto sin pérdidas de Gunawan 2018.
→ `modal_metrics.FoM_flat`. Umbral en T8: 2 dB (excelente) → 12 dB (pobre).

**C4. FoM_espacial — consistencia asiento-a-asiento (Welti).** plan §8
`⟨std_r[Ŝ(x_r,f)]⟩_f` sobre una grilla de receptores. → `modal_metrics.FoM_espacial`.

**C5. Solapamiento modal `M(f) ≥ 3` → f_cross (MDCF).** plan §9 / A13
Criterio de **suavidad/validez** que ve la forma. → `modal_overlap_crossover`.

**C6. Trade-off del par (el principio rector).**
La geometría fija `{fₙ, φₙ}` (no cambia con la fuente); la ubicación elige la
**excitación** (`φₙ(xₛ)`), la **consistencia espacial** (Welti) y el **peine de
frontera** (SBIR). El óptimo conjunto = elegir ratio por buen spread modal (FSI)
**y** ubicar fuentes por excitación balanceada + control de comb. → es la
arquitectura de T8 (objetivo ponderado de flat/espacial/sbir/suavidad).

**C7. Ponderación por uso (prioridad perceptual).** ⊘ diferido (Fastl/Zwicker, T4 tangencial — consulta puntual)
Voz → planitud/inteligibilidad; música → consistencia espacial (envoltura) +
control del comb. → `default_location_weights`.

**C8. Asimetría pico/nulo (perceptual).** ⊘ diferido (Fastl/Zwicker, T4 tangencial — propuesta en plan §8.2)
Los **picos** se oyen más que los nulos (resonancias audibles; nulos enmascarados)
→ pesar más las desviaciones **positivas** sobre la tendencia. Variante propuesta
en plan §8.2, no implementada.

**C9. Umbral perceptual de modos (Fazenda, Stephenson & Goldberg 2015).** [paper completo, JASA 137(3)]
Un modo es audible/colorea según su **tiempo de decaimiento T60** comparado con un **umbral
perceptual dependiente de la frecuencia**. Curva medida (estímulos artificiales = umbrales
**absolutos**, Fig. 4): **0.90 s @32 Hz → 0.30 s @63 Hz (rodilla) → ~0.20 s @100 Hz → 0.17 s @200 Hz**
(monótona decreciente; plana ≥100 Hz). Con música el umbral baja (enmascaramiento): ~0.51 s @63 Hz.
**Un modo colorea si `T60_modo > umbral(f)`.** ✅ implementado: `fazenda_modal_threshold` y reemplaza
el `Q>30` fijo en el scorer (que era ~3-6× más laxo). → criterio de **qué modos** importan. Refs de
soporte (no en el corpus): Avis-Fazenda-Davies 2007 (umbrales de Q), Olive 1997, Karjalainen 2004.

**C10. Límite del control pasivo sobre la varianza espacial.** [deck S70 / Hill-Hawksford]
**10× absorción** reduce la magnitud modal pero la **varianza espacial sólo ~5%**.
Justifica que la **ubicación de fuentes (multi-sub)** y no "sólo absorber" sea la
palanca para la consistencia asiento-a-asiento (FoM_espacial / Welti).

**C11. Predicción modal en geometría no-shoebox → requiere FEM.** [deck S72]
Con paredes inclinadas la distribución modal es **impredecible por métodos simples**;
sólo FEM la captura. **Valida el enfoque de la app** (FEM + MDCF consciente de forma).

**C12. Marco de 3 métricas VSA / MSV / SDMFS.** [deck S61-63]
Conjunto complementario: **VSA** (planitud del promedio espacial, ≈FoM_flat) ·
**MSV** (asiento-a-asiento, ≈FoM_espacial, Welti) · **SDMFS = std(Δfn)** (Louden).
Cubre las 3 dimensiones (planitud / consistencia / distribución modal) — espejo
casi exacto del scorer de T8.

## C.2 · Del deck de diagnóstico de control room (Bidondo, UNTREF)

**C13. Fase mínima vs NO mínima — criterio de corregibilidad.** [07 S39, Makivirta 2001]
Las regiones de **fase mínima** se corrigen con **EQ** (filtros f, Q). Las de **fase
NO mínima** (nulos por cancelación de frontera / SBIR) **NO se pueden ecualizar** →
**sólo se corrigen físicamente con acústica** (geometría/ubicación/absorción). **Es
el criterio que decide qué problemas EXIGEN la decisión geométrica/de fuente** y
cuáles delega al DSP. → Razón de fondo para optimizar ubicación (T8) y no "EQ después".
**Respaldo Toole** [§9 p160, §13.4.1 p239-244]: los **modos LF son fenómenos de fase mínima** →
un **pico** resonante se corrige con EQ, y corregir el dominio de frecuencia corrige también el
**ringing temporal**. En cambio un **nulo por cancelación** (interferencia destructiva) NO se llena
subiendo ganancia (gasta headroom) → la solución es **mode-canceling** (otra fuente) o reposicionar.
Toole describe **SFM** (Sound Field Management, §13.3.6 p231): optimización brute-force de
gain/delay/EQ por subwoofer minimizando la varianza asiento-a-asiento (C14) — **valida el enfoque de T8**.

**C14. Multipunto > single-point.** [07 S36, Brännmark & Sternad 2015]
La evaluación/corrección en **un solo punto** es **no-robusta**; usar **promedio
espacial sobre varios puntos**. → Justifica la grilla de receptores de FoM (vs el
σ de un punto de Gunawan).

**C15. Taxonomía de "distorsión acústica" (qué controlar).** [07 S14]
Patologías a minimizar: **SBIR · comb filters · mala distribución modal ·
amortiguación modal no uniforme · reflexiones tempranas con demasiado nivel ·
diferencias L/R**. Es la checklist de lo que un buen par geometría-fuente evita.

## C.3 · Diseño del control room (Everest cap. 21) — el par canónico

**C16. ITDG (Initial Time-Delay Gap) como criterio.** [Everest p429-437, Beranek]
Gap entre el directo y la **primera reflexión** en el oyente. Un ITDG bien definido da
**impresión de sala más grande**. Valores: ~**20 ms** (salas de concierto buenas, ej.
Concertgebouw) · ~**9 ms** (control room LEDE de calidad). Beranek lo acuñó para salas;
se trasladó a control rooms. Es el parámetro temporal del par geometría-fuente.

**C17. LEDE (Live-End-Dead-End).** [Everest p430-432, Davis]
Frente **muerto** (absorbente alrededor de los monitores) → elimina las tempranas →
**desenmascara el ITDG del estudio** + mejora claridad. Fondo **vivo** con **difusión**.
Resultado: imagen estéreo mejorada + ambiente espacioso.

**C18. RFZ (Reflection-Free-Zone).** [Everest p438, Berger & D'Antonio]
Alternativa a absorber: **conformar las superficies frontales** para **desviar** las
tempranas **lejos** del operador → zona libre de reflexiones en el punto de escucha.
Una fuente puntual en esquina trihedral tiene **respuesta plana** si el punto de
observación está en la RFZ (sin reflexiones que interfieran). Combina geometría (forma
de las paredes) + ubicación (operador en la zona limpia).
**Detalle histórico (Newell p390-392):** la RFZ/LEDE nace de medidas TEF/TDS (Davis) ⇒ zona
sin tempranas en la posición de escucha + fondo difuso. Los "Haas kickers" (paneles
especulares en esquinas traseras para prolongar el efecto Haas) se **abandonaron** (no
ayudaban a la imagen estéreo). Ventana temporal del efecto ~**1–40 ms**; segundo sonido
"apenas detectable" a **+4 a 6 dB** sobre el directo. Refina C16/C17.

## C.4 · Del Recording Studio Design (Newell, 3ª ed.)

**C19. Sala de modos amortiguados (Fazenda / Newell) — filosofía alternativa.** [Newell p373]
En vez de optimizar la **distribución** modal (familia A.1-A.2: FSI, Bonello, Bolt…), **amortiguar
TODOS los modos** por debajo del umbral perceptual de coloración (C9). Resultado: sala **más
tolerante** a la posición de parlante y oyente (no "bi-direccional", reversible). Es el **trade-off
de diseño** frente a la optimización por ratio: gastar absorción/damping en lugar de geometría.
Ata con C9 (umbral perceptual de Fazenda) y C10 (límite del control pasivo sobre la varianza).

**C20. "Non-Environment" (Hidley) — frente reflexivo + resto absorbente.** [Newell p392]
Pared **frontal maximalmente reflexiva** + todas las demás superficies (salvo piso duro)
**maximalmente absorbentes** → empuja los monitores hacia una carga **cuasi-anecoica**,
respuesta **independiente de la posición**. Filosofía de control room **alternativa** a LEDE
(C17) / RFZ (C18); las tres atacan las tempranas/coloración por caminos geométricos distintos.

**C21. Regla de corregibilidad por EQ — directo vs indirecto (Newell).** [Newell p346-349] (refina C13)
Criterio operativo de **qué problema exige acústica/geometría y cuál delega al DSP**:
- Si la sala afecta al parlante **directamente** (carga del diafragma por una frontera cercana =
  **fase mínima**, mismo cociente de niveles en toda la sala) → **EQ del drive lo corrige** en
  **todas** las posiciones. (Es el boost del flush, B25.)
- Si lo afecta **indirectamente** (superposición de **reflexiones y resonancias** = **fase NO
  mínima**, dependiente de la posición, p. ej. nulos SBIR y nulos modales) → **NO se ecualiza**;
  sólo se arregla **físicamente** (ratio, ubicación, absorción). Es la razón de fondo para optimizar
  geometría/fuente (T8) y no "EQ después" (mismo principio que C13, Makivirta 2001).

## C.5 · Del Acoustic Absorbers and Diffusers (Cox & D'Antonio, 2ª ed.)

**C22. Sala de reproducción = neutral; de producción = reflexión + difusión.** [Cox&D'Antonio Intro p2-3]
Dos paletas de diseño opuestas: **reproducción** (estudio, home theatre, control room) debe ser
**neutral** — toda la info espectral/espacial ya está grabada; domina **absorción + difusión**, la
reflexión especular es menor. **Producción** (sala de conciertos, teatro) usa **reflexión + difusión**
como herramienta primaria; la absorción sólo controla reverberancia. Confirma la sala neutral de
Newell (C19) y el LEDE/RFZ (C17/C18). → fija el régimen de la app (recintos de reproducción).

**C23. Regla difusor vs absorbente.** [Cox&D'Antonio Intro p4]
Para matar eco / coloración / corrimiento de imagen por una reflexión fuerte:
- conservar RT y energía → **difusor** (dispersa sin quitar energía). En salas de conciertos
  (energía es premium) → difusores preferidos;
- bajar RT / nivel → **absorbente**.
Refina D14/B21/B24 (criterio de elección del tratamiento de la reflexión problemática).

**C24. LF no-difuso → α estadístico no aplica → wave-based (FEM/BEM).** [Cox&D'Antonio §1.3 p16, §1.1 p13]
Debajo de Schroeder el campo **no es difuso** → los coeficientes de absorción de incidencia
aleatoria y las leyes estadísticas (Sabine/Eyring) **no son válidos**; el efecto real de un
absorbente sólo se calcula con un **método de onda (FE/BE)**. **Valida** el enfoque FEM de la app
(ata con C11) y **explica el caveat** de B18/B27 (la app ve α ISO 354, ciego a la posición y a la
no-difusividad). Nota: muchos practicantes aplican igual la teoría difusa por conveniencia (no es
físicamente correcto).

## C.6 · Del BBC Guide to Acoustic Practice (Rose, 2ª ed. 1990)

**C25. NO simetrizar la reflexión temprana — matar ambas (distingue de B14/B9).** [Rose §4.6 p125]
La imagen estéreo la daña sobre todo la **reflexión lateral entre parlante y operador** → tratarla
con absorción/difusión. Si una ventana de observación a un lado del operador deja una reflexión
inevitable → cortina. **Clave:** "**no hay ventaja en poner una reflexión simétrica del otro lado —
sólo empeora**". ⇒ la **simetría que sirve** (B14/B9) es la del **campo modal / par fuente-oyente**,
NO la de las **reflexiones tempranas**: a éstas hay que **eliminarlas**, no balancearlas (consistente
con RFZ/LEDE C17/C18). Matiz extra: la **forma de la sala** alrededor del triángulo no necesita ser
simétrica (incluso "mejor evitarlo"), pero la **altura del cielo sobre ambos parlantes sí** (B29).

**C26. Mesa de control: geometría que no coloree ni rompa la imagen.** [Rose §4.7 p125-126]
La consola está cerca del operador **y** de los parlantes → su geometría es crítica:
- **Wrap-round (envolvente) = lo peor** (coloración fuerte); paneles laterales **verticales** a la
  altura del oído sentado **dañan la imagen** (evitarlos a ambos lados — ata C25).
- Superficie de mesa **casi horizontal** grande → el **cielo encima** debe ser absorbente/difusor
  (reflexión mesa↔techo, comb — ata B21/C24).
- Paneles metálicos amortiguados; marcos tubulares **rellenos de arena** (anti-resonancia).

---

# §D — Criterios perceptuales y parámetros objetivos (ISO 3382 / Beranek–Ando)

> Del deck "Parámetros modernos" (Bidondo, Fumeo, Galarza). Criterios de **calidad
> acústica** (mayormente salas medianas/grandes) que cierran la lista. Muchos se
> acoplan a la **geometría** (reflexiones de superficies) y a la **fuente**
> (ubicación de la orquesta/instrumento). Segmentación: **Energético / Temporal /
> Espacial** [03 S31].

**D1. Intimidad / Presencia ← ITDG** (initial-time-delay gap). Cercanía percibida.
**D2. Reverberación / Liveness** — RT60 (>350 Hz), EDT; relación temprano/tardío.
**D3. Claridad** — `C50` (voz) / `C80` (música): energía temprana/tardía [dB].
**D4. Riqueza del tono (tone fullness)** — expansión temporal de la nota (RT).
**D5. Calidez (Warmth) / Bass Ratio** — graves 75–350 Hz vs medios 350–1400 Hz.
**D6. Brillo (Brilliance)** — prominencia y decay lento de agudos.
**D7. Sonoridad (Loudness / G, Strength)** — nivel subjetivo.
**D8. Balance** — equilibrio entre secciones; depende de ubicación de fuentes.
**D9. Blend** — mezcla armoniosa de fuentes; depende de ubicación de la orquesta.
**D10. Ensamble** — reflexiones tempranas que dejan a los músicos oírse.
**D11. Ataque / Inmediatez** — ERs rápidas hacia el escenario (ITDG en fuente).
**D12. Textura** — patrón/secuencia de reflexiones tempranas (sello de la sala).
**D13. Rango dinámico y ruido de fondo** — NC/RC, HVAC, aislamiento.
**D14. Acoustic Glare** — coloración por reflexiones fuertes/comb (superficies
planas para ER) → evitar **curvando** superficies o con **difusores**.
**D15. Uniformidad espacial** — evitar **dead spots**; homogeneidad asiento-a-asiento
(es el correlato perceptual de `FoM_espacial`).
**D16. IACC / BQI (binaural, Ando/Beranek)** — amplitud espacial / envoltura.

**D17. Efecto "seat dip" — incidencia rasante sobre el público (Carrión §5.5.4).** [Carrión p268]
En salas con público en pendiente suave, el sonido directo viaja **rasante** sobre las filas de
butacas → interferencia que crea un **hueco de absorción en graves-medios (~100–300 Hz)** en las
plateas. Criterio de **salas grandes** (out of scope del régimen modal chico de la app), pero
completa la lista; se mitiga con pendiente/rake adecuado de la platea. Ata con D5 (calidez/BR,
que el seat-dip degrada).

---

# §E — Síntesis accionable para el scorer (T8)

> Qué de toda la lista **cambia algo en la app** vs qué sólo **valida/confirma** el diseño actual.
> Es el puente del doc a `modal_metrics` / `generate_candidates` / `default_location_weights`.
> **Plan de integración con punteros de código:** ver `plan_integracion_criterios_T8.md`
> (A33/A36/B27 desglosados por archivo·función·esfuerzo·validación). Estado: plan escrito, sin
> implementar (decisión del usuario 2026-06-20).

## E.1 · Cambios concretos sugeridos

| # | Criterio | Acción en la app |
|---|---|---|
| **A33** | Caja de ratios BBC `1:1.14:1.4` (`w/h=1.14±0.1`, `l/h=1.4±0.14`) | **Constraint/seed directo** en `generate_candidates` (más simple y citable que el índice Walker de A9; coincide con Rindel A). |
| **A36** ✅ | Damping per-modo pesado por la presión modal en cada cara | **HECHO** (`compute_xi_per_mode_per_face`, `face_materials.py`): `α_eff(n)=Σ_g α_g·p_g(n)`, `p_g=∮_g|φ_n|²dA / ΣJ`. Reduce exacto a Sabine global si materiales uniformes; con tratamiento asimétrico amortigua selectivamente según *dónde* está la absorción. (Lo de axial>tang>obl con α uniforme quedó diferido.) |
| **B27** ✅ | Poroso a **λ/4** (vel. máx) vs resonante en **esquina** (presión máx) | **HECHO** (advisory UI): `lf_modal_absorption_hints` avisa si asignás poroso (α bajo en graves, ≥15% sup.) sin resonante para control modal → sugiere panel perforado/membrana o poroso+cámara. No cambia la física (α ISO 354 sigue igual). |
| **A6/A53→FSI** | Rindel FSI ψ(25), `l/w` domina, evitar ψ>1.6 | Candidato a **reemplazar** la "suavidad modal" del scorer por FSI (ya anotado en A6). |
| **C8** | Pesar más picos que nulos (asimetría perceptual) | Variante de `FoM_flat` (plan §8.2) — **propuesta, no implementada** (diferida, Fastl/Zwicker). |

## E.2 · Validaciones (no cambian código, respaldan decisiones)

- **A37** (Howard&Angus): frecuencia crítica = **solapamiento modal 3** → **corrobora** el `M≥3`
  del MDCF (A13) de forma independiente. El `f_cross` de la app está bien fundado.
- **B32** (Meyer): instrumentos **omni <500 Hz** → en banda modal toda fuente es omni → **valida**
  descartar directividad (plan §1.1), también para fuentes acústicas.
- **B31** (Beranek): SBIR (B3) y carga de frontera (B4/B23) son **el mismo modelo de imágenes** →
  respalda tratar ambos con la misma física en `sbir.py`/carga.
- **C13/C21** (fase mín/no-mín): los nulos SBIR y modales **no se ecualizan** → justifica optimizar
  ubicación (T8) en vez de "EQ después".
- **C11/C24**: no-shoebox y LF no-difuso **exigen FEM** → valida el solver de la app.

## E.3 · Marco de FoM espejo del scorer (referencia)

`VSA`≈`FoM_flat` (planitud del promedio espacial) · `MSV`≈`FoM_espacial` (Welti, asiento-a-asiento) ·
`SDMFS`=std(Δfₙ) (Louden) — ver C12. La app cubre las tres dimensiones (planitud / consistencia /
distribución), más `modal_overlap_crossover` (C5/A37) como criterio de validez/suavidad.

---

## Referencias nuevas descubiertas (vía los decks de cátedra)

- **Fazenda, Stephenson & Goldberg (2015)** — "Perceptual thresholds for the
  effects of room modes as a function of modal decay", JASA 137(3). [C9]
- **Sarris (2014)** — "A new method for the determination of acoustically good
  room dimension ratios", AES 136th Conv. [A]
- **Walker (1996)** — "Optimum Dimension Ratios for Small Rooms", AES 100th Conv. [A9]
- **Waterhouse** — potencia en recinto vs campo libre (base teórica del SBIR). [B3]
- **amroc / amcoustics** — calculadora online de modos (herramienta). [A]
- **Toole (2008)** — *Sound Reproduction: Loudspeakers and Rooms*. [C/§D]
- **Economou & Charalampous (2016)** — Room resonances using wave-based geometrical
  acoustics (WBGA), 23rd ICSV. [A13/crossover]
- **Makivirta, Antsalo, Karjalainen & Välimäki (2001)** — Low-frequency modal
  equalization of loudspeaker-room responses, AES. [C13]
- **Brännmark & Sternad (2015)** — Controlling impulse responses and spatial
  variability in digital loudspeaker-room correction. [C14]
- **Mourjopoulos (1994)** — Digital equalization of room acoustics, JAES 42(11). [C13]
- **Lacatis et al. (2008)** — Historical evolution of concert hall acoustics
  parameters, Euronoise/Acoustics'08. [§D]
- **Ermann (2005)** — Coupled Volumes: Aperture Size and the Double-Sloped Decay
  of Concert Halls, *Building Acoustics* 12(1). [A25]
- **Harrison et al.** — refinamiento del "coupling constant" (`RT*/T15`). [A25]
- **Cerdá et al. (2014)** — Optimal Volume for Concert Halls Based on Ando's
  Subjective Preference and Barron Revised Theories, *Buildings* 4. [A22]
- **Barron (2002)** — *Industrial Noise Control and Acoustics* (RT óptimo). [A23-A24]
- **Economou & Charalampous (2016, WBGA)**, **Toole (2008)** — ya listados arriba.
- **Gilford (1959)** — volumen mínimo de sala (~1500 ft³). [A26]
- **Davis (Don/Chips)** — Live-End-Dead-End control room (1978). [C17]
- **Berger & D'Antonio** — Reflection-Free-Zone (conformado de superficies). [C18]
- **Olive & Toole** — audibilidad de reflexiones tempranas. [B21]
- **D'Antonio / RPG Diffusor Systems** — difusores de fase (Schroeder/QRD). [B24]
- **Newell, Philip (2017)** — *Recording Studio Design*, 3ª ed., Focal/Routledge. [A29-A31, B25-B26, C19-C21]
- **Hidley, Tom** — concepto "Non-Environment" (frente reflexivo + resto absorbente). [C20]
- **Rodgers, C. "Puddie"** — RFZ y dips por reflexiones tempranas de consola (AES + tesis). [C18]
- **Bolt, Beranek & Newman** — diagrama de 4 zonas (pressure zone / modos / difusión / especular). [A29]
- **Fazenda, B.** — sala de "modos amortiguados" (damped-mode listening room). [C19] (mismo autor que C9)
- **Cox & D'Antonio (2017)** — *Acoustic Absorbers and Diffusers*, 2ª/3ª ed., CRC Press. [A31, B27-B28, C22-C24]
- **De Jong & van den Berg / Cox (1995)** — optimización iterativa de difusores Schroeder (BEM + figura de mérito). [contexto §9.10, no criterio de recinto]
- **Rose, Keith A. (1990)** — *BBC Guide to Acoustic Practice*, 2ª ed., BBC Engineering. [A31, A33-A34, B29-B30, C25-C26]
- **EBU R22-1985** — recomendación de RT/tolerancias para estudios (base del §3.2 BBC). [A34]
- **Walker, R. (BBC Research)** — rango de proporciones de buena distribución modal `w/h=1.14±0.1, l/h=1.4±0.14` (contribuidor del BBC Guide; = A9). [A33]
- **Beranek & Mellow (2012)** — *Sound Fields and Transducers*, Academic Press. Ch 4 (radiación de fuentes simples, reflexión en un plano, combinación de fuentes en fase = base física de la carga de frontera y el SBIR). [B31]
- **Carrión Isbert, Antoni (1998)** — *Diseño Acústico de Espacios Arquitectónicos*, Edicions UPC. Fórmula de Rayleigh, fig 1.42 (región l/w), seat-dip. [A35, D17] (texto de teatros/salas de conciertos en ES; mayormente confirmatorio para salas chicas)
- **Lord Rayleigh (1877)** — *Theory of Sound* (fórmula de modos propios de caja). [A35]
- **Howard & Angus (2017)** — *Acoustics and Psychoacoustics*, 4ª ed., Focal Press. Ch 6 (modos axial/tang/obl, decay modal 1-D, frecuencia crítica = solapamiento modal 3, salas grandes/chicas, Bonello). [A36-A37]
- **Meyer, Jürgen (2009)** — *Acoustics and the Performance of Music*, 5ª ed., Springer. Ch 4 (características direccionales de los instrumentos: omni <500 Hz, índice de directividad, dirección principal). [B32, amplía B12]
- **Toole, Floyd (2008)** — *Sound Reproduction: The Acoustics and Psychoacoustics of Loudspeakers and Rooms*, Focal Press. Cap 13 (modos LF, "range of validity" del ratio, multi-sub/Welti, SFM, EQ acústica vs electrónica = fase mínima), cap 12 (boundary/SBIR, montaje), Geddes (absorción distribuida > forma). [respaldo A33, A36, C13/C21; sin criterios geom/fuente nuevos]

## Progreso de minado

- ✅ **Deck Bidondo (control room, UNTREF 2024)** — modos, SBIR, métricas, monitores.
  Aportó A17–A21, B13–B17, C9–C12.
- ✅ **07 - Diagnóstico de Controles de Estudio** — fase mín/no-mín, multipunto,
  taxonomía de distorsión. Aportó C13–C15.
- ✅ **03 - Parámetros modernos** — ISO 3382 / Beranek-Ando. Aportó toda la §D.
- ✅ **10 - Acoplamiento Acústico** — volúmenes acoplados, doble pendiente, V/RT
  óptimos (Barron, Cerdá). Aportó A22–A25. (Era salas grandes, no `φₙ(xₛ)`.)
- ✅ **05 - Coeficiente de Absorción** — metodología de medición; aportó B18 (tipo
  de absorbente por frecuencia). Bajo rendimiento (mayormente normas ISO/ASTM).
- ⊘ **Textos de FEM** (Ihlenburg, FEM for Acoustics, Petrov-Galerkin) → **van al doc aparte**
  de **numérica/validez del solver** (`numerica_fem_validez.md`), no a este doc de criterios.

## Libros minados (T2/T3) — corpus de salas chicas/estudio CERRADO

1. ✅ **Everest (Master Handbook)** — caps. 15 (modal/Bonello, vía cátedra) + 19
   (listening room: volumen, proporciones, nulos, trampas, reflexiones) + 21
   (control room: ITDG/LEDE/RFZ, carga +3/+6/+9 dB). Aportó A26-A28, B19-B24, C16-C18.
2. ✅ **Newell (Recording Studio Design, 3ª ed.)** — caps. 4 (modos/flutter/pressure zone),
   5-6 (neutral rooms, pressure zone, 4-zonas), 11 (loudspeakers in rooms: fase mín/no-mín,
   dipolos), 12-13 (control rooms: flush, LEDE/RFZ/Non-Environment, Fazenda). Aportó
   A29-A31, B25-B26, C19-C21. (Poco de ratios: su enfoque es **amortiguar** modos, no elegir
   proporción — ver C19.)
3. ✅ **Cox & D'Antonio (Absorbers & Diffusers, 2ª ed.)** — §1.3 modal control en salas críticas
   (poroso a λ/4 vs resonante en esquina), difusor vs absorbente, LF no-difuso → FEM. El grueso
   del libro son devices (absorbers/diffusers), no sizing de recinto. → A31(refuerzo), B27-B28, C22-C24.
4. ✅ **BBC Guide (Rose, 1990)** — §3.3-3.4 dimensiones/modos/flutter, §3.2 RT/tolerancias,
   §4 layout de control room (triángulo estéreo, monitores, reflexiones, mesa). Aportó A33-A34,
   B29-B30, C25-C26 + refuerzo A31. **OJO: es PDF ESCANEADO** (sin capa de texto → `_scrape.py`
   no sirve; hay que `Read` páginas como imagen). Offset libro↔PDF = **+2**.
5. ✅ **Beranek & Mellow (Sound Fields & Transducers, 2012)** — Ch 4 §4.9-4.12: reflexión en un
   plano + método de imágenes + dos fuentes en fase → duplicación de presión (carga 2π/4π formal,
   raíz común de B2/B3/B4/B23/B26). Aportó B31. (700 pág de mate; el text-layer destroza ecuaciones
   → leer prosa con `_scrape.py`, figuras puntuales con `Read`.)
6. ⏳ **Beranek (Concert Halls) / Ando / Barron** — parámetros ortogonales (salas grandes).
   **DIFERIDO (fuera de alcance):** ya cubierto por §D (A16/A22-A25) vía decks de cátedra.
7. ✅ **Meyer (Performance of Music)** — Ch 4 directividad de instrumentos: omni <500 Hz, índice de
   directividad, dirección principal. Aportó B32 (amplía/resuelve B12). PDF con capa de texto OK.
8a. ✅ **Carrión Isbert (1998)** — §1.15.5 modos (fórmula de Rayleigh, fig 1.42 región l/w),
   §5.5.4 seat-dip. Aportó A35, D17. **Es texto de teatros/salas de conciertos (ES): mayormente
   confirmatorio** (sin capítulo de estudios/control rooms; el material chico está en Ch1).
8b. ✅ **Howard & Angus (2017)** — Ch 6 (Hearing Music in Different Environments): decay modal 1-D
   por tipo de modo (axial>tang>obl), frecuencia crítica = **solapamiento modal 3** (corrobora el
   MDCF/A13), salas grandes vs chicas, Bonello, distancia crítica. Aportó A36-A37. **PDF con capa de
   texto** (scrape OK, hasta las ecuaciones salen). Buen rendimiento, formaliza A17/A18/A30.
8c. ✅ **Toole (2008, Sound Reproduction)** — cap 13 (modos LF: "range of validity" del ratio,
   multi-sub/Welti, SFM, EQ acústica vs electrónica = **modos LF son fase mínima**), cap 12
   (boundary/SBIR, montaje), cap 4.3 (transition frequency). **No aporta criterios geom/fuente
   nuevos**: relativiza los ratios (su tesis = gestión activa > proporción) → es **respaldo** de
   A33 (nota range-of-validity), A36 (Geddes: absorción distribuida > forma) y C13/C21 (min-phase,
   SFM valida T8). Capa de texto OK (scrape). **Offset libro↔PDF = +19.** Caps de reflexiones/imaging/
   multicanal/eval de altavoces = ⊘ fuera de alcance (la app no tiene IR ni mid-high).
