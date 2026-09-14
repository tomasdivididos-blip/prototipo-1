# Plan — remallar superficies curvas de un CAD para gmsh (Opción 2)

> Estado: PLAN (sin implementar). Escrito 2026-09-13. Pedido del usuario: que un CAD
> importado con superficies curvas (techo en arco, bóveda) se malle **boundary-fitted
> con gmsh** en vez de caer a voxel escalonado. NO codear sin OK.

## 0. Objetivo y alineación (§0 del proyecto)

Norte: la simulación más EXACTA posible bajo Schroeder. Una frontera **conforme**
(gmsh, tets que siguen la superficie real) tiene error geométrico ~0 y error de
discretización $O(h^2)$; el voxel escalona las superficies NO alineadas a los ejes
(arco, columna oval) con error $O(h)$ en la frontera y puede **desdoblar
degeneraciones rotacionales** (lo avisa el router). Para recintos con superficies
curvas importadas, boundary-fitted es estrictamente más exacto. Hoy esos CAD caen a
voxel (correcto pero escalonado). Este plan busca cerrar esa brecha SIN resignar la
esencia (geometría/IO permitida como trimesh/gmsh; física en numpy/scipy).

## 1. Diagnóstico preciso (qué falla y qué YA se descartó)

Caso testigo: `aula con prediccion.room` = caja 6×8×3 con **techo en arco** en la
pared +x (springline z=1.0, cumbrera z=2.6) + **columna** oval. La columna ya se
resuelve por resta booleana (manifold3d) → túnel → gmsh. **El bloqueo es el arco.**

`mesh_gmsh.mesh_with_gmsh` hace: STL → `classifySurfaces(angle, boundary=True,
forReparametrization=True)` → `createGeometry()` → surfaceLoop → addVolume →
`generate(3)`. Sobre el arco:
- Con las caras degeneradas presentes → gmsh `generate(3)` lanza **"Singular matrix
  3x3"** (no parametriza el parche degenerado).
- Sin ellas (borradas) → la malla queda **no estanca** (las degeneradas eran
  triángulos-puente colineales en la transición del arco) → **"Invalid boundary mesh
  (overlapping facets)"**.

**Probado y descartado (2026-09-13, headless):**
- Quitar caras degeneradas (`nondegenerate_faces`): abre huecos → no estanca → falla.
- **Round-trip por manifold3d** (`trimesh.boolean.union([room])`): deja la malla
  watertight con **0 caras degeneradas**, y gmsh **IGUAL falla** "overlapping facets".
  ⇒ el problema NO son (solo) las degeneradas: es la **reparametrización de la
  superficie curva** (dos parches del arco se solapan al aplanarlos al plano
  paramétrico).
- `forReparametrization` True/False, con/sin `createGeometry`: las tres fallan.
- `classifySurfaces` con ángulos 40/60/80: sin efecto (el error es en `generate(3)`,
  fuera del loop de reintento). `angle=1` (una superficie por triángulo) cuelga.

Conclusión: hay que **remallar/re-triangular la superficie curva** para que
`classifySurfaces` arme parches parametrizables que no se solapen, o **evitar la
reparametrización** meshando el interior con la superficie discreta fija.

## 2. Candidatos (con trade-offs)

### C. gmsh discreto sin reparametrización (mesh del interior con la superficie fija)
Mallar el VOLUMEN dejando la superficie del STL como frontera fija (sin remeshear la
cara), vía topología discreta: `gmsh.merge` → `createTopology()` / clasificar como
discreto → volumen discreto → `generate(3)` con la 2D fija.
- **Pro:** no remalla (conserva la triangulación del CAD), sin dep nueva, boundary-
  fitted a la malla dada.
- **Contra:** la calidad de la frontera = la del CAD (puede tener triángulos finos);
  hay que dar con la secuencia de API correcta (los intentos previos con
  `createGeometry` fallaron; falta probar la ruta `createTopology` + volumen discreto).
- **Riesgo:** medio (API gmsh delicada); es el más barato de probar primero.

### A. Reparametrización afinada (remesh de gmsh)
Usar la reparametrización de gmsh PERO afinándola: `Mesh.MeshSizeFromCurvature`,
`Geometry.Tolerance`, `Mesh.AngleToleranceFacetOverlap`, `Geometry.OCCFixSmallEdges`,
curveAngle, y forzar más subdivisión de la cara curva antes de clasificar.
- **Pro:** sin dep nueva; si anda, gmsh remalla el arco con densidad por curvatura.
- **Contra:** mucho ensayo-error de parámetros; puede seguir dando "overlapping
  facets" si la triangulación base es mala.
- **Riesgo:** medio-alto (frágil, específico de gmsh).

### B. Remallado isotrópico previo (pymeshlab)
Remallar la superficie con `pymeshlab` (isotropic explicit remeshing, MeshLab) →
triangulación uniforme y bien formada → gmsh clasifica y malla sin solapes.
- **Pro:** el más robusto y general para cualquier CAD curvo; pipeline estándar
  "STL → remesh → gmsh".
- **Contra:** **dependencia nueva** (pymeshlab, ~pesada; wheels pip). Categoría
  geometría/IO (permitida como trimesh/gmsh) pero más grande que manifold3d; impacta
  el build de distribución (PyInstaller).
- **Riesgo:** bajo en robustez, alto en "peso" de dependencia. Requiere OK del usuario.

### D. Subdivisión + suavizado propio (numpy)
Subdividir la cara curva (midpoint) y opcional Laplacian smoothing para darle a
`classifySurfaces` más triángulos y parches más planos. numpy puro.
- **Pro:** sin dep, D0-puro.
- **Contra:** subdividir NO arregla el solape de parametrización (más triángulos del
  mismo parche curvo siguen solapando al aplanar); probablemente insuficiente solo.
  Útil como complemento de C/A, no como solución.
- **Riesgo:** alto de que no alcance.

## 3. Recomendación y orden de experimentación (spike con gate)

Es exploratorio (los caminos fáciles ya fallaron), así que va como **spike con
criterio de corte**, no como implementación a ciegas:

1. **Probar C primero** (gmsh discreto, `createTopology`): barato, sin dep. Oráculo:
   que malle el arco y dé modos ~= al arco paramétrico de la app (ver §5).
2. Si C falla → **A** (reparam afinada, 1-2 h de tuning con `MeshSizeFromCurvature` +
   tolerancias). Gate: si en ~2 h no anda robusto, cortar.
3. Si A falla → **B** (pymeshlab), pero **pidiendo OK explícito** por la dependencia y
   el impacto en el build. Es el más seguro de que funcione.
4. Si nada cierra con costo razonable → dejar **voxel** para curvos (documentado) y
   priorizar las **columnas paramétricas** (Opción 3), que dan el aula boundary-fitted
   por otra vía (arco paramétrico + columna paramétrica). Ver `plan_columnas.md`.

## 4. Dónde tocar (cuando se implemente)

- `mesh_gmsh.py`: nueva función `mesh_with_gmsh_discrete(...)` (candidato C) y/o
  parámetros de reparametrización (candidato A); o `_remesh_surface(...)` (B/pymeshlab).
- `mesh_router.build_mesh`: cadena de intento para CAD curvo →
  `reparam (actual) → discreto C → [remesh B] → voxel`. Mantener el fallback a voxel
  SIEMPRE (nunca dejar al usuario sin resultado).
- Detección de "CAD con superficie curva": heurística por dispersión de normales
  (muchas normales no alineadas a ejes ni agrupadas en pocos planos) para elegir la
  rama sin forzar a los shoebox axis-aligned (que ya andan).

## 5. Validación (oráculo, no creer)

- **Oráculo paramétrico:** construir el MISMO recinto (caja + arco) con la geometría
  PARAMÉTRICA de la app (roof_type="arch"), que gmsh ya malla limpio, y comparar sus
  modos con los del CAD arco remallado. Deben coincidir dentro de ~1% (mismo recinto).
- **Regresión:** caja+columna prismática debe seguir gmsh boundary-fitted (f1=21.4);
  shoebox axis-aligned y paramétricos intactos; el aula sigue dando un resultado
  válido (gmsh si se logra, voxel si no).
- **Calidad de malla:** reportar tets degenerados (q<0.1) del resultado gmsh; si son
  muchos, el remesh no sirvió.
- **Convergencia:** al refinar h, los modos deben converger (boundary-fitted $O(h^2)$).

## 6. Fallback (invariante)

Pase lo que pase, si el remesh/gmsh no cierra para un CAD, se cae a **voxel** con
aviso en el badge (como hoy). El usuario nunca queda sin cálculo.

## 7. Criterios de aceptación

- El aula (`aula con prediccion.room`) malla con gmsh boundary-fitted (o se decide
  formalmente que queda en voxel, documentado).
- Modos del arco remallado ~= oráculo paramétrico (≤1%).
- Sin regresión en caja+columna ni en paramétricos.
- Si entra pymeshlab: en `requirements.txt` + `.spec`, con OK del usuario.
