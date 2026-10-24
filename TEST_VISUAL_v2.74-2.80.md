# Test visual — tanda v2.74 a v2.80 (plan de 8 consignas)

Lanzar:

```bash
cd "C:/Users/aceve/OneDrive/Escritorio/prototipo 1" && "C:/Users/aceve/anaconda3/python.exe" main.py
```

Preparación general: abrí un `.room` shoebox (o armá una caja) con al menos una
fuente, asigná materiales y **Calcular modos (FEM)** una vez. Rótulos verificados
en código entre paréntesis.

---

## Item 6 — el campo 3D ya no se lava a blanco (v2.74)
- [ ] Pestaña Acústica, abajo «Campo 3D»: combo **Campo** en «Forma modal», subí
  **Resolución campo 3D (10–100)** a 60-80 y mirá un modo.
- [ ] PASA-si NO se blanquea (se ve la estructura azul/rojo del modo aun con muchos
  puntos) y SE VE ADENTRO del volumen. FAIL si todo el centro queda blanco/lavado.
- [ ] Contraprueba: bajá la resolución a 15 → sigue viéndose nítido (no cambia el
  criterio, solo el detalle).

## Configuración de render (v2.74)
- [ ] Botón **«Configuración de render…»** (sección Campo 3D). PASA-si abre el
  diálogo **«Configuración de render 3D»** con **Resolución (10–100)**,
  **Saturación (1–15)**, grupos **«Forma modal (color por signo)»** y **«Campo de
  presión |p|»**.
- [ ] Subí **Saturación** a 12 y Aceptar → el modo/campo queda más saturado; bajala
  a 2 → más tenue. PASA-si cambia visiblemente.
- [ ] Forma modal: cambiá **Máximo (+)** a otro color y tildá **«Cero transparente»**
  → los lóbulos positivos toman ese color y el centro (0) desaparece.
- [ ] Campo de presión (combo Campo en «Presión |p|», con una fuente): destildá
  **«Arcoíris (por default)…»**, elegí 3 colores, tildá **«Mínimo transparente»** →
  usa tus colores y el |p| bajo se vuelve invisible.
- FAIL: no abre el diálogo, o ningún control cambia el render.

## Item 7 — Δfₙ en el combo «Modo» al 1er cálculo (v2.74 tabla + v2.81 combo)
- [ ] Asigná una **impedancia** con reactancia (botón «Impedancias…», p.ej.
  membrana/perforado) y **Calculá modos (FEM) UNA vez**.
- [ ] Mirá el combo **«Modo»** (en «Visualización Modal»): PASA-si cada modo ya
  muestra la **f efectiva con el Δ** (p.ej. `12.56 Hz (Δ+0.50)`) en el PRIMER
  cálculo. FAIL si muestra la f rígida sin Δ hasta recalcular FEM una 2da vez.
- [ ] Contraprueba 1: también en la tabla **«Ver modos»** (columna Δfₙ) coincide.
- [ ] Contraprueba 2: con impedancias de β real (sin reactancia) no hay Δ (correcto).

## Item 5 — lista de fuentes editable estilo EASE (v2.75)
- [ ] Grupo **«Fuentes omnidireccionales»**: PASA-si la lista es una **tabla** con
  columnas **[check] · Fuente · X · Y · Z** (no el texto plano de antes).
- [ ] Cambiá un valor **X/Y/Z** con la **rueda del mouse** sobre la casilla o
  escribiéndolo → la fuente se mueve en el visor en el acto. PASA-si se mueve.
- [ ] Destildá el check de una fuente → queda silenciada (gris) y la excluyen
  FRF/campo. Contraprueba: volvé a tildarla → vuelve.
- FAIL: la lista no es tabla, o editar X/Y/Z no mueve la fuente.

## Item 4 — orden de capas del visor (v2.75)
- [ ] Botón **«👁»** (abajo-izquierda del visor) → PASA-si el menú ahora incluye
  **«Paredes»** y, abajo, **«Orden de capas…»**.
- [ ] Destildá **«Paredes»** → el recinto (mesh + aristas) se oculta; volvé a tildar
  → reaparece.
- [ ] «Orden de capas…» → diálogo **«Orden de capas (prioridad de dibujo)»** con la
  lista (Fuentes/Receptores/Muebles/Parches/Paredes/Planos) y **Subir/Bajar**.
  Movés una capa, Aceptar. PASA-si la lista reordena (el efecto de dibujo es
  best-effort: puede notarse poco por el límite GL de oclusión, está avisado).
- FAIL: no aparece «Paredes» ni «Orden de capas…».

## Item 3 — multi-receptor: optimizar sobre receptores elegidos (v2.76)
- [ ] Grupo del receptor: PASA-si los puntos de escucha son una **tabla** con
  **[check] · Receptor · X · Y · Z** editables. Botón «Agregar» suma un receptor en
  la posición del cursor.
- [ ] Agregá 2-3 receptores, editá sus X/Y/Z, destildá uno.
- [ ] Abrí **«Optimización de fuentes»** → «Evaluar» o «Optimizar». PASA-si la
  optimización/evaluación corre sobre los receptores ACTIVOS (los tildados), no
  sobre una zona genérica. Contraprueba: destildá TODOS → usa la zona fina de
  siempre (sin error).
- [ ] Doble click en el nombre de un receptor → mueve el cursor del receptor ahí.
- FAIL: la lista no es tabla, o el check no cambia qué se optimiza.

## Item 2 — auto-cálculo (v2.77)
- [ ] Sección FRF: PASA-si existe el checkbox **«Recalcular automáticamente
  (FRF + campo)»** (arranca apagado). Calculá modos y una FRF una vez.
- [ ] Tildá el checkbox. Cambiá una **impedancia**, un **α de material**, o la
  **posición de una fuente** (en la tabla). PASA-si la **FRF y el campo se
  recalculan solos** tras ~0.5 s, sin apretar «Calcular FRF».
- [ ] Verificá que NO se dispara solo el **decaimiento**, ni la **optimización**, ni
  la **predicción** (siguen a demanda).
- [ ] Contraprueba: destildá → al cambiar algo ya no recalcula solo.
- FAIL: no recalcula al cambiar, o recalcula decay/optimización solos.

## Item 1 — mapa de reflexiones por pared (v2.78 núcleo + v2.79 GUI)
- [ ] Botón **«Mapa de reflexiones…»** (sección FRF). PASA-si abre
  **«Mapa de reflexiones (energía por pared)»** con un **selector de banda de
  octava**, una **tabla** de paredes ordenada por energía (dB rel, la que más
  refleja en rojo) y el checkbox **«Pintar en 3D»**.
- [ ] Cambiá la **banda** → la tabla y los colores de las paredes cambian.
- [ ] Con «Pintar en 3D» tildado → las paredes del visor se colorean (rojo = la que
  más refleja hacia el receptor, azul = poco). Mové el receptor/fuente y reabrí →
  cambia qué pared manda más.
- [ ] Contraprueba: cerrá el diálogo → el pintado se limpia del visor.
- FAIL: no abre, o la tabla/pintado no cambian con la banda.

## Item 8 — barra de menú (v2.80)
- [ ] PASA-si arriba de la ventana hay una **barra de menú**: Archivo, Edición,
  Insertar, Ver, Herramientas, Calcular, Configuración, Ventana, Ayuda.
- [ ] **Archivo → Abrir…/Guardar** (Ctrl+O / Ctrl+S) funciona igual que los botones.
- [ ] **Calcular → Calcular modos (FEM) / Calcular FRF / Mapa de reflexiones…**
  dispara lo mismo que los botones.
- [ ] **Insertar → Fuente…** agrega una fuente; **Ver → Ir a Acústica** cambia de
  pestaña; **Configuración → Tema** cambia el tema; **Ayuda → Acerca de…** muestra
  el about.
- [ ] Los paneles y botones de siempre SIGUEN funcionando (el menú es adicional).
- FAIL: falta la barra, o alguna acción del menú no hace nada.

---

Marcá PASA/FAIL y, si algo falla, anotá qué viste; con eso lo ajusto.
