# Protocolo de medición para validación modal (campaña propia)

**Propósito.** Medir habitaciones reales con control total (geometría, materiales, fuente,
mics, RIRs) para validar el software por debajo de la frecuencia de Schroeder, destrabando
M3 (RT/impedancia) y M4 (forma espacial), que quedaron bloqueados con datasets públicos por
falta de datos de fuente y de materiales (ver `validation_results.md`, `REVIEW-VALIDACION.md`).

**Alcance de las normas (leer primero).** Las normas citadas (ISO 3382, ISO 18233, ISO 10534,
IEC 60268/61260/60942...) rigen la ADQUISICIÓN y la calibración, todas pensadas para campo
difuso / medias-altas. El ANÁLISIS modal (aparear fₙ, correlación espacial, corrimiento de fₙ)
queda FUERA de su ámbito: se valida contra el oráculo analítico y la línea base nula. Declararlo
así en el paper.

**Regla de oro (anti-sesgo, hereda de `validation_protocol.md` §1).** Nada se tunea al resultado.
Materiales del catálogo/medición, geometría medida tal cual, posiciones las medidas. Todo lo que
se ajuste se declara.

---

## FASE 0 — Diseño / elección de la sala (antes de ir)

Esto decide si la sala es VALIDABLE (lección C1: si los modos no se separan, M1 no discrimina).

- [ ] **Rectangular, NO cúbica, con razones NO conmensurables.** Objetivo ≈ **1 : 1.26 : 1.59**
  o **1 : 1.14 : 1.39** (Bolt 1946 / Louden 1971 / Sepmeyer 1965). Evitar 2:1, 3:2, cubo
  (degeneración → modos solapados).
- [ ] **Verificar separación modal.** Los modos a validar deben estar separados por más que su
  ancho de banda $B = 2.2/RT_{60}$ (Kuttruff §3). Con RT ≈ 0.5 s, B ≈ 4.4 Hz → querés espaciado > B.
  Contar los modos analíticos en la banda y chequear que no haya pares a < B.
- [ ] **Paredes rígidas y pesadas para el 1er caso** (hormigón/mampostería): β ≈ 0, modos ≈
  analíticos, picos filosos, alta Q. La absorción se agrega como perturbación en el caso 2.
- [ ] **Sala vacía** (sin muebles) en el 1er caso: la geometría es exactamente la modelada.
- [ ] **Pocos modos en banda** (sala no gigante): modos más espaciados, más fáciles de identificar.

---

## FASE 1 — Geometría (survey)

- [ ] **Dimensiones a milímetro** (fₙ ∝ 1/L: 1% de error en L = 1% en f).
- [ ] **Medir diagonales de planta y verificar escuadra.** Una sala "rectangular" real suele estar
  1-3° fuera de escuadra (FLAIR estaba rotada 8.5°). Anotar el desvío.
- [ ] **Definir origen y ejes** (una esquina = 0,0,0; ejes hacia las paredes). TODO (mics, fuente,
  materiales por superficie) se referencia a este marco único.
- [ ] Anotar alturas de piso irregular / cielorraso escalonado si los hay.
- [ ] Plano acotado + foto de cada superficie.

---

## FASE 2 — Materiales (condiciones de borde)

- [ ] **Impedancia compleja Z(f) por tipo de superficie** — **ISO 10534-2** (tubo de dos micrófonos)
  sobre muestras, o **ISO 13472-1** in situ. Es lo que destraba M3 y el modelo de reactancia (el α
  extrapolado sesga fₙ hasta 9%, por eso la reactancia-auto está OFF).
- [ ] Si solo hay α: **ISO 354** (cámara reverberante, incidencia aleatoria) o catálogo. **Declarar
  si el α es incidencia normal o aleatoria.**
- [ ] **Documentar CADA superficie** (piso, techo, 4 paredes, puerta, ventana) con material, área y
  Z(f)/α(f). Puertas y ventanas suelen ser el absorbente LF dominante (membrana): no omitir.
- [ ] Rango de frecuencia de los datos de material (que cubra la banda modal).

---

## FASE 3 — Fuente

- [ ] **Fuente única y compacta (monopolo).** Dimensión ≪ λ (a 50 Hz, λ ≈ 6.9 m → un sub cerrado
  chico anda). NO usar DBA / subs enfrentados (no es monopolo puntual). Requisitos de
  omnidireccionalidad: **ISO 3382-1** (Anexo).
- [ ] **Extensión en grave suficiente:** salida útil por DEBAJO del 1er modo axial $f_{100}=c/2L_{max}$
  con margen de SNR. Para 5 m, f₁ ≈ 34 Hz → sub plano a ~25-30 Hz. (Tu gotcha: si no baja, no se mide.)
- [ ] **FRD / respuesta del parlante medida** — **IEC 60268-21** (campo cercano / ground plane).
  Es lo que permite deconvolucionar la coloración de fuente (lo que hundió M4). Alternativa: CLF (.cf2).
- [ ] **Zona lineal** — **AES75**: nivel sin distorsión en grave.
- [ ] **Posición en esquina** (excita todos los modos; todos tienen antinodo en esquina). XYZ a cm en
  el marco de la Fase 1. Evitar nodos.

---

## FASE 4 — Micrófonos

- [ ] **10-15+ posiciones repartidas por TODA la sala** (no en un cluster local; ese fue el problema
  de MeshRIR para M4). Incluir antinodos (esquinas, centro, aristas) y puntos genéricos.
- [ ] **XYZ de cada mic a cm, en el marco único** de la Fase 1 (esto es lo que MeshRIR no publicó y
  dejó M4 inconcluso).
- [ ] **Calibración** — **IEC 60942** (calibrador/pistófono) antes y después. Mic de medición
  **IEC 61094**. Verificar **respuesta plana en grave** (muchos caen < 20 Hz) y, si se compara FRF
  compleja, la **fase**.
- [ ] No pegar el mic a la pared (duplicación de presión) salvo que se modele así. Anotar altura.

---

## FASE 5 — Adquisición

- [ ] **Barrido seno exponencial (ESS)** largo (10-30 s) — **ISO 18233** (método formalizado, Farina).
  Mejor SNR en grave que MLS y separa la distorsión.
- [ ] **Procedimiento de posiciones y promediado** — **ISO 3382-1**. Promediado sincrónico de varios
  barridos para subir SNR.
- [ ] **SNR ≥ 45-50 dB en la banda modal** — rango dinámico del EDC por **ISO 3382-2**. El grave es lo
  más difícil (ruido LF): medir el piso de ruido antes. (Tu gotcha: si la SNR no da, no se mide.)
- [ ] **fs 48 kHz**, **largo de IR ≥ 2×RT** (capturar todo el decaimiento, no truncar la FRF).
- [ ] **Filtros de banda** para RT/análisis — **IEC 61260-1** (octava/tercio).
- [ ] Documentar ventana y truncado (leakage).

---

## FASE 6 — Ambiente

- [ ] **Temperatura anotada en CADA medición** (c = 20.05·√(273.15+T); 3 °C ≈ 0.5% en fₙ). Absorción
  del aire: **ISO 9613-1** (menor en sala chica, pero es el dato formal).
- [ ] **HVAC apagado**, sala sellada (puertas cerradas → BC = la modelada). Medir de noche si el ruido
  de fondo lo exige.
- [ ] **Sin gente ni equipo suelto** adentro (absorben/difractan). Documentar lo que quede.
- [ ] Humedad relativa anotada.

---

## FASE 7 — Verificación en el lugar (antes de irte)

- [ ] **Repetir 1-2 posiciones** → varianza de medición (piso de "cuán bueno puede dar el match").
- [ ] **Chequear que se ven los modos**: mirar el espectro promedio de un par de mics in situ;
  confirmar picos separados en la banda esperada. Si el espectro sale suave/sin picos, revisar SNR,
  extensión de la fuente, o la sala (demasiado absorbente).
- [ ] Confirmar que el 1er modo axial cae dentro de la banda excitada por la fuente.

---

## FASE 8 — Handoff de datos (qué traerme y en qué forma)

Para correr la comparación sin ambigüedad, un directorio por sala con:

- [ ] **`geometria.txt`/plano**: dimensiones + vértices/paredes, con **origen y ejes** explícitos.
- [ ] **`fuente.txt`**: XYZ (mismo marco) + **FRD/CLF** o la IR ya deconvolucionada. Tipo de fuente.
- [ ] **`mics.csv`**: una fila por mic con `id, x, y, z` (mismo marco).
- [ ] **`rirs/`**: los **WAV** de cada RIR (nombrados por id de mic y de fuente), o IR ya procesadas.
- [ ] **`materiales.csv`**: por superficie, `superficie, material, area, tipo_dato(Z|alpha), incidencia,
  archivo_Z_o_alpha`.
- [ ] **`metadatos.txt`**: T y HR por medición, fs, tipo de excitación, largo de barrido, SNR estimada,
  relativo o calibrado en nivel, fecha/hora.

---

## Escalera de complejidad (aislar una variable por vez)

1. **Caja dura vacía, buenas razones** → valida M1 (oráculo analítico + medición). El caso más limpio.
2. **+ una superficie absorbente con Z medida** → valida amortiguamiento/reactancia (M3, corrimiento
   de fₙ, M4).
3. **+ muebles de geometría conocida** → valida geometría/scattering.
4. **Sala en L / no-caja** (dimensiones medidas directo, sin reconstrucción de nube) → valida la malla
   en geometría arbitraria.

---

## Tabla paso → norma

| Paso | Norma |
|---|---|
| Adquisición de RIR, posiciones, fuente omni | ISO 3382-1 |
| RT y rango dinámico / SNR del EDC | ISO 3382-2 |
| Método ESS/MLS con deconvolución | ISO 18233 |
| Impedancia Z(f) de materiales (tubo) | ISO 10534-2 (o -1) |
| Absorción α in situ / cámara | ISO 13472-1 / ISO 354 |
| Respuesta del parlante (FRD) | IEC 60268-21 (-5, -22) |
| Nivel lineal del parlante | AES75 |
| Calibrador / micrófono patrón | IEC 60942 / IEC 61094 |
| Filtros de octava/tercio | IEC 61260-1 |
| Absorción del aire / c(T) | ISO 9613-1 |
| Magnitudes y símbolos / vocabulario | ISO 80000-8 / IEC 60050-801 |

(En Argentina, buscar los equivalentes IRAM de ISO 3382 y de la instrumentación IEC.)
