# Plan: columnas (cilíndricas y prismáticas)

> Estado: **PLANIFICADO, sin implementar** (8 Sep 2026). No escribir código hasta
> OK explícito del usuario sobre este plan. Decisión de arquitectura ya tomada:
> **Opción C** (rol dentro de `Furniture`, no objeto nuevo).

---

## 0. Objetivo

Permitir agregar **columnas** interiores al recinto (sección **circular** = cilíndrica,
o **rectangular** = prismática) como elementos que atraviesan la sala de **piso a techo**,
y que su efecto sobre los modos (`fₙ`, `φₙ`) y sobre la FRF se calcule de forma **exacta**
(no perturbativa), coherente con el norte del proyecto (§0 de `notas_para_claude.md`).

## 1. Hallazgo que reencuadra el esfuerzo (leer antes de estimar)

**El motor físico ya existe y está validado.** `furniture.py` (Fase A) modela un mueble
como un **agujero en el dominio de aire**: `carve_mesh(nodes, tets, muebles)` remueve los
tetraedros cuyo centroide cae dentro de la primitiva, entre `build_volume_mesh` y
`build_KM`. La superficie del agujero queda como **pared rígida gratis** (Neumann homogénea
= condición natural en la forma débil; misma decisión D3 que la frontera escalonada). El
solver no se toca: recibe un dominio más chico y los modos salen corridos **por sí solos,
exacto**. Con lista vacía, la malla es bit a bit idéntica (regresión garantizada).

Las primitivas `kind="box"` y `kind="cylinder"` **ya están** (`Furniture`, con `to_dict`/
`from_dict`, `contains`, `to_local`). O sea:

- **columna cilíndrica** = `cylinder` con altura = alto de sala.
- **columna prismática** = `box` con altura = alto de sala.

Por lo tanto este feature **no agrega física de motor**. Agrega **semántica + UX + un
oráculo de validación nuevo** (el caso pasante piso-techo, que los muebles no ejercen).

**No tocar** (ya validado, D0-D5): `build_KM`, `solve_modes`, `build_volume_mesh`,
`carve_mesh`, las constantes precomputadas. Todo el trabajo es aditivo por encima.

## 2. Qué distingue una columna de un mueble genérico

El motor de carve es el mismo; la columna es un mueble con estas particularidades:

1. **Pasa de piso a techo.** Su altura no es libre: **rastrea el alto de sala** (incluye
   techo inclinado → tope por el perfil de la cara superior sobre la huella). Topológicamente
   el agujero deja de ser un vacío cerrado y se vuelve un **túnel** que atraviesa el dominio
   (género 1). Esto es lo único nuevo a validar (ver §6).
2. **Rígido por default** (hormigón / revoque duro). Puede tratarse después reusando la
   Fase B de muebles (`furniture_materials`), pero el default es `null` = rígido.
3. **Semántica arquitectónica**, no mobiliario: etiqueta, presets y reporte propios
   (una columna de hormigón de 30 cm no es "un mueble").

## 3. Régimen de validez (para reportar, coherente con §0)

Una columna de radio `a` en banda modal dispersa en **régimen de Rayleigh** cuando `ka ≪ 1`
(Morse & Ingard §8.2, dispersión por cilindro rígido). Con `k = 2πf/c`:

- Columna de 30 cm (`a = 0.15 m`) a 60 Hz: `ka ≈ 0.16` → efecto sobre los modos graves
  chico pero **no nulo**; crece hacia Schroeder.
- El criterio de significancia ya implementado, `significance_threshold(f_valid) = c/(8·f_valid)`
  (`is_significant`), marca la dimensión mínima que resuelve la banda: a `f_S ≈ 159 Hz` da
  `λ_max/8 ≈ 0.27 m`. Se reusa tal cual: se **avisa** si la columna es más fina que eso o si
  la malla (npm, D4) no la resuelve.

Mensaje al usuario: la columna importa sobre todo en la parte **alta** de la banda modal;
el soft reporta ese régimen y no muestra un corrimiento que la malla no sostiene.

## 4. Cambios por capa (todos aditivos)

| Capa | Archivo · símbolo | Cambio |
|---|---|---|
| Datos | `furniture.py` `Furniture` | Campo nuevo `role: str = "furniture"` (`"furniture"` \| `"column"`). Default preserva compat |
| Datos | `furniture.py` `to_dict`/`from_dict` | Serializar `role`; `from_dict` sin la clave → `"furniture"` (compat `.room` v7-v9) |
| Altura | `furniture.py` (helper nuevo) | `sync_column_height(furn, surface)`: fija `size[2]` = alto de sala sobre la huella (tope por perfil de techo). Se llama al crear/mover/al redimensionar la sala |
| Persistencia | `main.py` `FILE_VERSION` | Bump a **v10** (columnas). Aditivo: v7-v9 cargan `role="furniture"`. Documentar en la cadena de versiones |
| UI | `acoustic_panel.py` (MuebleDialog + panel) | Combo/botón "Columna" que crea con `role="column"`, `kind` ∈ {cylinder, box}, altura auto (campo de altura deshabilitado y atado al alto de sala). Presets de columna |
| UI/viewer | reusa | Gizmos, colisión-stop de fuentes/receptor (`point_inside_furniture`), picking: **heredados**, sin cambios |
| Reporte | `acoustic_panel.py` / auditoría | Listar columnas aparte de muebles; contar y reportar su régimen de significancia |

## 5. Fases

**Fase 1 — núcleo mínimo usable (rol + auto-altura + UI).**
- `role` en `Furniture` + serialización + bump `.room` v10.
- `sync_column_height` (auto-altura piso-techo, techo plano primero).
- Botón "Columna" en la UI: cilindro/prisma, altura atada al alto de sala.
- Regresión: `.room` sin columnas y `carve_mesh([])` siguen bit a bit idénticos.

**Fase 2 — presets + reporte + techo inclinado.**
- Presets de columna (hormigón 20/30/40 cm circular; prisma 30×30, 40×40).
- Reporte/auditoría distingue columnas; reusa `is_significant`.
- `sync_column_height` con tope por perfil de techo inclinado (usar la superficie real).

**Fase 3 — validación del pasante piso-techo (el oráculo nuevo).**
- `bench_columnas.py` con los oráculos de §6. Es el gate físico del feature.

**Fase 4 (opcional, diferida) — columna tratada.**
- Absorción sobre la columna reusando `furniture_materials` (Fase B). Solo si el usuario
  lo pide; el default rígido es lo correcto para hormigón.

## 6. Métricas de éxito y oráculos (Fase 3)

El caso nuevo es el **túnel piso-techo** (los benches de muebles prueban vacíos flotantes/
apoyados, no pasantes). Cuatro oráculos falsables:

1. **Reducción radio → 0.** Columna de radio decreciente en un shoebox 5×4×3 conocido:
   `fₙ(columna) → fₙ(sala vacía)` (error → 0 monótono). Falla si no converge al analítico.
2. **Convergencia en npm.** Para una columna fija, `Δfₙ` debe estabilizarse al subir npm
   (criterio de Cauchy: `|Δfₙ(npm) − Δfₙ(2·npm)|` decrece). La columna fina es el caso más
   exigente de resolución. Reporta el npm mínimo que estabiliza.
3. **Simetría.** Columna centrada en un shoebox: los modos deben respetar la simetría del
   recinto (rompe las degeneraciones que la geometría rompe, preserva las que preserva).
4. **Teoría de perturbación de cavidad (columna delgada, `ka ≪ 1`).** El corrimiento exacto
   del carve debe coincidir con la predicción perturbativa
   $$\frac{\Delta\omega_n}{\omega_n} \approx \frac{\int_{\Delta V}\big(\kappa\,|p_n|^2 - \rho\,|\mathbf{u}_n|^2\big)\,dV}{\int_V \big(\kappa\,|p_n|^2 + \rho\,|\mathbf{u}_n|^2\big)\,dV}$$
   (perturbación por inserción de un obstáculo rígido pequeño; Morse & Ingard §9.2, cavidad
   perturbada). Es la misma maquinaria de perturbación ya validada `<1%` en el proyecto
   (`[[damping-perturbation]]`), aplicada al **volumen** en vez de a la frontera. Tolerancia
   objetivo: acuerdo dentro de pocos por ciento en el régimen `ka ≪ 1`, degradándose de forma
   controlada al crecer `ka`.

**Regresión (todas las fases):** con cero columnas, malla, `K`, `M` y `fₙ` bit a bit
idénticos al estado previo.

## 7. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Malla no resuelve columna fina (huella < paso de rejilla → carve nulo o dentado) | Reusar `is_significant` + aviso; sugerir npm; documentar el mínimo resoluble |
| Túnel piso-techo genera slivers en el borde del carve (paredes curvas del cilindro sobre rejilla) | El filtro de slivers de `build_volume_mesh` ya actúa; el oráculo 2 (convergencia) lo detecta si contamina |
| Columna partiendo el dominio en dos regiones no conexas (columna que toca una pared) | Definir columna como interior (no coincidente con pared); avisar si la huella toca el borde |
| Fuente/receptor dentro de la columna | Heredado: `point_inside_furniture` ya frena y reubica (mismo criterio que muebles) |
| Auto-altura vs techo inclinado | Fase 2: tope por perfil real de la cara superior sobre la huella |

## 8. Decisiones abiertas (menores, resolver al implementar)

- ¿La columna prismática admite yaw (rotación en planta)? El `box` ya lo soporta (`orientation`);
  default 0, exponerlo es gratis.
- ¿Bump a `.room` v10 o campo aditivo sin bump? Propuesta: **v10** por claridad de changelog,
  con carga compat de v7-v9.
- Presets exactos de diámetro/sección (a confirmar con el usuario / catálogo).

## 9. Referencias

- Decisión D3 (Neumann natural, frontera rígida gratis): `notas_para_claude.md` §5 D3 y
  docstring de `furniture.py`.
- Dispersión por cilindro rígido, régimen de Rayleigh: Morse & Ingard, *Theoretical
  Acoustics*, §8.2.
- Perturbación de cavidad por obstáculo: Morse & Ingard §9.2; conexión con la maquinaria
  ya validada del proyecto en `[[damping-perturbation]]`.
- Motor de carve y significancia: `furniture.py` (`carve_mesh`, `significance_threshold`,
  `is_significant`); mallador `acoustic_mesh.py` (`build_volume_mesh`, `points_inside_surface`).
