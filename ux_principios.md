# Principios de UI/UX — Prototipo 1

Vara corta y estable para juzgar cada cambio de interfaz. No es teoria de diseno
web: son las heuristicas clasicas (Nielsen) filtradas a lo que es esta app, un
simulador de escritorio en PyQt5 para un usuario experto (acustico), no para el
publico general.

## Las reglas que aplican aca

1. **Visibilidad del estado.** El usuario siempre tiene que saber que esta pasando:
   si el FEM esta calculando, si el render es auto o manual, que frecuencia se ve,
   que modo de dibujo esta activo. Un estado que cambia sin feedback es un bug de UX.

2. **El atajo hace la accion frecuente, no abre el menu de la accion.** Ctrl+I debe
   importar, no abrir un panel desde donde despues hay que apretar "Importar". Un
   nivel de indireccion de menos por cada cosa que se hace 10 veces al dia.

3. **Config avanzada detras de un boton.** Lo que se toca una vez por sesion
   (numero de modos, npm, motor de mallado) no ocupa la vista principal: vive en un
   dialogo "Configuracion de X". La vista principal muestra la accion y el estado.

4. **Reconocer, no recordar.** Si el usuario dibuja "la pared lateral", que vea CUAL
   es (mini-preview, resaltado), que no la tenga que deducir. Cada vez que algo
   obliga a recordar un mapeo mental invisible, es candidato a ayuda visual.

5. **Control y libertad.** Toda accion tiene su vuelta atras barata: borrar el campo,
   salir de un modo (Esc), deshacer. Nada que asuste al explorar.

6. **Consistencia.** Mismos gestos y colores para lo mismo en toda la app: el color
   de un eje es el mismo en la flecha de origen y en su letra; un shortcut de "rotar"
   se comporta igual en todos los paneles; los botones de camara y de modo se ven y
   se ubican igual.

7. **Prevencion de error > mensaje de error.** Bloquear/atenuar lo que no aplica en un
   modo (que no se pueda pedir una vista que no existe, que no se rote algo sin foco)
   es mejor que dejar hacerlo y despues avisar que sali mal.

## Escala de esfuerzo (para priorizar, no para saltear calidad)

- **Bug**: algo ya se ve o funciona mal. Va primero, siempre.
- **Quick win**: 1 archivo, sin decision de diseno pendiente, bajo riesgo.
- **Medio**: toca un flujo (nuevo modo, nuevo estado), hay que definir eventos/bindings.
- **Grande**: interaccion nueva con varias decisiones de semantica. Se parte en etapas
  y la primera etapa ya tiene que dar valor sola.

## No negociable del proyecto

- Todo cambio de UI cierra con **test visual en formato checklist** (lanzar / pasos /
  que mirar con PASA-si falsable / contraprueba / FAIL). Nunca en prosa.
- Los rotulos de UI que se citen en un test se verifican contra el codigo real.
- El nucleo fisico no se toca desde un cambio de UI. Render, camara y atajos son
  presentacion; la simulacion queda igual (mismo campo, mismas frecuencias).
- Sin em dash en textos; sin emoji en el MANUAL.
