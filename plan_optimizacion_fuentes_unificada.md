# Plan — Panel unificado "Optimización de fuentes"

> Estado: DISEÑO (sin implementar). Escrito 2026-09-16. Pedido del profesor
> Bidondo (vía Ale, chat 15 Sep 2026) + acuerdo de dirección con el usuario
> (opción "panel único"). Los puntos 1 (cualquier par opuesto) y 2 (optimizador
> no-freeze) YA se implementaron; este .md es el punto 3. NO codear sin OK.

## 0. Motivación y norte físico

Feedback del profesor, en sus palabras: "la suma de todas las transferencias
modales (de los main y de los subs desparramados por el recinto) debe dar una
transferencia modal *compuesta* lo más *plana* posible", y "debería poder
optimizar o evaluar CABS/DBA sin importar la geometría del recinto ni si es
regular o convexo".

Corolario de diseño: el norte de la optimización es una **propiedad de la sala +
las fuentes** (aplanar la respuesta compuesta), independiente de la geometría y
del esquema de array. CABS/DBA dejan de ser "una herramienta aparte" y pasan a ser
**un criterio más** dentro de una optimización general de fuentes.

Referencias: Welti & Devantier, *Low-Frequency Optimization Using Multiple
Subwoofers*, JAES 54 (2006) (MSO: posición+ganancia+delay multi-sub); Celestinos &
Nielsen sobre CABS; el criterio SBIR (Ballou / Toole) y la uniformidad modal (Bolt).

## 1. Estado actual (por qué está partido y confunde)

Hay DOS entradas de optimización de fuentes, con criterios distintos:

- **Acústica → "Subs Enfrentados" (`dba_dialog.py` + `cabs_optimize.py`).**
  Criterios: DBA (drive canónico L/c) y CABS (trasero manejado). Objetivo =
  planitud + varianza espacial de la respuesta compuesta (SBIR + modal). Motor:
  `differential_evolution` sobre las variables libres por fuente (pos/delay/fc/
  polaridad/nivel). Antes ataba el criterio a un eje (frente/trasera) — corregido
  el 15 Sep (cualquier par opuesto, Auto).

- **Predicción → "Optimizar / Ubicación de fuentes" (`location_opt.py` +
  `prediction_panel.py`).** Criterios: `flat` (FoM planitud), `espacial` (FoM
  asiento-a-asiento), `sbir`, `smoothness` (uniformidad modal estilo Bolt), con
  PESOS por caso de uso (música/HT/mezcla). Motor: semillas heurísticas
  (estéreo simétrico, subs a 1/4, esquina, flush) + refinamiento. Geometría-
  agnóstico (corre sobre el FEM real de cualquier recinto).

Problemas que reporta Ale:
1. El nombre "Subs Enfrentados" sugiere que sólo sirve para subs enfrentados, y
   antes fallaba si no estaban en el eje más largo.
2. Los criterios están separados: Acústica NO tiene los criterios de Predicción y
   viceversa. El usuario no puede elegir un solo "norte" con todo junto.

## 2. Propuesta: un solo panel "Optimización de fuentes"

Renombrar/absorber "Subs Enfrentados" en un panel **"Optimización de fuentes"**
(el nombre que pidió Ale) con esta estructura conceptual:

### 2.1 Elegir el NORTE (criterio objetivo)

Un selector de criterio-norte, con TODOS los criterios juntos:

- **Transferencia compuesta plana** (default, el norte del profesor): minimizar la
  no-planitud de la respuesta compuesta (mains + subs) en la banda de interés.
  Reusa `dba_evaluate._config_metrics` (flat) — ya existe.
- **Uniformidad espacial** (varianza asiento-a-asiento): `spatial` / FoM_espacial.
- **CABS**: cancelación modal por par de paredes opuestas (trasero manejado).
- **DBA**: doble bass array con drive canónico L/c.
- **SBIR**: minimizar el peine de reflexiones de borde.
- **Uniformidad modal (Bolt)**: `modal_smoothness_score`.
- (Opcional) **Combinado con pesos**: como el scorer de Predicción por caso de uso
  (música/HT/mezcla), reusando `location_opt._weights_for_use`.

CABS/DBA se vuelven ítems de esta lista, no una pestaña. Cuando el norte es
CABS/DBA, se muestran sus controles específicos (eje Auto/manual, drive del array);
para los demás criterios esos controles se ocultan.

### 2.2 Grados de libertad por fuente (ya existe)

La tabla de fuentes con `free_vars` por fuente (pos / delay / fc / filtro /
polaridad / nivel). Las fuentes sin nada tildado quedan fijas. Es el mecanismo
actual de `cabs_optimize`; se mantiene tal cual.

### 2.3 Cualquier geometría

La optimización corre sobre el recinto real (regular, irregular o CAD). Para el
motor `differential_evolution` esto ya funciona con `inside_fn` (restricción al
polígono real) + el FEM/base modal del recinto. Para criterios que hoy sólo viven
en Predicción (FoM/smoothness sobre la malla FEM), hay que decidir el motor común
(ver §3).

### 2.4 No-freeze (ya implementado, punto 2)

Corre en un `QThread` con barra de progreso + Cancelar (hecho 15-16 Sep en
`dba_dialog._OptimizeWorker` + `cabs_optimize.optimize_cabs(progress_cb,
should_cancel)`, polish=off, popsize adaptativo). El panel unificado hereda esto.

## 3. Decisiones técnicas a resolver (antes de codear)

1. **¿Un solo motor o dos?** Hoy Acústica usa `differential_evolution` sobre
   free-vars; Predicción usa semillas heurísticas + refinamiento. Opciones:
   (A) unificar todo en `differential_evolution` con una función-objetivo que
   despacha por criterio-norte (más simple de UI, pierde las semillas heurísticas
   buenas de Predicción); (B) mantener los dos motores y que el criterio-norte
   elija cuál corre por detrás (más código, conserva lo mejor de cada uno);
   (C) motor de DE con SEMILLAS de las heurísticas de Predicción (lo mejor de los
   dos, más trabajo). Recomendación tentativa: C a mediano plazo, B como primer
   paso barato.
2. **Función-objetivo común.** `dba_evaluate._config_metrics` (flat/spatial) y
   `modal_metrics`/`location_opt` (FoM/sbir/smoothness) miden cosas parecidas pero
   NO idénticas (grillas, normalizaciones, SBIR). Hay que unificarlas o mapearlas a
   una escala común, y validar que el "norte compuesto plano" coincide con lo que
   el profesor espera (oráculo: una config conocida-plana debe puntuar mejor).
3. **Dónde vive el panel.** ¿Nueva pestaña "Optimización", o dentro de Acústica
   renombrando el grupo, o dentro de Predicción? (UX abajo). Sea cual sea, "Subs
   Enfrentados" se renombra y CABS/DBA quedan como criterios.
4. **Migración .room**: los `free_vars`, el criterio elegido y los pesos deberían
   guardarse. Ver versión del formato.

## 4. UX/UI (a validar con el usuario)

Layout tentativo del panel:

```
Optimización de fuentes
├─ Norte (criterio):  [Transferencia compuesta plana ▾]
│     (si CABS/DBA)   Eje: [Auto ▾]   Drive array: [LS ▾]
│     (si combinado)  Pesos: flat[..] espacial[..] sbir[..] modal[..]
├─ Banda:  fmin [20] – fmax [200] Hz     ξ [0.03]
├─ Fuentes (qué puede mover el optimizador):
│     ☐ MainL   pos☑ delay☐ nivel☑ …
│     ☐ SubR    pos☑ delay☑ polaridad☑ …
├─ [Evaluar]   [Optimizar]   (barra de progreso + Cancelar)
└─ Resultado: criterio antes→después, cambios propuestos, [Aplicar]
```

Preguntas de UX abiertas (para charlar):
- ¿Pestaña nueva "Optimización" o grupo dentro de una existente? (impacta el
  árbol de navegación y el .room).
- ¿El criterio-norte es único o se pueden combinar varios con pesos siempre?
- ¿"Evaluar" y "Optimizar" comparten el mismo criterio-norte (coherencia) —
  igual que hoy CABS evalúa y optimiza el mismo criterio?
- ¿Se muestran las semillas heurísticas (estéreo/1-4/esquina) como puntos de
  partida elegibles, o el motor las prueba solo?

## 5. Fases sugeridas (cuando haya OK)

1. **Fase A (UI):** renombrar "Subs Enfrentados" → "Optimización de fuentes",
   agregar el selector de criterio-norte con CABS/DBA + compuesta-plana +
   espacial (los que ya calcula `_config_metrics`). Sin motor nuevo. Barato.
2. **Fase B (criterios de Predicción):** traer SBIR + smoothness + FoM al panel
   (motor común, decisión §3.1). Requiere unificar la función-objetivo (§3.2).
3. **Fase C (semillas):** DE con semillas heurísticas de Predicción (opción C).
4. **Fase D:** deprecar/redirigir la entrada duplicada, .room versionado, MANUAL.

## 6. Qué NO cambia

- El núcleo físico (base modal, SBIR, respuesta compuesta) no se toca; sólo se
  reorganiza qué criterio se minimiza y desde qué panel.
- El fallback de "optimizar igual para uniformidad" cuando el criterio estricto
  (CABS/DBA) no es factible se mantiene: el gate informa, no bloquea.

## 7. Criterios de aceptación (de este plan, no del código)

- El usuario valida la dirección UX (§4) y el orden de fases (§5).
- Queda decidido el motor común (§3.1) y la unificación de la función-objetivo
  (§3.2) con un oráculo de "más plano = mejor puntaje".
- Recién entonces se implementa Fase A.

## 8. Geometría no rectangular: cómo evaluar los criterios de caja

CABS/DBA (y el "norte" de transferencia compuesta plana) están definidos, en su
teoría de arrays, para recintos **rectangulares (paralelepípedo)**. Cuando la sala
es un polígono irregular, un CAD o tiene techo curvo, aproximarla por su caja
contenedora (AABB) **agrega volumen de aire** (las esquinas/chaflanes que la sala
real no tiene), y evaluar los criterios sobre la caja analítica mide la geometría
equivocada. Tres caminos, del más limpio al más caro (pregunta del usuario 16 Sep):

### e) Evaluar sobre el campo FEM REAL (elegido, IMPLEMENTADO 16 Sep 2026)

El soft **ya malla la geometría real** (FEM voxel/gmsh), así que el campo modal
exacto del recinto está disponible. La métrica del criterio (planitud + varianza
espacial de la respuesta total modos+SBIR) se computa sobre ese campo FEM, no sobre
la caja analítica. No hay que aproximar nada.

Estado: HECHO para evaluar Y optimizar. `dba_evaluate.FEMModalField` adapta la
solución modal FEM (locator/freqs/phis) a la MISMA interfaz que `RectModalBasis`
(mapeando coords caja↔mundo por `origin`), así `_config_metrics` la usa sin cambios.
`evaluate_cabs(fem=...)` y `optimize_cabs(fem=...)` la reciben; el panel pasa el
bundle FEM en el `eval_context` **cuando la sala no es rectangular** y ya hay modos
resueltos (en una caja se sigue con la base analítica: exacta, más rápida y con más
modos). Los puntos de la grilla de zona que caen en el volumen extra del AABB (fuera
de la malla real) se **excluyen** del metric (`FEMModalField.inside_mask`), si no
darían presión 0 → −600 dB → varianza gigante. Oráculo en `bench_source_opt.py`: en
una caja, FEM ≈ analítico (planitud 8.04↔8.07, varianza 6.06↔5.78 dB).

Caveat: la calidad depende de cuántos modos resolvió el FEM (el panel usa
`n_modes`); para una banda hasta ~200 Hz conviene resolver suficientes modos. El
decay se saltea sobre FEM (no entra en el veredicto planitud+varianza).

### d) Aproximación rápida: perturbación de la forma del dominio

Si se quiere conservar la caja analítica y sólo corregir por el chaflán/esquina,
la herramienta es la **perturbación de cavidad** (teorema de Slater; Morse & Ingard
§9.4, Pierce §9): al quitar un volumen δV cada modo se corre

$$\frac{\Delta\omega_n}{\omega_n}=\frac{1}{2}\,\frac{\int_{\delta V}(k_n^{-2}|\nabla p_n|^2-|p_n|^2)\,dV}{\int_V |p_n|^2\,dV}$$

(quitar volumen donde el modo tiene máximo de presión sube fₙ; donde tiene máximo
de velocidad la baja). Da Δfₙ (y Δξₙ con el mismo esquema) sin re-resolver, y es el
MISMO tipo de perturbación que el amortiguamiento por β de pared que ya usa el soft
(`perturbation`, Morse & Ingard 9.4.14). Válido si la esquina es chica vs recinto y
vs λ. Candidato a mini-paper (perturbación geométrica ↔ paper G de perturbación de
frontera). NO implementado.

### c) Exacto formal: operador Dirichlet-a-Neumann en el plano de corte

Reemplazar la cuña por su operador DtN / Steklov-Poincaré sobre el plano de corte
preserva el campo exacto, pero el operador es **no local y dependiente de f** (no un
α ni una impedancia local; una impedancia local sólo lo aproxima en banda angosta).
Refs: Keller & Givoli (1989), *Exact non-reflecting boundary conditions*, J. Comput.
Phys. 82:172; Givoli, *Numerical Methods for Problems in Infinite Domains* (1992);
Steklov-Poincaré en Quarteroni & Valli (1999). Correcto pero overkill bajo Schroeder;
no se implementa.

**Decisión:** ruta **e** como primaria (ya hecha para evaluar/optimizar); ruta **d**
como aproximación rápida futura si se quiere el corrimiento modal analítico; ruta
**c** documentada pero descartada por costo.
