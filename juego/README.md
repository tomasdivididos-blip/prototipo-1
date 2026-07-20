# Acústica — Juego

Quiz de acústica de salas para el celular: preguntas conceptuales citadas de los
libros de `referencias/` + ejercicios numéricos parametrizados.

Es una **PWA**: HTML/JS puro, sin build, sin dependencias, sin SDK de Android.
Se instala desde el navegador y funciona offline.

## Probarlo en la compu

Los módulos ES no cargan con `file://`, hace falta un servidor:

```bash
cd "C:/Users/aceve/OneDrive/Escritorio/prototipo 1/juego"
python -m http.server 8777 --bind 127.0.0.1
# → http://127.0.0.1:8777
```

Se juega con el mouse o con el teclado: **A–D** para responder, **Enter** para avanzar.

## Instalarlo en Android

1. Publicar la carpeta `juego/` en cualquier hosting con **HTTPS** (obligatorio: sin
   HTTPS no se registra el service worker y no hay ni instalación ni offline).
2. Abrir la URL en Chrome del celular.
3. Menú ⋮ → **Agregar a pantalla de inicio**.

Queda como una app: ícono propio, pantalla completa, sin barra del navegador, y
anda sin internet.

Para probar desde el celu **en la red local** (sin publicar), `http://` contra una
IP privada no habilita el service worker: se juega igual pero sin instalar ni offline.

## Qué hay adentro

| Archivo | Qué hace |
|---|---|
| `index.html` | Las 3 pantallas: menú, partida, resumen |
| `app.js` | Motor: rondas, puntaje, racha, repaso de errores, barajado |
| `gen.js` | PRNG sembrado + helpers de ejercicios numéricos |
| `banco/conceptuales.js` | Preguntas conceptuales (con cita) |
| `banco/numericos.js` | Generadores parametrizados |
| `banco/index.js` | Áreas + validación de integridad del banco |
| `sw.js` | Service worker (offline). **Subir `VER` al tocar archivos** |

## Cómo funciona

**Preguntas conceptuales**: fijas, con `why` y `src`. El motor baraja las opciones
en cada tirada.

**Ejercicios numéricos**: no son preguntas fijas sino `gen(rng)` que sortea datos
nuevos cada vez → son infinitos y no se memorizan. Los distractores codifican
errores conceptuales concretos (olvidar el factor 2, usar `10·log` en vez de
`20·log`, sumar dB aritméticamente), así que al errar el feedback dice **cuál**
error cometiste, no sólo cuál era la respuesta.

**Repaso**: lo que fallás entra en una cola de errores y sale cuando lo acertás.
El progreso vive en `localStorage` (no hay servidor ni cuenta).

## Agregar contenido

Ver [CONTENIDO.md](CONTENIDO.md): regla de oro de las opciones, workflow para minar
los PDFs con `referencias/_scrape.py`, y cómo escribir un generador numérico.
