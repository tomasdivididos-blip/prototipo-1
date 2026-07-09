# `acoustic_mesh.py` — explicación hasta el hueso

> Construye una **malla tetraédrica del interior** del recinto a partir de la
> malla de **superficie** (la que da `geometry.make_room`). Es el paso previo
> al solver FEM: sin esta malla volumétrica, `acoustic_fem` no tiene dónde
> ensamblar K y M.

---

## 0. Idea general (sin código)

Necesitamos *tetraedros* dentro del recinto. La forma "industrial" sería
llamar a TetGen o CGAL. Acá usamos algo más simple y sin dependencias:

1. **Bounding box** (AABB): la caja más chica alineada a los ejes que contiene
   al recinto. Es solo `min` y `max` de las coordenadas de la superficie.
2. **Rejilla de hexaedros** (cubitos) dentro de esa caja, con `n_per_meter`
   celdas por metro.
3. **Cada cubo → 6 tetraedros** (descomposición de Freudenthal). Esto es lo
   más fino que se puede hacer sin mover vértices ni introducir nodos nuevos,
   y los tets quedan *conformes* entre cubos vecinos (comparten caras
   completas, no hay "huecos").
4. **Filtro punto-en-poliedro**: descartamos los tets cuyo *centroide* cae
   **fuera** del recinto. El test usa raycasting de Möller-Trumbore: tira
   un rayo desde el centroide y cuenta cuántas veces cruza la superficie.
   Impar = adentro, par = afuera (es la regla de Jordan).
5. **Remapeo**: limpiamos los nodos que ya no usa ningún tet.

Lo que queda es una malla "voxelizada" con frontera escalonada en zonas no
axis-aligned. Es aproximado, pero con paredes rígidas (Neumann homogénea
*natural*) el solver tolera bien el sesgo si la malla es lo bastante fina.

---

## 1. Imports y el truco Freudenthal (líneas 1-47)

```python
import numpy as np

HEX_TO_TETS = np.array([
    [0, 1, 3, 7],
    [0, 1, 7, 5],
    [0, 5, 7, 4],
    [0, 3, 2, 7],
    [0, 2, 6, 7],
    [0, 6, 4, 7],
], dtype=int)
```

`HEX_TO_TETS` es una **tabla fija** que dice cómo partir un cubo de 8 esquinas
en **6 tetraedros**. Los 8 índices son las esquinas del cubo, numeradas según
el orden:

```
       6 ───── 7        eje k arriba (+z)
      ╱│      ╱│
     4 ───── 5 │        eje j atrás  (+y)
     │ 2 ────│ 3        eje i derecha(+x)
     │╱      │╱
     0 ───── 1
```

Las 6 filas de la tabla son los tets, todos comparten el vértice `7`. Lo
importante: **es la única descomposición que mantiene la malla
conforme entre cubos vecinos** sin agregar nodos. Es exactamente la misma
tabla que usaba el viejo `fem_modal.py` cuando solo soportaba cajas
rectangulares (por eso el comentario dice "mismo split").

---

## 2. `points_inside_surface` — raycast Möller-Trumbore vectorizado

Esta función responde: *¿este punto está adentro del recinto?* Lo hace por
intersección rayo–triángulo, sobre los triángulos de la superficie.

### 2.1 Algoritmo en una línea

> *Tirá un rayo desde el punto en una dirección arbitraria, contá cuántos
> triángulos cruza. Si es impar, el punto está adentro.*

Esto se llama **Jordan ray test**. Funciona en cualquier malla cerrada.

### 2.2 Por qué Möller-Trumbore y no algo más naive

Hay muchas formas de chequear si un rayo cruza un triángulo. Möller-Trumbore
es la **estándar** en gráficos: usa coordenadas barycentric (igual que el
solver FEM más abajo) y no requiere precomputar normales ni planos.

Para un triángulo `(v₀, v₁, v₂)`, define los lados `e₁ = v₁ - v₀`,
`e₂ = v₂ - v₀`. El rayo es `r(t) = p + t·d` con `p` el origen (el punto) y
`d` la dirección. Imponer que `r(t)` esté en el plano del triángulo y dentro
de él lleva a un sistema 3×3 con solución cerrada en términos de productos
cruzados.

### 2.3 Vectorización (lo importante para el código)

La versión naive haría dos loops Python: por cada punto, por cada triángulo.
Para `Np ~ 14 000` puntos y `Nt ~ 500` triángulos, son 7 millones de
iteraciones — devastador.

Acá se procesa **todo el lote** con una sola expresión NumPy broadcasted, en
chunks de memoria.

### 2.4 Línea por línea

```python
pts = np.atleast_2d(np.asarray(points, dtype=float))   # (Np, 3)
Np = pts.shape[0]
```
`atleast_2d` te garantiza forma `(N, 3)` aunque pases un solo punto.

```python
v0 = surface_verts[surface_tris[:, 0]]     # (Nt, 3)
v1 = surface_verts[surface_tris[:, 1]]     # (Nt, 3)
v2 = surface_verts[surface_tris[:, 2]]     # (Nt, 3)
```
**Fancy indexing**: `surface_tris[:, 0]` es un array de índices de vértice
(uno por triángulo); cuando lo usás como índice de `surface_verts`, NumPy te
devuelve las coordenadas correspondientes. Resultado: tres arrays `(Nt, 3)`
con los tres vértices de cada triángulo.

```python
dirn = np.array([1e-4, 2e-4, 1.0])
dirn = dirn / np.linalg.norm(dirn)
```
Dirección del rayo: **casi vertical, con una inclinación minúscula en x e y**.
La inclinación es para no rozar exactamente las aristas axis-aligned del
recinto (sería un caso degenerado que rompe la cuenta de paridad).

```python
e1 = v1 - v0          # (Nt, 3)
e2 = v2 - v0          # (Nt, 3)
h = np.cross(dirn, e2)   # (Nt, 3)   — produce de cruzar dirn contra cada e2
a = np.einsum("tj,tj->t", e1, h)     # (Nt,)
```
Estos son los pasos 1-2 de Möller-Trumbore aplicados **simultáneamente** a
los `Nt` triángulos. `a[t]` es el determinante del sistema 3×3 del
triángulo `t`. Si `|a|` es chico, el rayo es paralelo al triángulo
(`mask_a = |a| > eps` filtra estos casos).

> Sobre `einsum("tj,tj->t", e1, h)`: leelo como "multiplicá componente a
> componente y sumá sobre `j` (los 3 componentes xyz), conservá `t`". Es
> el producto punto fila a fila — equivale a `(e1 * h).sum(axis=1)`, pero
> más explícito.

```python
f = np.zeros(Nt, dtype=float)
f[mask_a] = 1.0 / a[mask_a]
```
`f[t] = 1/a[t]` para los triángulos no paralelos. Lo dejamos en 0 donde
`a ≈ 0` para evitar dividir por cero; las máscaras posteriores los descartan.

```python
chunk_size = max(1, _CHUNK_PAIRS // max(Nt, 1))
counts = np.zeros(Np, dtype=np.int64)
mask_a_b = mask_a[None, :]      # (1, Nt), listo para broadcasting
```
**Chunking**: si hicieras todo en un solo lote, los arrays intermedios serían
`(Np × Nt × 3)` floats. Para `Np = 14 000`, `Nt = 500` son ~250 MB. Se procesa
de a `chunk_size` puntos por vez para mantener el pico de memoria acotado en
`_CHUNK_PAIRS = 10⁷` pares punto-triángulo.

`counts` lleva, para cada punto, **cuántos triángulos cruza** su rayo.

```python
for start in range(0, Np, chunk_size):
    end = min(start + chunk_size, Np)
    pts_chunk = pts[start:end]    # (n, 3)
```
Loop sobre chunks de puntos. `n = end - start` puntos en el chunk actual.

```python
s = pts_chunk[:, None, :] - v0[None, :, :]    # (n, Nt, 3)
```
**Truco clave de broadcasting**: `pts_chunk[:, None, :]` tiene forma
`(n, 1, 3)`; `v0[None, :, :]` tiene forma `(1, Nt, 3)`. NumPy las difunde
contra `(n, Nt, 3)`. Resultado: `s[p, t]` es el vector `pts_chunk[p] - v0[t]`.
**En una sola línea calculaste `n × Nt` restas vectoriales.**

```python
u = f[None, :] * np.einsum("ptj,tj->pt", s, h)   # (n, Nt)
```
`u[p, t]` es la primera coordenada barycentric del rayo en el triángulo
`t` cuando se origina en `pts_chunk[p]`. El `einsum` hace producto punto
sobre `j` (componentes xyz), conservando los ejes `p` y `t`. Multiplicar por
`f[None, :]` reparte el factor `1/a` por triángulo.

```python
q = np.cross(s, e1[None, :, :])      # (n, Nt, 3)
v_bc = f[None, :] * np.einsum("j,ptj->pt", dirn, q)
t_bc = f[None, :] * np.einsum("tj,ptj->pt", e2, q)
```
Lo mismo para la segunda coordenada `v_bc` y para el parámetro `t_bc`
del rayo (`r(t) = p + t·d`).

```python
mask_u = (u >= 0.0) & (u <= 1.0) & mask_a_b
mask_v = (v_bc >= 0.0) & (u + v_bc <= 1.0) & mask_u
hit = mask_v & (t_bc > eps)          # (n, Nt) bool
```
Las tres máscaras son la condición de **estar dentro del triángulo** en
coords barycentric (`u, v ≥ 0`, `u + v ≤ 1`) **y por delante del origen del
rayo** (`t_bc > 0`). Cada `hit[p, t]` es `True` si el rayo del punto `p`
atraviesa el triángulo `t`.

```python
counts[start:end] = hit.sum(axis=1)
```
Suma a lo largo de los triángulos: cantidad de cruces por punto.

```python
return (counts % 2) == 1
```
**Regla de Jordan**: paridad. Impar → adentro. Devuelve un bool por punto.

---

## 3. `build_volume_mesh` — el corazón del módulo

Construye la malla tet del interior. Devuelve `(nodes, tets)`.

### 3.1 AABB

```python
xmin, ymin, zmin = surface_verts.min(axis=0)
xmax, ymax, zmax = surface_verts.max(axis=0)
Lx, Ly, Lz = xmax-xmin, ymax-ymin, zmax-zmin
```
`min(axis=0)` colapsa las `Nv` filas dejando el mínimo por columna (x, y, z).
La AABB es solo `(min, max)` por coordenada.

### 3.2 Densidad de la rejilla

```python
nx = max(2, int(round(Lx * n_per_meter)))
ny = max(2, int(round(Ly * n_per_meter)))
nz = max(2, int(round(Lz * n_per_meter)))
```
`n_per_meter` = celdas por metro. Para una caja 5×4×3 con `n_per_meter=2`,
quedan `10×8×6 = 480` cubos → ~2880 tets candidatos.

```python
total = (nx + 1) * (ny + 1) * (nz + 1)
while total > max_nodes and n_per_meter > 0.5:
    n_per_meter *= 0.8
    ...
```
**Cap de seguridad**: si la rejilla supera `max_nodes`, se ajusta para abajo.
Evita reventar memoria con un recinto muy grande o un `n_per_meter` muy alto.

### 3.3 Generación de la rejilla de nodos

```python
xs = np.linspace(xmin, xmax, nx + 1)
ys = np.linspace(ymin, ymax, ny + 1)
zs = np.linspace(zmin, zmax, nz + 1)
X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
grid_nodes = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
```
`meshgrid` con `indexing="ij"` arma 3 arrays `(nx+1, ny+1, nz+1)` con la
coordenada x/y/z respectiva en cada nodo. Al hacer `ravel()` cada uno y
`stack([...], axis=1)` obtenés `grid_nodes` de forma `((nx+1)(ny+1)(nz+1), 3)`:
todos los nodos del grid, uno por fila, con sus coordenadas.

```python
def gid(i, j, k):
    return (i * (ny + 1) + j) * (nz + 1) + k
```
**Mapeo (i,j,k) → índice lineal** consistente con el orden `C` de NumPy
después de `ravel()`. Si visualizás el grid como un libro:
- `i` cambia más lento (página),
- `j` intermedio (línea),
- `k` más rápido (carácter).
Esta función te dice "el índice lineal del nodo en la posición
(i, j, k) del grid".

### 3.4 Tetraedros candidatos (vectorizado)

```python
ii, jj, kk = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz),
                          indexing="ij")
ii = ii.ravel(); jj = jj.ravel(); kk = kk.ravel()
```
Listamos **todos los cubos** de la rejilla: hay `nx * ny * nz` cubos, cada
uno identificado por su esquina inferior `(i, j, k)`. `ii, jj, kk` quedan
como vectores 1D del mismo largo `n_hex = nx*ny*nz`.

```python
hex_corners = np.stack([
    gid(ii,     jj,     kk),
    gid(ii + 1, jj,     kk),
    gid(ii,     jj + 1, kk),
    gid(ii + 1, jj + 1, kk),
    gid(ii,     jj,     kk + 1),
    gid(ii + 1, jj,     kk + 1),
    gid(ii,     jj + 1, kk + 1),
    gid(ii + 1, jj + 1, kk + 1),
], axis=1)    # (n_hex, 8)
```
Para cada cubo, calculamos los 8 índices lineales de sus esquinas, en el
**mismo orden** que asume `HEX_TO_TETS`. `gid` con arrays NumPy se aplica
componente a componente, así que ya estás haciéndolo para todos los cubos
de una pasada.

```python
cand_tets = hex_corners[:, HEX_TO_TETS].reshape(-1, 4)
```
**Indexing avanzado con un array de índices 2D**. `hex_corners` es
`(n_hex, 8)`. Indexar con `[:, HEX_TO_TETS]` donde `HEX_TO_TETS` es `(6, 4)`
da un resultado `(n_hex, 6, 4)`: para cada cubo, sus 6 tets, cada uno con sus
4 índices de vértice globales. Después `reshape(-1, 4)` lo aplana a
`(6·n_hex, 4)` — la lista de **todos los tets candidatos** del bounding box.

### 3.5 Filtro por centroide

```python
centroids = grid_nodes[cand_tets].mean(axis=1)
keep = points_inside_surface(centroids, surface_verts, surface_tris)
kept_tets = cand_tets[keep]
```
`grid_nodes[cand_tets]` es `(Ne, 4, 3)` (las coordenadas de los 4 vértices de
cada tet). `mean(axis=1)` promedia los 4 vértices → centroide de cada tet,
`(Ne, 3)`. Pasamos esos centroides al raycast: `keep` es un bool por tet.
`cand_tets[keep]` deja solo los tets cuyo centroide está adentro.

> Por qué filtrar por centroide y no por todos los vértices: con la malla
> escalonada, hay tets que tienen vértices justo en la frontera. El centroide
> es el criterio menos ambiguo: si el "centro de masa" del tet está adentro,
> el tet pertenece al volumen útil.

### 3.6 Remapeo de nodos

```python
used_idx = np.unique(kept_tets)
new_idx = -np.ones(grid_nodes.shape[0], dtype=int)
new_idx[used_idx] = np.arange(len(used_idx))
nodes = grid_nodes[used_idx]
tets = new_idx[kept_tets]
```
Después de filtrar quedan nodos que ya no usa ningún tet. Los descartamos:
1. `used_idx` = índices únicos de nodos que aparecen en algún tet (ordenado).
2. `new_idx` = tabla de traducción del índice viejo al nuevo (−1 si no se
   usa). Por ejemplo si `used_idx = [3, 7, 8, 12]`, entonces
   `new_idx[3]=0, new_idx[7]=1, new_idx[8]=2, new_idx[12]=3`.
3. `nodes` = coordenadas de los nodos que sobreviven.
4. `tets` = índices remapeados: `new_idx[kept_tets]` reemplaza cada índice
   viejo por su nuevo. Esto es **fancy indexing** otra vez: NumPy hace el
   lookup elemento a elemento.

Resultado: una malla compacta sin huecos en la numeración, lista para
`build_KM`.

---

## 4. `subdivide_surface` — refinar la superficie (opcional)

Cada triángulo se parte en 4 introduciendo los puntos medios de las 3 aristas.

```python
edge_mid = {}        # diccionario (i, j) ordenado -> índice del punto medio
```
La clave **ordenada** `(min, max)` garantiza que el punto medio de la
arista `(3, 7)` y el de `(7, 3)` sean el mismo — sin esto, dos triángulos
vecinos crearían dos copias del mismo punto y perderías conformidad.

```python
for tri in t:
    a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
    for i, j in ((a, b), (b, c), (c, a)):
        key = (min(i, j), max(i, j))
        if key not in edge_mid:
            edge_mid[key] = len(v)
            v.append([(v[i][k] + v[j][k]) * 0.5 for k in range(3)])
    ab = edge_mid[(min(a, b), max(a, b))]
    bc = edge_mid[(min(b, c), max(b, c))]
    ca = edge_mid[(min(c, a), max(c, a))]
    new_t += [[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]]
```
Cada triángulo `(a, b, c)` se reemplaza por:
- `(a, ab, ca)` — esquina en `a`,
- `(ab, b, bc)` — esquina en `b`,
- `(ca, bc, c)` — esquina en `c`,
- `(ab, bc, ca)` — central, invertido.

Cada nivel multiplica los triángulos por 4. **Esto no afecta la malla tet
volumétrica** — solo refina la superficie, útil para visualización o para
mejorar el filtro de centroide en zonas curvas.

---

## 5. `mesh_info` — estadísticos

```python
p0 = nodes[tets[:, 0]]
p1 = nodes[tets[:, 1]]
p2 = nodes[tets[:, 2]]
p3 = nodes[tets[:, 3]]
vols = np.abs(np.einsum("ij,ij->i",
                        np.cross(p1 - p0, p2 - p0),
                        p3 - p0)) / 6.0
V = float(vols.sum())
```
**Fórmula clásica del volumen de un tet**: `V_e = |((p1-p0) × (p2-p0)) · (p3-p0)| / 6`.
- `np.cross(p1-p0, p2-p0)` → `(Ne, 3)`, la normal al "triángulo base" escalada
  por dos veces su área.
- `einsum("ij,ij->i", ..., p3-p0)` → producto punto fila a fila →
  altura proyectada × área proyectada × 2.
- Dividido por 6 da el volumen del tet.

Vectorizado: todos los tets en una pasada.

```python
h_e = (6.0 * vols) ** (1.0 / 3.0)
```
**Tamaño característico** del elemento: si fuera un cubo de lado `h`, su
volumen sería `h³/6` (en realidad un tet regular tiene factor distinto,
pero como medida grosera para comparar resoluciones funciona). Útil para la
regla de "puntos por longitud de onda".

---

## 6. `max_solver_frequency` — regla del solver

```python
def max_solver_frequency(h_max, c=343.0, ppw=6.0):
    return c / (ppw * h_max)
```
**Regla práctica FEM**: la longitud de onda mínima resoluble cumple
`λ_min / h_max ≥ ppw`, con `ppw` (points-per-wavelength) típicamente 4 a 10.
Acá uso 6 como default. Equivalentemente: `f_max = c / (ppw · h_max)`.

Por debajo de `f_max` la malla representa fielmente la onda; por encima, el
solver introduce dispersión numérica grande y los modos quedan corridos.

---

## 7. Flujo típico desde fuera

Desde `acoustic_panel.py` o el orquestador, la secuencia es:

```python
1. v, t, _, _ = make_room(Lx, Ly, Lz, n_walls=4)
2. nodes, tets = build_volume_mesh(v, t, n_per_meter=2.0)
3. info = mesh_info(nodes, tets)
4. f_max = max_solver_frequency(info["h_max"], ppw=6)
5. K, M, _ = build_KM(nodes, tets)        # → acoustic_fem.py
6. freqs, phis = solve_modes(K, M, n_modes=N)
```

---

## 8. Patrones de NumPy que vale la pena fijar

| Patrón | Dónde aparece | Lectura |
|---|---|---|
| `arr[indices]` con `indices` de cualquier forma | `nodes[tets]`, `surface_verts[surface_tris[:,0]]` | "Trae los renglones cuyas índices son `indices`". Si `indices` es 2D, el resultado tiene un eje extra |
| Broadcasting con `None`/`np.newaxis` | `pts_chunk[:, None, :] - v0[None, :, :]` | Inserta un eje de tamaño 1 que NumPy "estira" para emparejar otra forma |
| `einsum("...", a, b)` | rigidez, raycast, barycentric | Suma de productos sobre los índices que no aparecen a la derecha de `->` |
| `np.cross` lote | normales, barycentric, volumen | Producto vectorial fila a fila si los dos arrays son `(N, 3)` |
| `np.unique` + remapeo con array auxiliar | `used_idx / new_idx` | Patrón estándar para "compactar" índices después de filtrar |
| `np.meshgrid(indexing="ij")` + `ravel` | construcción del grid | Recorre la rejilla en orden de loops anidados sin escribir el loop |
| `coo_matrix((data, (row, col)))` | `build_KM` (en `acoustic_fem`) | Construye sparse; entradas con la misma `(row, col)` se **suman** automáticamente |

---

## 9. Limitaciones conocidas y por qué se aceptan

1. **Frontera escalonada**. La malla no respeta la geometría exacta de las
   paredes. Para paredes axis-aligned esto no importa. Para paredes oblicuas
   sí hay error de frontera; se mitiga subiendo `n_per_meter`.
2. **Filtro por centroide**. Tets que tienen el centroide justo en el plano
   de la pared pueden quedar adentro o afuera dependiendo de redondeos. La
   inclinación del rayo (`[1e-4, 2e-4, 1.0]`) elimina ambigüedades de
   tangencia exacta a triángulos.
3. **No hay refinamiento adaptativo**. Densidad uniforme `n_per_meter`. Para
   este proyecto alcanza; para alta frecuencia local habría que adaptar.

Estas limitaciones son aceptables porque:
- Paredes rígidas se imponen *naturalmente* en la forma débil — no requieren
  que la frontera sea exacta.
- El error de los primeros modos (los que importan en baja frecuencia, que
  es donde vive el ojo de `gsd-ai-integration-phase` perdón, donde
  vive el problema acústico modal) es ~1-2 % con `n_per_meter=2`, según el
  benchmark del `__main__` de `acoustic_fem.py`.

---

## 10. Mapa mental

```
HEX_TO_TETS              tabla constante (split de Freudenthal 1 hex -> 6 tets)

points_inside_surface    raycast Möller-Trumbore vectorizado (todos los puntos vs
                         todos los triángulos en un lote, con chunking de memoria)

build_volume_mesh        AABB -> grid (nx, ny, nz) -> hexes -> tets
                         -> filtro por centroide -> remapeo de nodos

subdivide_surface        midpoint subdivision de la malla de superficie
                         (1 tri -> 4 tris). No toca tets

mesh_info                volumen total, tamaño característico h_avg y h_max

max_solver_frequency     f_max admisible dada la regla "ppw puntos por λ"
```

---

## 11. Para profundizar (referencias)

- **Möller-Trumbore**: paper original 1997, "Fast, Minimum Storage Ray-Triangle Intersection".
- **Descomposición de Freudenthal**: ver Bey, *Tetrahedral grid refinement*, 1995, para entender por qué la tabla de 6 tets es conforme y de uso libre.
- **Punto-en-poliedro por rayos**: cualquier texto de geometría computacional. La regla de Jordan es el ABC.
- **`points-per-wavelength` en FEM acústico**: Ihlenburg, *Finite Element Analysis of Acoustic Scattering*, cap. 4.

---

*Fuente: `acoustic_mesh.py`, líneas 1-316.*
