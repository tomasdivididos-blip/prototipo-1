#!/usr/bin/env python
"""Aplica citas verificadas (pagina/seccion) al banco, por id de pregunta.

Solo toca las preguntas del mapeo MAP; el resto queda como estaba. Reemplaza la
linea `src:` que sigue a cada `id:`. Verificado contra los PDF de referencias/
con _scrape.py + pdftotext (ver CITAS.md). Paginas = pagina IMPRESA del libro.
"""
import re, os, sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banco")

# id  ->  nueva cita. Everest offset 25 (impresa = PDF-25), verificado.
MAP = {
    # ───────── GEOMETRÍA (Everest pagina; Cox seccion+pagina TOC) ─────────
    "geo-schroeder-sentido": "Everest, Master Handbook of Acoustics, p. 325 (frecuencia de corte/crossover)",
    "geo-axial-energia":     "Everest, Master Handbook of Acoustics, p. 140 (potencia axial/tangencial/oblicuo)",
    "geo-tangencial-superficies": "Everest, Master Handbook of Acoustics, p. 140",
    "geo-cubo":              "Everest, Master Handbook of Acoustics, p. 284 (modos degenerados)",
    "geo-nodo-escucha":      "Everest, Master Handbook of Acoustics, p. 140",
    "geo-fs-volumen":        "Everest, Master Handbook of Acoustics, p. 325",
    "geo-ratios-por-que":    "Everest, Master Handbook of Acoustics, p. 276 · Bolt (1946); Louden (1971)",
    "geo-bonello":           "Everest, Master Handbook of Acoustics, p. 348 (The Bonello Criterion) · Bonello (1981)",
    "geo-concava":           "Everest, Master Handbook of Acoustics, p. 276 (formas cóncavas/foco)",
    "geo-flutter":           "Everest, Master Handbook of Acoustics, p. 494 (flutter → filtro peine)",
    "geo-mean-free-path":    "Everest, Master Handbook of Acoustics, p. 354 (Mean Free Path)",
    "geo-eyring-cuando":     "Everest, Master Handbook of Acoustics, p. 160 · Beranek, Acústica",
    "geo-aire-absorcion":    "Everest, Master Handbook of Acoustics, p. 203 · ISO 9613-1",
    "geo-volumen-rt":        "Everest, Master Handbook of Acoustics, p. 159 (ecuación de Sabine)",
    "geo-absorcion-distribuida": "Everest, Master Handbook of Acoustics, p. 160 · Beranek, Acústica",
    "geo-esquinas":          "Cox & D'Antonio, Acoustic Absorbers and Diffusers, cap. 5 · Everest, p. 203 (bass traps)",
    "geo-poroso-espesor":    "Cox & D'Antonio, Acoustic Absorbers and Diffusers, cap. 5 (Porous absorption), p. 156",
    "geo-airgap":            "Cox & D'Antonio, Acoustic Absorbers and Diffusers, cap. 5, p. 156",
    "geo-resistividad":      "Cox & D'Antonio, Acoustic Absorbers and Diffusers, §3.6/cap. 5, p. 95",
    "geo-panel-membrana":    "Cox & D'Antonio, Acoustic Absorbers and Diffusers, cap. 6 (Resonant absorbers), p. 196",
    "geo-helmholtz-resonador": "Cox & D'Antonio, Acoustic Absorbers and Diffusers, cap. 6 (Resonant absorbers), p. 196",
    "geo-perforado":         "Cox & D'Antonio, Acoustic Absorbers and Diffusers, cap. 6 (Resonant absorbers), p. 196",
    "geo-membrana-vs-poroso": "Cox & D'Antonio, Acoustic Absorbers and Diffusers, cap. 6, p. 196 · Newell, Recording Studio Design",
    "geo-alpha-mayor-1":     "UNE-EN ISO 354:2004 — referencias/ · Cox & D'Antonio, §3.4 (cámara reverberante), p. 84",
    "geo-iso354":            "UNE-EN ISO 354:2004 — referencias/ · Cox & D'Antonio, §3.4, p. 84",
    "geo-tubo-kundt":        "Cox & D'Antonio, Acoustic Absorbers and Diffusers, §3.6, p. 95 · ISO 10534",
    "geo-scattering-vs-diffusion": "Cox & D'Antonio, Acoustic Absorbers and Diffusers, §4.4–4.5, p. 130–135 · ISO 17497-1; AES-4id",

    # ───────── FUENTES (Toole seccion+pagina TOC; Everest pagina) ─────────
    "fte-sbir-empotrar":     "Toole, Sound Reproduction, §13.2, p. 201 · Newell, Recording Studio Design",
    "fte-sbir-peor":         "Toole, Sound Reproduction, §13.2, p. 201 · Newell, Recording Studio Design",
    "fte-consola-reflexion": "Newell, Recording Studio Design · Toole, Sound Reproduction, §13.2, p. 201",
    "fte-eq-picos-nulos":    "Toole, Sound Reproduction, §13.4, p. 239 · Welti & Devantier (2006)",
    "fte-eq-fase-minima":    "Toole, Sound Reproduction, §13.4, p. 239 · Low-Frequency Modal Equalization — referencias/",
    "fte-multisub":          "Welti & Devantier (2006) · Toole, Sound Reproduction, §13.3, p. 217",
    "fte-curva-objetivo":    "Toole, Sound Reproduction, §13.4, p. 239 · Harman target curve",
    "fte-cardioide-sub":     "Toole, Sound Reproduction, §13.3, p. 216 · Low frequency sound field control using CABS — referencias/",
    "fte-distancia-critica": "Everest, Master Handbook of Acoustics, p. 87 (critical distance)",
    "fte-near-field":        "Everest, Master Handbook of Acoustics, p. 87 · Newell, Recording Studio Design",
    "fte-campo-cercano":     "Toole, Sound Reproduction, §18.1.1, p. 366 · Beranek, Acústica",
    "fte-monitor-altura":    "Toole, Sound Reproduction, §18.2, p. 372",
    "fte-cruce-80":          "Toole, Sound Reproduction, §13.3, p. 216 · ITU-R BS.775",
    "fte-alineacion-fase":   "Toole, Sound Reproduction, §13.3, p. 216",
    "fte-bass-management":   "Toole, Sound Reproduction, §13.3, p. 216 · ITU-R BS.775",
    "fte-lfe":               "Toole, Sound Reproduction, §13.3, p. 216 · ITU-R BS.775",
    "fte-directividad":      "Toole, Sound Reproduction, §18.2, p. 372 (Objective Evaluations)",
    "fte-listening-window":  "Toole, Sound Reproduction, §18.2, p. 373 · ANSI/CTA-2034",
    "fte-waveguide":         "Toole, Sound Reproduction, §18.2, p. 372",
    "fte-mtm-lobing":        "Toole, Sound Reproduction, §18.2, p. 372 · D'Appolito (1983)",
    "fte-baffle-step":       "Toole, Sound Reproduction, §18.1, p. 366 · Beranek, Sound Fields and Transducers",
    "fte-difraccion-bordes": "Toole, Sound Reproduction, §18.2, p. 372 · Beranek, Sound Fields and Transducers",
    "fte-line-array":        "Toole, Sound Reproduction, §18.1.2, p. 368 · Beranek, Sound Fields and Transducers",
    "fte-medicion-gated":    "Toole, Sound Reproduction, §18.2.2, p. 376",
    "fte-klippel-nfs":       "Klippel & Bellmann (2016) · Toole, Sound Reproduction, §18.2.2, p. 376",
    "fte-sensibilidad":      "Beranek, Sound Fields and Transducers, §1.9 · Toole, Sound Reproduction, §18.6, p. 418",
    "fte-impedancia-minima": "Toole, Sound Reproduction, §18.6, p. 418 · Beranek, Sound Fields and Transducers",
    "fte-retardo-grupo":     "Toole, Sound Reproduction, §18.6.2, p. 420 · Blauert & Laws (1978)",
    "fte-lede-rfz":          "Newell, Recording Studio Design · Everest, Master Handbook of Acoustics, p. 431 (LEDE/RFZ)",

    # ───────── PSICOACÚSTICA (Everest pagina) ─────────
    "psi-precedencia":       "Everest, Master Handbook of Acoustics, p. 353 (Law of the First Wavefront)",
    "psi-haas":              "Haas (1951) · Everest, Master Handbook of Acoustics, p. 353",

    # ───────── NUMÉRICA (Ihlenburg seccion §) ─────────
    "num-helmholtz":         "Ihlenburg, Finite Element Analysis of Acoustic Scattering, §1.1 (ec. 1.3) · FEM for Acoustics",
    "num-forma-debil":       "Ihlenburg, Finite Element Analysis of Acoustic Scattering, §2.2 (forma débil)",
    "num-natural-esencial":  "Ihlenburg, Finite Element Analysis of Acoustic Scattering, §2.2",
    "num-pared-rigida":      "Ihlenburg, Finite Element Analysis of Acoustic Scattering, §2.2",
    "num-funciones-forma":   "Ihlenburg, Finite Element Analysis of Acoustic Scattering, §2.2 (hat functions)",
    "num-elementos-lambda":  "Ihlenburg, Finite Element Analysis of Acoustic Scattering, §2.3 (error estimates)",
    "num-malla-nyquist":     "Ihlenburg, Finite Element Analysis of Acoustic Scattering, §2.3 · FEM for Acoustics",
    "num-pollution":         "Ihlenburg, §2.3/§3.2 (large wavenumber) · Stable Multiscale Petrov-Galerkin FEM — referencias/",
    "num-condicionamiento":  "Ihlenburg, Finite Element Analysis of Acoustic Scattering, §3.2 (large wavenumber)",
    "num-gmres-helmholtz":   "Ihlenburg, §3.2 · Stable Multiscale Petrov-Galerkin FEM — referencias/",
    "num-numero-onda":       "Ihlenburg, Finite Element Analysis of Acoustic Scattering, §1.1",
    "num-h-vs-p":            "Ihlenburg, Finite Element Analysis of Acoustic Scattering, §2.3",

    # numericos (Everest pagina)
    "num-axial-1":           "Everest, Master Handbook of Acoustics, p. 140 · Rayleigh, Theory of Sound",
    "num-modo-general":      "Rayleigh, Theory of Sound · Everest, Master Handbook of Acoustics, p. 140",
    "num-sabine":            "Sabine (1922) · Everest, Master Handbook of Acoustics, p. 159 · Beranek, Acústica",
    "num-eyring":            "Eyring (1930) · Everest, Master Handbook of Acoustics, p. 160 · Beranek, Acústica",
    "num-schroeder":         "Schroeder (1962), JASA · Everest, Master Handbook of Acoustics, p. 325",
    "num-absorcion-area":    "Everest, Master Handbook of Acoustics, p. 160 · Beranek, Acústica",
    "num-inv-square":        "Beranek, Acústica · Everest, Master Handbook of Acoustics, p. 87",
}


def main():
    files = ["geometria.js", "fuentes.js", "psicoacustica.js", "numerica.js", "numericos.js"]
    aplicados, faltan = [], list(MAP.keys())

    for fn in files:
        path = os.path.join(BASE, fn)
        src = open(path, encoding="utf-8").read()
        for qid, nueva in MAP.items():
            pat = r'(id:\s*"' + re.escape(qid) + r'",[^}]*?\n\s*)src:\s*"[^"]*"'
            new, n = re.subn(pat, lambda m: m.group(1) + f'src: "{nueva}"', src, count=1, flags=re.S)
            if n:
                src = new
                aplicados.append(qid)
                if qid in faltan:
                    faltan.remove(qid)
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)

    print(f"Citas aplicadas: {len(aplicados)}/{len(MAP)}")
    if faltan:
        print("NO ENCONTRADAS:", faltan)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
