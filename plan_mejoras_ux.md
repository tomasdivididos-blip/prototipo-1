# Plan de mejoras UI/UX — Prototipo 1

Vara: `ux_principios.md`. Cada item cierra con test visual en checklist. Orden
acordado con el usuario: **6 -> (9, 1, 8) -> (2, 5) -> (3, 7) -> 4**.

Estado: NADA implementado. Este .md es para aprobar y ejecutar por tandas.

---

## Tanda 0 - Bug

### 6. Puntos del campo del tamano correcto (escalar con el recinto)
- **Que**: hoy los puntos de la nube de campo 3D se ven enormes en recintos chicos
  (dibujados) y chicos en recintos grandes (CAD importado).
- **Por que (raiz confirmada)**: `Field3DItem.update` / `update_signed` dibujan con
  `GLScatterPlotItem(size=7, pxMode=True)` (`acoustic_viewer.py` ~773 y ~800). Con
  `pxMode=True` el tamano es en PIXELES FIJOS de pantalla, no depende del tamano del
  recinto ni del espaciado de la grilla de puntos. Por eso se ve inconsistente.
- **Como**: pasar el tamano a unidades de mundo ligado al spacing de la grilla del
  campo (por ejemplo, punto aprox = medio spacing), o derivar el size en px del
  spacing. Los puntos quedan del mismo tamano fisico en cualquier recinto y escalan
  al hacer zoom.
- **Consecuencia**: consistencia visual; ningun cambio en la fisica (mismos puntos,
  mismos colores). Riesgo bajo, 1 archivo. Verificar rendimiento con nube densa.
- **Test visual**: recinto chico dibujado + recinto CAD grande -> los puntos se ven
  del mismo tamano relativo y tapan bien la grilla sin ser gigantes.

---

## Tanda 1 - Quick wins

### 9. Ejes X/Y/Z en el render 3D + flechas de origen mas saturadas
- **Que**: dibujar letras X, Y, Z en el 3D, cada una del color de su flecha de origen;
  subir la saturacion de flechas y letras.
- **Por que**: orientacion inmediata (reconocer > recordar); barato.
- **Como**: label 3D por eje junto a la punta de cada flecha de origen; unificar el
  color eje<->letra; subir saturacion de la terna de colores.
- **Consecuencia**: mejor lectura espacial; sin efecto en fisica. Riesgo bajo.
- **Test visual**: las tres letras aparecen, cada una sobre su flecha y del mismo
  color; se leen desde vista iso y planta.

### 1. Ctrl+I importa CAD directo
- **Que**: Ctrl+I abre el file-picker de importar CAD, en vez de abrir el panel de
  "Configuracion de CAD".
- **Por que**: el atajo debe hacer la accion frecuente, no abrir su menu (principio 2).
- **Como**: reasignar Ctrl+I a la accion Importar; el panel de config sigue accesible
  por su boton.
- **Consecuencia**: menos un click en el flujo mas repetido. Riesgo bajo. Verificar
  que Ctrl+I no choque con otro atajo global.
- **Test visual**: Ctrl+I abre directamente el dialogo de archivo; el panel de config
  sigue disponible por su via normal.

### 8. Panel FEM con dos botones + estado
- **Que**: el panel FEM queda con "Calcular FEM" y "Configuracion de FEM"; todas las
  opciones de hoy (numero de modos, npm, h gmsh, motor de mallado) pasan al dialogo de
  configuracion; el estado se muestra debajo del boton de configuracion.
- **Por que**: declutter; config avanzada detras de un boton (principio 3).
- **Como**: mover los controles actuales a un dialogo; dejar solo los dos botones y una
  linea de estado en el panel.
- **Consecuencia**: panel mas limpio, nada se pierde. Riesgo bajo-medio (reconexion de
  senales de los controles movidos).
- **Test visual**: el panel muestra solo dos botones + estado; el dialogo tiene los
  cuatro controles y aplican igual que antes.

---

## Tanda 2 - Medio

### 2. Modo de render Auto / Manual
- **Que**: selector Auto/Manual. En Auto, cambiar de frecuencia (y otros cambios)
  re-renderiza solo. En Manual hay que apretar Enter para renderizar.
- **Por que**: live vs on-demand; en recintos pesados el usuario no quiere que cada
  toque dispare un recalculo. Control del usuario (principio 5) + estado visible (1).
- **Como**: estado Auto/Manual visible; definir la lista de eventos que disparan
  auto-render (incluye cambio de frecuencia); en Manual, Enter dispara.
- **Consecuencia**: control sobre el costo de recalcular. A definir con precision QUE
  eventos entran en "auto" (solo frecuencia? tambien mover fuente?).
- **Test visual**: en Auto, cambiar 15->25 Hz renderiza solo; en Manual, cambiar no
  hace nada hasta Enter; el modo activo se ve.

### 5. Mini-preview del recinto en "Dibujar cortes laterales"
- **Que**: mini ventana que muestra el recinto y resalta CUAL pared se esta dibujando.
- **Por que**: hoy no se entiende que pared es cada corte (reconocer > recordar).
- **Como**: preview chico embebido en el modo de cortes que resalte la pared/plano
  activo mientras se dibuja.
- **Consecuencia**: menos errores al dibujar; medio esfuerzo (widget nuevo + sync con
  el estado del dibujo). Riesgo medio.
- **Test visual**: al entrar al modo, el preview muestra el recinto; al pasar de pared,
  el resalte sigue la pared activa.

---

## Tanda 3 - Atajos (revisar conflictos de binding)

### 3. Alt+Enter borra el campo
- **Que**: Alt+Enter limpia la nube de campo.
- **Por que**: vuelta atras barata (principio 5); reversible (se recalcula).
- **Como**: binding global Alt+Enter -> clear del campo; documentar.
- **Consecuencia**: menor; cuidar que no choque con Enter (render en Manual) ni otro
  atajo. Riesgo bajo.
- **Test visual**: con campo en pantalla, Alt+Enter lo borra; Enter (Manual) lo vuelve
  a dibujar.

### 7. Rotar fuente 90 grados con Ctrl+Alt + click derecho
- **Que**: con el mouse sobre la fuente y Ctrl+Alt apretados, el click derecho rota la
  fuente 90 grados.
- **Por que**: giro rapido en pasos limpios sin arrastrar.
- **Como**: gesto Ctrl+Alt + boton derecho sobre la fuente -> +90 grados.
- **Consecuencia**: el click derecho suele ser menu contextual: hay que resolver el
  conflicto (suprimir el menu bajo Ctrl+Alt, o elegir otra tecla como R). A definir
  el binding antes de codear. Riesgo medio.
- **Test visual**: Ctrl+Alt + click derecho sobre la fuente la gira 90 grados y no abre
  menu contextual; sin Ctrl+Alt el click derecho se comporta como siempre.

---

## Tanda 4 - Grande (EN DISCUSION, ver seccion aparte)

### 4. Botones de camara P / I / L + flechas para cambiar corte/arista
- **Que**: botones Planta / Isometrica / Lateral que fijan (bloquean) la camara; con un
  preset activo, flechas grises semitransparentes al costado del render para cambiar el
  corte lateral (que pared) o la arista desde la que se ve en isometrica. Planta no
  tiene flechas (vista unica desde arriba).
- **Base tecnica**: la camara se maneja por `opts["azimuth"/"elevation"/"distance"/
  "center"]` en `viewer.py` (hay `reset_camera` = iso az45/el30). Los presets son
  triviales: Planta = elevacion 90, Lateral = elevacion 0 con azimuth en {0,90,180,270},
  Iso = el30 con azimuth diagonal. La parte de flechas es la que tiene decisiones.
- **Etapas**:
  - **4a (quick-ish)**: los tres presets de camara P/I/L, con snap y lock (mientras
    esta lockeada, el orbit con mouse queda desactivado; se destraba al re-clickear o
    con un gesto claro). Da valor solo.
  - **4b (grande)**: flechas semitransparentes para ciclar corte lateral / arista iso.
- **Decisiones abiertas**: ver seccion "Discusion item 4".
- **Test visual**: (se define al cerrar la discusion).

---

## Discusion item 4 (a resolver antes de codear 4b)

Preguntas cuya respuesta define la semantica:
1. **Lateral**: la flecha cicla las 4 paredes (frente/fondo/izq/der), camara mirando
   de frente a esa pared? O es un corte real (plano de recorte que muestra el interior)?
2. **Isometrica**: la flecha rota el punto de vista de a 90 grados alrededor del eje
   vertical (las 4 esquinas/aristas)? Solo horizontal, o tambien alto/bajo?
3. **Lock**: mientras hay preset activo, el mouse NO orbita (solo las flechas mueven la
   vista). Se destraba re-clickeando el mismo boton, o arrastrando?
4. **Flechas**: cuantas y donde. Lateral e Iso alcanzarian con izquierda/derecha
   (ciclar). Hace falta arriba/abajo?
