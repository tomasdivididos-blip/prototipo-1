# Índice de referencias — criterios geometría ↔ fuentes

> Objetivo: extraer **todos** los criterios de elección/diseño de recintos y su
> acústica (geometría y/o fuentes) → `criterios_room_geom_fuente.md`.
> Triaje por relevancia para NO leer 40 tratados enteros: se leen a fondo los
> papers (T1) y SÓLO los capítulos marcados de los libros (T2/T3).

Leyenda: **T1** lectura completa · **T2** minar capítulos marcados ·
**T3** criterios de salas grandes (mirar selectivo) · **T4** tangencial (consulta puntual) ·
**T5** otra materia (no se mina).

---

## ⚡ CÓMO MINAR (workflow para sesión fresca — LEER PRIMERO)

> Tras un `/clear`, arrancá acá. El objetivo es seguir poblando
> `criterios_room_geom_fuente.md` (§A geometría / §B fuentes / §C combinado /
> §D perceptual) con los libros que faltan, **sin renderizar imágenes** (caro).

**Herramienta:** `referencias/_scrape.py` — usa `pdftotext` (Poppler, ya instalado)
para sacar la capa de texto y mostrar SOLO las páginas que matchean keywords.
~10× más barato que el `Read` de PDF (que renderiza cada página como imagen).

```bash
cd "C:/Users/aceve/OneDrive/Escritorio/prototipo 1/referencias"
PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe _scrape.py "<glob>" "<regex keywords>" [pag_ini] [pag_fin]
```

**Paso a paso por libro:**
1. Correr `_scrape.py "libro*.pdf" "keywords"` → leer las páginas que devuelve (texto).
2. Sólo si hace falta VER una figura/tabla/ecuación, `Read` esa página puntual (imagen).
3. Volcar los criterios nuevos a `criterios_room_geom_fuente.md` (numerar siguiendo lo
   existente; citar `[Libro pX]`), agregar refs nuevas, marcar el libro ✅ en este índice.
- Si `_scrape.py` no devuelve nada → PDF escaneado (sin texto) → ahí sí `Read`/OCR.

**Keywords sugeridas por libro pendiente:**

| Libro | glob | keywords |
|---|---|---|
| Newell, Recording Studio Design | `"Recording Studio*.pdf"` | `soffit\|flush\|monitor\|LEDE\|RFZ\|reflection.free\|early reflection\|mode\|proportion` |
| Cox & D'Antonio, Absorbers & Diffusers | `"Acoustic Absorbers*.pdf"` | `room siz\|dimension\|optimi\|diffuser\|QRD\|modal\|low.frequency\|aperture` |
| BBC Guide (Rose) | `"BBC Guide*.pdf"` | `ratio\|dimension\|proportion\|Walker\|studio\|mode` |
| Beranek, Sound Fields & Transducers | `"Sound Fields*.pdf"` | `baffle\|half.space\|boundary\|radiation impedance\|monopole\|directivity` |
| Beranek, Concert Halls | `"*Concert Halls*.pdf"` | `ITDG\|IACC\|BQI\|intimacy\|clarity\|strength\|reverberation\|optimum` |
| Ando, Architectural acoustics | `"Architectural acoustics - Yoichi*.pdf"` | `orthogonal\|preference\|IACC\|ITDG\|listening level\|subjective` |
| Meyer, Performance of Music | `"Acoustics and the Performance*.pdf"` | `directivity\|directional\|radiation\|instrument` |
| Carrión Isbert | `"Diseño Acústico*.pdf"` | `modo\|proporci\|dimension\|criterio\|relación` |

**Gotchas:** nombres con acento fallan en `Read` (no en `_scrape.py`/glob). En PDFs
gordos el offset libro↔PDF varía (Everest = +26); `_scrape.py` ya imprime el nº de
página de PDF para pasárselo al `Read`. Estado vivo: ver `[[criterios-research]]` en memoria.

---

## T1 — Papers centrales (lectura completa)

| Archivo | Autor / año | Qué aporta al doc de criterios |
|---|---|---|
| `Gunawan_2018_J._Phys.__Conf._Ser._1075_012049.pdf` | Gunawan, Aditanoyo 2018 | FoM σ_SPL por punto; ratios Bolt/Louden/Bonello/Cox; tablas ISO 266. **Base de FoM_flat.** |
| `Analysis on Modal Distribution and Modal Density-Based Crossover Frequency.pdf` | Wang, Du & Yu 2026 | **MDCF**: crossover por densidad modal numérica (ve la forma) vs Schroeder. Criterio de validez FEM↔GA. (plan §9) |
| `Hill-Hawksford-JAES-Nov-2011.pdf` | Hill & Hawksford 2011 | Varianza espacial asiento-a-asiento; corrección de modos en área amplia (DSP). Apoya FoM_espacial. |

## T2 — Libros con capítulos fuertes (minar SÓLO lo marcado)

| Archivo | Autor | Capítulos a minar |
|---|---|---|
| `Master Handbook Of Acoustics - Alton, F. Everest - .pdf` | Everest & Pohlmann | Room modes · **Dimensión/ratios de sala** · **criterio Bonello** · acústica de control room / listening room · ubicación de monitores |
| ✅ `Recording Studio Design 3rd Edition.pdf` | Newell | Diseño de control room · **soffit/flush mount de monitores** · LEDE/RFZ · control de modos LF → A29-A31, B25-B26, C19-C21 |
| ✅ `Acoustic Absorbers and Diffusers 2nd Edition - Cox _ D_antonio.pdf.pdf` | Cox & D'Antonio | §1.3 modal control (poroso λ/4 vs resonante esquina), §1.4 eco/flutter, difusor vs absorbente, LF no-difuso→FEM → A31, B27-B28, C22-C24. (NO trae sizing/FoM de recinto: es libro de devices) |
| ✅ `BBC Guide to Acoustic Practice - Keith Rose.pdf` ⚠️ESCANEADO | Rose (BBC) | §3.3-3.4 dims/modos/flutter, §3.2 RT, §4 layout control room → A33-A34, B29-B30, C25-C26. **Sin capa de texto: `_scrape.py` NO sirve, `Read` páginas img. Offset +2** |
| ✅ `Diseño Acústico de Espacios Arquitectónicos - Antoni Carrión Isbert.pdf` | Carrión Isbert | §1.15.5 modos (Rayleigh, fig 1.42 región l/w), §5.5.4 seat-dip → A35, D17. **Texto de teatros/conciertos (ES): confirmatorio, sin cap. de estudios** |
| `Architectural Acoustics - Long.pdf` | Long | Room modes · criterios de dimensiones · small-room design |
| ✅ `Sound Fields and Transducers - 2012 - Beranek.pdf` | Beranek & Mellow | Ch4 §4.9-4.12: reflexión en plano + imágenes + 2 fuentes en fase → +6dB/2π → B31 (raíz de B2/B3/B4/B23/B26). 700pág mate; text-layer rompe ecuaciones |
| ✅ `Acoustics and Psychoacoustics, Fourth Edition - David Howard, Jamie Angus.pdf` | Howard & Angus | Ch6: decay modal 1-D por tipo, frecuencia crítica = solapamiento modal 3 (corrobora MDCF), salas grandes/chicas, Bonello → A36-A37. Capa de texto OK |
| ✅ `Sound Reproduction ... Floyd Toole.pdf` | Toole (2008) | Cap 13 (modos LF, range-of-validity del ratio, multi-sub/Welti, SFM, EQ=fase mínima), cap 12 (boundary/SBIR/montaje), cap 4.3 (transition freq). **No suma criterio geom/fuente nuevo** → respaldo A33/A36/C13/C21. Capa texto OK. **Offset +19.** Caps reflexiones/imaging/multicanal = ⊘ fuera de alcance |

## T3 — Criterios de salas grandes / perceptuales (mirar selectivo)

| Archivo | Autor | Qué tiene |
|---|---|---|
| `Leo Beranek (auth.)-Concert Halls and Opera Houses...pdf` | Beranek 2004 | **Parámetros ortogonales** de sala (ITDG, BQI, G, RT, EDT…) — criterios de diseño de salas |
| `Architectural acoustics - Yoichi Ando.pdf` | Ando | **4 parámetros ortogonales** (nivel, ITDG, T_sub, IACC) · diseño por preferencia |
| `Auditorium Acoustics and Architectural Design - Michael Barron.pdf` | Barron | Criterios de diseño de auditorios · forma de sala |
| `Auditorium Acoustics and Architectural Design (2nd edition 2010) - Michael Barron.pdf` | Barron (2ª ed) | Ídem, edición ampliada |
| ✅ `Acoustics and the Performance of Music - Jurgen Meyer.pdf` | Meyer | Ch4 directividad de instrumentos: omni <500 Hz, índice de directividad, dirección principal → B32 (amplía B12). Capa de texto OK |
| `Auralization - Vorlander.pdf` | Vorländer | FEM vs acústica geométrica · crossover/validez (apoya MDCF) |
| `Ingeniería Acústica Teoría y Aplicaciones - Michael Möser.pdf` | Möser | Acústica de salas, fundamentos · modos |
| `Acustica - Beranek.pdf` | Beranek | Clásico: modos, fuentes, fundamentos |
| `Acústica Práctica - Carlos Savioli.pdf` | Savioli | Criterios prácticos (ES) |

## T4 — Tangencial (consulta puntual, no se mina sistemático)

`Psychoacoustics - Facts And Models - Third Edition (Hugo Fastl).pdf` ·
`Psychoacoustics, Facts and models - Zwicker1999.pdf` (peso perceptual pico/nulo) ·
`Principles and Applications of Spatial Hearing...pdf` ·
`Acoustics and Hearing - Peter Damaske.pdf` · `Acoustics-and-Hearing.pdf` ·
`Acustica y Psicoacustica de la Musica - Roederer, J.pdf` ·
`Materials and Acoustics Handbook - Michel Bruneau, Catherine Potel.pdf` ·
`Sound and Structural Vibration... - Fahy, Gardonio.pdf` ·
`Advanced Applications in Acoustics... - Frank Fahy.pdf` ·
`Hopkins - Sound insulation.pdf` · `UNE-EN_ISO_354=2004.pdf` (método de medición α)

## T2b — Material de cátedra (slides + PDFs) — ALTA relevancia, minar

| Archivo | Tema | Qué minar |
|---|---|---|
| `Controles de estudios de grabacion y mastering-2024.pptx` | control room | monitores, **soffit/flush**, RFZ/LEDE, control LF, simetría |
| `07 - Diagnóstico de Controles de Estudio(1).pptx` | diagnóstico CR | criterios de "buen" control room (modos, SBIR, RFZ) |
| `10 - Acoplamiento Acústico.pdf` (57 pág) | acople fuente-recinto | `φₙ(xₛ)`, salas acopladas, excitación modal |
| `03 - Parametros modernos - 2025.pptx` | parámetros ISO 3382 | C50/C80, STI, EDT, claridad — criterios de evaluación |
| `05 - Coeficiente de Absorción.pptx` | absorción | colocación de absorción → damping/suavidad modal |

## T3b — Salas grandes / preferencia (selectivo)

| Archivo | Autor | Qué tiene |
|---|---|---|
| `TEMPORAL_AND_SPATIAL_ACOUSTICAL_FACTORS.pdf` (346 pág) | Ando | **4 factores ortogonales** (nivel, ITDG, T_sub, IACC) — teoría de preferencia |
| `Preferred dimension ratios of small rectangular rooms.pdf` | Rindel 2021 | = el de la web (FSI ψ(25)). Ya en §A.6. ✅ |

## T6 — Numérica / validez del solver (NO se mina para criterios de diseño)

> Respaldo del fix del auto-tuner de malla y del crossover MDCF. Justifican el
> `ppw` y el `f_max_malla = c/(ppw·h)`. No son criterios acústicos de diseño.
> **Minado CERRADO (2026-06-21) → vuelca en `numerica_fem_validez.md`, NO en criterios.**

| Archivo | Qué aporta |
|---|---|
| ✅ `Ihlenburg, Finite Element Analysis of Acoustic Scattering.pdf` ⚠️ es **Langdon & Chandler-Wilde (2007)** | **pollution error** `C₂k³h²`, regla `ppw`, `O(h²)` → §2-4 (E1-E4). El libro real de Ihlenburg NO está en el corpus |
| ✅ `FEM for Acoustics.pdf` = **Desmet & Vandepitte (2002)** | sistema `[K]+jωC−ω²M`, taxonomía de BC, ensamblaje de C (impedancia), error geométrico → §5 (E5-E6) |
| ✅ `Stable Multiscale Petrov-Galerkin...pdf` = **Gallistl & Peterseim (2015)** | PG multiescala **pollution-free** (`H∝1/k` estable); alternativa NO usada → §5 (E7) |

## T4b — Cátedra tangencial (consulta puntual)

`01 - ERRORES EN LAS MEDICIONES_v2026.pptx` (metrología) ·
`08 - POTENCIA ACÚSTICA-2024.pptx` (sound power de fuente) ·
`09 - Clase Beamforming y cámara acústica_IMA_2025.pptx` (arrays/medición) ·
`11 - Sistemas Dinámicos.pptx` (sistemas/control)

## T5 — Otra materia (NO se mina para este doc)

`Coarticulation Theory...` · `Evolutionary Phonology...` ·
`Speech Acoustics and Phonetics - Gunnar Fant...` · `Robust Speech Recognition...` ·
`Multimodal Technologies for Perception of Humans...` · `Audiologia_Basica.pdf` ·
`Listening and Voice Phenomenologies of Sound - Don Ihde.pdf` ·
`Hearing An Introduction... 5th Edition...` ·
`Physiology, Psychoacoustics and Cognition... - Springer Open.pdf`

---

## Fuentes externas ya consultadas (web, fuera de `referencias`)

- Rindel 2021 (JASA EL) — **FSI ψ(25)**, l/w domina. [open-access]
- Welti & Devantier 2003 (AES) — **MSV**, multi-sub, 4 midwall > 4 esquinas.
- Cox, D'Antonio & Avis 2004 (JAES) — optimización conjunta dim + fuente/receptor.
- arqen — SBIR `f_c = c/(4d)`.

## Plan de extracción

1. ✅ Índice (este archivo).
2. ⏳ Leer a fondo T1 + capítulos marcados de T2 → extraer criterios.
3. ⏳ Volcar a `criterios_room_geom_fuente.md`: **§A Geometría · §B Fuentes · §C Combinado**,
   cada criterio con: nombre, FoM/fórmula, rango/umbral, fuente, y mapeo a T8.
