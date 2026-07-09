# Prototipo 1 — Modelador de Recintos 3D
## Guía de instalación y uso

---

## Requisitos del sistema

- Windows 10 / 11 (64-bit)
- Tarjeta gráfica compatible con OpenGL 2.1 o superior (cualquier GPU de los últimos 10 años)
- 2 GB de RAM mínimo

---

## Opción A — Ejecutable listo para usar (recomendado)

No requiere instalar Python ni nada más.

1. Ejecutar **`build.bat`** (una sola vez, tarda 2–3 minutos).  
   Esto genera la carpeta `dist\Prototipo1\` con todo incluido.
2. Copiar la carpeta **`dist\Prototipo1\`** completa al pendrive.
3. En la otra PC: doble click en **`Prototipo1.exe`**.

> Los archivos `.room` que guardes van aparte; copialos también al pendrive si los necesitás.

---

## Opción B — Desde el código fuente (requiere Anaconda)

El programa fue desarrollado con **Anaconda Python 3.12** en Windows 11.
**No uses el Python de Microsoft Store** (es un stub que no funciona).

1. Instalar [Anaconda](https://www.anaconda.com/download).
2. Copiar la carpeta `prototipo 1` completa a la PC destino.
3. Abrir **Anaconda Prompt** (o cmd con Anaconda en el PATH) y ejecutar:
   ```
   pip install pyqtgraph PyOpenGL
   ```
4. Doble click en **`run.bat`**.

> El `run.bat` encuentra Anaconda automáticamente y arranca la app.

---

## Atajos de teclado

| Atajo | Acción |
|---|---|
| `Ctrl+Z` | Deshacer |
| `Ctrl+Y` / `Ctrl+Shift+Z` | Rehacer |
| `Ctrl+S` | Guardar (pide nombre la primera vez) |
| `Ctrl+Shift+S` | Guardar como |
| `Ctrl+O` | Abrir archivo `.room` |
| `0` | Resetear vista isométrica |

---

## Controles del mouse (en la vista 3D)

| Acción | Resultado |
|---|---|
| **Rueda** (scroll) | Zoom |
| **Rueda presionada + arrastrar** | Rotar cámara (orbitar) |
| **Shift + rueda presionada + arrastrar** | Rotar solo en azimuth (altura fija) |
| **Click derecho + arrastrar SOBRE UNA PARED** | Inclinar esa pared en vivo |
| **Click derecho + arrastrar en espacio vacío** | Pan (desplazar cámara) |
| **Click izquierdo** | Sin acción |

---

## Controles de los sliders

- **Doble click sobre el slider** → resetea a 0.
- **Doble click sobre el número** → abre cuadro para tipear el valor exacto.
- **Rueda del mouse sobre un slider** → sin efecto (rueda solo scrolea el panel).

---

## Parámetros del recinto

### Dimensiones
- **Ancho (X)**, **Largo (Y)**: dimensiones horizontales en metros.
- **Alto (Z)**: altura del recinto en metros.

### Forma (modo regular — prisma)
- **Cantidad de paredes laterales**: 3 = triángulo, 4 = rectángulo, 6 = hexágono, hasta 12.
- **Estrechamiento del techo**: < 0 el techo es más chico que el piso, > 0 más grande.
- **Torsión del techo**: el techo rota respecto al piso (grados).

### Forma personalizada (dibujar)
Botón **"Dibujar / editar forma..."** → abre un canvas con grilla donde se puede dibujar cualquier contorno:
- Click izquierdo agrega vértices (snapeados a la grilla cada 0.5 m).
- Click sobre el **primer punto** (o Enter) cierra el polígono.
- Click derecho o Esc deshace el último punto.
- Con el polígono cerrado: **drag de vértices** para moverlos, click derecho sobre un vértice para borrarlo.
- Botón "Quitar forma" vuelve al modo de prisma regular.

### Techo y piso
- **Arco del techo**: genera un techo abovedado (barrel-vault). El arco corre a lo largo del eje más largo del recinto.
- **Techo · pitch X / Y**: inclina el techo entero en X o Y.
- **Piso · pitch X / Y**: inclina el piso.

### Inclinación por pared
Un slider por cada pared lateral. Valores negativos = la pared se inclina hacia adentro, positivos = hacia afuera.

Se puede ajustar también **arrastrando con click derecho directamente sobre la pared** en la vista 3D.

---

## Modos de visualización

Combo "Vista" en el footer del panel:

| Modo | Descripción |
|---|---|
| **Aristas** | Malla translúcida azul + aristas violetas (default) |
| **Externa** | Paredes gris claro opacas, sin aristas |
| **Contorno** | Solo las aristas, sin relleno (wireframe) |

Los modos son solo visuales; no se guardan en el archivo `.room`.

---

## Botón "Etiquetas"

Toggle que muestra la **longitud de cada arista** en cajitas blancas sobre la vista 3D, proyectadas correctamente en perspectiva.

---

## Formato de archivo `.room`

Formato nativo del programa. Internamente es **JSON puro**, editable con cualquier editor de texto.

Contiene todos los parámetros del recinto: dimensiones, inclinaciones, forma personalizada, arco, etc.  
**Portable**: se puede copiar al pendrive y abrir en cualquier PC que tenga el programa instalado.

Para asociar doble-click en `.room` con el programa:
1. Click derecho sobre un archivo `.room` → Abrir con → Elegir otra aplicación.
2. Navegar a la carpeta del programa y elegir `run.bat` (o `Prototipo1.exe` si usaste build.bat).
3. Tildar "Usar siempre esta aplicación".

---

## Ejes de referencia (en la vista 3D)

- **X** → rojo
- **Y** → azul
- **Z** → verde

---

## Solución de problemas

### La app no abre / "DLL load failed"
- **No usar el Python de Microsoft Store** (es un placeholder vacío).
- Usar siempre el `run.bat` que detecta Anaconda automáticamente.
- PyQt6 / PySide6 son incompatibles con Anaconda en esta configuración; el programa usa **PyQt5** exclusivamente.

### Vista 3D en negro / sin render
- Actualizar los drivers de la GPU.
- Verificar que la GPU soporta OpenGL 2.1 (`glxinfo` o GPU-Z).

### Archivo `.room` no abre
- Asegurarse de abrir con `run.bat` o `Prototipo1.exe`, no con el Bloc de Notas.
- Verificar que el archivo tenga `"format": "prototipo1.room"` en su interior.

---

## Stack tecnológico

| Librería | Rol | Lenguaje base |
|---|---|---|
| PyQt5 | GUI, ventanas, sliders | C++ (Qt Framework) |
| pyqtgraph + PyOpenGL | Render 3D acelerado | C/C++ (OpenGL) |
| NumPy | Geometría, matrices, proyecciones | C/Fortran (BLAS) |

---

*Última actualización: junio 2026 (v2.12). Para macOS/Linux ver LEEME_MAC.txt.*
