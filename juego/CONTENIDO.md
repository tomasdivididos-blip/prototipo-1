# Cómo hacer crecer el banco de preguntas

## Estado actual

| Área | Archivo | Conceptuales | Numéricos |
|---|---|---|---|
| Geometría y modos | `banco/geometria.js` | 37 | 6 |
| Fuentes y monitoreo | `banco/fuentes.js` | 37 | 4 |
| Psicoacústica | `banco/psicoacustica.js` | 34 | 0 |
| Numérica y FEM | `banco/numerica.js` | 35 | 2 |

**155 ítems**: 143 conceptuales + 12 generadores numéricos (infinitos, sortean
datos cada vez; viven en `banco/numericos.js`, que reparte sus `area`).

Un archivo por área: para agregar preguntas de un tema, se toca sólo ese archivo.
Cada uno aplica su `area` con `.map()` al final, así que en los bloques no va el
campo `area`.

**Citas pendientes de minar (página fina).** El grueso está citado a nivel
libro/capítulo pero SIN número de página verificado — hay que pasar `_scrape.py`
por cada libro y completar. Psicoacústica se apoya mucho en Zwicker, Moore,
Blauert y Bregman; numérica en Ihlenburg y «FEM for Acoustics»; los dos están sin
verificar página por página.

## Regla de oro de las opciones

**Las 4 opciones van del mismo largo**, con tolerancia de ±5 caracteres
(`SPREAD_MAX` en `banco/index.js`). Todo el razonamiento va en `why`, **nunca**
dentro de la opción correcta.

> Esto no es cosmético. La primera versión tenía la explicación metida en la
> opción correcta: en 24/24 preguntas la correcta era la más larga (241 vs 48
> caracteres) y en 22/24 era la «B». Se sacaba 100% con «elegí la más larga o
> elegí B», sin saber nada de acústica.

Para emparejar, **agregá contenido real al distractor — nunca relleno**. Un
distractor inflado con paja se nota y se convierte en un tell nuevo; uno más
desarrollado es además un mejor distractor. El motor baraja las posiciones, así
que `ans` puede quedar en cualquier índice.

Hay dos validadores equivalentes:

```bash
python check_banco.py       # desde consola, sin navegador (con -v lista todo)
```
```js
window.__auditarBanco()     // en la consola del navegador, sobre el banco cargado
```

Los dos miden lo mismo: spread por pregunta, y cada cuánto la correcta gana por
un margen visible (≥3 caracteres) sobre la segunda más larga. `check_banco.py` te
imprime, por cada pregunta despareja, cuántos caracteres le faltan a cada opción
para emparejar — muy cómodo para corregir.

Detecta: ids duplicados, áreas inválidas, `ans` fuera de rango, opciones
desparejas (spread > 5) y sesgo de largo agregado (la correcta es la más larga
mucho más seguido que 1/4 de las veces).

Sobre `sesgoLargo`: con spread ≤ 5 el «más larga» suele ser un empate técnico, así
que un valor algo arriba de 1/4 no preocupa. Lo que importa es que no haya
`problemas`.

## Citas: no inventar páginas

`src` sólo lleva capítulo o página **si se verificó contra el PDF**. Si sólo sabés
el libro, poné el libro solo. Una cita inventada es peor que ninguna: en una tesis
te la van a chequear.

Los PDFs **no están en git** (`.gitignore`: copyright + 1,5 GB). Están sólo en
`referencias/` en la máquina local → **minar no se puede hacer desde el celular**.
Desde el celu sí podés jugar, corregir redacción y tocar código.

## Workflow para minar un libro

```bash
cd "C:/Users/aceve/OneDrive/Escritorio/prototipo 1/referencias"
PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe _scrape.py "<glob>" "<regex keywords>" [pag_ini] [pag_fin]
```

`_scrape.py` usa `pdftotext` y muestra sólo las páginas que matchean: ~10× más
barato que `Read` sobre el PDF (que renderiza cada página como imagen).

1. Correr con keywords **angostas** (las anchas devuelven 60 páginas y se come el contexto).
2. Leer las páginas que devuelve; anotar el número de página **del PDF**.
3. Escribir la pregunta en `banco/conceptuales.js` con `src: "Libro, cap. X (p. NNN)"`.
4. Marcar el libro en la tabla de arriba.

Si no devuelve nada → PDF escaneado sin capa de texto → ahí sí `Read`/OCR.

Ver `referencias/_indice.md` para el triaje de relevancia por libro (T1–T5) y las
keywords sugeridas.

## Agregar un ejercicio numérico

En `banco/numericos.js`. Cada distractor codifica **un error conceptual concreto**,
no ruido — es lo que permite que el feedback diga «tu error fue X»:

```js
{
  id: "num-loquesea",
  area: "geometria", cat: "Modos", dif: 2,   // dif: 1..3 → ●/●●/●●●
  gen(rng) {
    const L = rnd(rng, 3, 7, 0.1);
    const f = C / (2 * L);
    const o = opciones(rng, f, [
      { v: C / L,       err: "Te olvidaste el factor 2: λ = 2L, no L." },
      { v: C / (4 * L), err: "λ = 4L es tubo cerrado-abierto." },
    ], "Hz", 1);
    return {
      q: `Sala de ${dato(L, "m", 2)}. ¿Modo axial fundamental?`,
      opts: o.opts, ans: o.ans, errs: o.errs,
      why: pasos(`<code>f = c/(2L)</code>`, `<b>f = ${fmt(f, 1)} Hz</b>`),
    };
  },
}
```

`opciones()` descarta sola las trampas que colisionan con la correcta al redondear
y rellena hasta 4 si hace falta. **Cuidado con distractores absurdos**: el de
Schroeder invertido da ~37 kHz y se descarta sin pensar, lo que regala la pregunta.
Si un distractor da un valor imposible, buscá un error más plausible.

## Tests

Servidor local (los módulos ES no andan con `file://`):

```bash
cd "C:/Users/aceve/OneDrive/Escritorio/prototipo 1/juego"
python -m http.server 8777 --bind 127.0.0.1
```

En la consola del navegador, ejercitar todos los generadores:

```js
const { NUMERICOS } = await import('/banco/numericos.js');
const { mulberry32 } = await import('/gen.js');
for (const g of NUMERICOS) for (let i = 0; i < 200; i++) {
  const r = g.gen(mulberry32(i));
  console.assert(r.opts.length === 4 && new Set(r.opts).size === 4, g.id, 'opts');
  console.assert(r.errs[r.ans] === null, g.id, 'errs[ans]');
  console.assert(!/NaN|undefined/.test(r.opts.join()+r.q+r.why), g.id, 'NaN');
}
```

`banco/index.js` además valida ids duplicados, áreas inválidas y `ans` fuera de
rango al cargar: mirá la consola.

## Al tocar cualquier archivo: subir la versión del service worker

`sw.js` cachea todo con `const VER = "acu-v1"`. Si no la subís, el celular sigue
sirviendo la copia vieja y no vas a ver tus cambios. Bumpear a `acu-v2`, `v3`…
y agregar los archivos nuevos al array `ASSETS`.
