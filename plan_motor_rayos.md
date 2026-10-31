# Plan: motor de rayos / acústica geométrica (híbrido con el núcleo modal)

> Estado: **DISEÑO CERRADO (grill 2026-10-31), SIN CÓDIGO todavía.** Árbol de
> decisiones acordado con el usuario (Q1-Q10). Antes de implementar una línea de
> cada fase (R1-R5), OK explícito del usuario, igual que el resto del proyecto.
> Referencias en `referencias/13_acustica-geometrica/` (más Kuttruff, Morse &
> Ingard, Vorländer en `01`, y el crossover en `02`/electroacústica).

---

## 0. Objetivo y encuadre

Extender el simulador a **toda la banda audible** como un **híbrido**: el núcleo
modal FEM (exacto, abajo de la frecuencia de Schroeder f_S) y un **motor
geométrico** nuevo (arriba de f_S), empalmados sin doble conteo ni salto en la
FRF. El norte sigue siendo §0 de `notas_para_claude.md`: la simulación más
EXACTA posible, cada modelo validado por fase contra un oráculo analítico,
cruzado o medido. El norte del motor es simular todos los fenómenos de la onda:
generación/radiación, propagación, reflexión, absorción, difusión (scattering),
difracción, e inmisión en el receptor. Transmisión queda diferida (ver Q8).

**Disciplina D0 (no negociable):** TODO el motor es **numpy/scipy desde cero**
(trazado, imágenes, BTM, FFT del crossover). PyQt5/pyqtgraph/trimesh/gmsh siguen
siendo solo GUI/IO. La geometría sale de las **caras de la malla FEM** que ya se
construye (no un modelo aparte).

## 1. Semilla que ya existe (leer antes de estimar)

- `reflections_ism.py` (v2.78): fuentes-imagen (ISM) EXACTO para **shoebox**
  hasta orden 3, energía por banda de octava. Es el **oráculo especular** del
  motor y el punto de partida de R1. Limitación declarada: shoebox convexo, sin
  test de visibilidad (CAD no convexo = salto al motor).
- `acoustic_mesh` / `acoustic_fem.FieldEvaluator`: la malla de tetraedros y el
  locator ya existen; las **caras de frontera** del dominio son la geometría
  sobre la que corren rayos e imágenes (no hay que mallar aparte).
- `frd.load_clf` (v2.29): lector CLF validado 0.000 dB vs CLF Viewer. Es la
  **directividad** de la fuente geométrica (R4). Abajo de f_S se ignora (omni,
  correcto); arriba sí entra.
- Materiales (Capa 0): α por tercio/octava y modelos de impedancia. El motor
  agrega **s(f)** (scattering) como propiedad nueva por material, en paralelo a α.
- Receptores (`listen_points`) y métricas (RT, EDT, C50, SBIR, FRF, mapa): se
  reusan; el motor extiende su rango a banda completa por el híbrido.

## 2. Árbol de decisiones (grill Q1-Q10, cerrado)

| # | Decisión | Resolución |
|---|---|---|
| Q1 | ¿Energía o fase? | **Híbrido energía+fase.** El geométrico mantiene fase (IR de presión por imágenes) en el temprano/especular → peine y SBIR a toda frecuencia; energía estocástica solo en la cola difusa tras el mixing time |
| Q2 | Empalme FEM↔geométrico en f_S | **Crossover complementario en frecuencia** tipo Linkwitz-Riley (magnitud plana en la suma): FEM pasa-bajos + geométrico pasa-altos, banda de transición f_S a ~2·f_S, fase cero, sin doble conteo |
| Q3 | Familia de método y geometría | **Dos motores sobre la malla FEM real:** imágenes con test de visibilidad (temprano, orden ~2-3) + rayos estocásticos Möller-Trumbore (cola difusa); scattering reparte especular/difuso (Lambert). Radiosidad = oráculo/alternativa |
| Q4 | Difracción | **BTM 1er orden coherente** obligatoria en bordes visibles (columna, muebles, aberturas, bafle); 2do opcional con subdivisión de Calamia; espesor finito Chu/Stanton/Pierce. En la cola difusa la difracción se absorbe en el scattering |
| Q5 | Difusión / scattering s(f) | **Por superficie, dependiente de f**, default estimado (Kuttruff/Vorländer) + override medido ISO 17497, enganchado a materiales (Capa 0) junto a α |
| Q6 | Radiación / directividad | Fuente geométrica con **directividad CLF/GLL** (`frd.load_clf`), multi-driver sumado coherente en el temprano; omni abajo de f_S, directiva arriba, continua en el cruce |
| Q7 | Mixing time y aire | Handoff imágenes→rayos en el **mixing time** (regla de volumen, Vorländer); **absorción del aire** por coeficiente m (temp/humedad, Kuttruff / ISO 9613-1) |
| Q8 | Transmisión | **Diferida** a milestone posterior; por ahora solo como impedancia/admitancia de frontera (donde ya entra) |
| Q9 | Validación | **Un bench por fase** (oráculos abajo) + end-to-end vs medición (MeshRIR/FLAIR arriba de f_S) con tolerancia por **JND** |
| Q10 | Salida | **IR de presión híbrido + FRF + métricas de banda completa** por receptor; auralización/BRIR diferida |

## 3. Fases (R0-R5), cada una con su oráculo

> Regla de oro por fase: no se avanza a la siguiente sin el bench verde. Cada
> fase es física GEOMÉTRICA nueva = NÚCLEO EN ALCANCE del auditor (salvo lo
> marcado GUI).

**R0 — Andamiaje + contrato de validación (poco código).**
- Definir el módulo (API: fuente/receptor/geometría desde caras FEM) y el arnés
  de benches. `reflections_ism.py` queda formalizado como oráculo especular.
- Sin física nueva; prepara R1-R5.

**R1 — Imágenes con visibilidad sobre geometría arbitraria (temprano, coherente).**
- Extender el ISM de shoebox a **poliedro arbitrario** con test de visibilidad;
  IR de **presión complejo** (fase), orden ~2-3.
- Oráculo (`bench_ism_general`): vs `reflections_ism` en shoebox (debe coincidir
  EXACTO); 1er orden analítico; continuidad al cruzar frontera de zona especular.

**R2 — Trazado estocástico de rayos (cola difusa, energía).**
- Rayos Möller-Trumbore sobre caras FEM; histograma de energía; en cada impacto
  el **scattering ISO 17497** reparte especular/difuso (Lambert).
- Oráculo (`bench_ray_diffuse`): vs **radiosidad** (Nosal, determinista) misma
  geometría; decaimiento Sabine/Eyring/Kuttruff; conservación de energía;
  convergencia en nº de rayos (varianza Monte Carlo).

**R3 — Difracción BTM (fuentes secundarias coherentes).**
- 1er orden obligatoria en bordes visibles; 2do opcional (subdivisión de
  Calamia); espesor finito (Chu/Stanton/Pierce) cuando el canto es grueso.
- Oráculo (`bench_btm_diffraction`): **cuña exacta de Morse & Ingard** (§8-9) +
  casos de Calamia; continuidad del IR al cruzar sombra/zona especular.

**R4 — Fuente, scattering, aire, mixing time (entradas físicas).**
- Directividad CLF/GLL en la fuente geométrica; s(f) por material (default
  estimado + override ISO); absorción del aire (coef. m, temp/humedad); mixing
  time (regla de volumen).
- Oráculo (`bench_source_air_scatter`): balloon de directividad vs CLF Viewer
  (reusa la validación del lector); límites s=0 (recupera ISM puro) y s=1
  (Lambert puro); m vs tabla ISO 9613-1; mixing time vs fórmula de volumen.

**R5 — Empalme híbrido en f_S + validación end-to-end.**
- Crossover complementario LR; ensamblar FEM(<f_S) ⊕ geométrico(>f_S) → IR de
  presión / FRF / métricas de banda completa por receptor.
- Oráculo (`bench_hybrid_crossover` + end-to-end): **continuidad de la FRF en
  f_S** (sin salto en módulo ni fase), el híbrido matchea FEM abajo y geométrico
  arriba en el solape; **end-to-end vs medición** (extender MeshRIR/FLAIR por
  encima de f_S) con tolerancia por JND (incertidumbre de Vorländer 2011,
  comparación tipo Rindel et al. 1999).

## 4. Qué NO toca (regresión garantizada)

El núcleo modal (FEM, perturbación, QEP, carve, métricas abajo de f_S) **no
cambia**: el motor es aditivo y vive por encima de f_S. Con el motor apagado, o
por debajo de f_S, la salida es bit a bit la de hoy. Transmisión y auralización
quedan fuera de este milestone.

## 5. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Test de visibilidad caro/frágil en CAD no convexo | Orden bajo (~2-3) en imágenes; la cola la hace el rayo (escala a geometría arbitraria sin visibilidad explícita) |
| Ruido Monte Carlo en la cola difusa | Radiosidad (Nosal) como oráculo determinista; reportar convergencia en nº de rayos |
| s(f) incierto mueve el resultado (Vorländer 2011) | Default estimado conservador + override medido ISO 17497; reportar sensibilidad |
| Salto o doble conteo en el cruce f_S | Par complementario LR (suma de magnitud plana), fase cero; bench de continuidad de FRF |
| Difracción explícita en la cola (costo) | Solo en bordes tempranos dominantes; en la cola se absorbe en scattering (práctica estándar) |

## 6. Referencias (por decisión)

- **Híbrido, crossover, auralización:** Vorländer, *Auralization* (`01`);
  Aretz, *Combined Wave And Ray Based Room Acoustic Simulations Of Small Rooms*
  (`13`); Kuttruff, *Room Acoustics* cap. 3-4 (`01`); forma del filtro:
  Butterworth 1930 + Douglas Self, *The Design of Active Crossovers* (LR =
  Butterworth²).
- **Imágenes:** Allen & Berkley 1979, *Image method for efficiently simulating
  small-room acoustics* (`13`); `reflections_ism.py`.
- **Rayos / intersección:** Möller & Trumbore 1997, *Fast, Minimum Storage
  Ray/Triangle Intersection* (`13`).
- **Difusas (oráculo):** Nosal, Hodgson & Ashdown 2004, radiosidad acústica (`13`).
- **Difracción:** Calamia & Svensson 2007 + Calamia 2009 (tesis Princeton) (`13`);
  Chu, Stanton & Pierce 2007, borde de espesor finito (`13`); cuña exacta:
  Morse & Ingard, *Theoretical Acoustics* §8-9 (`01`).
- **Scattering/difusión:** ISO 17497-1 (scattering) y -2 (diffusion) (`13`);
  Kuttruff; Cox & D'Antonio (`04`).
- **Directividad:** `frd.load_clf`; Vorländer, *Auralization*.
- **Aire:** ISO 9613-1 (m, atenuación atmosférica); Kuttruff (`01`).
- **Validación/aceptación:** Rindel, Shiokawa, Christensen & Gade 1999 (sim vs
  medición) (`13`); Vorländer 2011, *Models and Algorithms for Computer
  Simulations in Room Acoustics* (incertidumbre de entradas) (`13`); pipeline
  empírico propio (MeshRIR/FLAIR, `[[validacion-empirica]]`).
