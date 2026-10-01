# Plan: impedancia por default por material (link α → modelo de impedancia)

Estado: PLANEADO (30 Sep 2026). NO implementado. Implementar DESPUÉS del batch 3+4+5
(rename a «Impedancias», mover parches confinados, hover de α en parches).

## Objetivo
Cuando el usuario elige un material (α) por cualquier vía (preset, manual, carga de
catálogo), la superficie ya trae un modelo de impedancia con parámetros constructivos,
visible y EDITABLE en el panel «Impedancias» (ex «Construcción de pared»). Los
parámetros no especificados se estiman. Solo se asigna modelo cuando el material es
CLARAMENTE identificable por su nombre/descripción; los inespecíficos quedan SIN modelo
y el panel avisa que hay que elegirlo a mano.

## Restricción de partida (catálogo ABIERTO)
El catálogo no es fijo: el usuario carga sus JSON. Cada material = `name` + `category` +
`description` (texto libre) + α por banda. NO hay campos estructurados de
espesor/densidad/tipo constructivo; eso solo aparece a veces en el nombre ("lana de
vidrio, 40 mm, 70 kg", "corcho 30 mm"). Por eso el mapeo es **keyword-driven** (palabras
clave del nombre/descripción), NO por nombre exacto ni por forma-del-α.

## Criterio (decisión del usuario, 30 Sep 2026)
- Asignar modelo SOLO si el nombre/descripción tiene keywords que indican un tipo
  constructivo claro → se estima "con derecho" (respaldo textual).
- INESPECÍFICOS → SIN modelo + aviso en el panel «Impedancias». Son inespecíficos:
  (a) materiales cargados por el usuario (category "Personalizado" o filename fuera del
  catálogo base), (b) α plano / porcentaje fijo de absorción, (c) sin keyword reconocible.
- Re(β)=α SIEMPRE exacto (amortiguamiento, sin regresión). La reactancia (Im β,
  corrimiento de fₙ) SOLO aparece cuando el keyword justifica un modelo real. NO revierte
  el hallazgo M1 (que era α-shape → Miki extrapolado ciego): acá la reactancia tiene
  evidencia constructiva EXPLÍCITA en el nombre. Igual queda etiquetada "estimada" y
  editable.

## Tabla de mapeo keyword → modelo + params
Keywords normalizados (sin acento, minúsculas) sobre nombre+descripción:

| keywords | modelo | params estimados | refs |
|---|---|---|---|
| lana (vidrio/roca), fibra, fieltro, espuma, poliuretano, melamina, poroso, "acoustic foam" | porous (Miki) | σ de `sigma_from_alpha`; espesor "NN mm" del nombre o 50 mm; air_gap del nombre o 0 | Cox&D'Antonio 5-6; Bies&Hansen (σ↔densidad) |
| alfombra, moqueta, carpet | porous fino | espesor del nombre o 10 mm; σ alto (~50 k) | Cox 5-6 |
| cortina, drapeado, terciopelo, tela (colgada) | porous + air_gap | espesor tela + cámara típica (nombre o 50 mm) | Cox 5-6 |
| corcho | porous denso | espesor del nombre | Aygun |
| panel perforado / perforated / ranurado / slotted | perforated (Maa) | t/d/ratio del nombre si están, si no típicos; cavidad del nombre o 50-100 mm; f₀ chequeado vs pico de α | Maa 1998; Cox 7 |
| microperforado / mpp | perforated (micro, d<1 mm) | ídem, d<1 mm | Maa 1998 |
| membrana / panel (yeso/madera) sobre cámara / placa / diafragmático / drywall / pladur | membrane | m = espesor×densidad (yeso ρ≈800, madera ρ≈600 kg/m³) si parseable, si no de f₀=60/√(mD); cámara del nombre | Cox 6; Fuchs |
| helmholtz / resonador / botella | helmholtz | SOLO si trae dimensiones explícitas; si no, NO asignar (subdeterminado) | Cox 8 |
| hormigón, concreto, ladrillo, vidrio, baldosa, cerámica, mármol, piedra, yeso pintado liso, pintura, metal, madera maciza/piso, agua, audiencia/público | rigid/resistive (β real) | ninguno (sin reactancia) | — |
| (ninguno) / α plano / usuario | SIN modelo | — | avisar en el panel |

## Detección de "inespecífico"
- α plano (porcentaje fijo): `std(α_bands)/mean < 0.15` y sin keyword → sin modelo.
- Origen usuario: `category == "Personalizado"` o filename fuera de la carpeta base →
  sin modelo (regla dura del usuario: los materiales cargados por él no llevan modelo,
  aunque el nombre tenga keyword).
- Sin keyword reconocible → sin modelo.

## Estimación de parámetros (reglas)
- Espesor: regex `(\d+([.,]\d+)?)\s*(mm|cm)` en nombre+descripción.
- Densidad: regex `(\d+)\s*kg` → para membrana m = t·ρ.
- σ poroso: `imp.sigma_from_alpha` (ISO 9053 equivalente, ya existe). Si el ajuste es
  malo (residual alto) pero el keyword dice poroso → σ típico por densidad
  (Bies&Hansen) y marcar baja confianza.
- Cavidad/air_gap: del nombre ("+ cámara NN mm") o default por tipo.
- Cada spec se marca con origen "auto (estimado del material)" y queda EDITABLE.

## Wiring (cómo aparece y entra a la física)
- Nuevo módulo `impedance_defaults.py` (numpy puro, D0): `default_spec_for_material(mat)
  -> spec|None` (keyword match + estimación) e `is_nonspecific(mat) -> (bool, motivo)`.
- Mapa SEPARADO en el panel: `_material_default_spec {clave -> spec}` (NO el
  `_construction_map` de construcciones manuales). Se puebla al asignar materiales
  (`_on_face_materials_applied`, `apply_zone_materials`, presets), sin pisar
  construcciones manuales. Se MUESTRA en el panel «Impedancias» como sugerencia editable
  (distinto color/etiqueta "auto"); al editarla, se promueve a construcción manual
  (entra al `_construction_map`).
- Física: Re(β)=α ya entra siempre por el camino material. La reactancia del default
  entra SOLO donde hay spec keyword-driven (reemplaza la Im opt-in de Miki de
  `_material_surface`, que era ciega). Los inespecíficos = β real (como hoy con la
  reactancia auto apagada).
- Aviso en el panel «Impedancias»: "N materiales sin modelo específico (usan β real).
  Asigná una impedancia a mano si querés su reactancia."

## Validación / bench
- `bench_impedance_defaults.py`: keyword→modelo correcto (tabla), inespecífico→None+motivo,
  parsing de espesor/densidad (mm/cm/kg), material duro NO recibe reactancia, material de
  usuario (Personalizado) → sin modelo aunque el nombre tenga keyword.
- No-regresión: Re(β)=α exacto (ya cubierto por W3/W6 de bench_capa0_wiring).
- Honestidad: el corrimiento de fₙ del default se muestra en la tabla de modos (5c) con la
  fuente "auto (estimado)".

## Fuera de alcance
- No inventa params de Helmholtz (subdeterminado) salvo dimensiones explícitas.
- No usa la forma-del-α para ELEGIR modelo (solo para validar σ del poroso).
- No toca el solver ni el ensamblaje FEM.

---

## ETAPA 2 (1 Oct 2026) — selección por forma del α + ajuste de params (IMPLEMENTADA)

**Motivo (bug real, Control Ale.room):** la etapa 1 (keyword-only, params del
nombre) producía modelos cuyo α CONTRADECÍA el catálogo. Al APLICAR sugerencias,
el α del modelo reemplaza al medido; en los materiales del profesor los modelos
daban α≈0 en las paredes (membrana del «Emplacado» con Re(β)≈0) y forma invertida
en el techo (poroso Miki para un absorbedor de pico grave) → el amortiguamiento
colapsaba → RT explotaba → **f_S 188 → 1135 Hz**. Ver
[[bug-material-no-resuelto-rigido]] y el diagnóstico en `auditor_contexto.md`.

**Decisión del usuario:** "el plan era para elegir qué modelo le toca a cada α".
Se REVISA la regla etapa-1 "keyword-only, sin mirar la forma del α": ahora la
FORMA del α elige el TIPO y los PARAMS se AJUSTAN para reproducir el α.

**Diseño (en `impedance_defaults.py`):**
- Objetivo de ajuste = Re(β) a incidencia NORMAL (θ=0), que es LO QUE USA el kernel
  de perturbación (`compute_xi_shift_with_impedance`) y fija el RT/f_S. El blanco
  es `beta_from_alpha_random(α_cat)` (idéntico al camino de material). Ajuste en
  β-space = barato (sin integral de θ) y exacto para el amortiguamiento.
- `_alpha_shape(mat)`: flat (cv<0.30) / low_peak (pico ≤125 Hz que cae) / mid_peak
  / rising / other. La forma + el keyword fijan los TIPOS candidatos
  (`_SHAPE_TYPES`): low_peak→membrana, mid_peak→perforado/membrana, rising→poroso;
  el tipo del keyword se agrega como alternativa.
- `_fit_spec_to_alpha`: `scipy.least_squares` multi-start (grillas chicas + salida
  temprana) ajusta los params del tipo (poroso σ/d/gap; membrana m/D/η; perforado
  t/d/ratio/cavidad) con peso a graves (sub-Schroeder).
- Se elige el candidato de menor residuo que PASA la tolerancia (`_fit_is_acceptable`,
  relativa a la escala de β). Si ninguno reproduce el amortiguamiento, o el α es
  PLANO, cae a **β real (α exacto, sin reactancia)**: no se falsea la absorción.
- Re(β)=α sigue siendo el invariante: o exacto (β real), o bien-ajustado (modelo).
  La reactancia (Im β, corrimiento de fₙ) solo aparece con un modelo que PASA.
- Cacheado por (nombre, categoría, α). `classify_material` conserva la etiqueta
  fina (cork/carpet/…) si la forma no cambió el tipo.

**Resultado (Control Ale, sugerencias aplicadas):** Techo→membrana ajustada,
Emplacado→β real (plano), mármol→β real → **f_S = 215 Hz** (vs 1135). xi no
colapsa.

**Validación:** `bench_impedance_defaults.py` reescrito al nuevo contrato (32/32):
parsers + caminos sin-modelo intactos; recuperación por ORÁCULO (α generado de un
modelo conocido → recupera tipo + damping-match); selección por forma
(rising→poroso, low_peak→membrana aun con keyword poroso, plano→β real); e
INVARIANTE anti-bug: el Re(β) efectivo reproduce el del catálogo en graves para
los 4 materiales reales (nunca colapsa). `bench_impedance_defaults_wiring` 14/14,
`bench_capa0_all` 190/190 sin regresión. Ref: Cox & D'Antonio cap. 5-7.

**Pendiente/limitaciones:** (a) materiales SIN keyword con forma resonante clara
siguen quedando inespecíficos (no se propone modelo por forma pura, conservador);
extensión futura. (b) el ajuste del Techo mueve el pico de 63→125 Hz (membrana
simple no captura exacto un compuesto); el β en graves sí matchea. (c) FALTA test
visual del usuario (T7 en `TEST_VISUAL_material_fallback.md`).
