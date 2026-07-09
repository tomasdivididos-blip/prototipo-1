# Cobertura de materiales del manual de referencia

Cruza el listado de materiales de el Cox (140 entradas) contra la libreria interna (428 materiales).

## Resumen

- **MATCH** (score >= 55): 70 / 140 (50.0 %) — material reconocido con alta confianza.
- **SIMILAR** (score 40-55): 28 / 140 (20.0 %) — hay candidato parecido pero conviene revisar.
- **FALTA** (score < 40): 42 / 140 (30.0 %) — no aparece en la libreria, conviene agregarlo.


### Score: 
ponderado 60 % Jaccard de tokens semanticos + 40 % difflib ratio. Aplica diccionario de sinonimos en/es (fibreglass→lana_vidrio, plywood→contrachapado, carpet→alfombra, etc.). 100 = nombre identico; 50 = comparten la mayoria de palabras clave.


## Absorbentes

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Acoustic tile, 1.9 cm thick | **FALTA** | 38 | (sin coincidencia) |
| Polyurethane foam, 2.5 cm thick | **FALTA** | 24 | (sin coincidencia) |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Acoustic tile, 1.9 cm thick**:
- 38.2 · Yeso acustico
- 37.8 · Puerta acustica
- 25.1 · Yeso acustico de 68 mm de espesor

**Polyurethane foam, 2.5 cm thick**:
- 23.8 · Panel de contrachapado, 1 cm de espesor
- 23.6 · Panel acústico (espuma + tela)
- 22.2 · Alfombra pesada sobre espuma de goma

</details>


## Ballast

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Ballast or other crushed stone, 3.18 cm, 15.2 cm deep | **FALTA** | 35 | (sin coincidencia) |
| Ballast or other crushed stone, 3.18 cm, 30.5 cm deep | **FALTA** | 35 | (sin coincidencia) |
| Ballast or other crushed stone, 3.18 cm, 45.7 cm deep | **FALTA** | 35 | (sin coincidencia) |
| Ballast or other crushed stone, 0.64 cm, 15.2 cm deep | **FALTA** | 35 | (sin coincidencia) |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Ballast or other crushed stone, 3.18 cm, 15.2 cm deep**:
- 34.8 · Absorcion del 18%
- 34.8 · Absorcion del 15%
- 23.3 · Panel de contrachapado, 1 cm de espesor

**Ballast or other crushed stone, 3.18 cm, 30.5 cm deep**:
- 34.8 · Absorcion del 30%
- 34.8 · Absorcion del 18%
- 23.3 · Panel de contrachapado, 1 cm de espesor

**Ballast or other crushed stone, 3.18 cm, 45.7 cm deep**:
- 34.8 · Absorcion del 45%
- 34.8 · Absorcion del 18%
- 23.3 · Panel de contrachapado, 1 cm de espesor

**Ballast or other crushed stone, 0.64 cm, 15.2 cm deep**:
- 34.8 · Absorcion del 64%
- 34.8 · Absorcion del 15%
- 23.8 · Panel de contrachapado, 1 cm de espesor

</details>


## Microperforados

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Microperforated absorber, 4 cm cavity | **MATCH** | 55 | Panel microperforado, 7% abierto, absorbente de 30 mm a 81 kg/m3, cavidad de 20 mm |
| Microperforated absorber, 40 cm cavity | **SIMILAR** | 49 | Panel microperforado, 7% abierto, absorbente de 40 mm a 81 kg/m3 |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Microperforated absorber, 40 cm cavity**:
- 49.5 · Panel microperforado, 7% abierto, absorbente de 40 mm a 81 kg/m3
- 49.5 · Panel microperforado, 6% abierto, absorbente de 40 mm a 81 kg/m3
- 47.3 · Panel microperforado, 7% abierto, absorbente de 30 mm a 81 kg/m3, cavidad de 20 mm

</details>


## Difusores

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Hybrid absorber-diffuser BAD panel on 2.5 cm fibreglass | **FALTA** | 37 | (sin coincidencia) |
| 2D N=7 QRD, design freq 500 Hz | **FALTA** | 8 | (sin coincidencia) |
| 2D N=7 QRD with cloth covering | **FALTA** | 7 | (sin coincidencia) |
| 1D N=7 QRD, design freq 500 Hz | **FALTA** | 8 | (sin coincidencia) |
| 1D N=7 QRD with cloth covering | **FALTA** | 7 | (sin coincidencia) |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Hybrid absorber-diffuser BAD panel on 2.5 cm fibreglass**:
- 37.0 · Panel de contrachapado, 1 cm de espesor
- 33.9 · Vidrio de ventana
- 32.9 · Vidrio (ventana/mampara)

**2D N=7 QRD, design freq 500 Hz**:
- 7.9 · Lana de roca 50 mm, 30 kg/m3
- 7.1 · Lana de roca 50 mm, 81 kg/m3
- 7.1 · Lana de roca 50 mm, 64 kg/m3

**2D N=7 QRD with cloth covering**:
- 7.1 · Hilado de lana de oveja copetudo
- 7.0 · Ladrillo pintado
- 6.9 · Puerta de nucleo hueco

**1D N=7 QRD, design freq 500 Hz**:
- 7.9 · Lana de roca 50 mm, 30 kg/m3
- 7.1 · Lana de roca 50 mm, 81 kg/m3
- 7.1 · Lana de roca 50 mm, 64 kg/m3

**1D N=7 QRD with cloth covering**:
- 7.1 · Hilado de lana de oveja copetudo
- 7.0 · Ladrillo pintado
- 6.9 · Puerta de nucleo hueco

</details>


## Cortinas

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Light velour 0.338 kg/m2 hung straight in contact with wall | **MATCH** | 63 | Terciopelo liviano colgado recto en contacto con la pared |
| Medium velour 0.475 kg/m2 hung straight | **SIMILAR** | 53 | Terciopelo semipesado colgado recto |
| Medium velour 0.475 kg/m2 draped to half area | **SIMILAR** | 48 | Terciopelo semipesado drapeado a mitad de area |
| Heavy velour 0.61 kg/m2 hung straight | **MATCH** | 71 | Terciopelo pesado colgado recto |
| Heavy velour 0.61 kg/m2 draped to half area | **MATCH** | 62 | Terciopelo pesado drapeado a mitad de area |
| Cortinas hung straight | **MATCH** | 90 | Cortinas colgadas rectas |
| Cortinas draped to half area | **MATCH** | 70 | Cortinas drapeadas al 40% del area |
| Cortinas draped to 40% of area | **MATCH** | 96 | Cortinas drapeadas al 40% del area |
| Curtains in folds against wall | **FALTA** | 32 | (sin coincidencia) |
| Cotton curtains 0.475 kg/m2 draped to 7/8 area | **MATCH** | 64 | Cortinas de algodon drapeadas al 75% del area |
| Cotton curtains 0.475 kg/m2 draped to 3/4 area | **MATCH** | 64 | Cortinas de algodon drapeadas al 88% del area |
| Cotton curtains 0.475 kg/m2 draped to 1/2 area | **MATCH** | 64 | Cortinas de algodon drapeadas al 88% del area |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Medium velour 0.475 kg/m2 hung straight**:
- 53.1 · Terciopelo semipesado colgado recto
- 52.8 · Terciopelo pesado colgado recto
- 42.1 · Cortinas colgadas rectas

**Medium velour 0.475 kg/m2 draped to half area**:
- 47.8 · Terciopelo semipesado drapeado a mitad de area
- 47.7 · Terciopelo pesado drapeado a mitad de area
- 39.1 · Cortinas drapeadas al 40% del area

**Curtains in folds against wall**:
- 32.0 · Cortinas colgadas rectas
- 26.4 · Pared de mamposteria revocada
- 25.5 · Cortinas drapeadas a mitad de area

</details>


## Alfombras

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Carpet heavy on concrete | **MATCH** | 86 | Alfombra pesada sobre hormigon |
| Heavy carpet on foam rubber or hair felt 1.35 kg/m2 | **MATCH** | 69 | Alfombra pesada sobre espuma de goma |
| Heavy carpet with latex backing on foam rubber or hair felt | **MATCH** | 82 | Alfombra pesada con respaldo de latex sobre espuma de goma |
| Haircord on felt | **SIMILAR** | 43 | Pelo corto sobre fieltro |
| Pile and thick felt | **MATCH** | 56 | Pelo y fieltro grueso |
| Woven wool loop carpet 1.2 kg/m2 2.4mm pile no underlay | **MATCH** | 62 | Pelo de lana con base |
| Woven wool loop carpet 1.4 kg/m2 6.4mm pile no underlay | **MATCH** | 62 | Pelo de lana con base |
| Woven wool loop carpet 2.3 kg/m2 9.5mm pile no underlay | **MATCH** | 62 | Pelo de lana con base |
| Loop pile tufted carpet 1.4 kg/m2 hair underlay | **MATCH** | 61 | Alfombra con base |
| Loop pile tufted carpet 1.4 kg/m2 hair underlay 3 kg/m2 | **MATCH** | 61 | Alfombra con base |
| Loop pile tufted carpet 1.4 kg/m2 hair and jute underlay 3 kg/m2 | **MATCH** | 60 | Alfombra con base |
| Loop pile tufted carpet 1.4 kg/m2 no underlay | **MATCH** | 61 | Alfombra con base |
| Loop pile tufted carpet 0.7 kg/m2 1.4 kg/m2 hair underlay | **MATCH** | 61 | Alfombra con base |
| 16mm wool pile with underlay | **MATCH** | 77 | Pelo de lana con base |
| 9.5mm wool pile no underlay on concrete | **MATCH** | 72 | Pelo de lana con base |
| Cord carpet | **SIMILAR** | 42 | Alfombra con base |
| Thin 6mm carpet on underlay | **MATCH** | 71 | Alfombra con base |
| 6mm pile carpet bonded to closed-cell foam underlay | **MATCH** | 62 | Alfombra con base |
| Thick 9mm carpet on underlay | **MATCH** | 71 | Alfombra con base |
| Needle felt 5mm stuck to concrete | **FALTA** | 34 | (sin coincidencia) |
| Thin carpet cemented to concrete | **SIMILAR** | 50 | Alfombra pesada sobre hormigon |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Haircord on felt**:
- 42.5 · Pelo corto sobre fieltro
- 40.1 · Pelo y fieltro grueso
- 37.0 · Alfombra de pelo copetudo sobre base de fieltro

**Cord carpet**:
- 42.1 · Alfombra con base
- 38.9 · Baldosas de alfombra
- 36.1 · Alfombra persa de doble base

**Needle felt 5mm stuck to concrete**:
- 34.4 · Parquet sobre hormigon
- 34.3 · Hormigón visto
- 33.3 · Hormigon rugoso

**Thin carpet cemented to concrete**:
- 50.5 · Alfombra pesada sobre hormigon
- 37.7 · Parquet sobre hormigon
- 37.0 · Hormigon rugoso

</details>


## Mobiliario

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Orchestra with instruments 1.5 m2/person | **MATCH** | 77 | Orquesta con instrumentos |
| Wooden pews 100% occupancy | **MATCH** | 91 | Bancos de madera (100% de ocupacion) |
| Wooden chairs 100% occupancy | **MATCH** | 91 | Sillas de madera (100% de ocupacion) |
| Wooden pews 75% occupancy | **MATCH** | 91 | Bancos de madera (75% de ocupacion) |

## Misc

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Water surface in swimming pool | **MATCH** | 64 | Agua |
| Marble or glazed tile | **FALTA** | 37 | (sin coincidencia) |
| Ventilation grille | **MATCH** | 90 | Rejilla de ventilacion |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Marble or glazed tile**:
- 37.1 · Piso de marmol
- 27.9 · Baldosas esmaltadas lisas
- 7.9 · Panel de corcho de 30 mm de espesor

</details>


## Madera

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Solid wooden door | **MATCH** | 77 | Puerta de madera |
| Plywood panelling 1 cm thick | **MATCH** | 63 | Panel de contrachapado, 1 cm de espesor |
| 22 mm chipboard 50 mm cavity filled with mineral wool | **SIMILAR** | 54 | Aglomerado con respaldo de lana mineral |
| 3-4 mm plywood sheets >75 mm cavity 25-50 mm mineral wool | **SIMILAR** | 44 | Lana de vidrio 50 mm, 25 kg/m3 |
| Plywood hardwood air space | **FALTA** | 24 | (sin coincidencia) |
| 6 mm wood fibreboard on laths cavity >100 mm deep | **MATCH** | 57 | Madera |
| Fibreboard solid backing | **MATCH** | 88 | Tablero de fibras, respaldo solido |
| Fibreboard 25 mm air space | **MATCH** | 58 | Madera |
| Wood panelling 9.5-12.7 mm 5-10 cm air space | **MATCH** | 55 | Madera |
| Wood 50 mm thick | **MATCH** | 63 | Madera de 50 mm de espesor |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**22 mm chipboard 50 mm cavity filled with mineral wool**:
- 54.0 · Aglomerado con respaldo de lana mineral
- 37.6 · Madera de 50 mm de espesor
- 35.9 · Lana de roca 50 mm, 81 kg/m3

**3-4 mm plywood sheets >75 mm cavity 25-50 mm mineral wool**:
- 44.2 · Lana de vidrio 50 mm, 25 kg/m3
- 36.7 · Aglomerado con respaldo de lana mineral
- 36.2 · Madera de 50 mm de espesor

**Plywood hardwood air space**:
- 24.3 · Panel de contrachapado, 1 cm de espesor
- 7.3 · Panel de madera con camara de aire por detras
- 7.3 · Placa de yeso de 13 mm sobre bastidor, camara de aire de 100 mm

</details>


## Rigidos

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Rough concrete | **SIMILAR** | 42 | Hormigón visto |
| Smooth unpainted concrete | **MATCH** | 87 | Hormigon liso sin pintar |
| Smooth concrete painted or glazed | **MATCH** | 80 | Hormigon liso pintado |
| Concrete block coarse | **SIMILAR** | 54 | Bloque de hormigon, rugoso |
| Concrete block painted | **MATCH** | 88 | Bloque de hormigon, pintado |
| Porous concrete blocks 400-800 kg/m3 | **SIMILAR** | 45 | Bloque de hormigon, pintado |
| Clinker concrete no surface finish 800 kg/m3 | **FALTA** | 32 | (sin coincidencia) |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Rough concrete**:
- 42.1 · Hormigón visto
- 41.9 · Hormigon rugoso
- 40.6 · Parquet sobre hormigon

**Concrete block coarse**:
- 54.4 · Bloque de hormigon, rugoso
- 53.4 · Bloque de hormigon, pintado
- 38.1 · Hormigon rugoso

**Porous concrete blocks 400-800 kg/m3**:
- 44.7 · Bloque de hormigon, pintado
- 43.5 · Bloque de hormigon, rugoso
- 34.2 · Hormigon rugoso

**Clinker concrete no surface finish 800 kg/m3**:
- 32.5 · Hormigón visto
- 32.4 · Hormigon rugoso
- 30.2 · Parquet sobre hormigon

</details>


## Ladrillo

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Brick unglazed | **MATCH** | 87 | Ladrillo sin esmaltar |
| Brickwork plain painted | **MATCH** | 79 | Ladrillo pintado |
| Smooth brickwork with flush pointing painted | **MATCH** | 69 | Ladrillo pintado |
| Brick unglazed painted | **MATCH** | 79 | Ladrillo pintado |
| Smooth brickwork with flush pointing | **MATCH** | 70 | Ladrillos lisos |
| Smooth brickwork 10 mm deep pointing pit sand mortar | **MATCH** | 60 | Ladrillos lisos |
| Breeze block | **FALTA** | 36 | (sin coincidencia) |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Breeze block**:
- 35.7 · Bloque de hormigon, rugoso
- 35.7 · Bloque de hormigon, pintado
- 7.4 · Yeso sobre respaldo solido

</details>


## Yeso

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Lime cement plaster | **FALTA** | 39 | (sin coincidencia) |
| Glaze plaster | **SIMILAR** | 40 | Pared de mamposteria revocada |
| Painted plaster surface | **SIMILAR** | 54 | Yeso pintado / Revoque fino |
| Plaster with wallpaper on backing paper | **SIMILAR** | 49 | Pared de mamposteria revocada |
| Plaster gypsum or lime rough finish on lath | **FALTA** | 33 | (sin coincidencia) |
| Plaster gypsum or lime smooth finish on lath | **FALTA** | 36 | (sin coincidencia) |
| Plaster on laths studs air space | **FALTA** | 38 | (sin coincidencia) |
| Plaster gypsum or lime smooth finish on tile or brick | **MATCH** | 65 | Ladrillos lisos |
| Plaster lime of gypsum on solid backing | **MATCH** | 79 | Yeso sobre respaldo solido |
| Acoustic plaster | **MATCH** | 90 | Yeso acustico |
| Acoustic plaster 40 mm thick | **MATCH** | 70 | Yeso acustico de 40 mm de espesor |
| Acoustic plaster 68 mm thick | **MATCH** | 70 | Yeso acustico de 68 mm de espesor |
| Gypsum board 1.27 cm nailed to studs 4.1 m c-t-c | **FALTA** | 37 | (sin coincidencia) |
| Plasterboard on frame 9.5mm boards 10cm empty cavity | **SIMILAR** | 42 | Placa de yeso de 13 mm sobre bastidor, camara de aire de 100 mm |
| Plasterboard on frame 9.5mm boards 10cm cavity mineral wool | **SIMILAR** | 49 | Placa de yeso de 13 mm sobre bastidor, 100 mm de lana mineral por detras |
| Plasterboard on frame 13mm boards 10cm empty cavity | **SIMILAR** | 43 | Placa de yeso de 13 mm sobre bastidor, camara de aire de 100 mm |
| Plasterboard on frame 13mm boards 10cm cavity mineral wool | **SIMILAR** | 49 | Placa de yeso de 13 mm sobre bastidor, 100 mm de lana mineral por detras |
| 2x13mm plasterboard on steel frame 5cm mineral wool | **SIMILAR** | 51 | Placa de yeso de 13 mm sobre bastidor, 100 mm de lana mineral por detras |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Lime cement plaster**:
- 38.8 · Yeso acustico
- 29.3 · Pared de mamposteria revocada
- 27.1 · Yeso acustico de 68 mm de espesor

**Glaze plaster**:
- 40.1 · Pared de mamposteria revocada
- 39.6 · Yeso acustico
- 37.6 · Yeso sobre respaldo solido

**Painted plaster surface**:
- 54.2 · Yeso pintado / Revoque fino
- 37.6 · Ladrillo pintado
- 36.9 · Yeso acustico

**Plaster with wallpaper on backing paper**:
- 48.6 · Pared de mamposteria revocada
- 46.4 · Yeso sobre respaldo solido
- 33.8 · Yeso acustico

**Plaster gypsum or lime rough finish on lath**:
- 32.9 · Yeso acustico
- 28.0 · Yeso pintado / Revoque fino
- 27.1 · Pared de mamposteria revocada

**Plaster gypsum or lime smooth finish on lath**:
- 36.1 · Ladrillos lisos
- 32.8 · Yeso acustico
- 26.7 · Yeso pintado / Revoque fino

**Plaster on laths studs air space**:
- 37.9 · Placa de yeso clavada a montantes
- 33.6 · Yeso acustico
- 28.2 · Pared de mamposteria revocada

**Gypsum board 1.27 cm nailed to studs 4.1 m c-t-c**:
- 37.4 · Placa de yeso clavada a montantes
- 33.9 · Yeso acustico
- 33.0 · Absorcion del 27%

**Plasterboard on frame 9.5mm boards 10cm empty cavity**:
- 42.4 · Placa de yeso de 13 mm sobre bastidor, camara de aire de 100 mm
- 42.4 · Placa de yeso de 10 mm sobre bastidor, camara de aire de 100 mm
- 34.3 · Placa de yeso clavada a montantes

**Plasterboard on frame 9.5mm boards 10cm cavity mineral wool**:
- 48.5 · Placa de yeso de 13 mm sobre bastidor, 100 mm de lana mineral por detras
- 48.5 · Placa de yeso de 10 mm sobre bastidor, 100 mm de lana mineral por detras
- 41.2 · Placa de yeso de 13 mm sobre bastidor, camara de aire de 100 mm

**Plasterboard on frame 13mm boards 10cm empty cavity**:
- 43.1 · Placa de yeso de 13 mm sobre bastidor, camara de aire de 100 mm
- 42.8 · Placa de yeso de 10 mm sobre bastidor, camara de aire de 100 mm
- 34.3 · Placa de yeso clavada a montantes

**Plasterboard on frame 13mm boards 10cm cavity mineral wool**:
- 49.2 · Placa de yeso de 13 mm sobre bastidor, 100 mm de lana mineral por detras
- 48.9 · Placa de yeso de 10 mm sobre bastidor, 100 mm de lana mineral por detras
- 41.9 · Placa de yeso de 13 mm sobre bastidor, camara de aire de 100 mm

**2x13mm plasterboard on steel frame 5cm mineral wool**:
- 51.0 · Placa de yeso de 13 mm sobre bastidor, 100 mm de lana mineral por detras
- 50.6 · Placa de yeso de 10 mm sobre bastidor, 100 mm de lana mineral por detras
- 40.3 · Aglomerado con respaldo de lana mineral

</details>


## Suelos

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Wood block lino or rubber flooring | **MATCH** | 59 | Madera |
| Parquet fixed with asphalt on concrete | **MATCH** | 72 | Parquet sobre hormigon |
| Wood on solid floor | **MATCH** | 76 | Piso de madera |
| Floors wood | **MATCH** | 83 | Piso de madera |
| Wood platform large airspace below | **MATCH** | 60 | Madera |
| Floor boards on joist floor | **FALTA** | 38 | (sin coincidencia) |
| Floors concrete or terrazzo | **FALTA** | 39 | (sin coincidencia) |
| Linoleum or vinyl stuck to concrete | **MATCH** | 57 | Linoleo o vinilo sobre hormigon |
| Linoleum asphalt tile or cork tile on concrete | **SIMILAR** | 52 | Linoleo o vinilo sobre hormigon |
| Layer of rubber cork linoleum and underlay | **FALTA** | 35 | (sin coincidencia) |
| Cork lino or rubber tile on solid floor | **FALTA** | 35 | (sin coincidencia) |
| 25 mm cork on solid backing | **SIMILAR** | 50 | Yeso sobre respaldo solido |
| Slate | **FALTA** | 8 | (sin coincidencia) |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Floor boards on joist floor**:
- 38.4 · Piso de marmol
- 37.0 · Piso de escenario
- 36.4 · Piso de madera

**Floors concrete or terrazzo**:
- 39.3 · Piso de madera
- 39.2 · Hormigon rugoso
- 38.4 · Hormigón visto

**Linoleum asphalt tile or cork tile on concrete**:
- 52.2 · Linoleo o vinilo sobre hormigon
- 36.9 · Baldosas de corcho
- 35.9 · Parquet sobre hormigon

**Layer of rubber cork linoleum and underlay**:
- 35.3 · Baldosas de corcho
- 34.7 · Alfombra con base
- 34.1 · Baldosas de goma

**Cork lino or rubber tile on solid floor**:
- 34.6 · Piso de marmol
- 33.8 · Piso de madera
- 33.6 · Piso de escenario

**25 mm cork on solid backing**:
- 50.1 · Yeso sobre respaldo solido
- 39.6 · Tablero de fibras, respaldo solido
- 36.4 · Absorcion del 25%

**Slate**:
- 7.6 · Sillas de madera
- 7.6 · Losas de terrazo
- 7.3 · Madera

</details>


## Asientos

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Theatre seating unoccupied Beranek values | **MATCH** | 75 | Asientos de teatro, desocupados |
| Average of nine modern seating designs 0.9m row | **FALTA** | 33 | (sin coincidencia) |
| One seat type 0.8m row spacing | **FALTA** | 9 | (sin coincidencia) |
| Same seat 0.9m row spacing | **FALTA** | 10 | (sin coincidencia) |
| Same seat 1m row spacing | **FALTA** | 10 | (sin coincidencia) |
| Upholstered seating | **MATCH** | 83 | Asientos tapizados |
| Upholstered seating well upholstered | **MATCH** | 72 | Asientos tapizados |
| Upholstered seating leather covered | **MATCH** | 77 | Asientos tapizados, cubiertos en cuero |
| Occupied theatre seating average | **MATCH** | 80 | Asientos de teatro ocupados |
| Audience on timber seats 1/m2 | **SIMILAR** | 47 | Audiencia sobre asientos de madera (1/m2) |
| Audience on timber seats 2/m2 | **SIMILAR** | 47 | Audiencia sobre asientos de madera (2/m2) |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Average of nine modern seating designs 0.9m row**:
- 33.1 · Asientos tapizados
- 26.2 · Asientos de teatro, desocupados
- 24.9 · Asientos de teatro ocupados

**One seat type 0.8m row spacing**:
- 8.8 · Bancos de madera (75% de ocupacion)
- 8.6 · Bancos de madera (100% de ocupacion)
- 8.0 · Sillas de madera (100% de ocupacion)

**Same seat 0.9m row spacing**:
- 10.5 · Sillas de madera (100% de ocupacion)
- 9.8 · Bancos de madera (100% de ocupacion)
- 9.3 · Bancos de madera (75% de ocupacion)

**Same seat 1m row spacing**:
- 10.2 · Sillas de madera (100% de ocupacion)
- 9.5 · Bancos de madera (100% de ocupacion)
- 9.0 · Bancos de madera (75% de ocupacion)

**Audience on timber seats 1/m2**:
- 46.6 · Audiencia sobre asientos de madera (1/m2)
- 45.8 · Audiencia de pie (1 persona/m2)
- 45.4 · Audiencia sobre asientos de madera (2/m2)

**Audience on timber seats 2/m2**:
- 46.6 · Audiencia sobre asientos de madera (2/m2)
- 45.7 · Audiencia de pie (2 personas/m2)
- 45.4 · Audiencia sobre asientos de madera (1/m2)

</details>


## Vidrio

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| Glass ordinary window glass | **MATCH** | 74 | Vidrio (ventana/mampara) |
| Single pane of glass 3-4mm | **MATCH** | 57 | Vidrio simple, 3-4 mm |
| Single pane of glass >4mm | **MATCH** | 57 | Vidrio simple, >4 mm |
| Single pane of glass 3mm | **MATCH** | 57 | Vidrio simple, 3-4 mm |
| Double glazing 2-3mm glass 1cm gap | **FALTA** | 35 | (sin coincidencia) |
| Double glazing 2-3mm glass >3cm gap | **FALTA** | 35 | (sin coincidencia) |
| Glass large panes heavy glass | **FALTA** | 38 | (sin coincidencia) |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**Double glazing 2-3mm glass 1cm gap**:
- 34.8 · Vidrio de ventana
- 33.5 · Vidrio (ventana/mampara)
- 31.7 · Doble vidrio de 2-3 mm, camara de aire de 10 mm

**Double glazing 2-3mm glass >3cm gap**:
- 34.7 · Vidrio de ventana
- 33.4 · Vidrio (ventana/mampara)
- 32.3 · Doble vidrio de 2-3 mm, camara de aire >30 mm

**Glass large panes heavy glass**:
- 37.7 · Vidrio de ventana
- 36.3 · Vidrio (ventana/mampara)
- 30.3 · Alfombra pesada sobre espuma de goma

</details>


## Lanas y espumas

| Material del manual | Status | Score | Mejor match en libreria |
|---|:---:|---:|---|
| 25 mm fibreglass rigid backing | **SIMILAR** | 51 | Lana de vidrio 50 mm, 25 kg/m3 |
| 2.54 cm fibreglass 24-48 kg/m3 | **SIMILAR** | 48 | Lana de vidrio 50 mm, 25 kg/m3 |
| 2.5 cm fibreglass 2.5 cm airspace | **FALTA** | 37 | (sin coincidencia) |
| 2.1 cm fibreglass rigid backing | **FALTA** | 39 | (sin coincidencia) |
| 5 cm fibreglass rigid backing | **FALTA** | 39 | (sin coincidencia) |
| 7.5 cm fibreglass rigid backing | **FALTA** | 39 | (sin coincidencia) |
| 10 cm fibreglass rigid backing | **FALTA** | 38 | (sin coincidencia) |
| 5 cm mineral wool 40 kg/m3 glued to wall | **SIMILAR** | 48 | Lana de vidrio 40 mm, 25 kg/m3 |
| 5 cm mineral wool 40 kg/m3 with thin plastic solution | **SIMILAR** | 45 | Lana de vidrio 40 mm, 25 kg/m3 |
| 5 cm mineral wool 70 kg/m3 30cm in front of wall | **FALTA** | 35 | (sin coincidencia) |
| 5 cm wood-wool set in mortar | **MATCH** | 62 | Madera |
| 5.1 cm fibreglass panels with plastic sheet wrapping | **FALTA** | 37 | (sin coincidencia) |
| 5.1 cm fibreglass 24-48 kg/m3 | **SIMILAR** | 49 | Lana de vidrio 100 mm, 25 kg/m3 |
| Acoustic tile 1.27 cm thick | **FALTA** | 37 | (sin coincidencia) |

<details>
<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>


**25 mm fibreglass rigid backing**:
- 51.4 · Lana de vidrio 50 mm, 25 kg/m3
- 51.4 · Lana de vidrio 20 mm, 25 kg/m3
- 50.7 · Lana de vidrio 80 mm, 25 kg/m3

**2.54 cm fibreglass 24-48 kg/m3**:
- 47.6 · Lana de vidrio 50 mm, 25 kg/m3
- 47.6 · Lana de vidrio 50 mm, 18 kg/m3
- 47.6 · Lana de vidrio 40 mm, 25 kg/m3

**2.5 cm fibreglass 2.5 cm airspace**:
- 37.5 · Lana de vidrio 50 mm, 25 kg/m3
- 36.8 · Lana de vidrio 50 mm, 18 kg/m3
- 36.4 · Lana de roca 25 mm, 57 kg/m3, con velo de fibra de vidrio

**2.1 cm fibreglass rigid backing**:
- 39.3 · Aglomerado con respaldo de lana mineral
- 35.8 · Vidrio de ventana
- 34.4 · Vidrio (ventana/mampara)

**5 cm fibreglass rigid backing**:
- 39.5 · Aglomerado con respaldo de lana mineral
- 36.1 · Vidrio de ventana
- 34.6 · Vidrio (ventana/mampara)

**7.5 cm fibreglass rigid backing**:
- 39.3 · Aglomerado con respaldo de lana mineral
- 35.8 · Vidrio de ventana
- 34.4 · Vidrio (ventana/mampara)

**10 cm fibreglass rigid backing**:
- 38.3 · Aglomerado con respaldo de lana mineral
- 35.2 · Vidrio de ventana
- 33.8 · Vidrio (ventana/mampara)

**5 cm mineral wool 40 kg/m3 glued to wall**:
- 47.6 · Lana de vidrio 40 mm, 25 kg/m3
- 47.6 · Lana de vidrio 40 mm, 18 kg/m3
- 46.6 · Lana de roca 40 mm, 81 kg/m3

**5 cm mineral wool 40 kg/m3 with thin plastic solution**:
- 45.4 · Lana de vidrio 40 mm, 25 kg/m3
- 45.4 · Lana de vidrio 40 mm, 18 kg/m3
- 44.6 · Lana de roca 40 mm, 81 kg/m3

**5 cm mineral wool 70 kg/m3 30cm in front of wall**:
- 35.3 · Cielorraso acustico (lana de roca), 40 mm, 70 kg/m3, suspendido a 50 mm
- 35.3 · Cielorraso acustico (lana de roca), 20 mm, 70 kg/m3, suspendido a 50 mm
- 35.3 · Cielorraso acustico (lana de roca), 40 mm, 70 kg/m3, suspendido a 200 mm

**5.1 cm fibreglass panels with plastic sheet wrapping**:
- 36.8 · Sillas de plastico
- 34.8 · Panel de contrachapado, 1 cm de espesor
- 33.0 · Vidrio (ventana/mampara)

**5.1 cm fibreglass 24-48 kg/m3**:
- 48.7 · Lana de vidrio 100 mm, 25 kg/m3
- 48.7 · Lana de vidrio 100 mm, 18 kg/m3
- 48.2 · Lana de vidrio 80 mm, 25 kg/m3

**Acoustic tile 1.27 cm thick**:
- 37.3 · Absorcion del 27%
- 37.0 · Yeso acustico
- 36.7 · Puerta acustica

</details>


---


## Lista de materiales que parecen faltar

Estos son los materiales del manual donde el mejor match de la libreria tiene score < 40. Si los necesitas para tus simulaciones, conviene agregarlos a la carpeta `materials/` como JSON.

| # | Material del manual | Score mejor candidato | Mejor candidato |
|---:|---|---:|---|
| 1 | Acoustic tile, 1.9 cm thick | 38 | Yeso acustico |
| 2 | Polyurethane foam, 2.5 cm thick | 24 | Panel de contrachapado, 1 cm de espesor |
| 3 | Ballast or other crushed stone, 3.18 cm, 15.2 cm deep | 35 | Absorcion del 18% |
| 4 | Ballast or other crushed stone, 3.18 cm, 30.5 cm deep | 35 | Absorcion del 30% |
| 5 | Ballast or other crushed stone, 3.18 cm, 45.7 cm deep | 35 | Absorcion del 45% |
| 6 | Ballast or other crushed stone, 0.64 cm, 15.2 cm deep | 35 | Absorcion del 64% |
| 7 | Hybrid absorber-diffuser BAD panel on 2.5 cm fibreglass | 37 | Panel de contrachapado, 1 cm de espesor |
| 8 | 2D N=7 QRD, design freq 500 Hz | 8 | Lana de roca 50 mm, 30 kg/m3 |
| 9 | 2D N=7 QRD with cloth covering | 7 | Hilado de lana de oveja copetudo |
| 10 | 1D N=7 QRD, design freq 500 Hz | 8 | Lana de roca 50 mm, 30 kg/m3 |
| 11 | 1D N=7 QRD with cloth covering | 7 | Hilado de lana de oveja copetudo |
| 12 | Curtains in folds against wall | 32 | Cortinas colgadas rectas |
| 13 | Needle felt 5mm stuck to concrete | 34 | Parquet sobre hormigon |
| 14 | Marble or glazed tile | 37 | Piso de marmol |
| 15 | Plywood hardwood air space | 24 | Panel de contrachapado, 1 cm de espesor |
| 16 | Clinker concrete no surface finish 800 kg/m3 | 32 | Hormigón visto |
| 17 | Breeze block | 36 | Bloque de hormigon, rugoso |
| 18 | Lime cement plaster | 39 | Yeso acustico |
| 19 | Plaster gypsum or lime rough finish on lath | 33 | Yeso acustico |
| 20 | Floor boards on joist floor | 38 | Piso de marmol |
| 21 | Floors concrete or terrazzo | 39 | Piso de madera |
| 22 | Layer of rubber cork linoleum and underlay | 35 | Baldosas de corcho |
| 23 | Cork lino or rubber tile on solid floor | 35 | Piso de marmol |
| 24 | Slate | 8 | Sillas de madera |
| 25 | Average of nine modern seating designs 0.9m row | 33 | Asientos tapizados |
| 26 | One seat type 0.8m row spacing | 9 | Bancos de madera (75% de ocupacion) |
| 27 | Same seat 0.9m row spacing | 10 | Sillas de madera (100% de ocupacion) |
| 28 | Same seat 1m row spacing | 10 | Sillas de madera (100% de ocupacion) |
| 29 | Plaster gypsum or lime smooth finish on lath | 36 | Ladrillos lisos |
| 30 | Plaster on laths studs air space | 38 | Placa de yeso clavada a montantes |
| 31 | Gypsum board 1.27 cm nailed to studs 4.1 m c-t-c | 37 | Placa de yeso clavada a montantes |
| 32 | Double glazing 2-3mm glass 1cm gap | 35 | Vidrio de ventana |
| 33 | Double glazing 2-3mm glass >3cm gap | 35 | Vidrio de ventana |
| 34 | Glass large panes heavy glass | 38 | Vidrio de ventana |
| 35 | 2.5 cm fibreglass 2.5 cm airspace | 37 | Lana de vidrio 50 mm, 25 kg/m3 |
| 36 | 2.1 cm fibreglass rigid backing | 39 | Aglomerado con respaldo de lana mineral |
| 37 | 5 cm fibreglass rigid backing | 39 | Aglomerado con respaldo de lana mineral |
| 38 | 7.5 cm fibreglass rigid backing | 39 | Aglomerado con respaldo de lana mineral |
| 39 | 10 cm fibreglass rigid backing | 38 | Aglomerado con respaldo de lana mineral |
| 40 | 5 cm mineral wool 70 kg/m3 30cm in front of wall | 35 | Cielorraso acustico (lana de roca), 40 mm, 70 kg/m3, suspendido a 50 mm |
| 41 | 5.1 cm fibreglass panels with plastic sheet wrapping | 37 | Sillas de plastico |
| 42 | Acoustic tile 1.27 cm thick | 37 | Absorcion del 27% |


## Como agregar materiales faltantes

Cada archivo `.json` en `materials/` define UN material o un ARRAY de materiales. Formato minimo:

```json
{
  "name": "Mi material",
  "category": "Difusores",
  "source": "Cox & D'Antonio, Acoustic Absorbers and Diffusers, A.1",
  "absorption_coef": [0.17, 0.17, 0.40, 0.86, 1.00, 0.84, 0.61, 0.61]
}
```

Los 8 valores corresponden a las bandas **63 / 125 / 250 / 500 / 1000 / 2000 / 4000 / 8000 Hz**. Si el manual da solo 6 bandas (125 – 4000 Hz), conviene **extrapolar** o repetir el primer y el ultimo valor para 63 y 8000 Hz respectivamente (el software interpola en escala log).

Despues, en la pestana Acustica del software, apretar **Recargar materiales** y los nuevos aparecen disponibles en el dialogo de Materiales.
