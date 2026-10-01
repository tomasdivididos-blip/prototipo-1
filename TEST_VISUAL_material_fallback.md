# Test visual — fallback de material no resuelto + aviso + embebido (A/B) y feature 1-2

Cubre lo que el bench headless no toca: que el aviso aparezca en la GUI, que el
f_Schroeder deje de explotar, y el panel «Impedancias…» (sugerencias + hover) de
feature 1-2. Benches verdes de respaldo: `bench_material_fallback.py` 13/13,
`bench_capa0_all` 190/190, `bench_impedance_defaults` 52/52 + wiring 14/14.

## Cómo lanzar

```bash
./run.bat
```

---

## T1 — Aviso fuerte al cargar un .room con material no resuelto (A/B)

Pasos:
1. Abrir `Control Ale.room` (el del profesor, SIN cargar antes la carpeta de materiales custom).
2. Leer el cartel que aparece al terminar de cargar.

| Qué mirar | PASA si… |
|---|---|
| Diálogo de aviso | Aparece un QMessageBox titulado **«Materiales sin cargar»** |
| Texto del cartel | Lista los materiales faltantes (p.ej. «Emplacado del Control Room SMA», «Techo de madera machihembrada y chapa») y dice que esas caras usan **α=0.03** por defecto |

Contraprueba: abrir `test239.room` (materiales resueltos) → **NO** aparece el cartel «Materiales sin cargar».

FAIL: no aparece el cartel aunque falten materiales · aparece con todos resueltos · crash al cargar.

---

## T2 — El f_Schroeder ya no explota por materiales faltantes (A, núcleo del bug)

Pasos:
1. Con `Control Ale.room` abierto (materiales SIN cargar, tras T1), ir a la pestaña Acústica.
2. Calcular f_Schroeder / modos (botón de cálculo de la pestaña).
3. Anotar el f_S mostrado.

| Qué mirar | PASA si… |
|---|---|
| f_Schroeder | Queda en el orden de **~180 Hz** (gable 4.8×3.9×3.1, V≈69), **NO** ~1100 Hz |
| Barra de estado | Muestra el aviso «AVISO: N material(es) no resuelto(s) (…); esas caras usan α=0.03 por default» |

Contraprueba (opcional): cargar la carpeta de materiales custom desde **«Materiales…»** y recalcular → f_S se mantiene en ~180 Hz (Sabine 174 / perturbación 182 coinciden), el aviso desaparece.

FAIL: f_S ~1100 Hz (o cualquier valor > ~300 Hz) con las paredes/techo faltantes · f_S distinto antes/después de cargar la carpeta por más de ~10% (debería ser estable porque el default 0.03 ya daba un número sano).

---

## T3 — Panel «Impedancias…»: sugerencias y avisos (feature 1-2)

Pasos:
1. En la pestaña Acústica, pulsar **«Impedancias…»**.
2. Mirar la lista de superficies.

| Qué mirar | PASA si… |
|---|---|
| Superficie con material de keyword clara (p.ej. «lana», «panel perforado», «membrana») | Fila en **teal** con prefijo **«⟲ sugerido: …»** y el modelo propuesto |
| Superficie con material inespecífico (custom / α plano / sin keyword) | Fila en **ámbar** con **«⚠ sin modelo (elegí a mano)»** |
| Resumen (label teal abajo) | Dice **«N sin modelo específico (elegí a mano)»** con un N ≥ 1 si hay inespecíficos |
| Tooltip al pasar sobre una fila sugerida/avisada | Muestra la justificación (texto del keyword / motivo de inespecífico) |

FAIL: una superficie con keyword clara sale ámbar «sin modelo» · un material custom del usuario recibe modelo automático (debía quedar ámbar) · el resumen no actualiza el conteo.

---

## T4 — Aplicar sugerencias (feature 1-2)

Pasos:
1. En «Impedancias…», pulsar **«Aplicar sugerencias automáticas»**.
2. Observar las filas teal.

| Qué mirar | PASA si… |
|---|---|
| Filas antes teal «⟲ sugerido» | Pasan a **azul** (asignada) con la etiqueta del modelo |
| Filas ámbar «⚠ sin modelo» | **No** cambian (no se tocan) |
| Botón «Aplicar a seleccionadas» | Con una fila sin sugerencia seleccionada, avisa «Las seleccionadas no tienen sugerencia automática…» |

FAIL: aplica modelo a las ámbar · pisa una impedancia ya asignada a mano · no cambia nada al pulsar.

---

## T5 — Hover 3D desde «Impedancias…» (feature 1-2)

Pasos:
1. Con «Impedancias…» abierto, pasar el mouse sobre las filas de la lista.
2. Mirar el visor 3D.

| Qué mirar | PASA si… |
|---|---|
| Cara/parche en el 3D | Se **resalta** la superficie correspondiente a la fila bajo el mouse |
| Al sacar el mouse / cerrar el diálogo | El resaltado se **apaga** |

FAIL: no resalta nada · resalta la cara equivocada · el resaltado queda pegado tras cerrar.

---

## T6 — Portabilidad: el re-guardado embebe los materiales usados (B)

Pasos:
1. Abrir un `.room` que traiga materiales custom embebidos (o cargar la carpeta custom desde **«Materiales…»** y asignarlos).
2. Guardar el `.room` (Guardar / Guardar como).
3. Reabrir el `.room` guardado SIN volver a cargar la carpeta (simula otra máquina).

| Qué mirar | PASA si… |
|---|---|
| Al reabrir | **NO** aparece «Materiales sin cargar» (los customs viajaron embebidos) |
| f_S / absorción | Igual que antes de cerrar (α real de los customs, no 0.03) |
| Si falta embeber algo | La barra de estado avisa «Aviso: no se pudo embeber N material(es) (…)» (no se pierde en silencio) |

Contraprueba: un `.room` con un material asignado que no está ni en lib ni embebido → al guardar, la barra avisa el material que no se pudo embeber.

FAIL: el `.room` reabierto muestra «Materiales sin cargar» pese a haber tenido los customs · `embedded_materials` vacío en el JSON aunque se usaron customs · pérdida silenciosa (sin aviso) de un material no embebible.

---

## T7 — Aplicar sugerencias NO dispara el f_Schroeder (feature 1-2 etapa 2, el bug reportado)

El clasificador ahora elige el TIPO de impedancia por la FORMA del α y ajusta los params para reproducir el α de catálogo; si ningún modelo lo logra (o el α es plano) cae a β real (α exacto). Antes, aplicar sugerencias metía modelos cuyo α contradecía el catálogo (membrana con α≈0 en las paredes) y el f_S saltaba a ~1135 Hz.

Pasos (con `Control Ale.room` y sus materiales resueltos):
1. Abrir «Impedancias…».
2. Pulsar «Aplicar sugerencias automáticas».
3. Cerrar el diálogo. Calcular f_Schroeder.
4. «Calcular FEM» (modos).

| Qué mirar | PASA si… |
|---|---|
| Techo madera+lana+chapa (pico grave) | Sugerencia teal **«⟲ sugerido: membrana…»** (la forma del α elige membrana, no poroso) |
| Emplacado SMA (α plano ~0.2) | Fila **gris «usa el material»** (β real); el hover explica «el modelo no reproduce α → β real (α exacto)» |
| f_Schroeder tras «Calcular FEM» | Queda **~180-215 Hz**, NO ~1135 |
| Barra de estado / xi | El amortiguamiento no colapsa (ninguna cara queda casi rígida) |

Contraprueba: sin aplicar sugerencias, el f_S por materiales ya daba ~188; aplicar no debe empeorarlo a >300.

FAIL: f_S ~1135 (o >300) tras aplicar + FEM · el Techo sale poroso con α invertido (sube con f) · el Emplacado recibe una membrana con pico espurio en vez de β real · cualquier cara con material resuelto queda con absorción ~0.

Respaldo headless: `bench_impedance_defaults.py` 32/32 (incluye el invariante «el amortiguamiento no colapsa» para los 4 materiales reales), `bench_impedance_defaults_wiring.py` 14/14, `bench_capa0_all` 190/190.
