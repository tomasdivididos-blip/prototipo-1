# Numérica y validez del solver FEM acústico

> Respaldo bibliográfico de las decisiones numéricas de la app: la regla `ppw`,
> el techo de validez `f_max_malla = c/(ppw·h)`, el orden de error P1 = O(h²), y
> el "pollution effect" a alta frecuencia. **NO son criterios de diseño acústico**
> (esos van en `criterios_room_geom_fuente.md`); son la justificación del solver
> y del fix del auto-tuner de malla.
>
> Corpus T6 (minado CERRADO 2026-06-21): Langdon & Chandler-Wilde (2007) §2-4,
> Desmet & Vandepitte (2002) §5, Gallistl & Peterseim (2015) §5. (El libro de
> Ihlenburg 1998 NO está en el corpus — ver §6.) Ver `referencias/_indice.md`.

---

## 1. La ecuación y la estructura del sistema (= la del proyecto)

Helmholtz time-harmonic: `Δu + k²u = 0`, con **wavenumber `k = ω/c`** (proporcional
a la frecuencia). BC de impedancia `∂u/∂n + i·k·u = g`.

Galerkin P1 (hat functions) → sistema lineal **`(A − k²B − i·k·C)·u = f`**, donde:
- `A` = matriz de **rigidez** (∇Nᵢ·∇Nⱼ) = la **K** del proyecto.
- `B` = matriz de **masa** (Nᵢ·Nⱼ) = la **M** del proyecto.
- `C` = matriz de **impedancia de superficie** (∫_∂Ω Nᵢ Nⱼ) = la **C** que el
  proyecto **NO ensambla** (usa damping modal ξₙ en su lugar — decisión D5b).

> El problema modal del proyecto es el caso `g=0`, paredes rígidas (C=0): `K φ = λ M φ`
> con `λ = ω²/c² = k²`. Mismo origen, sin el término de impedancia.
[Langdon & Chandler-Wilde §2.2, ecs. 2.5–2.10]

---

## 2. Estimación de error y la regla `ppw`

**E1. Orden de convergencia P1 = O(h²).** [LCW ec. 2.11]
`‖u − U‖ / ‖u‖ ≤ C·h²`, con `C` independiente de `h` (pero **sí dependiente de k**).
**Asintótico**: vale sólo para `h` suficientemente chico. → justifica D1 (P1, error
O(h²); bajar h a la mitad reduce el error ×4).

**E2. Regla de "elementos por longitud de onda" (`ppw`).** [LCW §2.3; Ihlenburg]
Para resolver la oscilación `e^{ikx}` (período `λ = 2π/k`) hace falta un **número
fijo de elementos por longitud de onda**. Regla de pulgar de la literatura: **~10
elementos/λ** (Ihlenburg, Zienkiewicz). La app usa **`ppw = 6`** (más permisivo,
aceptable para los primeros modos). De ahí el techo de validez:
```
f_max_malla = c / (ppw · h_max)
```
> Esta es **la fórmula del fix del auto-tuner de malla**. El `h_max` (peor tet) define
> la validez; gmsh lo sub-entrega ×1.5 → ver `[[mesh-autotuner-fix]]`.

**E3. Costo crece con k.** [LCW §2.3]
Mantener `ppw` constante con `k` creciente exige `N ∝ k` en 1D (más rápido en 3D).
→ a alta frecuencia el FEM se vuelve prohibitivo (por qué el proyecto vive ≤ Schroeder).

---

## 3. El "pollution effect" (la clave de alta frecuencia)

**E4. Error de polución.** [LCW ec. 2.12; Ihlenburg p.127]
```
‖(u − U)'‖ / ‖u'‖  ≤  C₁·h·k  +  C₂·k³·h²
```
- **1er término `C₁·h·k`** = error de **aproximación**: se controla manteniendo
  `h·k` constante (≡ `ppw` constante).
- **2° término `C₂·k³·h²`** = **pollution**: crece con `k³` **aunque** mantengas
  `ppw` constante. Es el error de **fase** que se acumula y propaga: la longitud de
  onda numérica no es exactamente la física → la solución se "corre".

**Implicación para la app:**
- A **baja frecuencia (régimen modal, k chico)** el término `k³h²` es despreciable
  → los primeros modos salen con ~1–2% de error (lo medido en el bench de la caja).
- A **alta frecuencia** el pollution domina: aunque la malla tenga `ppw=6`, los modos
  altos quedan numéricamente sucios. **Esto es la justificación física del clip B6**
  (`_clip_modes_to_mesh_validity`): descartar modos `f > f_max_malla` no es paranoia,
  es que el pollution los corrió.
- Refuerza el **MDCF / crossover** (`criterios §A.13`): arriba del cruce el modelo
  ondulatorio (FEM) pierde sentido y conviene acústica geométrica.

---

## 4. Mapeo a decisiones del proyecto

| Concepto (LCW/Ihlenburg) | En el proyecto |
|---|---|
| `(A − k²B − ikC)u = f` | K, M, (C no ensamblada → ξₙ modal, D5b) |
| Error P1 = O(h²) asintótico | decisión D1 (P1 sobre P2) |
| `ppw` ~10 (regla) → app usa 6 | `max_solver_frequency`, `f_max_malla` |
| Pollution `C₂k³h²` | razón física del clip de modos B6 |
| Costo `N ∝ k` | por qué se trabaja ≤ Schroeder |
| BC impedancia `Ω_z` → matriz C (Desmet E5) | la C no ensamblada → `ξₙ` modal (D5b) |
| Error geométrico de discretización (Desmet E6) | costo de la malla escalonada (Freudenthal) |
| PG multiescala pollution-free (G&P E7) | alternativa NO usada (se clipea, no se corrige) |

---

## 5. Confirmaciones y extensiones (Desmet & Vandepitte; Gallistl & Peterseim)

### Del *Finite Element Modeling for Acoustics* (Desmet & Vandepitte, ISAAC 2002)

**E5. Sistema y taxonomía de BC — confirma §1 desde una 2ª fuente.** [Desmet §2.3.3]
La forma débil de Helmholtz por residuos ponderados (Galerkin) da
`([K] + jω[C] − ω²[M])·{p} = {Q} + {V} + {P}` — **idéntica** a la `(A − k²B − i·k·C)u = f`
del §1 (K=rigidez, M=masa, C=amortiguamiento; `k=ω/c`). Tres tipos de **condición de frontera**:
- **Presión prescrita** `Ω_p` (Dirichlet) → se impone asignando el valor nodal directo.
- **Velocidad normal prescrita** `Ω_v` (Neumann) → entra como **vector de excitación `{V}`** (RHS).
- **Impedancia/admitancia normal** `Ω_z` → es lo que **genera la matriz `[C]`** (LHS), ensamblada
  `C_ij = ∫_{Ω_z} ρ₀c₀·Aₙ·Nᵢ·Nⱼ dΩ` por cara (admitancia `Aₙ` constante por cara).
> ⇒ Detalla **exactamente la `C` que el proyecto NO ensambla** (decisión D5b: usa `ξₙ` modal en
> vez de la BC de impedancia). Pared rígida = `Ω_z` vacía = `C=0` = el problema modal `Kφ=λMφ`.
> Nota conceptual de Desmet: la `K` se llama "rigidez" por analogía estructural pero **es una
> matriz de movilidad/masa inversa** (relaciona presión con aceleración).

**E6. Doble fuente de error: aproximación + descripción GEOMÉTRICA.** [Desmet §2.4]
Convergencia exige **completitud** de las shape functions (reproducir campo constante + su
gradiente; las P1-hat la cumplen). Además, en geometría compleja una malla de tets/prismas
**no describe exactamente la forma** → además del error de aproximación de presión hay un
**error de discretización geométrica**. → Es la base teórica del costo de la malla **escalonada
(voxelización Freudenthal)** del proyecto: el stair-stepping es justamente ese error geométrico
(ata con `acoustic_mesh_explicado.md` y `[[mesh-autotuner-fix]]`).

### Del *Stable Multiscale Petrov-Galerkin FEM* (Gallistl & Peterseim, 2015)

**E7. Método pollution-free (opción para empujar arriba de Schroeder).** [G&P abstract, §1, §3]
PG **multiescala** que **elimina el pollution** (E4): usa Q1 estándar a una escala **gruesa `H`**
como funciones *trial*, pero las funciones *test* se calculan resolviendo **problemas locales a
una escala fina `h`** (corrección de subescala, à la homogeneización numérica). Con sobre-muestreo
`m ~ log(k)` y `h` chico, el método es **estable y cuasi-óptimo manteniendo `H ∝ 1/k`** (≡ **ppw
constante**) — es decir, **sin** el refinamiento extra `k³h²` que el pollution le impone al Galerkin
P1 (E4). En medios homogéneos las test functions dependen sólo de la config. local de malla →
costo extra ~ `(m·log k)^d`. **Relevancia para el proyecto:** es la alternativa *si alguna vez* se
quisiera resolver arriba de Schroeder sin refinar la malla; hoy el proyecto en cambio **descarta**
los modos sucios (clip B6) y trabaja ≤ Schroeder. Petrov-Galerkin = *trial ≠ test*.

### Del *Validation of an optimization procedure...* (Zhu, Ma, Zhu & Cheng, Applied Acoustics 2006)

**E8. Validación experimental de la optimización FEM de geometría para LF.** [Zhu et al. 2006, §4-5]
Optimizan por **FEM** una modificación de pared (secuencia de profundidades de pozos = difusor
escalonado) para **aplanar la respuesta LF** en salas chicas, y lo **validan con modelos a escala
1:5** (banda real 300-600 Hz ↔ 60-120 Hz a escala). El óptimo FEM mejora la planitud medida.
→ **Respalda empíricamente** el enfoque FEM forma↔respuesta-LF del proyecto (ata C11/C24 de
criterios) y la geometría (splay/difusión) como palanca a baja frecuencia.

**E9. Métrica SRD (planitud con detrend por regresión).** [íd., §3]
`SRD = √(Σ desviaciones² del SPL respecto de la recta de ajuste A+B·f)` sobre la banda. A diferencia
del `FoM_flat` del proyecto (σ respecto de la **media** suavizada), SRD **quita la tendencia lineal**
(recta de regresión) antes de medir la desviación → no penaliza una **inclinación global** de la
respuesta, sólo el rizado modal. **Posible refinamiento de `FoM_flat` (C3 de criterios):** detrend
por regresión en vez de por media. No implementado (anotado en `plan_gaps_criterios.md`).

---

## 6. Estado del minado (T6) — CERRADO (2026-06-21)

- ✅ **Langdon & Chandler-Wilde (2007)** — `ppw`, `O(h²)`, pollution `C₂k³h²` (§2-4, E1-E4).
- ✅ **Desmet & Vandepitte (2002)** — sistema `[K]+jωC−ω²M`, taxonomía de BC, ensamblaje de C,
  error geométrico (E5-E6).
- ✅ **Gallistl & Peterseim (2015)** — PG multiescala pollution-free; `H∝1/k` estable (E7).
- ⊘ **Ihlenburg (1998), libro** — **NO está en el corpus**. El PDF rotulado `Ihlenburg, Finite
  Element Analysis...` es en realidad las lecture notes de **Langdon & Chandler-Wilde**, que citan
  a Ihlenburg como fuente del análisis de pollution. El análisis ya quedó capturado vía LCW (§3).
