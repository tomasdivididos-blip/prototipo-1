# Plan: validación de los criterios (¿funcionan? ¿mejoran de verdad el campo?)

> Estado: **metodología (29 Oct 2026)**. Responde el ítem iv del backlog del
> profesor (`backlog-charla-sep.md`). Material de tesis (papers B/D, `tesis-plan`).
> Semilla implementada: `bench_criteria_validation.py` (Capa 1, in silico).

## 0. El problema (planteo del usuario)

Tenemos criterios de diseño en tres lugares: la **Predicción** (Bolt, FSI, Bonello,
Modal-Q/Fazenda, Schroeder, RT, STI...), la **optimización de ubicación** (FoM de
planitud + espacial + SBIR + suavidad) y el **CABS/DBA** (drive de subs enfrentados).
La pregunta honesta: **no sabemos si funcionan**, es decir, si seguir un criterio
*realmente mejora el campo dentro de la sala*. Validarlos construyendo y demoliendo
salas reales es **carísimo e irreal**.

## 1. La idea que disuelve el costo

"Construir y demoler salas" es prohibitivo en lo **físico**, pero **gratis en
simulación**. El motor FEM modal es EXACTO y ya está validado contra oráculos
independientes (modos analíticos shoebox, QEP de frontera, SLEPc en WSL) y contra
medición (FLAIR M1 = 1.42 %, [[validacion-empirica]]). Por lo tanto el motor ES la
**verdad de terreno** barata: validar un criterio = **experimento computacional
sobre un ENSAMBLE de salas simuladas**. Lo físico se reduce a **unas pocas
mediciones A/B** (el delta), no a un ensamble de salas construidas.

## 2. De qué tipo es cada criterio (define si la validación es circular)

Hay que separar dos clases, porque se validan distinto:

1. **Heurísticos externos** (Bolt, Bonello, Louden, **FSI de Rindel**, umbral de
   Fazenda): reglas de la literatura o de teoría simplificada, que miran SOLO las
   frecuencias/geometría. Testearlos contra el **campo FEM exacto** (que mira la
   respuesta real, modos + formas) es validación **REAL, no circular**: ¿la regla
   predice lo que la física exacta muestra?
2. **Métricas internas del modelo** (FoM_flat, FoM_espacial, el objetivo del
   optimizador, la varianza de zona del CABS): **SON** el campo exacto medido sobre
   una grilla. Validarlas tiene dos partes: (a) que el **motor** sea fiel (ya: Capa
   2), y (b) que **optimizarlas** dé mejor campo (A/B) y que la métrica sea **proxy
   de percepción** (anclaje a umbrales de audibilidad + medición). Testear una
   métrica interna "contra sí misma" SÍ sería circular; por eso su validación vive
   en las Capas 2 y 3, no en la 1.

## 3. Tres capas de validación (costo creciente, todas falsables)

### Capa 1 — Ensamble in silico (GRATIS): ¿el criterio correlaciona con el campo exacto?

Generar N salas (barrer dimensiones/ratios/ubicación de fuente-receptor). Por cada
una, computar **el score del criterio** Y **la métrica de campo exacta del FEM**
(planitud espacial, varianza entre asientos, irregularidad del espaciado modal
real). Test: **¿el criterio correlaciona (Spearman) con la métrica exacta?** Un
criterio que "funciona" rankea las salas **igual** que la física exacta.

- **Falsable:** si el score de Bolt (o el FSI) NO correlaciona con la planitud modal
  que el FEM computa sobre, digamos, 300 salas aleatorias, el criterio (o su peso en
  el scorer) es sospechoso y hay que revisarlo.
- **Es exactamente "construir y demoler salas"**, pero en simulación → gratis.
- Esta capa es **nueva** y es la que faltaba. Semilla: `bench_criteria_validation.py`.

### Capa 2 — Oráculos exactos (BARATO): el motor es confiable

Validar el campo FEM contra oráculos independientes: modos analíticos de shoebox, el
QEP de frontera exacto, SLEPc. **Ya hecho** (benches del proyecto). Sostiene la Capa
1: sin un motor confiable, correlacionar contra él no significa nada.

### Capa 3 — Medición A/B (CARA pero MÍNIMA, real): el delta

Verdad de terreno última: que el FEM coincide con una sala **real**. NO se
reconstruye nada: se mide **UNA sala en dos ESTADOS** (A/B: con/sin tratamiento, o
dos configuraciones de subs) y se valida que el modelo predice el **CAMBIO (Δ)**, no
un número absoluto. El delta **cancela los errores sistemáticos** (calibración,
frame, posición de mic). Es el enfoque del **paper B/D** ([[tesis-plan]]) y de la
medición #6c pendiente ([[criterios-research]], [[validacion-empirica]]). FLAIR M1
ya PASA; falta la campaña propia A/B (`protocolo_medicion.md`).

## 4. Qué experimento concreto por familia

| Familia | Capa 1 (ensamble in silico) | Capa 3 (medición A/B) |
|---|---|---|
| **Predicción** (Bolt/FSI/Bonello/ModalQ/Schroeder) | Correlación de CADA sub-score con la métrica de campo exacta sobre N salas. El que no correlaciona, no discrimina → revisar peso o descartarlo. | Medir 2 salas (o 1 en 2 estados) y ver si el ranking predicho por el scorer coincide con el ranking medido. |
| **Optimización de ubicación** | A/B: ¿el layout que elige el optimizador tiene MEJOR métrica de campo exacta que M layouts aleatorios en la misma sala? (fracción de veces que gana, sobre N salas). | Medir la sala con la ubicación óptima vs una ubicación control, ver si el Δ medido tiene el signo y orden predichos. |
| **CABS/DBA** | Salas × {CABS/DBA ON vs OFF, drive canónico vs naive}: ¿la varianza espacial LF exacta BAJA con el drive recomendado, como predicen Celestinos/Santillán? | Medir la sala con y sin el array trasero retardado/invertido; validar el Δ de uniformidad espacial. |

## 5. Estado

- **Capa 2:** HECHA (oráculos analítico/QEP/SLEPc en los benches del núcleo).
- **Capa 3:** parcial (FLAIR M1 PASA); falta la campaña propia A/B (#6c, protocolo
  escrito en `protocolo_medicion.md`).
- **Capa 1:** NUEVA. Semilla en `bench_criteria_validation.py` (ensamble de salas +
  correlación de un criterio con el campo exacto). Extensiones: más criterios, más
  salas, el A/B del optimizador y del CABS.

## 6. Falsabilidad y límites

- El ranking de Spearman (Capa 1) es falsable: un criterio con |ρ| bajo contra la
  métrica exacta NO está prediciendo el campo (o la métrica exacta no es la
  relevante; hay que declarar CUÁL métrica de campo se toma como referencia).
- Circularidad: NO testear una métrica interna del modelo contra sí misma. La Capa 1
  valida HEURÍSTICOS (type 1) contra el motor; las métricas internas se validan por
  motor (Capa 2) + percepción/medición (Capa 3).
- Todo esto vale **bajo Schroeder** (régimen modal, el norte del proyecto §0). Las
  reflexiones tempranas / media-alta frecuencia quedan para el futuro motor de rayos.

## 7. Referencias

- Ensambles de salas simuladas para evaluar criterios: enfoque estadístico-modal de
  Welti & Devantier (multi-sub, JAES 2006), Cox & D'Antonio (optimización de salas).
- CABS/DBA: Celestinos & Nielsen (JAES 56(11) 2008), Santillán (JASA 110(4) 2001).
- Validación por delta A/B y medición: [[validacion-empirica]], [[calibracion-rirs]],
  `protocolo_medicion.md`; FLAIR/MeshRIR.
- Criterios y su cobertura: `criterios_room_geom_fuente.md`,
  `cobertura_criterios_en_soft.md`.
