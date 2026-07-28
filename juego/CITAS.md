# Registro de verificación de citas (scraping de tesis)

Verificación de las fuentes del banco contra los PDF de `referencias/`, con
`referencias/_scrape.py` (pdftotext filtrado) + `pdftotext -layout` sobre el
índice. **Página = página impresa del libro** (no la del PDF), salvo aclaración.

Aplicado con `apply_citas.py` + `apply_citas2.py` (mapean id → cita, para no
romper con los `src` repetidos). **101 de 155 ítems** tienen página o sección
verificada.

## Libros verificados a nivel página/sección

| Libro | En carpeta | Método | Notas |
|---|---|---|---|
| Everest, *Master Handbook of Acoustics* | ✅ | página impresa | **offset 25**: impresa = pág. PDF − 25 (verificado: "Mean Free Path 353" en índice ↔ PDF 379) |
| Cox & D'Antonio, *Acoustic Absorbers and Diffusers* | ✅ | sección + pág. del índice | caps. 5 (porosos, p. 156), 6 (resonadores, p. 196); §§3.4/3.6, 4.4–4.5 |
| Toole, *Sound Reproduction* | ✅ | sección + pág. del índice | §13.2–13.5 (graves/sala), §18.1–18.6 (parlantes) |
| Ihlenburg, *FE Analysis of Acoustic Scattering* | ✅ | sección § | monografía; §1.1, §2.2, §2.3, §3.2 |
| **Zwicker & Fastl, *Psychoacoustics*** | ✅ (escaneado) | **índice leído como imagen** | sin capa de texto → `pdftoppm` + lectura visual; **offset 10**; §§ del contents |
| **Beranek & Mellow, *Sound Fields and Transducers*** | ✅ | capítulo (pág. de inicio por DOI) | cap. 4 (radiación/directividad, p. 129), cap. 6 (parlantes, p. 241), cap. 7 (recintos, p. 289) |
| **Beranek, *Acústica*** | ✅ | página impresa (**offset 8**) | reverberación p. 218; índice de directividad p. 96 |

### Zwicker & Fastl — secciones verificadas (offset 10, índice por imagen)
| Concepto | § | p. |
|---|---|---|
| Enmascaramiento (upward spread) | 4.1 | 62 |
| Premasking / backward masking | 4.4.2 | 82 |
| Banda crítica | 6.1 | 150 |
| Escala Bark (critical-band rate) | 6.2 | 158 |
| JND de nivel (~1 dB) | 7.1.2 | 180 |
| Fon / sonio (loudness) | 8.1–8.2 | 203–205 |
| Integración temporal de sonoridad | 8.5 | 216 |
| Ponderación A / loudness meters | 8.7.3 | 233 |
| Agudeza (sharpness) | 9.1–9.2 | 239 |
| Aspereza (roughness) | 11.1 | 257 |
| BMLD (binaural) | 15.2 | 295 |

### Beranek — SF&T por capítulo (DOI da la pág. de inicio)
cap. 4 Acoustic components (radiación, directividad, baffle, line source) p. 129 ·
cap. 6 Electrodynamic loudspeakers (sensibilidad, impedancia, distorsión) p. 241 ·
cap. 7 Loudspeaker Enclosures (sellada/bass-reflex, puerto) p. 289.
*Acústica*: reverberación (Sabine/Eyring/absorción) p. 218; directividad p. 96.
*Concert Halls* (IACC, ASW/LEV): queda a nivel libro — offset del índice
inconsistente, no se fijó página con confianza.

### Everest — páginas verificadas (offset 25)
| Concepto | pág. |
|---|---|
| Potencia axial/tangencial/oblicuo; nodos | 140 |
| Ecuación de Sabine; V lineal en RT | 159 |
| Absorción total A; Eyring vs Sabine | 160 |
| Absorción del aire (humedad) | 203 |
| Proporciones (Bolt/Louden); formas cóncavas | 276 |
| Cubo / modos degenerados | 284 |
| Frecuencia de corte/crossover (Schroeder) | 325 |
| Bonello Criterion | 348 |
| Mean Free Path | 354 |
| Law of the First Wavefront (precedencia) | 353 |
| Distancia crítica / near-field | 87 |
| LEDE/RFZ | 431 |
| Flutter → filtro peine | 494 |

### Cox & D'Antonio — secciones (índice)
Porous absorption cap. 5 (p. 156) · Resonant absorbers cap. 6 (p. 196) ·
Cámara reverberante §3.4 (p. 84) · Propiedades internas/tubo §3.6 (p. 95) ·
Diffusion/scattering coeff. §4.4–4.5 (p. 130–135) · Absorbers from Schroeder
diffusers §7.2 (p. 230).

### Toole — secciones (índice)
§13.2 Room Modes and Standing Waves (p. 201) · §13.3 Delivering Good Bass in
Small Rooms (p. 216) · §13.3.1 Reducing Energy in Room Modes (p. 217) ·
§13.4 Time and Frequency Domains / EQ (p. 239) · §18.1.1 Point Sources (p. 366) ·
§18.1.2 Line Sources (p. 368) · §18.2 Measuring Loudspeakers (p. 372–376) ·
§18.6 Other Measurements: impedance/sensitivity/phase (p. 418–420).

## Pendiente de verificar página (queda a nivel libro/capítulo)

Están en la carpeta pero su índice no se extrajo limpio; falta una pasada:
**Newell** (*Recording Studio Design*), **Fahy**, **Vorländer**, **Roederer**,
**Barron**, **Ando**, **Hopkins**, y **Beranek *Concert Halls*** (offset del
índice inconsistente).

## No verificables (no están como PDF) → se dejan autor-año / norma

- Libros: **Moore**, **Blauert**, **Kuttruff**, **Kinsler & Frey**, **Bregman**.
- Papers clásicos: Sabine (1922), Eyring (1930), Weyl (1912), Schroeder (1962),
  Haas (1951), Rayleigh, Welti & Devantier (2006), Klippel & Bellmann (2016),
  Peutz (1971), D'Appolito (1983), Bonello (1981), Bolt (1946), Louden (1971),
  Allen & Berkley (1979), Courant-Friedrichs-Lewy (1928), Glasberg & Moore (1990),
  Blauert & Laws (1978).
- Normas (salvo ISO 354, que sí está): ISO 226, ISO 9613-1, ISO 10534, ISO 17497-1,
  ISO 1999, IEC 61672, IEC 60268-16, ITU-R BS.775, ASTM C423, ANSI/CTA-2034, AES-4id.

Estas citas son correctas como referencia; sólo no llevan número de página porque
la fuente primaria no está en `referencias/`.

## Cómo re-correr / ampliar
1. Scrapear: `python _scrape.py "<libro>*.pdf" "<keywords>"` en `referencias/`.
2. Anotar la página impresa (aparece en el texto) o la sección del índice.
3. Agregar la entrada a `MAP` en `juego/apply_citas.py` y correrlo.
4. `python check_banco.py` · `python build_artifact.py` · republicar.
