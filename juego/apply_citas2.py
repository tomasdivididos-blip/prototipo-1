#!/usr/bin/env python
"""Segunda pasada de citas: Zwicker & Beranek (ver CITAS.md).

Zwicker escaneado (sin texto): índice leído como imagen (pdftoppm), offset 10.
Beranek con texto: SF&T por capítulo (DOI da la pág. de inicio), Acústica offset 8.
"""
import re, os, sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banco")

MAP = {
    # ───────── ZWICKER (§sección, p. impresa; offset 10) ─────────
    "psi-enmascaramiento":        "Zwicker & Fastl, Psychoacoustics, §4.1, p. 62",
    "psi-banda-critica":          "Zwicker & Fastl, Psychoacoustics, §6.1, p. 150",
    "psi-bark":                   "Zwicker & Fastl, Psychoacoustics, §6.2 (critical-band rate/Bark), p. 158",
    "psi-enmascaramiento-temporal": "Zwicker & Fastl, Psychoacoustics, §4.4.2 (premasking), p. 82 · Moore",
    "psi-fon-sonio":              "Zwicker & Fastl, Psychoacoustics, §8.1–8.2 (fon/sonio), p. 203–205",
    "psi-ponderacion-a":          "Zwicker & Fastl, Psychoacoustics, §8.7.3 (loudness meters), p. 233 · IEC 61672",
    "psi-integracion-temporal":   "Zwicker & Fastl, Psychoacoustics, §8.5 (temporal effects), p. 216",
    "psi-aspereza":               "Zwicker & Fastl, Psychoacoustics, §11.1, p. 257 · Roederer, Acústica y Psicoacústica",
    "psi-agudeza":                "Zwicker & Fastl, Psychoacoustics, §9.1–9.2 (sharpness), p. 239",
    "psi-jnd-nivel":              "Zwicker & Fastl, Psychoacoustics, §7.1.2, p. 180 · Moore · Toole, Sound Reproduction",
    "psi-bmld":                   "Zwicker & Fastl, Psychoacoustics, §15.2, p. 295 · Moore · Blauert",

    # ───────── BERANEK & MELLOW, Sound Fields and Transducers (cap. + pág. inicio) ─────────
    "fte-baffle-step":       "Toole, Sound Reproduction, §18.1, p. 366 · Beranek & Mellow, Sound Fields and Transducers, cap. 4, p. 129",
    "fte-difraccion-bordes": "Toole, Sound Reproduction, §18.2, p. 372 · Beranek & Mellow, Sound Fields and Transducers, cap. 4, p. 129",
    "fte-line-array":        "Toole, Sound Reproduction, §18.1.2, p. 368 · Beranek & Mellow, Sound Fields and Transducers, cap. 4",
    "fte-sellada-ported":    "Beranek & Mellow, Sound Fields and Transducers, cap. 7 (Loudspeaker Enclosures), p. 289 · Toole, Sound Reproduction",
    "fte-port-noise":        "Beranek & Mellow, Sound Fields and Transducers, cap. 7 (Loudspeaker Enclosures), p. 289",
    "fte-sensibilidad":      "Beranek & Mellow, Sound Fields and Transducers, cap. 6, p. 241 · Toole, Sound Reproduction, §18.6, p. 418",
    "fte-impedancia-minima": "Toole, Sound Reproduction, §18.6, p. 418 · Beranek & Mellow, Sound Fields and Transducers, cap. 6, p. 241",
    "fte-thd-imd":           "Beranek & Mellow, Sound Fields and Transducers, cap. 6, p. 241 · Toole, Sound Reproduction",
    "fte-compresion":        "Beranek & Mellow, Sound Fields and Transducers, cap. 6, p. 241",
    "fte-directividad-q":    "Beranek, Acústica, p. 96 (índice de directividad) · Everest, Master Handbook of Acoustics",

    # ───────── BERANEK, Acústica (offset 8; reverberación p. 218) ─────────
    "geo-eyring-cuando":       "Everest, Master Handbook of Acoustics, p. 160 · Beranek, Acústica, p. 218",
    "geo-absorcion-distribuida": "Everest, Master Handbook of Acoustics, p. 160 · Beranek, Acústica, p. 218",
    "num-sabine":              "Sabine (1922) · Everest, Master Handbook of Acoustics, p. 159 · Beranek, Acústica, p. 218",
    "num-eyring":              "Eyring (1930) · Everest, Master Handbook of Acoustics, p. 160 · Beranek, Acústica, p. 218",
    "num-absorcion-area":      "Everest, Master Handbook of Acoustics, p. 160 · Beranek, Acústica, p. 218",
}


def main():
    files = ["geometria.js", "fuentes.js", "psicoacustica.js", "numerica.js", "numericos.js"]
    hechos, faltan = [], list(MAP.keys())
    for fn in files:
        path = os.path.join(BASE, fn)
        src = open(path, encoding="utf-8").read()
        for qid, nueva in MAP.items():
            pat = r'(id:\s*"' + re.escape(qid) + r'".*?\n\s*)src:\s*"[^"]*"'
            new, n = re.subn(pat, lambda m: m.group(1) + f'src: "{nueva}"', src, count=1, flags=re.S)
            if n:
                src, = (new,)
                hechos.append(qid)
                if qid in faltan:
                    faltan.remove(qid)
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    print(f"Citas aplicadas: {len(hechos)}/{len(MAP)}")
    if faltan:
        print("NO ENCONTRADAS:", faltan)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
