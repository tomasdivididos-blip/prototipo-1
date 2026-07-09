"""check_materials_coverage.py
================================
Cruza el listado de materiales del manual de referencia (las imagenes que
mando el usuario) contra la libreria interna y reporta cuales estan,
cuales se parecen y cuales faltan.

Estrategia
----------
1. Para cada material objetivo, normalizamos el nombre (minusculas, sin
   acentos, sustitucion de sinonimos en/es).
2. Generamos "tokens semanticos" usando dictionario de equivalencias
   (mineral wool == lana mineral, fibreglass == fibra de vidrio, etc.).
3. Para cada material de la libreria hacemos lo mismo.
4. Comparamos con Jaccard de tokens + difflib ratio.
5. Reportamos: top 3 candidatos por cada material, con score, marcando
   MATCH / SIMILAR / FALTA segun umbrales.

Salida: MATERIALS_COVERAGE.md con el cruce completo.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from material_library import MaterialLibrary


# ---------------------------------------------------------------------------
# Lista de materiales del manual (transcripcion de las 5 imagenes)
# Formato: (categoria_visible, nombre_original, [coefs_125_250_500_1k_2k_4k] | None)
# ---------------------------------------------------------------------------
TARGETS = [
    # --- Image 1: difusores y absorbentes especiales ---
    ("Absorbentes", "Acoustic tile, 1.9 cm thick",
     [0.09, 0.28, 0.78, 0.84, 0.73, 0.64]),
    ("Absorbentes", "Polyurethane foam, 2.5 cm thick",
     [0.16, 0.25, 0.45, 0.84, 0.97, 0.87]),
    ("Ballast", "Ballast or other crushed stone, 3.18 cm, 15.2 cm deep",
     [0.19, 0.23, 0.43, 0.37, 0.58, 0.62]),
    ("Ballast", "Ballast or other crushed stone, 3.18 cm, 30.5 cm deep",
     [0.27, 0.58, 0.48, 0.54, 0.73, 0.63]),
    ("Ballast", "Ballast or other crushed stone, 3.18 cm, 45.7 cm deep",
     [0.41, 0.53, 0.64, 0.84, 0.91, 0.63]),
    ("Ballast", "Ballast or other crushed stone, 0.64 cm, 15.2 cm deep",
     [0.22, 0.64, 0.7, 0.79, 0.88, 0.72]),
    ("Microperforados", "Microperforated absorber, 4 cm cavity",
     [0.08, 0.27, 0.70, 0.35, 0.11, 0.04]),
    ("Microperforados", "Microperforated absorber, 40 cm cavity",
     [0.64, 0.56, 0.41, 0.28, 0.13, 0.06]),
    ("Difusores", "Hybrid absorber-diffuser BAD panel on 2.5 cm fibreglass",
     [0.17, 0.40, 0.86, 1.00, 0.84, 0.61]),
    ("Difusores", "2D N=7 QRD, design freq 500 Hz",
     [0.14, 0.12, 0.14, 0.20, 0.09, 0.12]),
    ("Difusores", "2D N=7 QRD with cloth covering",
     [0.16, 0.17, 0.28, 0.41, 0.26, 0.3]),
    ("Difusores", "1D N=7 QRD, design freq 500 Hz",
     [0.11, 0.1, 0.07, 0.08, 0.06, 0.06]),
    ("Difusores", "1D N=7 QRD with cloth covering",
     [0.17, 0.16, 0.2, 0.2, 0.24, 0.23]),

    # --- Image 2: Cortinas y alfombras ---
    ("Cortinas", "Light velour 0.338 kg/m2 hung straight in contact with wall",
     [0.04, 0.05, 0.11, 0.18, 0.30, 0.35]),
    ("Cortinas", "Medium velour 0.475 kg/m2 hung straight",
     [0.05, 0.07, 0.13, 0.22, 0.32, 0.35]),
    ("Cortinas", "Medium velour 0.475 kg/m2 draped to half area",
     [0.07, 0.31, 0.49, 0.75, 0.70, 0.60]),
    ("Cortinas", "Heavy velour 0.61 kg/m2 hung straight",
     [0.05, 0.12, 0.35, 0.48, 0.38, 0.36]),
    ("Cortinas", "Heavy velour 0.61 kg/m2 draped to half area",
     [0.14, 0.35, 0.55, 0.77, 0.70, 0.60]),
    ("Cortinas", "Cortinas hung straight",
     [0.04, 0.16, 0.19, 0.17, 0.20, 0.25]),
    ("Cortinas", "Cortinas draped to half area",
     [0.15, 0.25, 0.30, 0.28, 0.35, 0.40]),
    ("Cortinas", "Cortinas draped to 40% of area",
     [0.19, 0.31, 0.35, 0.34, 0.44, 0.50]),
    ("Cortinas", "Curtains in folds against wall",
     [0.05, 0.15, 0.35, 0.40, 0.50, 0.50]),
    ("Cortinas", "Cotton curtains 0.475 kg/m2 draped to 7/8 area",
     [0.03, 0.12, 0.15, 0.27, 0.37, 0.42]),
    ("Cortinas", "Cotton curtains 0.475 kg/m2 draped to 3/4 area",
     [0.04, 0.23, 0.40, 0.57, 0.53, 0.40]),
    ("Cortinas", "Cotton curtains 0.475 kg/m2 draped to 1/2 area",
     [0.07, 0.37, 0.49, 0.81, 0.65, 0.54]),

    ("Alfombras", "Carpet heavy on concrete",
     [0.02, 0.06, 0.14, 0.37, 0.60, 0.65]),
    ("Alfombras", "Heavy carpet on foam rubber or hair felt 1.35 kg/m2",
     [0.08, 0.24, 0.57, 0.69, 0.71, 0.73]),
    ("Alfombras", "Heavy carpet with latex backing on foam rubber or hair felt",
     [0.08, 0.27, 0.39, 0.34, 0.48, 0.63]),
    ("Alfombras", "Haircord on felt",
     [0.10, 0.15, 0.25, 0.30, 0.30, 0.30]),
    ("Alfombras", "Pile and thick felt",
     [0.07, 0.25, 0.50, 0.50, 0.60, 0.65]),
    ("Alfombras", "Woven wool loop carpet 1.2 kg/m2 2.4mm pile no underlay",
     [0.10, 0.16, 0.11, 0.30, 0.50, 0.47]),
    ("Alfombras", "Woven wool loop carpet 1.4 kg/m2 6.4mm pile no underlay",
     [0.15, 0.10, 0.12, 0.32, 0.52, 0.57]),
    ("Alfombras", "Woven wool loop carpet 2.3 kg/m2 9.5mm pile no underlay",
     [0.17, 0.18, 0.21, 0.50, 0.63, 0.83]),
    ("Alfombras", "Loop pile tufted carpet 1.4 kg/m2 hair underlay",
     [0.03, 0.05, 0.20, 0.55, 0.70, 0.62]),
    ("Alfombras", "Loop pile tufted carpet 1.4 kg/m2 hair underlay 3 kg/m2",
     [0.10, 0.40, 0.62, 0.70, 0.63, 0.88]),
    ("Alfombras", "Loop pile tufted carpet 1.4 kg/m2 hair and jute underlay 3 kg/m2",
     [0.20, 0.50, 0.68, 0.72, 0.65, 0.90]),
    ("Alfombras", "Loop pile tufted carpet 1.4 kg/m2 no underlay",
     [0.04, 0.05, 0.17, 0.33, 0.59, 0.75]),
    ("Alfombras", "Loop pile tufted carpet 0.7 kg/m2 1.4 kg/m2 hair underlay",
     [0.10, 0.19, 0.35, 0.79, 0.69, 0.79]),
    ("Alfombras", "16mm wool pile with underlay",
     [0.20, 0.25, 0.35, 0.40, 0.50, 0.75]),
    ("Alfombras", "9.5mm wool pile no underlay on concrete",
     [0.09, 0.08, 0.21, 0.26, 0.27, 0.37]),
    ("Alfombras", "Cord carpet",
     [0.05, 0.05, 0.10, 0.20, 0.45, 0.65]),
    ("Alfombras", "Thin 6mm carpet on underlay",
     [0.03, 0.09, 0.20, 0.54, 0.70, 0.72]),
    ("Alfombras", "6mm pile carpet bonded to closed-cell foam underlay",
     [0.03, 0.09, 0.25, 0.31, 0.33, 0.44]),
    ("Alfombras", "Thick 9mm carpet on underlay",
     [0.08, 0.08, 0.30, 0.60, 0.75, 0.80]),
    ("Alfombras", "Needle felt 5mm stuck to concrete",
     [0.02, 0.02, 0.05, 0.15, 0.30, 0.40]),
    ("Alfombras", "Thin carpet cemented to concrete",
     [0.02, 0.04, 0.08, 0.20, 0.35, 0.4]),

    # --- Image 3: Mobiliario, agua, madera, hormigon, ladrillo, yeso ---
    ("Mobiliario", "Orchestra with instruments 1.5 m2/person",
     [0.27, 0.53, 0.67, 0.93, 0.87, 0.8]),
    ("Mobiliario", "Wooden pews 100% occupancy",
     [0.57, 0.61, 0.75, 0.86, 0.91, 0.86]),
    ("Mobiliario", "Wooden chairs 100% occupancy",
     [0.60, 0.74, 0.88, 0.96, 0.93, 0.85]),
    ("Mobiliario", "Wooden pews 75% occupancy",
     [0.46, 0.56, 0.65, 0.75, 0.72, 0.65]),
    ("Misc", "Water surface in swimming pool",
     [0.01, 0.01, 0.01, 0.02, 0.02, 0.02]),
    ("Misc", "Marble or glazed tile",
     [0.01, 0.01, 0.01, 0.01, 0.02, 0.02]),
    ("Madera", "Solid wooden door",
     [0.14, 0.10, 0.06, 0.08, 0.10, 0.10]),
    ("Misc", "Ventilation grille",
     [0.60, 0.60, 0.60, 0.60, 0.60, 0.60]),
    ("Madera", "Plywood panelling 1 cm thick",
     [0.28, 0.22, 0.17, 0.09, 0.10, 0.11]),
    ("Madera", "22 mm chipboard 50 mm cavity filled with mineral wool",
     [0.12, 0.04, 0.06, 0.05, 0.05, 0.05]),
    ("Madera", "3-4 mm plywood sheets >75 mm cavity 25-50 mm mineral wool",
     [0.50, 0.30, 0.10, 0.05, 0.05, 0.05]),
    ("Madera", "Plywood hardwood air space",
     [0.32, 0.43, 0.12, 0.10, 0.07, 0.11]),
    ("Madera", "6 mm wood fibreboard on laths cavity >100 mm deep",
     [0.30, 0.20, 0.20, 0.10, 0.10, 0.05]),
    ("Madera", "Fibreboard solid backing",
     [0.05, 0.1, 0.15, 0.25, 0.3, 0.3]),
    ("Madera", "Fibreboard 25 mm air space",
     [0.3, 0.3, 0.3, 0.3, 0.3, 0.3]),
    ("Madera", "Wood panelling 9.5-12.7 mm 5-10 cm air space",
     [0.30, 0.25, 0.20, 0.17, 0.15, 0.10]),
    ("Madera", "Wood 50 mm thick",
     [0.01, 0.05, 0.05, 0.04, 0.04, 0.04]),

    ("Rigidos", "Rough concrete",
     [0.02, 0.03, 0.03, 0.03, 0.04, 0.07]),
    ("Rigidos", "Smooth unpainted concrete",
     [0.01, 0.01, 0.02, 0.02, 0.02, 0.05]),
    ("Rigidos", "Smooth concrete painted or glazed",
     [0.01, 0.01, 0.01, 0.02, 0.02, 0.02]),
    ("Rigidos", "Concrete block coarse",
     [0.36, 0.44, 0.31, 0.29, 0.39, 0.25]),
    ("Rigidos", "Concrete block painted",
     [0.10, 0.05, 0.06, 0.07, 0.09, 0.08]),
    ("Rigidos", "Porous concrete blocks 400-800 kg/m3",
     [0.05, 0.05, 0.05, 0.08, 0.14, 0.20]),
    ("Rigidos", "Clinker concrete no surface finish 800 kg/m3",
     [0.10, 0.20, 0.40, 0.60, 0.50, 0.60]),

    ("Ladrillo", "Brick unglazed",
     [0.03, 0.03, 0.03, 0.04, 0.05, 0.07]),
    ("Ladrillo", "Brickwork plain painted",
     [0.05, 0.04, 0.02, 0.04, 0.05, 0.05]),
    ("Ladrillo", "Smooth brickwork with flush pointing painted",
     [0.01, 0.01, 0.02, 0.02, 0.02, 0.02]),
    ("Ladrillo", "Brick unglazed painted",
     [0.01, 0.01, 0.02, 0.02, 0.02, 0.03]),
    ("Ladrillo", "Smooth brickwork with flush pointing",
     [0.02, 0.03, 0.03, 0.04, 0.05, 0.07]),
    ("Ladrillo", "Smooth brickwork 10 mm deep pointing pit sand mortar",
     [0.08, 0.09, 0.12, 0.16, 0.22, 0.24]),
    ("Ladrillo", "Breeze block",
     [0.2, 0.3, 0.6, 0.6, 0.5, 0.5]),

    ("Yeso", "Lime cement plaster",
     [0.02, 0.02, 0.03, 0.04, 0.05, 0.05]),
    ("Yeso", "Glaze plaster",
     [0.01, 0.01, 0.01, 0.02, 0.02, 0.02]),
    ("Yeso", "Painted plaster surface",
     [0.02, 0.02, 0.02, 0.02, 0.02, 0.02]),
    ("Yeso", "Plaster with wallpaper on backing paper",
     [0.02, 0.03, 0.04, 0.05, 0.07, 0.08]),
    ("Yeso", "Plaster gypsum or lime rough finish on lath",
     [0.02, 0.03, 0.04, 0.05, 0.04, 0.03]),

    # --- Image 4 (continued) ---
    ("Suelos", "Wood block lino or rubber flooring",
     [0.02, 0.04, 0.05, 0.05, 0.1, 0.05]),
    ("Suelos", "Parquet fixed with asphalt on concrete",
     [0.04, 0.04, 0.07, 0.06, 0.06, 0.07]),
    ("Suelos", "Wood on solid floor",
     [0.04, 0.04, 0.03, 0.03, 0.03, 0.02]),
    ("Suelos", "Floors wood",
     [0.15, 0.11, 0.10, 0.07, 0.06, 0.07]),
    ("Suelos", "Wood platform large airspace below",
     [0.40, 0.30, 0.20, 0.17, 0.15, 0.10]),
    ("Suelos", "Floor boards on joist floor",
     [0.15, 0.20, 0.10, 0.10, 0.10, 0.10]),
    ("Suelos", "Floors concrete or terrazzo",
     [0.01, 0.01, 0.015, 0.02, 0.02, 0.02]),
    ("Suelos", "Linoleum or vinyl stuck to concrete",
     [0.02, 0.02, 0.03, 0.04, 0.04, 0.05]),
    ("Suelos", "Linoleum asphalt tile or cork tile on concrete",
     [0.02, 0.03, 0.03, 0.03, 0.03, 0.02]),
    ("Suelos", "Layer of rubber cork linoleum and underlay",
     [0.02, 0.02, 0.04, 0.05, 0.05, 0.10]),
    ("Suelos", "Cork lino or rubber tile on solid floor",
     [0.04, 0.03, 0.04, 0.04, 0.03, 0.02]),
    ("Suelos", "25 mm cork on solid backing",
     [0.05, 0.1, 0.2, 0.55, 0.6, 0.55]),
    ("Suelos", "Slate",
     [0.01, 0.01, 0.01, 0.02, 0.02, 0.02]),

    ("Asientos", "Theatre seating unoccupied Beranek values",
     [0.19, 0.37, 0.56, 0.67, 0.61, 0.59]),
    ("Asientos", "Average of nine modern seating designs 0.9m row",
     [0.34, 0.46, 0.64, 0.71, 0.77, 0.85]),
    ("Asientos", "One seat type 0.8m row spacing",
     [0.29, 0.39, 0.61, 0.74, 0.83, 0.88]),
    ("Asientos", "Same seat 0.9m row spacing",
     [0.25, 0.35, 0.58, 0.70, 0.78, 0.84]),
    ("Asientos", "Same seat 1m row spacing",
     [0.23, 0.34, 0.52, 0.65, 0.73, 0.75]),
    ("Asientos", "Upholstered seating",
     [0.45, 0.60, 0.73, 0.80, 0.75, 0.64]),
    ("Asientos", "Upholstered seating well upholstered",
     [0.44, 0.60, 0.77, 0.89, 0.82, 0.70]),
    ("Asientos", "Upholstered seating leather covered",
     [0.40, 0.50, 0.58, 0.61, 0.58, 0.50]),
    ("Asientos", "Occupied theatre seating average",
     [0.41, 0.58, 0.80, 0.90, 0.92, 0.89]),
    ("Asientos", "Audience on timber seats 1/m2",
     [0.16, 0.24, 0.56, 0.69, 0.81, 0.78]),
    ("Asientos", "Audience on timber seats 2/m2",
     [0.24, 0.4, 0.78, 0.98, 0.96, 0.87]),

    # --- Image 5 (continued) plaster, glazing, mineral wools ---
    ("Yeso", "Plaster gypsum or lime smooth finish on lath",
     [0.14, 0.1, 0.06, 0.04, 0.04, 0.03]),
    ("Yeso", "Plaster on laths studs air space",
     [0.3, 0.1, 0.1, 0.05, 0.04, 0.05]),
    ("Yeso", "Plaster gypsum or lime smooth finish on tile or brick",
     [0.013, 0.015, 0.02, 0.03, 0.04, 0.05]),
    ("Yeso", "Plaster lime of gypsum on solid backing",
     [0.03, 0.03, 0.02, 0.03, 0.04, 0.05]),
    ("Yeso", "Acoustic plaster",
     [0.30, 0.35, 0.5, 0.7, 0.7, 0.7]),
    ("Yeso", "Acoustic plaster 40 mm thick",
     [0.31, 0.55, 0.84, 0.78, 0.71, 0.54]),
    ("Yeso", "Acoustic plaster 68 mm thick",
     [0.47, 0.74, 0.76, 0.65, 0.62, 0.49]),
    ("Yeso", "Gypsum board 1.27 cm nailed to studs 4.1 m c-t-c",
     [0.29, 0.1, 0.05, 0.04, 0.07, 0.09]),
    ("Yeso", "Plasterboard on frame 9.5mm boards 10cm empty cavity",
     [0.11, 0.13, 0.06, 0.05, 0.05, 0.05]),
    ("Yeso", "Plasterboard on frame 9.5mm boards 10cm cavity mineral wool",
     [0.28, 0.14, 0.09, 0.06, 0.05, 0.05]),
    ("Yeso", "Plasterboard on frame 13mm boards 10cm empty cavity",
     [0.08, 0.11, 0.05, 0.03, 0.02, 0.05]),
    ("Yeso", "Plasterboard on frame 13mm boards 10cm cavity mineral wool",
     [0.30, 0.12, 0.08, 0.06, 0.06, 0.05]),
    ("Yeso", "2x13mm plasterboard on steel frame 5cm mineral wool",
     [0.15, 0.10, 0.06, 0.04, 0.04, 0.05]),

    ("Vidrio", "Glass ordinary window glass",
     [0.35, 0.25, 0.18, 0.12, 0.07, 0.04]),
    ("Vidrio", "Single pane of glass 3-4mm",
     [0.2, 0.15, 0.1, 0.07, 0.05, 0.05]),
    ("Vidrio", "Single pane of glass >4mm",
     [0.1, 0.07, 0.05, 0.03, 0.02, 0.02]),
    ("Vidrio", "Single pane of glass 3mm",
     [0.08, 0.04, 0.03, 0.03, 0.02, 0.02]),
    ("Vidrio", "Double glazing 2-3mm glass 1cm gap",
     [0.10, 0.07, 0.05, 0.03, 0.02, 0.02]),
    ("Vidrio", "Double glazing 2-3mm glass >3cm gap",
     [0.15, 0.05, 0.03, 0.03, 0.02, 0.02]),
    ("Vidrio", "Glass large panes heavy glass",
     [0.18, 0.06, 0.04, 0.03, 0.02, 0.02]),

    ("Lanas y espumas", "25 mm fibreglass rigid backing",
     [0.08, 0.25, 0.45, 0.75, 0.75, 0.65]),
    ("Lanas y espumas", "2.54 cm fibreglass 24-48 kg/m3",
     [0.08, 0.25, 0.65, 0.85, 0.8, 0.75]),
    ("Lanas y espumas", "2.5 cm fibreglass 2.5 cm airspace",
     [0.15, 0.55, 0.8, 0.9, 0.85, 0.8]),
    ("Lanas y espumas", "2.1 cm fibreglass rigid backing",
     [0.21, 0.50, 0.75, 0.90, 0.85, 0.80]),
    ("Lanas y espumas", "5 cm fibreglass rigid backing",
     [0.35, 0.50, 0.80, 0.90, 0.85, 0.80]),
    ("Lanas y espumas", "7.5 cm fibreglass rigid backing",
     [0.50, 0.80, 0.95, 1.00, 0.95, 0.90]),
    ("Lanas y espumas", "10 cm fibreglass rigid backing",
     [0.45, 0.95, 1.00, 0.95, 0.90, 0.85]),
    ("Lanas y espumas", "5 cm mineral wool 40 kg/m3 glued to wall",
     [0.15, 0.70, 0.60, 0.60, 0.85, 0.90]),
    ("Lanas y espumas", "5 cm mineral wool 40 kg/m3 with thin plastic solution",
     [0.15, 0.70, 0.65, 0.60, 0.75, 0.75]),
    ("Lanas y espumas", "5 cm mineral wool 70 kg/m3 30cm in front of wall",
     [0.70, 0.45, 0.65, 0.60, 0.75, 0.65]),
    ("Lanas y espumas", "5 cm wood-wool set in mortar",
     [0.08, 0.17, 0.35, 0.45, 0.65, 0.65]),
    ("Lanas y espumas", "5.1 cm fibreglass panels with plastic sheet wrapping",
     [0.33, 0.79, 0.99, 0.91, 0.76, 0.64]),
    ("Lanas y espumas", "5.1 cm fibreglass 24-48 kg/m3",
     [0.17, 0.55, 0.8, 0.9, 0.85, 0.8]),
    ("Lanas y espumas", "Acoustic tile 1.27 cm thick",
     [0.07, 0.21, 0.66, 0.75, 0.62, 0.49]),
]


# ---------------------------------------------------------------------------
# Normalizacion: sinonimos en/es + tokens semanticos
# ---------------------------------------------------------------------------
SYNONYMS = {
    # Materiales
    "fibreglass": "lana_vidrio",
    "fiberglass": "lana_vidrio",
    "fibra_vidrio": "lana_vidrio",
    "glass_wool": "lana_vidrio",
    "lana_vidrio": "lana_vidrio",
    "mineral_wool": "lana_mineral",
    "rockwool": "lana_mineral",
    "lana_mineral": "lana_mineral",
    "lana_roca": "lana_mineral",
    "concrete": "hormigon",
    "hormigon": "hormigon",
    "brick": "ladrillo",
    "ladrillo": "ladrillo",
    "brickwork": "ladrillo",
    "carpet": "alfombra",
    "alfombra": "alfombra",
    "curtain": "cortina",
    "curtains": "cortina",
    "drape": "cortina",
    "drapes": "cortina",
    "cortina": "cortina",
    "wood": "madera",
    "wooden": "madera",
    "madera": "madera",
    "plywood": "contrachapado",
    "contrachapado": "contrachapado",
    "chipboard": "aglomerado",
    "fibreboard": "fibra_madera",
    "fiberboard": "fibra_madera",
    "plaster": "yeso",
    "gypsum": "yeso",
    "yeso": "yeso",
    "plasterboard": "placa_yeso",
    "glass": "vidrio",
    "vidrio": "vidrio",
    "foam": "espuma",
    "espuma": "espuma",
    "polyurethane": "poliuretano",
    "tile": "baldosa",
    "baldosa": "baldosa",
    "audience": "audiencia",
    "seating": "asientos",
    "pew": "banco",
    "pews": "banco",
    "chair": "silla",
    "chairs": "silla",
    "upholstered": "tapizado",
    "orchestra": "orquesta",
    "linoleum": "linoleo",
    "cork": "corcho",
    "rubber": "goma",
    "slate": "pizarra",
    "marble": "marmol",
    "parquet": "parquet",
    "felt": "fieltro",
    "diffuser": "difusor",
    "qrd": "qrd",
    "bad": "bad_panel",
    "microperforated": "microperforado",
    # descriptores
    "thick": "grueso",
    "thin": "delgado",
    "heavy": "pesado",
    "light": "ligero",
    "smooth": "liso",
    "rough": "rugoso",
    "painted": "pintado",
    "unpainted": "sin_pintar",
    "unglazed": "sin_esmaltar",
    "glazed": "esmaltado",
    "underlay": "base",
    "backing": "respaldo",
    "rigid": "rigido",
    "cavity": "cavidad",
    "filled": "relleno",
    "empty": "vacio",
    "covering": "recubrimiento",
    "covered": "recubierto",
    "occupied": "ocupado",
    "unoccupied": "desocupado",
    "occupancy": "ocupacion",
    "panel": "panel",
    "panelling": "paneles",
    "panels": "paneles",
    "sheet": "lamina",
    "sheets": "lamina",
    "frame": "marco",
    "studs": "perfiles",
    "joist": "viga",
    "floor": "piso",
    "floors": "piso",
    "ceiling": "techo",
    "wall": "pared",
    "door": "puerta",
    "ventilation": "ventilacion",
    "grille": "rejilla",
    "water": "agua",
    "swimming": "piscina",
    "pool": "piscina",
    "ballast": "balasto",
    "stone": "piedra",
    "crushed": "triturado",
    "loop": "bucle",
    "pile": "pelo",
    "tufted": "tufting",
    "needle": "aguja",
    "haircord": "haircord",
    "velour": "velour",
    "cotton": "algodon",
    "wool": "lana",
    "woven": "tejido",
    "draped": "drapeado",
    "hung": "colgado",
    "straight": "recto",
    "folds": "pliegues",
    "deep": "profundo",
    "row": "fila",
    "spacing": "separacion",
    "theatre": "teatro",
    "modern": "moderno",
    "beranek": "beranek",
    "leather": "cuero",
    "well": "bien",
    "design": "diseno",
    "frequency": "frecuencia",
    "freq": "frecuencia",
    "hz": "hz",
    "kg": "kg",
    "m2": "m2",
    "m3": "m3",
    "mm": "mm",
    "cm": "cm",
    "thickness": "espesor",
    "rigida": "rigido",
    "absorber": "absorbedor",
    "absorbente": "absorbedor",
    "absorption": "absorcion",
    # Variantes espanol que aparecen en la libreria (stems mas comunes)
    "drapeada": "drapeado",
    "drapeadas": "drapeado",
    "colgada": "colgado",
    "colgadas": "colgado",
    "colgadar": "colgado",   # stem
    "drapead": "drapeado",
    "colgad": "colgado",
    "pesad": "pesado",
    "pesada": "pesado",
    "pesadas": "pesado",
    "lisos": "liso",
    "lisas": "liso",
    "rugosa": "rugoso",
    "pintada": "pintado",
    "pintadas": "pintado",
    "pintad": "pintado",
    "ocupada": "ocupado",
    "ocupadas": "ocupado",
    "ocupad": "ocupado",
    "desocupada": "desocupado",
    "desocupadas": "desocupado",
    "tapizada": "tapizado",
    "tapizadas": "tapizado",
    "tapizad": "tapizado",
    "delgada": "delgado",
    "delgadas": "delgado",
    "gruesa": "grueso",
    "gruesas": "grueso",
    "fina": "fino",
    "finas": "fino",
    "ligera": "ligero",
    "ligeras": "ligero",
    "semipesada": "semipesado",
    "terciopelo": "velour",
    "terciopel": "velour",
    "velvet": "velour",
    # estructura y construccion
    "bastidor": "marco",
    "montante": "perfiles",
    "montantes": "perfiles",
    "camara": "cavidad",
    "esmaltado": "esmaltado",
    "esmaltada": "esmaltado",
    "esmaltadas": "esmaltado",
    "esmaltados": "esmaltado",
    "revoque": "yeso",
    "revocada": "yeso",
    "revocado": "yeso",
    "mamposteria": "ladrillo",
    "bloque": "bloque",
    "bloques": "bloque",
    "tablero": "fibra_madera",
    "tableros": "fibra_madera",
    "aglomerado": "aglomerado",
    "contrachapado": "contrachapado",
    "espesor": "espesor",
    "cielorraso": "techo",
    "cielo": "techo",
    "suspendido": "suspendido",
    "suspendida": "suspendido",
    # Pieces / mobiliario / asientos
    "audiencia": "audiencia",
    "audiencias": "audiencia",
    "publico": "audiencia",
    "espectadores": "audiencia",
    "silla": "silla",
    "sillas": "silla",
    "banco": "banco",
    "bancos": "banco",
    "asiento": "asientos",
    "asientos": "asientos",
    "concierto": "concierto",
    "teatro": "teatro",
    "auditorio": "teatro",
    "orquesta": "orquesta",
    "tela": "tela",
    "cubierto": "tapizado",
    "cubierta": "tapizado",
    "cubiertos": "tapizado",
    "cubiertas": "tapizado",
    "cuero": "cuero",
    # Pisos
    "piso": "piso",
    "pisos": "piso",
    "suelo": "piso",
    "suelos": "piso",
    "fieltro": "fieltro",
    "fieltros": "fieltro",
    "corcho": "corcho",
    "lana_roca": "lana_mineral",
    "lana": "lana",
    "vinilo": "vinilo",
    "linoleo": "linoleo",
    "marmol": "marmol",
    "pizarra": "pizarra",
    "parquet": "parquet",
    "asfalto": "asfalto",
    "goma": "goma",
    "esponjosa": "esponjoso",
    "esponjoso": "esponjoso",
    "celda": "celda",
    "abierta": "abierto",
    "cerrada": "cerrado",
    "abierto": "abierto",
    "cerrado": "cerrado",
    "respaldo": "respaldo",
    "respaldos": "respaldo",
    "base": "base",
    "bases": "base",
    "subpiso": "base",
    "puerta": "puerta",
    "puertas": "puerta",
    "nucleo": "nucleo",
    "hueco": "hueco",
    "macizo": "macizo",
    "solido": "solido",
    "solida": "solido",
    "agua": "agua",
    "natacion": "piscina",
    "piscina": "piscina",
    "rejilla": "rejilla",
    "rejillas": "rejilla",
    "ventilacion": "ventilacion",
    "lana_vidrio": "lana_vidrio",
    # Difusores
    "qrd": "qrd",
    "schroeder": "qrd",
    "bad": "bad_panel",
    "bad_panel": "bad_panel",
    "difusor": "difusor",
    "difusores": "difusor",
    # Balasto / piedra
    "balasto": "balasto",
    "piedra": "piedra",
    "piedras": "piedra",
    "triturado": "triturado",
    "triturada": "triturado",
    # Pelo (alfombras)
    "pelo": "pelo",
    "alfombrado": "alfombra",
    "copetudo": "tufted",
    "copetuda": "tufted",
    "haircord": "haircord",
    # vidrio / ventanas
    "window": "ventana",
    "windows": "ventana",
    "ventana": "ventana",
    "ventanas": "ventana",
    "pane": "vidrio",
    "panes": "vidrio",
    "single": "simple",
    "double": "doble",
    "doble": "doble",
    "mampara": "ventana",
    "ordinary": "comun",
    "common": "comun",
    "comun": "comun",
    # otros sinonimos util
    "hair": "fieltro",   # "hair felt" -> fieltro
    "occupancy": "ocupacion",
    "ocupacion": "ocupacion",
    "ocupada": "ocupacion",
    "ocupadas": "ocupacion",
    "platform": "plataforma",
    "asphalt": "asfalto",
    "lath": "listones",
    "laths": "listones",
    "lime": "cal",
    "cement": "cemento",
    "wallpaper": "papel_pared",
    "block": "bloque",
    "blocks": "bloque",
    "breeze": "ceniza",
    "clinker": "clinker",
    "porous": "poroso",
    "coarse": "grueso",
    "fine": "fino",
    "natural": "natural",
    "synthetic": "sintetico",
    "acoustic": "acustico",
    "acustico": "acustico",
    "acoustical": "acustico",
}


_STOPWORDS = {
    # ingles
    "a", "an", "the", "on", "in", "of", "for", "to", "with", "or", "and",
    "from", "as", "is", "by", "at", "above", "below", "behind", "between",
    # espanol
    "el", "la", "los", "las", "de", "del", "en", "con", "sin", "para",
    "por", "y", "o", "u", "un", "una", "sobre", "entre", "ante", "tras",
    "hacia", "desde", "que", "se", "lo", "le", "al", "este", "esta",
    "su", "sus", "mi", "tu", "es", "son", "fue",
}


def normalize(text: str) -> str:
    """Pasa a minusculas, quita acentos y reemplaza separadores."""
    text = text.lower().strip()
    text = "".join(c for c in unicodedata.normalize("NFKD", text)
                    if not unicodedata.combining(c))
    text = re.sub(r"[\(\)\[\]/\.,;:]+", " ", text)
    text = re.sub(r"-", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def stem_es(token: str) -> str:
    """Stemmer espanol/ingles muy simple: quita plurales y terminaciones de
    genero. La idea es que 'pesada', 'pesadas', 'pesados' colapsen a 'pesad'.
    No es perfecto pero alcanza para emparejar.
    """
    if len(token) <= 3:
        return token
    # Plurales: "es" tras consonante o "s" tras vocal
    if len(token) > 4:
        if token.endswith("es") and token[-3] not in "aeiou":
            token = token[:-2]
        elif token.endswith("s") and not token.endswith("us") and not token.endswith("is"):
            token = token[:-1]
    # Genero: final "a"/"o" tras consonante (pesado, pesada -> pesad)
    if len(token) > 4 and token[-1] in "ao" and token[-2] not in "aeiou":
        token = token[:-1]
    # Diminutivos comunes -> quita "ito", "ita"
    if token.endswith(("ito", "ita")) and len(token) > 5:
        token = token[:-3]
    return token


def tokenize(text: str) -> set:
    """Tokeniza con substitucion semantica + stemming.

    Soporta sinonimos COMPUESTOS: una entrada como
    ``"fibreglass": "lana vidrio"`` se expande a DOS tokens ('lana', 'vidrio')
    para que matchee con materiales escritos como "Lana de vidrio 20 mm".

    Pipeline (importante el orden):
      1. Normalize + split
      2. Skip stopwords y tokens muy cortos
      3. Numero con unidad: dejar tal cual
      4. SINONIMO directo (sin stem)
      5. STEM y luego buscar sinonimo del stem
      6. STEM final UNIFORME del resultado de (4) o (5), asi
         'alfombra' (espanol nativo) y 'carpet -> alfombra' (sinonimo) ambos
         colapsan a 'alfombr' (forma canonica usada en la comparacion).
    """
    norm = normalize(text)
    raw = norm.split()
    out = set()
    for t in raw:
        t = re.sub(r"[^\w]", "", t)
        if not t or len(t) < 2:
            continue
        if t in _STOPWORDS:
            continue
        # Numeros con unidad pasan limpios (distinguen '5cm' de '10cm')
        if re.match(r"^\d+(\.\d+)?(mm|cm|m|kg|hz)?$", t):
            out.add(t)
            continue
        # 1) sinonimo directo
        if t in SYNONYMS:
            canonical = SYNONYMS[t]
        else:
            # 2) stem y luego sinonimo
            stemmed = stem_es(t)
            canonical = SYNONYMS.get(stemmed, stemmed)
        # 3) si canonical contiene espacios o "_", expandir a multiples tokens
        for piece in re.split(r"[_\s]+", canonical):
            if not piece:
                continue
            if piece in _STOPWORDS or len(piece) < 2:
                continue
            out.add(stem_es(piece))
    return out


def similarity(target: str, candidate: str) -> float:
    """Score 0-100 combinando varias metricas de tokens.

    Casos:
    - Coincidencia exacta: target = candidate (tokens identicos) -> 100.
    - Candidate es SUBSET del target (libreria con nombre mas conciso
      que el manual): precision = 1, recall < 1, jaccard moderado.
    - Target es SUBSET del candidate: precision < 1, recall = 1.
    - Token muy ruidoso: todos los scores caen.

    El score final usa el MAYOR de precision y recall como senal principal,
    para no penalizar cuando una lista de tokens es mas breve que la otra.
    """
    tt = tokenize(target)
    tc = tokenize(candidate)
    if not tt or not tc:
        return 0.0
    inter = len(tt & tc)
    union = len(tt | tc)
    jaccard = inter / union if union else 0.0
    recall    = inter / len(tt)            # target tokens cubiertos por cand
    precision = inter / len(tc)            # cand tokens cubiertos por target
    coverage  = max(precision, recall)     # "el menor lado encaja"
    sm = SequenceMatcher(None, normalize(target), normalize(candidate)).ratio()
    # Ponderacion final
    return 100.0 * (0.50 * coverage + 0.30 * jaccard + 0.20 * sm)


# ---------------------------------------------------------------------------
# Reporte
# ---------------------------------------------------------------------------
def main():
    ml = MaterialLibrary("materials")
    lib_names = ml.names
    print(f"Libreria: {len(lib_names)} materiales en {len(ml.by_category())} categorias.")
    print(f"Materiales del manual a verificar: {len(TARGETS)}")
    print()

    # Umbrales
    MATCH_THRESHOLD = 55.0      # >= se considera match probable
    SIMILAR_THRESHOLD = 40.0    # entre 40 y 55: similar (revisar)
    # < 40: faltante

    counts = {"match": 0, "similar": 0, "missing": 0}
    rows = []
    for category, target_name, coefs in TARGETS:
        scored = [(similarity(target_name, n), n, i)
                   for i, n in enumerate(lib_names)]
        scored.sort(reverse=True)
        top3 = scored[:3]
        best_score, best_name, best_idx = top3[0]
        if best_score >= MATCH_THRESHOLD:
            status = "MATCH"
            counts["match"] += 1
        elif best_score >= SIMILAR_THRESHOLD:
            status = "SIMILAR"
            counts["similar"] += 1
        else:
            status = "FALTA"
            counts["missing"] += 1
        rows.append({
            "category": category,
            "target": target_name,
            "status": status,
            "best_score": best_score,
            "best_name": best_name,
            "best_alphas": ml[best_idx].alpha_bands() if best_score >= MATCH_THRESHOLD else None,
            "target_alphas": coefs,
            "top3": top3,
        })

    # Resumen
    total = len(TARGETS)
    print(f"  MATCH  (>= {MATCH_THRESHOLD:.0f}): {counts['match']:3d}  "
           f"({counts['match']*100/total:.1f} %)")
    print(f"  SIMILAR ({SIMILAR_THRESHOLD:.0f}-{MATCH_THRESHOLD:.0f}): {counts['similar']:3d}  "
           f"({counts['similar']*100/total:.1f} %)")
    print(f"  FALTA  (< {SIMILAR_THRESHOLD:.0f}): {counts['missing']:3d}  "
           f"({counts['missing']*100/total:.1f} %)")
    print()

    # Construir markdown
    md = []
    md.append("# Cobertura de materiales del manual de referencia\n")
    md.append("Cruza el listado de materiales que mando el usuario "
              f"({total} entradas, 5 imagenes) contra la libreria interna "
              f"({len(lib_names)} materiales).\n")
    md.append("## Resumen\n")
    md.append(f"- **MATCH** (score >= {MATCH_THRESHOLD:.0f}): "
              f"{counts['match']} / {total} "
              f"({counts['match']*100/total:.1f} %) — material reconocido "
              f"con alta confianza.")
    md.append(f"- **SIMILAR** (score {SIMILAR_THRESHOLD:.0f}-{MATCH_THRESHOLD:.0f}): "
              f"{counts['similar']} / {total} "
              f"({counts['similar']*100/total:.1f} %) — hay candidato "
              f"parecido pero conviene revisar.")
    md.append(f"- **FALTA** (score < {SIMILAR_THRESHOLD:.0f}): "
              f"{counts['missing']} / {total} "
              f"({counts['missing']*100/total:.1f} %) — no aparece en la "
              f"libreria, conviene agregarlo.\n")
    md.append("\n### Score: ")
    md.append("ponderado 60 % Jaccard de tokens semanticos + 40 % difflib "
              "ratio. Aplica diccionario de sinonimos en/es "
              "(fibreglass→lana_vidrio, plywood→contrachapado, carpet→alfombra, "
              "etc.). 100 = nombre identico; 50 = comparten la mayoria de "
              "palabras clave.\n")

    # Agrupar por categoria
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    for cat in by_cat:
        md.append(f"\n## {cat}\n")
        md.append("| Material del manual | Status | Score | Mejor match en libreria |")
        md.append("|---|:---:|---:|---|")
        for r in by_cat[cat]:
            md.append(f"| {r['target']} | "
                       f"**{r['status']}** | "
                       f"{r['best_score']:.0f} | "
                       f"{r['best_name'] if r['status'] != 'FALTA' else '(sin coincidencia)'} |")
        # Mostrar top-3 para los FALTA y SIMILAR (para auditoria)
        revisables = [r for r in by_cat[cat] if r["status"] != "MATCH"]
        if revisables:
            md.append("\n<details>")
            md.append("<summary>Top-3 candidatos de los items SIMILAR o FALTA</summary>\n")
            for r in revisables:
                md.append(f"\n**{r['target']}**:")
                for sc, name, _ in r["top3"]:
                    md.append(f"- {sc:.1f} · {name}")
            md.append("\n</details>\n")

    # Lista limpia de FALTANTES al final
    md.append("\n---\n")
    md.append("\n## Lista de materiales que parecen faltar\n")
    missing_rows = [r for r in rows if r["status"] == "FALTA"]
    if not missing_rows:
        md.append("_(Ninguno marcado como faltante.)_\n")
    else:
        md.append("Estos son los materiales del manual donde el mejor match "
                  f"de la libreria tiene score < {SIMILAR_THRESHOLD:.0f}. "
                  "Si los necesitas para tus simulaciones, conviene agregarlos "
                  "a la carpeta `materials/` como JSON.\n")
        md.append("| # | Material del manual | Score mejor candidato | Mejor candidato |")
        md.append("|---:|---|---:|---|")
        for i, r in enumerate(missing_rows, 1):
            md.append(f"| {i} | {r['target']} | "
                       f"{r['best_score']:.0f} | "
                       f"{r['best_name']} |")
    md.append("")

    # Recomendaciones
    md.append("\n## Como agregar materiales faltantes\n")
    md.append("Cada archivo `.json` en `materials/` define UN material o un "
              "ARRAY de materiales. Formato minimo:\n")
    md.append("```json")
    md.append("{")
    md.append('  "name": "Mi material",')
    md.append('  "category": "Difusores",')
    md.append('  "source": "Cox & D\'Antonio, Acoustic Absorbers and Diffusers, A.1",')
    md.append('  "absorption_coef": [0.17, 0.17, 0.40, 0.86, 1.00, 0.84, 0.61, 0.61]')
    md.append("}")
    md.append("```\n")
    md.append("Los 8 valores corresponden a las bandas **63 / 125 / 250 / "
              "500 / 1000 / 2000 / 4000 / 8000 Hz**. Si el manual da solo "
              "6 bandas (125 – 4000 Hz), conviene **extrapolar** o repetir "
              "el primer y el ultimo valor para 63 y 8000 Hz respectivamente "
              "(el software interpola en escala log).\n")
    md.append("Despues, en la pestana Acustica del software, apretar "
              "**Recargar materiales** y los nuevos aparecen disponibles en "
              "el dialogo de Materiales.\n")

    out = Path(__file__).parent / "MATERIALS_COVERAGE.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"[OK] Reporte escrito en {out}")
    print()
    # Lista corta en consola
    print("--- Materiales FALTANTES (score < 40) ---")
    for r in rows:
        if r["status"] == "FALTA":
            print(f"  {r['best_score']:5.1f}  {r['target']}")


if __name__ == "__main__":
    main()
