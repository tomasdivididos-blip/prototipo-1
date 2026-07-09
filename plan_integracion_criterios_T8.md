# Plan de integración — criterios del doc al scorer (T8)

> Traduce la **§E.1 (síntesis accionable)** de `criterios_room_geom_fuente.md` a cambios
> concretos de código. Estado: **PLAN (no implementado)** — escrito 2026-06-20 tras minar el
> corpus de salas chicas/estudio. El usuario pidió dejar el plan y NO tocar código todavía.
>
> Los 3 cambios son independientes; se pueden hacer en cualquier orden. Recomendación de
> prioridad: **A33 (trivial) → A36 (infra ya existe) → B27 (advisory UI)**.

---

## A33 · Ratio BBC/Rindel en la biblioteca de candidatos — ✅ HECHO (2026-06-20) · esfuerzo BAJO

> **Implementado:** entrada "BBC/Rindel" `(1.40, 1.14, 1.00)` agregada a `RATIO_LIBRARY`
> (`prediction.py`), docstring de `generate_candidates` actualizada (4→5). Validado:
> `generate_candidates` produce 5 candidatos; el BBC/Rindel escala a planta compacta
> (l/w≈1.23) y `predict()` lo rankea en el top-3 sin romper la verificación FEM ni el
> control negativo. (Su `score_uniformity` queda algo más bajo que Louden/Bolt en salas
> muy chicas: es esperable — el bin-spacing premia alargar; la caja BBC optimiza la
> *distribución* LF, no el spacing puro.) **Resto de esta sección = registro histórico.**


**Criterio:** caja de proporciones de buena distribución modal `w/h = 1.14 ± 0.1`,
`l/h = 1.4 ± 0.14` (BBC/Walker; ≈ Rindel/Meissner A `1:1.20:1.45`). Ver A33/A9 del doc.

**Estado del código:**
- `RATIO_LIBRARY` en `prediction.py:123` — lista de 4 dicts (Louden, Bolt, Sepmeyer, Cox).
- `generate_candidates` (`prediction.py:357`) **itera la lista**, escala cada ratio a `v_target`
  con `_scale_ratio_to_volume` y verifica por FEM. Un 5º dict entra automáticamente.

**Cambio (vía mínima, on-architecture):** agregar una entrada
```python
{
    "name": "BBC/Rindel",
    "ratio": (1.40, 1.14, 1.00),   # 1 : 1.14 : 1.40  (alto=1)
    "note": "Ratio BBC/Walker (1:1.14:1.4) ≈ Rindel/Meissner A; caja de buena "
            "distribución modal LF, óptimo en salas chicas de reproducción.",
},
```
**Caveat:** A33 es una *caja de tolerancia*, no un punto. La entrada captura sólo el óptimo.
La vía "fuerte" (no recomendada para empezar) sería un **bonus en el scorer** para candidatos
cuyo `w/h, l/h` caigan dentro de la caja, independientemente del ratio textbook.

**Validación:** `bench_predict_location.py` / `bench_predict.py` — confirmar que el nuevo
candidato aparece, escala bien y rankea de forma sensata (debería quedar arriba en salas chicas).

---

## A36 · Decay modal per-modo pesado por la forma modal — ✅ HECHO (2026-06-20) · esfuerzo MEDIO

> **Implementado:** `compute_xi_per_mode_per_face(freqs, phis, locator, verts, tris, groups,
> g2m, V)` en `face_materials.py`, cableada en `_xi_per_mode_from_faces` (`acoustic_panel.py`)
> con **fallback** a la Sabine global per-banda. Validado en `bench_xi_perface.py`.
>
> **Decisión de alcance (honesta):** se implementó la versión **segura** = absorción efectiva
> **pesada por la presión de frontera** del modo: `α_eff(n) = Σ_g α_g(f_n)·p_g(n)`,
> `p_g(n) = J_g(n)/ΣJ`, `J_g(n) = ∮_g|φ_n|²dA` (evaluada con el `locator` en los centroides de
> los triángulos de cada grupo; los modos son M-ortonormales → `∫_V|φ|²=1`). Propiedades probadas:
>   - **Material uniforme → reduce EXACTO a la Sabine global** (relerr 0.00% en el bench) → no
>     regresiona ningún caso validado.
>   - **Tratamiento asimétrico → diferencia los modos** (spread 6.6× con piso absorbente),
>     acotado entre el límite rígido y el absorbente. Captura el efecto de **alto valor**:
>     qué modos amortigua *dónde* está el tratamiento (B13/Newell/A36).
>
> **NO incluido (diferido):** el efecto "camino libre medio" (axial decae más que oblicuo con α
> *uniforme*, H&A fig 6.38). Requiere la integral de superficie ABSOLUTA (sensible a la
> calibración de evaluación en la malla escalonada) y aporta poco frente a la versión segura.
> **Resto de esta sección = registro histórico de diseño.**


**Criterio:** `T60_modal = 0.04·L_mode/(−ln(1−α))`; un modo decae más lento cuanto **menos caras
carga** → axial (2 caras) > tangencial > oblicuo (6 caras), 0/−3/−6 dB. Ver A36/A17/A18 del doc.

**Estado del código (clave):**
- `compute_xi_per_mode` (`material_library.py:274`) hoy da `ξ_n = 1.1/(f_n·RT60(f_n))` —
  **depende de la frecuencia pero es IGUAL para todos los modos a esa f**.
- `compute_sabine_rt60_per_face` (`material_library.py`) da **un RT60 global por banda** usando
  áreas y α por cara (`FaceMaterialMap`).
- `_xi_per_mode_from_faces` (`acoustic_panel.py:3147`) cablea eso al solver.
- `compute_forced_response` (`modal_metrics.py:67`) **ya acepta `damping` como array per-modo**
  (`xi[:Nm]`), así que el sink está listo.

**Lo que falta (lo nuevo de A36):** pesar el `α` de **cada modo** por qué caras carga **su forma
modal** (energía `|φ_n|²` integrada por cara), en vez de usar el RT60 global de la banda. Es la
generalización **físicamente correcta a FEM** (no necesita etiquetas nx/ny/nz: la forma modal ya
"sabe" qué superficies toca).

**Cambio:** función nueva, p. ej.
```
compute_xi_per_mode_per_face(freqs, phis, groups, g2m, V) -> xi[Nm]
  para cada modo n:
    w_face[c] = Σ_nodos∈cara |φ_n|²   (normalizado a Σ_c w_face = 1)
    α_eff(n)  = Σ_c w_face[c] · α_face[c](banda de f_n)
    T60(n)    = 0.161·V / (S_tot·α_eff(n))     # o Eyring para α alto
    ξ(n)      = 1.1/(f_n·T60(n))
```
Cablearla como alternativa en `_xi_per_mode_from_faces` (flag o reemplazo). El `locator` ya evalúa
φ en nodos; el costo extra es modesto (una integral por cara y por modo).

**Validación (importante):** correr en **shoebox** con absorción uniforme y verificar que reproduce
el orden **axial > tangencial > oblicuo** (≈0/−3/−6 dB de A17) — sumarlo a `bench_modal_metrics.py`.
Comparar `FoM_flat`/`FoM_espacial` antes/después: deberían afilarse los picos axiales.

**Caveat:** con absorción muy NO uniforme (una pared muerta), el orden axial/tang/oblicuo se rompe
—y eso es **deseable** (es justo lo que A36 captura y el RT60 global no). No esperar el 0/−3/−6 dB
fuera del caso uniforme.

---

## B27 · Advisory de colocación de absorbente (poroso λ/4 vs resonante esquina) — ✅ HECHO (2026-06-20) · esfuerzo BAJO (UI)

> **Implementado:** `lf_modal_absorption_hints(groups, g2m, lowest_mode_hz)` en
> `face_materials.py` (función PURA, sin GUI) + hook `_emit_lf_absorption_hints` en
> `_on_face_materials_applied` (`acoustic_panel.py`) que loguea el aviso vía `self._log`.
> Clasifica por `material.category`: porosos = {Porosos, Alfombras, Cortinas} (velocidad),
> resonantes = {Paneles perforados} (presión). **Dispara UN aviso** sólo si: régimen modal
> (modo más bajo ≤160 Hz) + poroso con α bajo en graves cubriendo ≥15% de la superficie +
> CERO paneles perforados/membrana asignados. Validado con materiales reales de `materials/`
> (4 casos: dispara / no dispara con resonante / no dispara fuera de banda modal / no dispara
> con poco poroso). No es física (el solver sigue viendo α ISO 354); es guía educativa.
> Caras sin asignar no cuentan (`_group_to_material_dict` las excluye) → sin falsos positivos.
> **Resto de esta sección = registro histórico de diseño.**


**Criterio:** poroso opera sobre **velocidad** → máx a λ/4 de la pared, ≈0 en esquina/sobre pared;
resonante opera sobre **presión** → va en esquina/máx de presión. Ver B27/B13/B18 del doc.

**Estado del código:** el solver ve `α` de incidencia aleatoria (ISO 354), **ciego a la posición /
velocidad-vs-presión** (ver C24). Por eso B27 **no se puede "calcular"** en el modelo modal sin un
modelo de absorción dependiente del campo (fuera de alcance).

**Cambio realista (advisory, no física):** cuando el usuario asigna un material **poroso** a una
cara con rol de **esquina / pared completa** con intención de control de graves, mostrar un aviso:
> "El poroso es ineficaz en esquina (velocidad ≈ 0 ahí). Para graves usá resonante/membrana, o
> despegá el poroso ~λ/4 de la pared (~1 m @ 100 Hz)."

Se maneja con: (a) taxonomía del material (poroso vs resonante — ¿existe ya el flag en
`material_library`? **verificar**), (b) rol de la cara (¿es esquina? — derivable de `FaceMaterialMap`).

**Caveat:** es **guía**, no cambia el `α` del solver. Honesto declararlo como tal en la UI.

---

## Notas transversales

- **Numeración:** los IDs (A33, A36, B27) refieren a `criterios_room_geom_fuente.md` (v2 cerrado).
- **Orden sugerido:** A33 primero (win rápido y reversible), luego A36 (ganancia de precisión real
  y testeable), B27 al final (toca UI, no solver).
- **Antes de tocar A36:** leer `acoustic_fem_explicado.md` (superposición modal, `FieldEvaluator`)
  y `bench_modal_vs_impedance.py` (ya compara ξ_n Sabine vs impedancia — referencia directa).
- **Decisión del usuario (2026-06-20):** dejar este plan escrito, **no implementar todavía**.
