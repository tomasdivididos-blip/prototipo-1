#!/usr/bin/env python
"""Audita el banco de preguntas sin necesidad de navegador.

Chequea la regla de oro: las 4 opciones de cada pregunta tienen que ser del mismo
largo (tolerancia SPREAD_MAX). Si la correcta es sistematicamente la mas larga, se
acierta por longitud sin saber acustica.

Uso:
    python check_banco.py            # audita todo banco/
    python check_banco.py -v         # ademas lista cada opcion con su largo
"""
import re, sys, glob, os

SPREAD_MAX = 5   # maxima diferencia de largo entre opciones de una pregunta
MARGEN_TELL = 3  # ventaja de la correcta sobre la 2da que ya se empieza a notar
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banco")

BLOQUE = re.compile(r"\{\s*\n\s*id:\s*\"([^\"]+)\"(.*?)\n  \},", re.S)
CAMPO  = lambda n, s: (re.search(rf'{n}:\s*"([^"]*)"', s) or [None, None])[1]


def opciones(bloque):
    m = re.search(r"opts:\s*\[(.*?)\]", bloque, re.S)
    if not m:
        return None
    # Strings de nivel superior del array (permite comillas escapadas).
    return re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))


def main():
    verbose = "-v" in sys.argv
    archivos = sorted(glob.glob(os.path.join(BASE, "*.js")))
    total = fallos = 0
    mas_larga = 0
    fijas = 0
    por_area = {}

    for fn in archivos:
        base = os.path.basename(fn)
        if base in ("index.js", "numericos.js"):
            continue
        src = open(fn, encoding="utf-8").read()
        for qid, cuerpo in BLOQUE.findall(src):
            total += 1
            # El area se aplica con .map() al final de cada archivo de area,
            # asi que si no esta en el bloque, sale del nombre del archivo.
            area = CAMPO("area", cuerpo) or os.path.splitext(base)[0]
            por_area[area] = por_area.get(area, 0) + 1
            opts = opciones(cuerpo)
            ans = re.search(r"ans:\s*(\d+)", cuerpo)
            if not opts or len(opts) != 4:
                print(f"  FALLA {qid}: {len(opts) if opts else 0} opciones"); fallos += 1; continue
            if not ans or not (0 <= int(ans.group(1)) <= 3):
                print(f"  FALLA {qid}: ans invalido"); fallos += 1; continue
            ans = int(ans.group(1))
            fijas += 1

            largos = [len(o) for o in opts]
            spread = max(largos) - min(largos)
            # Tell real = la correcta es ESTRICTAMENTE la mas larga y por un margen
            # visible sobre la segunda. Ganar por 1 caracter, o empatar, no se ve.
            resto = sorted(largos[:ans] + largos[ans + 1:], reverse=True)
            if largos[ans] - resto[0] >= MARGEN_TELL:
                mas_larga += 1
            if spread > SPREAD_MAX:
                objetivo = max(largos)
                print(f"  DESPAREJA {qid}  {'/'.join(map(str, largos))}  spread {spread}")
                for k, (o, L) in enumerate(zip(opts, largos)):
                    marca = "*" if k == ans else " "
                    print(f"     {marca} [{L:>3}] {'+' if L < objetivo else ' '}{objetivo - L if L < objetivo else 0:>2}  {o}")
                fallos += 1
            elif verbose:
                print(f"  ok {qid}  {'/'.join(map(str, largos))}")

    print()
    print(f"Preguntas fijas: {fijas}   por area: {por_area}")
    print(f"Desparejas (spread > {SPREAD_MAX}): {fallos}")
    esperado = fijas / 4 if fijas else 0
    print(f"Correcta gana por >={MARGEN_TELL} chars: {mas_larga}/{fijas}  (azar ~ {esperado:.0f})")
    if fijas and mas_larga > esperado * 2:
        print("  AVISO: sesgo de largo agregado — la correcta gana por longitud demasiado seguido.")
    print("OK" if fallos == 0 else f"FALLOS: {fallos}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
