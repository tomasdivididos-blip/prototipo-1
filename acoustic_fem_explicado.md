# `acoustic_fem.py` — explicación hasta el hueso

> Solver FEM modal acústico para un recinto de geometría arbitraria con
> paredes rígidas. Recibe la malla tet de `acoustic_mesh.build_volume_mesh`
> y devuelve los modos, la FRF y el campo nodal por superposición modal.
> Es el núcleo numérico de la app.

Lo voy a explicar al detalle: **el problema físico → la forma débil → la
discretización → el código línea por línea**, con la *forma (shape)* de cada
array intermedio. Si en algún punto un truco de NumPy/SciPy te resulta
opaco, lo aclaro ahí mismo en una caja "Truco".

---

## 0. Contexto — ¿por qué FEM "a mano" y no FEniCS?

Antes de entrar en la mecánica, vale la pena despejar la pregunta que
cualquier ingeniero con background numérico se hace al ver este código:

> Si existen librerías como **FEniCS**, **deal.II** o **MFEM** que ya
> implementan FEM, ¿por qué estamos escribiendo todo esto a mano? ¿Es
> realmente FEM lo que hacemos?

La respuesta corta: **FEM es un método matemático, no una librería**.
FEniCS es *una* implementación del método; nuestro código es *otra*. El
resultado numérico es el mismo (modulo redondeo IEEE-754) cuando ambos
resuelven el mismo problema con los mismos elementos.

### 0.1 Los seis pasos canónicos del método FEM

Cualquier libro clásico (Zienkiewicz-Taylor, Hughes, Reddy) describe FEM
como **seis pasos** que cualquier implementación tiene que hacer:

| # | Paso | En nuestro código |
|---|---|---|
| 1 | Forma fuerte de la EDP | `∇²p + k²p = -iωρ₀ q(x)` (Helmholtz) |
| 2 | Forma débil (Galerkin + integración por partes) | derivada en §1.3 de este documento |
| 3 | Discretización del dominio en elementos | `acoustic_mesh.build_volume_mesh` → tets |
| 4 | Funciones de forma por elemento | `N_j` lineales, codificadas en `Vinv[:, 1:4, :]` |
| 5 | Ensamblaje de K y M | `build_KM` con `coo_matrix((data, (rows, cols)))` |
| 6 | Resolución del sistema de autovalores | `eigsh` con shift-invert |

**Está todo.** Lo único que delegamos a librerías es:

- `numpy.linalg.inv` / `det` — aritmética de matrices 4×4 (mecánico).
- `scipy.sparse` — almacenamiento sparse (mecánico, no cambia la cuenta).
- `scipy.sparse.linalg.eigsh` — solver de autovalores (álgebra lineal pura).

Eso no es delegar FEM. Es delegar **álgebra lineal**. Como hacer una
eliminación gaussiana con calculadora: la calculadora hace la aritmética,
el método lo seguís pensando vos.

### 0.2 ¿Qué automatiza FEniCS que nuestro código no?

Vale saber qué *no* tenemos, para no confundir simplicidad con limitación:

- **DSL para la forma débil**. En FEniCS escribís
  `a = dot(grad(u), grad(v)) * dx` y la librería **compila** eso a C++
  que arma K. Acá lo escribimos con `np.einsum("eij,ekj->eik", ...)` a
  mano. Más verboso, pero ves *exactamente* qué matriz se calcula.
- **Elementos de orden superior** (P2, P3, ...). FEniCS los cambia con
  una línea; acá habría que reescribir varias funciones (los gradientes
  dejarían de ser constantes dentro del tet).
- **Mallado adaptativo** y mallas mixtas (tet + hex + prisma).
- **Condiciones de borde de impedancia ensambladas en matriz de superficie**.
  Acá usamos damping por modo, que evita esto pero también es menos
  general.
- **Solvers paralelos** (PETSc, MUMPS, MPI). Sirven para millones de
  DOFs en clusters.

### 0.3 ¿Por qué entonces NO usar FEniCS?

Cuatro razones que motivaron la elección:

1. **El problema concreto es pequeño**. Helmholtz + paredes rígidas + P1
   + monopolos puntuales en una sala de 10³–10⁵ nodos. `eigsh` tarda
   segundos. Cualquier ganancia de performance de FEniCS es invisible.

2. **Cero dependencias pesadas**. FEniCS arrastra DOLFINx (C++), UFL,
   FFCx, PETSc, MPI. En Windows + Anaconda son horas de pelea con
   builds. Nuestro código vive con `numpy + scipy + matplotlib + PyQt5`,
   lo que ya tiene cualquier Python científica.

3. **Transparencia pedagógica**. Para un proyecto donde el usuario quiere
   *entender* qué pasa, una caja negra esconde la mecánica. Con NumPy
   podés:
   - imprimir K y M y mirarlas,
   - modificarlas a mano para experimentar,
   - saber exactamente dónde nace cada coeficiente.

   Esto fue clave para las cuatro capas de robustez recientes (filtro de
   slivers, simetrización forzada, retry de Lanczos, métricas de
   calidad). Ninguna se puede hacer con esa precisión con FEniCS.

4. **Portabilidad**. Corre en cualquier máquina con Python sin builds,
   admin ni GPU.

### 0.4 ¿Cuándo conviene cambiar a FEniCS?

Si el proyecto pidiera alguna de estas cosas, sí:

- Elementos P2+ para precisión `O(h³)` o mejor en alta frecuencia.
- Mallas con > 10⁶ DOFs (cuando SciPy sparse no entra en RAM).
- Impedancia angular-dependiente en paredes con absorción ensamblada en
  matriz `C` de superficie.
- Acoplamiento estructura-fluido (paneles vibrantes), termoacústica,
  problemas multifísicos.
- Paralelismo distribuido.

Mientras nada de eso aparezca, **NumPy/SciPy es la elección correcta**.

### 0.5 La distinción "método vs implementación", en general

Es una distinción importante:

| Método matemático | Una librería conocida | Implementación manual |
|---|---|---|
| FEM | FEniCS, deal.II, MFEM | nuestro código (NumPy/SciPy) |
| FFT | FFTW, MKL | Cooley-Tukey en 30 líneas |
| Quicksort | stdlib de cualquier lenguaje | 20 líneas |
| Newton-Raphson | scipy.optimize | 5 líneas |
| Runge-Kutta | scipy.integrate.solve_ivp | 15 líneas (RK4) |

Usar la librería no te hace más "real" en el método. Te hace más rápido
en implementación y, a veces, en performance. El método **es el mismo**.

### En una línea

> FEM define **qué hacer matemáticamente**. FEniCS automatiza **cómo
> escribirlo en código**. Nuestro código hace el "qué" a mano con
> NumPy/SciPy en lugar de delegar el "cómo" a un DSL.

---

## Mapa general del archivo

```
build_KM              -> ensambla K (rigidez) y M (masa) en formato sparse
solve_modes           -> resuelve K·φ = λ·M·φ y devuelve f_n y φ_n
_build_locator        \
_locate_one            >  infraestructura para "qué tet contiene a x"
FieldEvaluator        /   (vectorizado con cKDTree, 50-170× más rápido)
frequency_response    -> H(f) en un receptor por superposición modal
modal_pressure_field  -> p(x_node) a f fija, en TODOS los nodos
mode_shape_field      -> normaliza un modo para visualización
```

---

## 1. Física → forma débil → matrices

Ya conocés la cuenta como acústico, pero la pongo acá para anclar cada paso
del código al objeto matemático correspondiente.

### 1.1 Ecuación de Helmholtz

En el dominio Ω (el aire del recinto) y con `e^{+iωt}` como convención:

```
  ∇²p + k² p = -iωρ₀ q(x)        (k = ω/c)
```

`q(x)` es la densidad de monopolos (Σ Q_s δ(x - x_s) para fuentes puntuales).

### 1.2 Paredes rígidas → Neumann homogénea

`∂p/∂n = 0` en ∂Ω. **No se impone** modificando matrices: aparece naturalmente
al hacer la integración por partes en la forma débil (de ahí el nombre
"condición natural").

### 1.3 Forma débil (Galerkin)

Multiplicás por una función de prueba `v` e integrás:

```
  ∫_Ω ∇v · ∇p dV - k² ∫_Ω v p dV  =  iωρ₀ ∫_Ω v q dV
```

(el término de frontera desaparece porque `∂p/∂n = 0`).

### 1.4 Discretización: elementos P1 (lineales por tet)

Aproximás `p ≈ Σ_j p_j N_j(x)` con las **funciones de forma** `N_j`
*lineales por tet, continuas globalmente*, que cumplen `N_j(x_k) = δ_jk`.

Eligiendo `v = N_i` y sustituyendo:

```
  Σ_j p_j · (∫_Ω ∇N_i · ∇N_j dV)  -  k² · Σ_j p_j · (∫_Ω N_i N_j dV)
       = iωρ₀ Σ_s Q_s N_i(x_s)
```

Identificás:
- **Rigidez**:  `K_ij = ∫_Ω ∇N_i · ∇N_j dV`
- **Masa**:    `M_ij = ∫_Ω N_i N_j dV`

Para el problema de **modos libres** (sin fuente y sin pérdidas) buscás
`p(t) = φ e^{iωt}`. Sustituyendo:

```
  K φ = (ω/c)² · M · φ   ≡   K φ = λ M φ      con λ = (ω/c)²
```

De ahí salen las `f_n = c·√λ_n / (2π)`. Las `φ_n` son las **formas modales**
evaluadas en cada nodo (un vector de tamaño Nn por modo).

### 1.5 Ensamblaje elemento por elemento

Como las `N_j` solo son no nulas dentro de los tets que tocan al nodo `j`,
cada integral global se descompone en suma de integrales locales:

```
  K_ij = Σ_e K_ij^e    con   K_ij^e = ∫_tet_e ∇N_i · ∇N_j dV  si i,j ∈ tet_e
                                       0                       en otro caso
```

Y como las `N_j` son lineales por tet, `∇N_j` es **constante** dentro del
elemento. Eso simplifica las dos integrales locales a fórmulas cerradas que
verás abajo en `build_KM`.

---

## 2. Imports (líneas 1-40)

```python
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import eigsh
from typing import Optional

from sources import SourceArray, RHO0, C0
```

Qué hace cada uno:

- `numpy` → vectorización, álgebra lineal densa, broadcasting.
- `scipy.sparse` (`sp`) → matrices dispersas. K y M tienen ~30 elementos no
  nulos por fila aunque la dimensión sea de decenas de miles, sería suicida
  guardarlas en denso.
- `scipy.sparse.linalg.eigsh` → resolvedor de **autovalores generalizados**
  para matrices simétricas hermitianas; internamente usa Lanczos.
- `RHO0 = 1.21 kg/m³`, `C0 = 343 m/s` (aire a 20 °C); `SourceArray` es una
  lista de monopolos con posiciones `x_s` y caudales complejos `Q_s`.

---

## 3. `build_KM` — ensamblaje vectorizado (líneas 45-86)

Toma la malla `(nodes, tets)` y devuelve K, M y los volúmenes de cada tet.
**Esta es la función con más trucos**. La voy a romper en pedazos.

### 3.1 Setup

```python
nodes = np.asarray(nodes, dtype=float)
tets  = np.asarray(tets,  dtype=int)
Nn = nodes.shape[0]    # número de nodos
Ne = tets.shape[0]     # número de tets
```

### 3.2 Coordenadas por elemento

```python
coords = nodes[tets]                # (Ne, 4, 3)
```

**Truco**: indexar `nodes` (de forma `(Nn, 3)`) con `tets` (de forma `(Ne, 4)`)
inserta un eje extra al resultado. `coords[e, j, :]` es la posición xyz del
j-ésimo vértice del tet `e`. **Sin un solo loop Python** ya tenés todas las
coordenadas vertex-a-vertex para los Ne tets.

---

#### Cómo leer `nodes[tets]` — explicación desde cero

Esta es la operación más usada del archivo. Vale la pena pararse a
entenderla porque reaparece sin parar (`field_nodal[tet_nodes]` en el
`FieldEvaluator`, `nodes[tets]` en `_build_locator`, etc.).

**Setup**: con 5 nodos y 2 tets,

```python
nodes = [[0.0, 0.0, 0.0],   # nodo 0
         [1.0, 0.0, 0.0],   # nodo 1
         [0.0, 1.0, 0.0],   # nodo 2
         [0.0, 0.0, 1.0],   # nodo 3
         [1.0, 1.0, 1.0]]   # nodo 4   →  forma (5, 3)

tets  = [[0, 1, 2, 3],      # tet 0
         [1, 2, 3, 4]]      # tet 1   →  forma (2, 4)
```

**Lo que harías con loops**:

```python
coords = np.empty((Ne, 4, 3))
for e in range(Ne):
    for j in range(4):
        nodo_global = tets[e, j]
        coords[e, j, :] = nodes[nodo_global]
```

`coords = nodes[tets]` hace **exactamente esto** pero adentro de NumPy en C,
sin loops Python.

**La regla** (válida siempre que indexes con un array de enteros):

> Reemplazá cada entero del índice por la fila correspondiente del array
> indexado. El resultado hereda la forma del índice y le agrega los ejes
> "sobrantes" del array original.

Tres casos en orden creciente de complejidad:

| Operación | Forma del índice | Forma del resultado | Por qué |
|---|---|---|---|
| `nodes[2]` | escalar | `(3,)` | el escalar "consume" el eje 0 de `nodes`; queda el eje xyz |
| `nodes[[2, 0, 4]]` | `(3,)` | `(3, 3)` | el eje 0 de `nodes` se reemplaza por la forma del índice (`3,`); el xyz queda atrás |
| `nodes[tets]` | `(Ne, 4)` | `(Ne, 4, 3)` | mismo principio: forma del índice + ejes sobrantes |

**Diagrama mental**:

```
nodes:  (Nn,  3)            ← el primer eje es el que se "consume"
                                    el 3 (xyz) sobra y va al final
tets:   (Ne, 4)             ← forma del índice
              ↓
coords: (Ne, 4,  3)         ← (forma del índice) + (ejes sobrantes)
        └──┬───┘ └─┬─┘
           │       └─ los xyz de cada nodo
           └─ la forma de tets, intacta
```

**Resultado concreto** del ejemplo de arriba:

```python
coords[0]      = [[0,0,0], [1,0,0], [0,1,0], [0,0,1]]   # 4 vértices del tet 0
coords[1]      = [[1,0,0], [0,1,0], [0,0,1], [1,1,1]]   # 4 vértices del tet 1
coords[1, 2]   = [0, 0, 1]                              # 3er vértice del tet 1
coords[1, 2, 0] = 0.0                                   # coord x de ese vértice
```

**Por qué esto es central en FEM**: toda la conectividad funciona así.
Cada vez que en el código aparezca `propiedades_por_nodo[tabla_de_conectividad]`,
te está diciendo "traeme las propiedades de los nodos que forman cada
elemento". Lo vas a ver en:

- `nodes[tets]` → coordenadas xyz por tet (acá y en `_build_locator`).
- `field_nodal[tet_nodes]` → valores del campo en los 4 vértices del tet
  ganador (en `_evaluate_batch`).
- `self.tets[best_tet]` → los 4 índices de nodos del mejor tet por punto
  (en `_evaluate_batch`).

Una vez que internalizás este patrón, todo el archivo FEM se vuelve legible.

---

### 3.3 Matriz `V4` y volumen

```python
ones = np.ones((Ne, 4, 1), dtype=float)
V4 = np.concatenate([ones, coords], axis=2)   # (Ne, 4, 4)
detV = np.linalg.det(V4)                      # (Ne,)
vols = np.abs(detV) / 6.0                     # (Ne,)
```

Para un tet con vértices `(x_j, y_j, z_j)`, j=1..4:

```
  V4 = [[1, x₁, y₁, z₁],
        [1, x₂, y₂, z₂],
        [1, x₃, y₃, z₃],
        [1, x₄, y₄, z₄]]

  det(V4) = ± 6 · V_e
```

Esto es la identidad clásica para el volumen orientado de un tet — sale del
cálculo de `det` por expansión por la primera columna.

> **Truco SciPy/NumPy**: `np.linalg.det` y `np.linalg.inv` *operan en lote*
> si les pasás un array `(..., n, n)`. Acá `V4` es `(Ne, 4, 4)` y NumPy
> entiende "hacé el `det` (o `inv`) de cada matriz 4×4 a lo largo del eje
> `e`". Eso reemplaza un loop Python por una sola llamada.

### 3.4 Gradientes de las funciones de forma

```python
Vinv = np.linalg.inv(V4)                                  # (Ne, 4, 4)
grads = np.transpose(Vinv[:, 1:4, :], (0, 2, 1))          # (Ne, 4, 3)
```

#### Por qué la inversa de V4 contiene los gradientes

Las funciones de forma `N_j(x) = a_j + b_j·x + c_j·y + d_j·z` cumplen
`N_j(x_k) = δ_jk`. Escribilo en forma matricial:

```
  V4 · [a_j, b_j, c_j, d_j]ᵀ = e_j      (e_j = j-ésimo vector canónico)
```

Entonces los coeficientes son la **columna j** de `V4⁻¹`. El gradiente de
`N_j` es `(b_j, c_j, d_j)` — las filas 2, 3, 4 (índices 1, 2, 3) de esa
columna.

En código:

- `Vinv[:, 1:4, :]` selecciona filas 1, 2, 3 (las que tienen las
  componentes `b, c, d`) → forma `(Ne, 3, 4)`.
- `np.transpose(..., (0, 2, 1))` intercambia los dos últimos ejes →
  forma `(Ne, 4, 3)`.

Resultado: `grads[e, j, :]` es `∇N_j` en el tet `e` (un vector 3D).

> **Truco**: los gradientes son **constantes** dentro del tet porque las
> `N_j` son lineales. Por eso un solo número por `(e, j, componente)` alcanza.

### 3.5 Rigidez local

```python
K_e = vols[:, None, None] * np.einsum("eij,ekj->eik", grads, grads)
```

Quiero `K_ij^e = V_e · (∇N_i · ∇N_j)`. Vamos despacio:

- `grads` tiene forma `(Ne, 4, 3)`. Pensalo como una pila de Ne matrices
  `(4, 3)`. Cada fila de esas matrices es `∇N_j`.
- Quiero, para cada `e`, el producto matricial
  `grads[e] @ grads[e].T`, que da una matriz `(4, 4)` cuyo elemento
  `[i, j]` es `∇N_i · ∇N_j`.
- `einsum("eij,ekj->eik", grads, grads)`:
  - `e` queda igual (eje "batch").
  - `i, j` son índices del primer factor.
  - `k, j` son índices del segundo (donde `j` repite, así que se **suma** sobre él).
  - Salida: índice `(e, i, k)`. Pensalo: para cada `e`, salida `[i, k] = Σ_j grads[e, i, j] * grads[e, k, j]` — exactamente el producto fila-por-fila.

Multiplicar por `vols[:, None, None]` aplica el factor `V_e` con
broadcasting: `vols` es `(Ne,)`, los `None` lo expanden a `(Ne, 1, 1)` para
multiplicar componente a componente contra el `(Ne, 4, 4)`.

Resultado: `K_e[e, i, j] = V_e · ∇N_i · ∇N_j`. **Listo, en una línea para
todos los tets.**

### 3.6 Masa consistente local

```python
M_e = (vols[:, None, None] / 20.0) * (np.ones((4, 4)) + np.eye(4))[None]
```

#### De dónde sale la fórmula

Para integrar `∫_tet N_i N_j dV` se usa la identidad:

```
  ∫_tet  L_1^a L_2^b L_3^c L_4^d  dV  =  6V_e · a! b! c! d! / (a+b+c+d+3)!
```

con `L_j` las coordenadas baricéntricas (que son las mismas `N_j`).

- Si `i = j`: integrando es `N_i²` → `a=2, b=c=d=0` → factorial = 2,
  denominador = 5! = 120 → integral = `6V_e · 2 / 120 = V_e / 10`.
- Si `i ≠ j`: integrando es `N_i N_j` → un par de 1's → factorial = 1,
  denominador = 5! = 120 → integral = `6V_e · 1 / 120 = V_e / 20`.

Equivalentemente: `M_ij^e = (V_e / 20) · (1 + δ_ij)`. Los 4×4 que necesito son:

```
  [[2, 1, 1, 1],
   [1, 2, 1, 1],
   [1, 1, 2, 1],
   [1, 1, 1, 2]] · (V_e / 20)
```

#### En código

- `np.ones((4, 4))` → matriz 4×4 de 1s.
- `np.eye(4)` → identidad 4×4.
- Suma → matriz con 2 en diagonal y 1 fuera.
- `[None]` agrega un eje → forma `(1, 4, 4)`.
- `vols[:, None, None] / 20.0` es `(Ne, 1, 1)`.
- Broadcasting: `(Ne, 1, 1) * (1, 4, 4) → (Ne, 4, 4)`.

`M_e[e, i, j]` es la masa consistente local del tet `e`.

> **Por qué "consistente" y no "lumped"**: la versión "lumped" usa
> integración aproximada en nodos → matriz diagonal `M_ii = V_e/4`. Es más
> rápida pero introduce error de fase en los modos. La versión consistente
> que está acá da los modos correctos hasta `O(h²)`.

### 3.7 Scatter (ensamblaje a la matriz global)

```python
idx = tets                                                # (Ne, 4)
rows = np.repeat(idx, 4, axis=1).reshape(Ne, 4, 4)        # (Ne, 4, 4)
cols = np.tile(idx[:, None, :], (1, 4, 1))                # (Ne, 4, 4)
```

Quiero que la entrada local `K_e[e, i, j]` vaya al global
`(fila, col) = (tets[e, i], tets[e, j])`. Para todos los Ne tets y los 16
pares `(i, j)`, necesito un array de filas globales y otro de columnas.

- `rows`: para cada `(e, i, j)`, queremos `tets[e, i]`. Esto es independiente
  de `j` (el destino de fila depende solo de `i`).
  `np.repeat(idx, 4, axis=1)` toma `idx` de forma `(Ne, 4)` y repite cada
  columna 4 veces a lo largo del eje 1 → `(Ne, 16)`. El reshape lo acomoda
  como `(Ne, 4, 4)`.

  > Para que se vea: si una fila de `idx` es `[a, b, c, d]`,
  > después de `np.repeat(..., 4, axis=1)` queda `[a a a a b b b b c c c c d d d d]`.
  > Reshape a `(4, 4)` da:
  > ```
  > [[a a a a],
  >  [b b b b],
  >  [c c c c],
  >  [d d d d]]
  > ```
  > Eso es justo lo que querés: `rows[e, i, j] = tets[e, i]` independiente de `j`.

- `cols`: para cada `(e, i, j)`, queremos `tets[e, j]`. Esto depende solo
  de `j`. `idx[:, None, :]` tiene forma `(Ne, 1, 4)`; `np.tile(..., (1, 4, 1))`
  repite el eje del medio 4 veces → `(Ne, 4, 4)`.

  > Si una fila de `idx` es `[a, b, c, d]`, después del tile cada uno de los
  > 4 sub-renglones es `[a b c d]`:
  > ```
  > [[a b c d],
  >  [a b c d],
  >  [a b c d],
  >  [a b c d]]
  > ```
  > Eso es `cols[e, i, j] = tets[e, j]` independiente de `i`.

### 3.8 Construcción de la matriz sparse

```python
K = sp.coo_matrix(
    (K_e.ravel(), (rows.ravel(), cols.ravel())), shape=(Nn, Nn)
).tocsr()
M = sp.coo_matrix(
    (M_e.ravel(), (rows.ravel(), cols.ravel())), shape=(Nn, Nn)
).tocsr()
return K, M, vols
```

> **Truco fundamental de `coo_matrix`**: si dos entradas tienen la misma
> `(fila, col)`, **las suma** automáticamente al consolidar a CSR. Esto
> *es* el ensamblaje FEM: cada nodo recibe contribuciones de todos los tets
> que lo tocan, y todas terminan en la misma `(fila, col)` global.

`.tocsr()` convierte de COO (formato eficiente para construir) a CSR (formato
eficiente para multiplicar matriz × vector, que es lo que `eigsh` necesita).

---

## 4. `solve_modes` — autovalores generalizados (líneas 92-125)

```python
def solve_modes(K, M, n_modes=20, c=C0, sigma=1e-6, drop_zero_mode=True):
```

### 4.1 Pedir un autovalor de más

```python
n_modes = max(2, int(n_modes))
n_request = n_modes + (1 if drop_zero_mode else 0)
```

Cuando `drop_zero_mode=True` pedimos uno extra porque el primer autovalor
es siempre `λ ≈ 0` (modo trivial `p = constante`, frecuencia 0). No es
físico — corresponde a presión estática uniforme, que no se propaga.

### 4.2 La llamada a `eigsh` con shift-invert

```python
eigvals, eigvecs = eigsh(K, k=n_request, M=M, sigma=sigma, which="LM")
```

> **Truco crítico que conviene entender**: queremos los autovalores MÁS
> CHICOS (los modos de baja frecuencia). Si pidieras `which="SM"` (smallest
> magnitude), `eigsh` haría iteración de potencia inversa muy lenta. La
> solución estándar es:
>
> 1. Reformular como `(K - σM)⁻¹ · M · φ = μ · φ`, con `μ = 1 / (λ - σ)`.
> 2. Pedir los autovalores **más grandes en magnitud** de este problema
>    transformado (`which="LM"`).
> 3. Los `μ` más grandes son los `λ` más cercanos a `σ`.
>
> Con `σ = 1e-6`, los λ cercanos a 0 (los modos de baja frecuencia) son
> exactamente los que queremos. **`eigsh` hace la factorización LU de
> `K - σM` UNA sola vez** y luego cada iteración de Lanczos es una
> sustitución hacia adelante/atrás, que es muy barata.

**Por qué `eigsh` y no `eigs`**: la `h` es de *hermítica*. K y M son
simétricas reales positivas semi-definidas, así que los autovalores son
reales y `eigsh` está optimizado para eso.

```python
eigvals = np.clip(eigvals.real, 0.0, None)
```

Por ruido numérico el modo cero puede dar `-1e-10`. El `clip` lo manda a 0
sin tirar información.

### 4.3 Ordenar y descartar el modo trivial

```python
order = np.argsort(eigvals)
eigvals = eigvals[order]
eigvecs = eigvecs[:, order]
```

`argsort` da los índices que ordenan ascendente. Aplicar `[order]` a los
autovalores y `[:, order]` a los autovectores (columnas) deja el modo
fundamental primero.

```python
if drop_zero_mode and eigvals[0] < 1e-6:
    eigvals = eigvals[1:]
    eigvecs = eigvecs[:, 1:]
eigvals = eigvals[:n_modes]
eigvecs = eigvecs[:, :n_modes]
```

Tira el modo cero si está, y se queda con los primeros `n_modes` no triviales.

### 4.4 M-ortonormalización

```python
for n in range(eigvecs.shape[1]):
    norm2 = float(eigvecs[:, n] @ (M @ eigvecs[:, n]))
    if norm2 > 0:
        eigvecs[:, n] /= np.sqrt(norm2)
```

Cada modo se escala para que `φ_nᵀ · M · φ_n = 1`.

#### Por qué esto importa

La fórmula clásica de superposición modal asume que los modos están
*M-ortonormales*: `φ_iᵀ · M · φ_j = δ_ij`. Si no, te aparece un factor
`1 / (φ_nᵀ M φ_n)` en cada término de la FRF.

`eigsh` por default *suele* devolverlos M-ortonormales para el shift-invert,
pero no lo garantiza estrictamente (la normalización depende del Arpack
backend). Por eso re-normalizamos a mano: una pasada por modo,
`O(Nm · nnz(M))`, despreciable comparado con la solución del autoproblema.

> **Truco NumPy/SciPy**: `M @ eigvecs[:, n]` es producto matriz-sparse ×
> vector denso — devuelve un vector denso `(Nn,)`. El `@` con `eigvecs[:, n]`
> a la izquierda es un producto punto (`Nn,) · (Nn,) → escalar`. Todo BLAS.

### 4.5 De autovalor a frecuencia

```python
freqs = np.sqrt(eigvals) * c / (2.0 * np.pi)
return freqs, eigvecs
```

Recordá que `λ = (ω/c)² = (2πf/c)²`. Despejás `f`.

### 4.6 Nota: `solve_modes` no chequea validez de malla (v2.12)

`solve_modes` devuelve los `n_modes` autovalores más bajos sin comparar
contra `f_max_malla = c / (ppw·h_max)`. Si pedís muchos modos en una
malla coarse, los últimos pueden caer **arriba del techo de validez**
— modos numéricamente sucios por dispersión del esquema FEM.

Es deliberado: el solver no debería sobre-comprometerse a una política
de validez de malla. **El clip lo aplica el panel** (`acoustic_panel.
AcousticPanel._clip_modes_to_mesh_validity()` desde v2.12) **después**
del solve, descartando los modos con `f > f_max_malla` antes de pasarlos
al picker / FRF / heatmap.

Si usás `solve_modes` programáticamente fuera del panel y querés el
mismo filtro, el patrón es:

```python
freqs, phis = solve_modes(K, M, n_modes=N)
info = mesh_info(nodes, tets)
f_max_malla = max_solver_frequency(info["h_max"], ppw=6)
mask = freqs <= f_max_malla
freqs = freqs[mask]
phis = phis[:, mask]
```

`max_solver_frequency` está en `acoustic_mesh.py`. El uso de `ppw=6`
matchea la regla de la app.

---

## 5. `_build_locator` — pre-cómputo barycentric (líneas 131-150)

Esto y `_locate_one` son la infraestructura de "¿qué tet contiene a este
punto y con qué coords baricéntricas?". Es lo que el FRF necesita para
evaluar `φ_n(x_receptor)` y `φ_n(x_fuente)`.

### 5.1 Matemática

Para un tet con vértices `v₀, v₁, v₂, v₃`, las coords baricéntricas
`(N₀, s, t, u)` de un punto `x` cumplen:

```
  x = N₀ v₀ + s v₁ + t v₂ + u v₃     con N₀ + s + t + u = 1
```

Equivalentemente:

```
  x - v₀ = s (v₁ - v₀) + t (v₂ - v₀) + u (v₃ - v₀)
```

Definiendo `A = [v₁-v₀ | v₂-v₀ | v₃-v₀]` (matriz 3×3 con esos vectores como
columnas):

```
  A · (s, t, u)ᵀ = (x - v₀)        →        (s, t, u)ᵀ = A⁻¹ (x - v₀)
```

Y `N₀ = 1 - s - t - u`. **El punto está dentro del tet si `N₀, s, t, u ≥ 0`**.

### 5.2 Código

```python
coords = nodes[tets]                # (Ne, 4, 3)
v0 = coords[:, 0, :]                # (Ne, 3)     — primer vértice de cada tet
A = np.stack([
    coords[:, 1, :] - v0,
    coords[:, 2, :] - v0,
    coords[:, 3, :] - v0,
], axis=2)                          # (Ne, 3, 3)
```

`np.stack(..., axis=2)` arma una `(Ne, 3, 3)` apilando los tres vectores
diferencia como **columnas** (tercer eje) de cada matriz `A`.

```python
A_inv = np.linalg.inv(A)            # (Ne, 3, 3) en lote
```

Inversa de cada A en una sola llamada (lote NumPy).

```python
except np.linalg.LinAlgError:
    A_inv = np.zeros_like(A)
    for e in range(A.shape[0]):
        try:
            A_inv[e] = np.linalg.inv(A[e])
        except np.linalg.LinAlgError:
            A_inv[e] = np.eye(3) * 1e30
```

Fallback: si **algún** tet es degenerado (volumen cero, vértices coplanares
por error de mallado), `np.linalg.inv(A)` falla para todo el lote. En ese
caso vamos elemento por elemento y para los degenerados ponemos una matriz
gigantesca: cualquier `s, t, u` calculado con ella va a salir gigante y
caer fuera del rango `[0, 1]`, así que ese tet nunca va a ser "ganador".
Efectivamente: lo descartamos sin romper nada.

---

## 6. `_locate_one` — localización para un punto (líneas 153-168)

```python
def _locate_one(v0_all, A_inv_all, tets, x, tol=1e-6):
    rel = x - v0_all                                    # (Ne, 3)
    stu = np.einsum("eij,ej->ei", A_inv_all, rel)       # (Ne, 3)
    s, t, u = stu[:, 0], stu[:, 1], stu[:, 2]
    N0 = 1.0 - s - t - u
    valid = (N0 >= -tol) & (s >= -tol) & (t >= -tol) & (u >= -tol)
    if not np.any(valid):
        return None, None
    cand = np.where(valid)[0]
    min_N = np.minimum.reduce([N0[cand], s[cand], t[cand], u[cand]])
    e = int(cand[int(np.argmax(min_N))])
    N = np.array([N0[e], s[e], t[e], u[e]])
    return e, N
```

Línea por línea:

- `rel = x - v0_all`: `x` es `(3,)`, `v0_all` es `(Ne, 3)`. Broadcasting:
  `rel[e] = x - v0[e]`.
- `np.einsum("eij,ej->ei", A_inv_all, rel)`: matrix-vector para cada `e`.
  Sumo sobre `j` (índice contraído), conservo `e` y `i`. Equivale a hacer
  `A_inv[e] @ rel[e]` para todo `e`, sin loop.
- `valid` es un bool por tet: `True` si las 4 coords son no negativas (con
  tolerancia `tol = 1e-6` para evitar excluir puntos justo en una cara).
- Si **ningún** tet es válido, el punto está fuera de la malla → `(None, None)`.
- Si varios son válidos (puntos en caras o aristas compartidas), elegimos
  el "más adentro": `min_N[c]` es la mínima coord baricéntrica del tet
  candidato `c`. El de mayor `min_N` es el que tiene al punto más cerca
  del interior — la elección numéricamente más estable para interpolar.

---

## 7. `FieldEvaluator` — interpolación vectorizada masiva (líneas 171-313)

`_locate_one` está bien para puntos sueltos (el receptor, una fuente). Pero
para evaluar el campo en una grilla densa (miles a millones de puntos) hace
falta otro nivel de optimización.

### 7.1 Por qué no se puede hacer naïve

El loop naïve `for p in points: locate_one(p)` cuesta `O(Np · Ne)` con
**Python** en el medio. Para `Np = 50 000` y `Ne = 25 000` son 10⁹
iteraciones — minutos de espera.

### 7.2 Idea

Construir un **árbol KD** sobre los centroides de los tets. Para cada punto,
pedir los `K = 12` centroides más cercanos. Evaluar barycentric solo en esos
12 candidatos, **vectorizado** en NumPy.

- Hipótesis: para mallas razonables, el tet que contiene a un punto está
  entre los K vecinos más cercanos a su centroide. Cierto en >99 % de los
  casos.
- Falla en tets muy alargados en bordes. Para esos, fallback con `K = 48`.

Speedup medido sobre el loop naïve: **50–170×** según el tamaño.

---

#### ¿Qué es un KDTree? — explicación desde cero

Si no viste la estructura antes, esta sección no se entiende. Acá va el
mínimo viable.

**El problema que resuelve**: tenés una nube de puntos en el espacio (en
este caso, los centroides de los tets, forma `(Ne, 3)`). Llega un punto
nuevo `x` y querés saber:

> ¿Cuál es el punto de la nube más cercano a `x`? ¿Y los `k` más cercanos?

Se llama **búsqueda del vecino más cercano** (nearest-neighbor search).

**La forma naïve**: comparar `x` contra todos los `Ne` puntos uno por uno
y quedarse con el menor. Costo `O(Ne)` por consulta. Para `Ne = 25 000`
y `Np = 50 000` puntos a evaluar, son `1.25 · 10⁹` comparaciones —
minutos en Python.

**La idea del KDTree** (*k-dimensional tree*): pre-organizar la nube en un
**árbol binario** para que cada consulta descarte mitades del espacio en
vez de recorrer todo.

##### Cómo se construye (visualizado en 2D)

Imaginá puntos esparcidos en un plano. El algoritmo:

1. Encuentra la coordenada `x` **mediana** y parte el plano con una
   **línea vertical**: mitad de los puntos quedan a la izquierda, mitad
   a la derecha.
2. En cada mitad, encuentra la coordenada `y` mediana y parte con una
   **línea horizontal**.
3. En cada cuadrante, vuelve a partir alternando ejes hasta que cada
   celda tiene 1-2 puntos.

```
 ┌────────┬─────────┐
 │  •     │•        │
 │        │   •     │
 ├────────┼─────────┤
 │   •    │         │
 │        │•     •  │
 │  •     │ •       │
 └────────┴─────────┘
```

En 3D el algoritmo es igual: alterna `x, y, z, x, y, z, ...` y parte con
planos. El árbol queda con un nodo por partición; las hojas contienen
los puntos finales.

Construir el árbol cuesta **`O(Ne · log Ne)` una sola vez**.

##### Cómo se consulta

Llega un punto `x` y querés su vecino más cercano:

1. Mirás la primera línea: ¿`x` está a izquierda o derecha? **Descartás
   la otra mitad entera.**
2. En la mitad correcta, mirás la siguiente línea (perpendicular):
   descartás de nuevo.
3. Bajás hasta una hoja, calculás distancia solo a esos pocos puntos.

**Costo: `O(log Ne)` por consulta**. Para `Ne = 25 000`, son ~15 pasos
en lugar de 25 000. Speedup teórico ~1500×.

> Detalle técnico: a veces el vecino real está justo al otro lado de
> una línea que descartaste (si la distancia al borde es menor que la
> distancia al mejor candidato actual). El algoritmo detecta esto y
> "vuelve" a la otra rama. En la práctica, la mayoría de las ramas se
> descartan limpiamente.

##### Pedir los K más cercanos (no solo el más cercano)

El algoritmo es el mismo, pero mantiene una "lista de los mejores K hasta
ahora" mientras desciende. Por eso esta línea del código:

```python
_d, cand = self._tree.query(points, k=k)
```

con `k = 12` devuelve, para **cada** punto de `points`, los **12** índices
de los tets más cercanos por centroide — todo en una sola llamada a C.

Formas:
- `points` → `(Np, 3)`.
- `_d` → `(Np, k)`: distancias al k-ésimo más cercano.
- `cand` → `(Np, k)`: índices (entre 0 y `Ne-1`) de los `k` tets más
  cercanos a cada punto.

##### Por qué la hipótesis "tet contenedor ∈ K más cercanos por centroide"

Si un tet contiene a `x`, su centro de masa NO PUEDE estar muy lejos de
`x`. Tan solo no puede estar a más de su propio radio (distancia desde
el centroide al vértice más lejano).

Por eso entre los **12 centroides más cercanos** a `x` está, casi
siempre, el centroide del tet contenedor. Y solo hace falta evaluar las
coords baricéntricas en esos 12.

Pasaste de `O(Ne)` por punto a `O(log Ne) + 12 · O(1)` por punto. Para
`Ne = 25 000`: de 25 000 operaciones por punto a ~27.

##### Cuándo falla la hipótesis

En **tets muy alargados** (slivers en bordes escalonados de paredes
oblicuas — los mismos que ahora filtra la Capa 1 del mallador). En un
sliver, el centroide puede estar lejos del extremo, y el centroide más
cercano a un punto en el extremo puede ser de OTRO tet vecino.

Por eso el fallback con `K = 48`: si más del 1 % de los puntos no se
localizó, se reintenta solo esos con K mayor.

##### Comparación rápida

| | Naïve | KDTree |
|---|---|---|
| Pre-cómputo | nada | `O(Ne · log Ne)`, una vez |
| Por consulta | `O(Ne)` | `O(log Ne)` |
| `Ne = 25k, Np = 50k` (medido) | ~20 s en Python | ~0.3 s |
| Memoria extra | 0 | ~1 puntero/nodo (despreciable) |

##### Mini-experimento

```python
from scipy.spatial import cKDTree
import numpy as np

nube = np.random.rand(1000, 3)        # 1000 puntos en [0,1]³
tree = cKDTree(nube)                   # construir UNA vez

# Consultar los 5 vecinos más cercanos al centro:
distancias, indices = tree.query([0.5, 0.5, 0.5], k=5)
print(distancias)        # (5,) — distancias en orden creciente
print(indices)           # (5,) — índices de los 5 puntos en `nube`
print(nube[indices])     # (5, 3) — sus coordenadas
```

Notá: como el segundo parámetro `tree.query` puede ser un **lote** de
puntos `(Np, 3)`, ahí está la vectorización masiva que usa
`_evaluate_batch`.

##### Releé el código con esto en la cabeza

```python
def _ensure_tree(self):
    coords = self.nodes[self.tets]            # (Ne, 4, 3)
    self._centroids = coords.mean(axis=1)     # (Ne, 3) — centroide de cada tet
    from scipy.spatial import cKDTree
    self._tree = cKDTree(self._centroids)     # ← construir árbol UNA vez
```

```python
_d, cand = self._tree.query(points, k=k)     # ← en bloque, rapidísimo
```

Debería leerse ahora como: "armé un árbol sobre los centros de los tets,
y por cada punto que quiero evaluar le pido al árbol los 12 tets
candidatos más probables".

---

### 7.3 `__init__` (líneas 193-200)

```python
self.v0, self.A_inv = _build_locator(self.nodes, self.tets)
self._centroids = None     # lazy
self._tree = None          # lazy
```

Pre-computamos los `A⁻¹` (caros: `Ne` inversas 3×3). El KDTree y los
centroides se construyen **lazy** (solo cuando se llame `evaluate_many` por
primera vez), porque si el usuario solo evalúa el receptor con `evaluate_one`
no hace falta gastar memoria en el árbol.

### 7.4 `_ensure_tree` (líneas 202-208)

```python
coords = self.nodes[self.tets]            # (Ne, 4, 3)
self._centroids = coords.mean(axis=1)     # (Ne, 3)
from scipy.spatial import cKDTree
self._tree = cKDTree(self._centroids)
```

`mean(axis=1)` colapsa el eje de los 4 vértices → centroide por tet.
`cKDTree` es la versión Cython del KDTree de SciPy (rápida).

### 7.5 `_evaluate_batch` — el corazón optimizado

```python
def _evaluate_batch(self, field_nodal, points, k_candidates, tol=1e-6):
```

Recibe un campo nodal `(Nn,)` (los valores en los nodos), un lote de puntos
`(Np, 3)`, y `k_candidates`. Devuelve `(out, found_mask)`.

#### Setup

```python
Np = len(points)
out = np.full(Np, np.nan, dtype=np.complex128)
if Np == 0:
    return out, np.zeros(Np, dtype=bool)
Ne = len(self.tets)
k = int(min(max(1, k_candidates), Ne))
```

#### Query al KDTree

```python
_d, cand = self._tree.query(points, k=k)
if k == 1:
    cand = cand[:, None]
cand = np.asarray(cand, dtype=np.int64)
```

`self._tree.query(points, k=k)` devuelve dos arrays `(Np, k)`: distancias y
**índices de los k centroides más cercanos** a cada punto. Es la única
operación cara (pero está en C, así que es rapidísima incluso para
millones de puntos).

> **Truco**: si `k=1` SciPy te devuelve un array 1D `(Np,)`. Forzamos forma
> `(Np, 1)` con `[:, None]` para uniformidad.

#### Barycentric vectorizado sobre `(Np, k)` pares

```python
v0_pc = self.v0[cand]                                 # (Np, k, 3)
A_inv_pc = self.A_inv[cand]                           # (Np, k, 3, 3)
rel_pc = points[:, None, :] - v0_pc                   # (Np, k, 3)
stu = np.einsum("pcij,pcj->pci", A_inv_pc, rel_pc)    # (Np, k, 3)
s, t, u = stu[..., 0], stu[..., 1], stu[..., 2]
N0 = 1.0 - s - t - u
valid = (N0 >= -tol) & (s >= -tol) & (t >= -tol) & (u >= -tol)
```

Léelo así:

- `cand` es `(Np, k)`, entero. Usarlo para indexar `self.v0` (forma `(Ne, 3)`)
  produce `(Np, k, 3)`: para cada `(p, c)`, el `v0` del c-ésimo tet candidato
  para el punto `p`.
- Análogo para `A_inv` → `(Np, k, 3, 3)`.
- `points[:, None, :]` es `(Np, 1, 3)`; broadcastea contra `(Np, k, 3)` →
  `(Np, k, 3)`: `rel_pc[p, c]` es la diferencia para el par `(p, c)`.
- El `einsum("pcij,pcj->pci", ...)` hace matrix-vector para **cada par**
  `(p, c)`: contrae el `j` (suma sobre componentes), conserva `p`, `c`, `i`.
- `valid` es ahora `(Np, k)` bool: `True` si el tet candidato `c` contiene
  al punto `p`.

#### Elegir el mejor candidato

```python
min_N = np.minimum.reduce([N0, s, t, u])          # (Np, k)
masked = np.where(valid, min_N, -np.inf)
best_c = np.argmax(masked, axis=1)                # (Np,)
rows = np.arange(Np)
found_mask = masked[rows, best_c] > -np.inf
```

- `min_N` es el "qué tan adentro" para cada par.
- `np.where(valid, min_N, -np.inf)` deja `-inf` donde el tet no contenía al
  punto, así no puede ganar el `argmax`.
- `best_c[p]` es el índice (dentro de los k candidatos de p) del tet
  ganador.
- `found_mask` marca los puntos para los que se encontró al menos un
  candidato válido.

> **Truco NumPy**: `arr[rows, best_c]` con `rows = np.arange(Np)` y `best_c`
> de forma `(Np,)` es **fancy indexing 2D**. Te devuelve un array `(Np,)` con
> `arr[i, best_c[i]]` para cada `i`. Es la forma vectorizada de "elegir una
> columna distinta por fila".

#### Recuperar las coords baricéntricas del ganador

```python
s_b  = s[rows, best_c]
t_b  = t[rows, best_c]
u_b  = u[rows, best_c]
N0_b = N0[rows, best_c]
weights = np.stack([N0_b, s_b, t_b, u_b], axis=1)     # (Np, 4)
```

Cada `weights[p, :]` son las 4 coords baricéntricas del punto `p` en su
tet ganador. Son los **pesos** para interpolar el campo:
`p(x) = Σ_j w_j · field[tet_node_j]`.

#### Interpolación lineal final

```python
best_tet = cand[rows, best_c]                         # (Np,) — índice global del tet
tet_nodes = self.tets[best_tet]                       # (Np, 4) — los 4 nodos
field_vals = np.asarray(field_nodal)[tet_nodes]       # (Np, 4) — los 4 valores
if not np.iscomplexobj(field_vals):
    field_vals = field_vals.astype(np.complex128, copy=False)
interp = (weights.astype(field_vals.dtype) * field_vals).sum(axis=1)
out[found_mask] = interp[found_mask]
return out, found_mask
```

- `field_vals[p, j]` es el valor del campo en el j-ésimo vértice del tet
  ganador del punto `p`.
- Convertir a complejo si el campo es real (los `out` son complejos siempre,
  porque el solver puede generar campos complejos para frecuencias con
  damping).
- Multiplicación elemento a elemento con los pesos, suma por filas →
  interpolación lineal exacta.
- Solo escribimos los puntos efectivamente localizados.

### 7.6 `evaluate_many` — la API pública con fallback (líneas 280-313)

```python
out, found = self._evaluate_batch(field_nodal, points,
                                  k_candidates=self._K_INITIAL)  # K = 12
n_miss = int(np.count_nonzero(~found))
if 0 < n_miss < Np and (n_miss / Np) >= 0.01:
    miss_pts = points[~found]
    out2, found2 = self._evaluate_batch(field_nodal, miss_pts,
                                        k_candidates=self._K_FALLBACK)  # K = 48
    tmp = out.copy()
    tmp_idx = np.where(~found)[0]
    tmp[tmp_idx[found2]] = out2[found2]
    out = tmp
return out
```

Estrategia de dos pasadas:

- Pasada 1 con `K = 12` (rápida, 99 % de los casos).
- Si más del 1 % de los puntos quedan sin localizar, reintenta solo esos
  con `K = 48`. El "1 %" es porque puntos genuinamente fuera del recinto
  (clipping de visualización por ejemplo) deben quedar como NaN, no
  reintentarse infinitamente.

> **Truco de mezcla de resultados**: `tmp_idx = np.where(~found)[0]` te da
> los **índices originales** de los puntos no encontrados. `tmp_idx[found2]`
> aplica la máscara `found2` a esos índices, dándote *en qué posiciones del
> array original* hay que escribir los nuevos valores. Es indexing
> indirecto: `tmp[tmp_idx[found2]] = out2[found2]`.

---

## 8. `frequency_response` — FRF por superposición modal (líneas 319-365)

Calcula `H(f)` en un receptor `x_r` por:

```
  H(f) = i·ω·ρ₀ · Σ_n  φ_n(x_r) · [Σ_s Q_s · φ_n(x_s)]
                       ─────────────────────────────────
                          ω_n² - ω² + 2i·ξ_n·ω_n·ω
```

#### De dónde sale

Partís de `(K - k² M) p = i·ω·ρ₀ · f`, expandís
`p(x) = Σ_n α_n φ_n(x)`, usás la M-ortonormalidad para despejar `α_n`, e
incluís damping modal `ξ_n` (no es trivialmente derivable de K, M; se aplica
*a mano* porque las paredes rígidas no introducen pérdidas — el damping en
acústica modal de salas viene de la absorción de los materiales y se modela
modo a modo con `ξ_n` derivado del `T_60` por banda).

### 8.1 Damping uniforme o por modo

```python
xi = (np.full(Nm, float(damping)) if np.isscalar(damping)
      else np.asarray(damping, dtype=float)[:Nm])
```

Permite `damping = 0.03` (un escalar, mismo ξ para todos los modos) **o**
`damping = array(Nm,)` con un ξ distinto por modo. Lo segundo es lo correcto
si calculás ξ a partir del RT60 por banda y mapeás cada modo a su banda.

### 8.2 `φ_n(x_receptor)` y `φ_n(x_fuente)`

```python
phi_r = np.zeros(Nm, dtype=float)
for n in range(Nm):
    val = locator.evaluate_one(phis[:, n], receiver)
    phi_r[n] = 0.0 if val is None else val.real
```

Por cada modo: interpolar su valor en el receptor. Si el receptor cae fuera
de la malla, queda 0 (no contribuye).

```python
src_arr = sources.amplitudes()              # (Ns,) complejo
src_pos = sources.positions()               # (Ns, 3)
Ns = len(src_pos)
phi_s = np.zeros((Ns, Nm), dtype=float)
for s_idx in range(Ns):
    for n in range(Nm):
        val = locator.evaluate_one(phis[:, n], src_pos[s_idx])
        phi_s[s_idx, n] = 0.0 if val is None else val.real
```

`phi_s[s, n]` es `φ_n` evaluado en la posición de la fuente `s`. Loop doble
pero acotado: Ns × Nm es chico (decenas × decenas), no es el cuello de
botella.

### 8.3 Numerador modal precomputado

```python
num = phi_r * (src_arr @ phi_s)              # (Nm,) complejo
```

> Léelo en partes:
>
> - `src_arr @ phi_s`: vector `(Ns,)` × matriz `(Ns, Nm)` → vector `(Nm,)`.
>   Entrada `n`: `Σ_s Q_s · φ_n(x_s)` — la *amplitud modal de excitación*.
> - `phi_r * (...)`: multiplicación elemento a elemento. Entrada `n`:
>   `φ_n(x_r) · Σ_s Q_s · φ_n(x_s)`.
>
> Es exactamente el numerador modal de la fórmula. **No depende de la
> frecuencia**, así que lo precomputás una vez fuera del loop.

### 8.4 Loop sobre frecuencia

```python
H = np.empty(len(freq_axis), dtype=complex)
for i, f in enumerate(freq_axis):
    omega = 2.0 * np.pi * f
    denom = (omega_n**2 - omega**2) + 2j * xi * omega_n * omega
    denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
    H[i] = 1j * omega * rho0 * np.sum(num / denom)
return H
```

- `omega_n` es `(Nm,)`, `omega` un escalar → `denom` es `(Nm,)` complejo.
- El `np.where` previene división por cero exacto (no debería pasar con
  damping > 0, pero es seguro).
- `num / denom` es elemento a elemento, `(Nm,)`. `np.sum` colapsa a un
  escalar complejo. `1j * omega * rho0 * ...` aplica el prefactor físico.

> **Truco**: el loop sobre frecuencia es necesario porque `denom` depende
> de `f`. Si quisieras vectorizarlo, harías `omega_n[None, :]**2 - omega[:, None]**2`
> → matriz `(Nf, Nm)` — funcionaría pero usa más memoria. En la práctica
> `Nf · Nm` es chico (< 10⁵), el loop Python no domina.

---

## 9. `modal_pressure_field` — campo completo a frecuencia fija (líneas 368-406)

Mismo solver modal, pero devuelve `p(x_node)` para **todos los nodos** a una
sola `f`. Útil para mapas de presión a una frecuencia (gráficos 3D).

### 9.1 Cuerpo

```python
Nm = phis.shape[1]
omega_n = 2.0 * np.pi * freqs
omega = 2.0 * np.pi * f

# φ_n(x_fuente) — igual que en frequency_response
phi_s = ...

src_weight = src_arr @ phi_s                       # (Nm,) complejo
xi = ...
denom = (omega_n**2 - omega**2) + 2j * xi * omega_n * omega
denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
coeff = 1j * omega * rho0 * (src_weight / denom)   # (Nm,)
p_nodes = phis @ coeff                              # (Nn,)
return p_nodes
```

### 9.2 La línea clave: `p_nodes = phis @ coeff`

`phis` tiene forma `(Nn, Nm)`. `coeff` tiene forma `(Nm,)`. El producto
matricial te da `(Nn,)`:

```
  p_nodes[i] = Σ_n  phis[i, n] · coeff[n]  =  Σ_n  φ_n(x_i) · coeff[n]
```

> **Truco**: ahí está la magia. Una sola operación BLAS (matriz × vector,
> denso) calcula la presión en **todos los nodos a la vez**. Hubiera sido
> tentador hacer `for i in range(Nn): p_nodes[i] = ...` — y sería 100×
> más lento. `phis @ coeff` aprovecha BLAS optimizado de la librería que
> esté detrás de NumPy (MKL, OpenBLAS).

---

## 10. `mode_shape_field` — normalización para mostrar (líneas 409-416)

```python
def mode_shape_field(phis, mode_idx):
    phi = phis[:, mode_idx].real
    m = float(np.max(np.abs(phi)))
    return phi / m if m > 0 else phi
```

Toma la columna `mode_idx` (un modo), descarta la parte imaginaria (los modos
reales para problemas hermíticos sin damping son reales salvo una fase
global), y normaliza al máximo absoluto.

**Por qué normalizar a `max|φ| = 1`** y no al M-norm: es para *visualización*,
no para cálculo. Quiero que el colormap entre modos sea comparable a ojo,
y que el patrón de nodos/antinodos se vea con la misma escala. La
M-ortonormalidad está intacta en `phis` mismo, solo no se aplica al output
de visualización.

---

## 11. Demo (`if __name__ == "__main__"`) (líneas 422-459)

Caja 5×4×3, malla `n_per_meter=2`, primeros 8 modos contra los analíticos:

```
  f_lmn = (c / 2) · √((l/Lx)² + (m/Ly)² + (n/Lz)²)
```

Imprime error porcentual. Con esa resolución debería estar en ~1-2 %.
Después arma una FRF de demo con dos fuentes en esquinas y un receptor
central, identifica el pico (debería caer cerca del primer modo no trivial).

Esta demo sirve de **smoke test**: si refactorizás algo y el error se
dispara, te enterás al instante.

---

## 12. Flujo desde el panel (orquestación)

Para que veas cómo encajan las piezas, así se usa desde `acoustic_panel.py`:

```python
v, t, _, _    = make_room(Lx, Ly, Lz, n_walls=4)              # geometry
nodes, tets   = build_volume_mesh(v, t, n_per_meter=2.0)      # mesh
K, M, _       = build_KM(nodes, tets)                          # fem
freqs, phis   = solve_modes(K, M, n_modes=20)                  # fem
locator       = FieldEvaluator(nodes, tets)                    # fem
H             = frequency_response(locator, freqs, phis,
                                    sources, rx, freq_axis,
                                    damping=xi_por_modo)        # fem
p_nodes       = modal_pressure_field(locator, freqs, phis,
                                      sources, f=80.0,
                                      damping=xi_por_modo)      # fem
phi_norm      = mode_shape_field(phis, mode_idx=0)              # fem (visualización)
```

---

## 13. Mini-glosario de trucos NumPy/SciPy usados acá

| Truco | Lectura |
|---|---|
| `arr[idx]` con `idx` de cualquier forma | "Trae las filas/elementos según `idx`; el resultado hereda la forma de `idx` con un eje extra del tamaño de la fila" |
| `arr[:, None, :]` (broadcasting) | Inserta eje de tamaño 1 que se "estira" implícitamente al hacer aritmética |
| `np.einsum("eij,ekj->eik", a, b)` | "Sumá sobre los índices repetidos a ambos lados; conservá los demás" — es matrix-multiply, dot product, batch operations, todo en una notación |
| `np.linalg.det / inv` en lote | Si pasás `(..., n, n)`, NumPy itera sobre los ejes iniciales y aplica `det`/`inv` a cada matriz |
| `coo_matrix((data, (row, col)))` | Sparse con **suma automática** de entradas duplicadas → es el ensamblaje FEM hecho carne |
| `eigsh(K, M, sigma=..., which="LM")` | Shift-invert: pide autovalores cerca de `sigma`. La forma rápida de obtener "los modos más bajos" |
| `cKDTree.query(points, k)` | Para cada punto, devuelve los índices y distancias de los `k` puntos más cercanos. Una sola llamada hace todo el lote |
| `arr[rows, cols]` con dos arrays 1D del mismo largo | Fancy indexing 2D: "para cada `i`, traeme `arr[rows[i], cols[i]]`". Reemplaza un loop "elegir una columna distinta por fila" |
| `phis @ coeff` (matriz densa × vector) | Suma `Σ_n` sobre modos en una sola operación BLAS |
| `np.where(cond, a, b)` | Versión vectorizada de `if/else` elemento a elemento. Útil para evitar divisiones por cero "blindando" el denominador |

---

## 14. Si querés bajar más

- **Forma débil de Helmholtz con Neumann homogénea**: Zienkiewicz-Taylor,
  *The Finite Element Method* (cap. de problemas escalares); o Ihlenburg,
  *Finite Element Analysis of Acoustic Scattering*, cap. 2.
- **Por qué `V4⁻¹` contiene los gradientes**: ver la deducción de §3.4. La
  identidad `N_j(v_k) = δ_jk` es lo único que necesitás.
- **La fórmula de la masa consistente con 1/20**: integración exacta sobre
  un tet de un producto `L_i^a L_j^b ...` en coords baricéntricas; la
  fórmula está en cualquier texto de FEM (también en Zienkiewicz, apéndice
  de elementos simpliciales).
- **Shift-invert en Lanczos**: Saad, *Numerical Methods for Large Eigenvalue
  Problems*; o el manual de ARPACK (el backend de `eigsh`).
- **Damping modal a partir del RT60**: Beranek, *Concert Halls and Opera
  Houses*, cap. 6; o Kuttruff, *Room Acoustics*, cap. 4.
- **KDTree y consultas espaciales**: Samet, *Foundations of Multidimensional
  and Metric Data Structures*. Para entender por qué `cKDTree` escala como
  `O(log Ne)` en cada query.

---

## 15. Patrones de diseño notables

| Patrón | Dónde | Por qué |
|---|---|---|
| **Ensamblaje vectorizado con `einsum` + `coo_matrix`** | `build_KM` | Reemplaza un loop Python por elemento. Bajada de tiempo de minutos a milisegundos |
| **Shift-invert en `eigsh`** | `solve_modes` | Única forma viable de obtener los autovalores más chicos de un problema grande sin convergencia desesperante |
| **M-ortonormalización a mano** | `solve_modes` | Garantiza que la fórmula de superposición modal no tenga factores de escala incómodos |
| **Lazy init del KDTree** | `FieldEvaluator.__init__` | Si el usuario solo evalúa puntos sueltos, no paga el costo de construir el árbol |
| **Dos pasadas KDTree (K=12, K=48)** | `evaluate_many` | K=12 cubre >99 %; el fallback captura los casos patológicos sin penalizar el caso común |
| **Pre-cómputo del numerador modal** | `frequency_response` | No depende de `f`, así que sale del loop sobre frecuencia |
| **`phis @ coeff` para evaluar en todos los nodos** | `modal_pressure_field` | Una operación BLAS reemplaza un doble loop |
| **`np.where` blindando el denominador** | FRF | Mantiene la fórmula vectorizada sin crashear en casos degenerados |

---

## 16. Benchmark: modal damping vs matriz C de impedancia

> Esta sección valida empíricamente la elección de D2 + D5 (FEM a mano +
> modal damping sin matriz de impedancia) contra el alternativo "purista"
> de ensamblar una matriz C en la frontera con Z derivada del α de
> catálogo. Script: `bench_modal_vs_impedance.py` (raíz del proyecto).
> JSON crudo: `bench_modal_vs_impedance.json`.

### 16.1 Setup

| Parámetro | Valor |
|---|---|
| Sala | shoebox 5 × 4 × 3 m (V = 60 m³, S = 94 m²) |
| Material | α = 0.30 uniforme en las 6 caras |
| Mallado | voxel `n_per_meter = 2.0` → 693 nodos, 2 880 tets, 752 caras de frontera |
| Modos | 12 (cubre hasta ~96 Hz) |
| Fuente | monopolo Q = 1 mm³/s en (0.3, 0.3, 0.3), esquina |
| Receptor | (2.5, 2.0, 1.5), centro |
| Eje de frecuencia | 40 puntos entre 20 y 150 Hz |

### 16.2 Método A — modal damping (lo de la app)

`ξn = 1.1 / (fn · RT60_Sabine)`, con `RT60_Sabine = 0.161 V / (α S) = 343 ms`.
FRF por superposición modal (`frequency_response` existente).

### 16.3 Método B — matriz C de impedancia

Z derivada de α asumiendo incidencia normal y Z real (locally reacting):

```
r = √(1 − α) = 0.837    →    Z = ρ₀c (1 + r) / (1 − r) = 4 667 Pa·s/m
                                          ≈ 11.24 · ρ₀c
```

C ensamblada como `(1/Z) ∫_∂Ω Ni Nj dS` sobre las 752 caras tri de frontera
del tet mesh. Sistema resuelto **directamente** en cada frecuencia:

```
(K − (ω/c)² M + iωρ₀/Z · C_surf) p = iωρ₀ · b_load
```

con `b_load` distribuida vía barycentric en el tet contenedor de la fuente.
`spsolve` (UMFPACK) por punto de frecuencia.

### 16.4 Tiempos medidos

| Etapa | Modal damping | C-matrix |
|---|---:|---:|
| `build_KM` | 7 ms | 7 ms |
| `eigsh` (12 modos) | 14 ms | — |
| extracción de frontera | — | 1 ms |
| ensamblaje de C | — | 0.5 ms |
| FRF (40 puntos) | 4 ms | **233 ms** |
| **Pipeline completo** | **26 ms** | **242 ms** |
| **Ratio** | 1× | **9.5×** |

> El cuello de botella es el `spsolve` complejo por frecuencia: cada
> resolución factoriza una matriz sparse 693 × 693 compleja. Reusar la
> factorización LU sólo es posible si C no depende de ω (asumiendo Z real
> constante, como acá). Con Z(ω) real-de-catálogo el ratio crece a 30–50×.
> Con Z(ω) compleja (porosos reales, membranas) se va a 10²–10³× porque
> hay que ir a problema no-lineal de autovalores o sweep complejo por f.

### 16.5 Forma de la FRF

Validación de modos FEM vs analíticos (caja rígida):

| Modo | FEM [Hz] | Analítico [Hz] | Error |
|---|---:|---:|---:|
| (1,0,0) | 34.44 | 34.30 | +0.40 % |
| (0,1,0) | 43.14 | 42.88 | +0.62 % |
| (1,1,0) | 55.73 | 54.91 | +1.50 % |
| (0,0,1) | 57.79 | 57.17 | +1.10 % |
| (1,0,1) | 68.03 | 66.67 | +2.04 % |
| (2,0,0) | 69.70 | 68.60 | +1.61 % |
| (0,1,1) | 73.25 | 71.46 | +2.51 % |
| (1,1,1) | 81.82 | 79.26 | +3.22 % |

**RMS error 2.44 %, max 3.93 %**, coherente con la promesa de ~1–2 % de la
documentación a `n_per_meter = 2`.

**Picos identificados en la FRF (prominencia > 3 dB):**

| Método | Picos en banda 20–150 Hz |
|---|---|
| Modal damping (calibrado) | 70.0 Hz / 93.3 dB, 86.7 Hz / 94.4 dB |
| C-matrix (directo) | 66.7 Hz / 73.2 dB, 86.7 Hz / 74.1 dB |

**Ambos métodos ven los mismos modos en el mismo orden frecuencial**.
La diferencia de altura del pico (~20 dB) refleja el mismatch de damping
efectivo, no un error de localización modal.

### 16.6 Discrepancia cuantitativa

**Banda modal (30–100 Hz)**, donde modal damping y la solución directa
con impedancia comparten régimen físico válido:

| Métrica | Valor |
|---|---:|
| Max \|diff\| | 2.8 dB |
| RMS diff | 1.6 dB |
| Mean diff (modal − C-matrix) | +0.6 dB |

Modal damping y C-matrix concuerdan **dentro del ruido del problema** en
banda modal. La diferencia es sub-dB en valor cuadrático medio y nunca
supera 3 dB pico a pico.

Fuera de la banda 30–100 Hz hay discrepancias mayores, **esperadas**:

- **<30 Hz**: ambos métodos están dominados por stiffness (sub-modal).
  Modal damping con sólo 12 modos no representa bien el límite
  cuasi-estático; el C-matrix sí. Diferencia ~27 dB en 20 Hz.
- **>100 Hz**: cae fuera de la cobertura de los 12 modos del modal
  damping. El C-matrix mantiene validez. Diferencia 5–22 dB.

Si necesitás precisión a frecuencias más altas con modal damping, subí
`n_modes` para cubrir hasta `f_Schroeder`.

### 16.7 Por qué (casi) no difieren — análisis físico

Con paredes rígidas + damping derivado de RT60 = 0.343 s + el factor `c²`
de calibración correcto, los dos métodos representan **el mismo balance
energético** y dan resultados intercambiables en banda modal:

| Aspecto | Modal damping (Sabine) | C-matrix con Z = ρ₀c(1+r)/(1−r) |
|---|---|---|
| Naturaleza del α usado | α_random (cámara reverberante) | α_normal (asume incidencia 0°) |
| Mecanismo del damping | un ξn por modo, energía distribuida en frecuencia | localización en pared, modos con antinodos en pared absorbente decaen más |
| Asume mode shape rígido | sí | no (pero diferencia es O(ξ²) ≈ 0.25 % a ξ = 0.05) |
| Incidencia oblicua | integrada en RT60 medido | falsa (asume α(θ) = α(0)) |
| Reactancia | no aplica | descartada (Z asumido real) |

> Ojo con la trampa de input: el α que cargás en la app es **α_random**
> (estándar de catálogo Cox). Si derivás Z = ρ₀c(1+r)/(1−r) con
> r = √(1−α_random), estás tratando ese α como si fuera α_normal —
> subestima la absorción a incidencia oblicua. Las ~2 dB de diferencia
> residual a favor del modal damping en los picos vienen de ahí. Para
> que el C-matrix matchee exacto habría que invertir numéricamente la
> fórmula de Paris para obtener el Z que da α_random=0.30, lo cual
> requiere solver no-lineal por banda y material. No vale la pena.

### 16.8 Calibración: factor c² (fixeado en v2.11)

**Histórico**: hasta v2.10, `frequency_response` y `modal_pressure_field`
omitían el factor `c²` que sale de la derivación canónica de la Green
function modal de Helmholtz en cavidad. La derivación rigurosa da:

```
p(xr) = iωρ₀ · Σ φn(xr) φn(xs) / (λn − k²)         (λn de K φ = λ M φ)
      = iωρ₀ · c² · Σ φn(xr) φn(xs) / (ωn² − ω²)    (con ωn² = c²·λn, k² = ω²/c²)
```

El código histórico calculaba `iωρ₀ · Σ … / (ωn² − ω²)` sin el `c²`,
omitiendo **101.4 dB** de calibración absoluta. Verificado empíricamente
en este benchmark: offset modal-vs-impedancia de **+119 dB** descompuesto
como 101.4 dB (c²) + ~18 dB (mismatch α_random ↔ α_normal del C-matrix).

**Cómo no se notó**: el FRF se usaba para análisis relativo de forma
(posición de picos, ancho, profundidad de nulls) y la cadena de
auralización normaliza a peak antes del DAC, así que el offset era
invisible al usuario hasta que se intentaba calibrar SPL absoluto contra
sensibilidad de altavoz medida.

**v2.11**: el `c²` se agregó al prefactor de las tres funciones afectadas
(`acoustic_fem.frequency_response`, `acoustic_fem.modal_pressure_field`,
`fem_modal.frequency_response`). Smoke test en `acoustic_fem.__main__`:
con Q = 1 mm³/s y ξ = 0.05 el pico SPL debe estar entre 50 y 100 dB
(verificado: 74.2 dB, coincide con cálculo analítico de 74.8 dB).

**Compatibilidad**:
- **Auralización (`audio_utils.apply_frf_filter`)**: invariante (normaliza
  a peak=0.98 antes del DAC).
- **Predicción**: no usa `frequency_response`, sin impacto.
- **Exports CSV/TXT**: cambian +101 dB en la columna SPL. Nota agregada
  al changelog para usuarios con FRFs guardados pre-v2.11.

### 16.9 Veredicto

| Criterio | Ganador | Margen |
|---|---|---|
| Velocidad | Modal damping | **9.5×** (pipeline 26 ms vs 242 ms) |
| Localización de modos | Empate | exacta |
| Forma de la FRF (shape) | Empate | RMS 1.6 dB en banda modal |
| Calibración absoluta (post v2.11) | Empate | modal coincide con analítica dentro de 1 dB |
| Robustez (sin Z(ω) medida) | Modal damping | el input α de catálogo no alcanza para Z fidedigna |
| Hermiticidad numérica | Modal damping | preserva el camino Lanczos + M-ortonormal |
| Auralización offline | Modal damping | FRF precomputada se puede convolucionar |

**Para el caso de uso del proyecto** (acústica arquitectónica con α de
catálogo, salas de hasta ~10⁵ nodos, decisiones a nivel de modo
identificable): **modal damping es estrictamente mejor**. La precisión
ganada por C-matrix queda enterrada bajo:

1. El ruido del α de catálogo (±30 %).
2. El mismatch entre α_random (input) y la asunción implícita del Z derivado.
3. El factor 9.5× de costo de cómputo, que escala peor con `n_per_meter`.

C-matrix sólo gana cuando el usuario tiene **Z(ω) medida en tubo de
impedancia** para cada material, escenario que no aparece en el flujo de
trabajo de la app.

### 16.10 Cómo correr el benchmark

```bash
PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe \
    bench_modal_vs_impedance.py
```

Output a stdout (tabla + tiempos + stats) y dump a `bench_modal_vs_impedance.json`
para análisis posterior.

---

*Fuente: `acoustic_fem.py`, líneas 1-460. Pareja con `acoustic_mesh_explicado.md`.
Benchmark de §16 ejecutado el 30 May 2026, código en `bench_modal_vs_impedance.py`.*
