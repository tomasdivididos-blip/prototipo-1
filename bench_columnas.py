"""bench_columnas.py — Oraculos de columnas piso-techo (v2.88, Fase 3).

El motor es el MISMO carve de furniture.py (ya validado en bench_furniture.py).
Lo NUEVO de una columna es el caso TUNEL piso-techo (genero 1): los muebles son
vacios flotantes/apoyados, una columna atraviesa el dominio de lado a lado. Estos
4 oraculos (plan_columnas.md §6) son el gate fisico del feature. Todos falsables.

  O1. Reduccion de la huella -> 0: columna cada vez mas fina en un shoebox 5x4x3
      conocido -> fn(columna) -> fn(sala vacia) (error decreciente, -> 0). La sala
      vacia coincide con el analitico (ancla).
  O2. Convergencia en npm: para una columna fija, el corrimiento Dfn se estabiliza
      al subir npm (Cauchy: |Df(npm) - Df(npm+1)| decrece). La columna fina es el
      caso mas exigente de resolucion; reporta el npm que estabiliza.
  O3. Simetria: columna centrada en una sala de base cuadrada -> el par degenerado
      (1,0,0)/(0,1,0) SIGUE degenerado (la columna simetrica no lo parte) y AMBOS
      se corren (la columna actua).
  O4. Regimen perturbativo ka<<1 (Morse & Ingard §9.2, perturbacion de cavidad por
      obstaculo pequeno): el corrimiento escala con el AREA de la seccion (Dw ~ a^2,
      porque DV ~ a^2 y el integrando es ~ cte en la columna fina). Doblar el lado
      cuadruplica el corrimiento. Falsa si escalara lineal (~2x) en vez de ~4x.
  Regresion: sin columnas, malla identica bit a bit (heredado, se re-chequea).

Correr:  python bench_columnas.py
"""

import numpy as np

import geometry
import acoustic_mesh
import acoustic_fem
import furniture as fu


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def room_mesh(Lx, Ly, Lz, npm=4.0):
    v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
    nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=npm)
    return v, nodes, tets


def solve(nodes, tets, n_modes=15):
    K, M, _ = acoustic_fem.build_KM(nodes, tets)
    freqs, _ = acoustic_fem.solve_modes(K, M, n_modes=n_modes)
    return np.asarray(freqs)


def nearest(freqs, f0):
    freqs = np.asarray(freqs)
    return float(freqs[np.argmin(np.abs(freqs - f0))])


def carve_column(surface_v, nodes, tets, *, kind="box", side=0.5, diam=None,
                 center=(0.0, 0.0)):
    """Talla una columna piso-techo centrada en `center`. Devuelve (nodes2,tets2,info,furn)."""
    if kind == "cylinder":
        col = fu.make_column("cylinder", diameter=(diam if diam else side),
                             position=(center[0], center[1], 0.0))
    else:
        col = fu.make_column("box", diameter=side, depth=side,
                             position=(center[0], center[1], 0.0))
    fu.sync_column_height(col, surface_v)                 # altura = alto de sala
    n2, t2, info = fu.carve_mesh(nodes, tets, [col])
    return n2, t2, info, col


# ---------------------------------------------------------------------------
print("O0: regresion — sin columnas, malla intacta")
v0, nodes0, tets0 = room_mesh(5, 4, 3, npm=4.0)
n2, t2, info = fu.carve_mesh(nodes0, tets0, [])
check("nodes/tets identicos bit a bit",
      np.array_equal(n2, nodes0) and np.array_equal(t2, tets0),
      f"{len(nodes0)} nodos, {len(tets0)} tets")

# ---------------------------------------------------------------------------
print("\nO1: reduccion de la huella -> 0 (columna -> sala vacia -> analitico)")
# Ancla: sala vacia vs analitico shoebox.
f_empty = solve(nodes0, tets0, n_modes=15)


def analytic(Lx, Ly, Lz, fmax=120, c=343.0):
    out = []
    for nx in range(4):
        for ny in range(4):
            for nz in range(3):
                if nx == ny == nz == 0:
                    continue
                f = c / 2 * np.sqrt((nx/Lx)**2 + (ny/Ly)**2 + (nz/Lz)**2)
                if f <= fmax:
                    out.append(f)
    return np.array(sorted(out))


anchors = [(34.3, "100"), (42.875, "010"), (57.17, "001"), (68.6, "200")]
e_anchor = max(abs(nearest(f_empty, f0) - f0) / f0 for f0, _ in anchors) * 100
check("sala vacia ~ analitico (<4%)", e_anchor < 4.0, f"max err {e_anchor:.1f}%")

# Columna centrada, lado decreciente. max|Df/f| sobre los axiales anclados.
def shift_metric(fr):
    return max(abs(nearest(fr, f0) - nearest(f_empty, f0)) / nearest(f_empty, f0)
               for f0, _ in anchors) * 100

sides = [0.75, 0.50, 0.25, 0.10]      # 0.10 < paso de malla (0.25) -> sub-resolucion
S = []
ntets = []
for sd in sides:
    nc, tc, inf, _ = carve_column(v0, nodes0, tets0, kind="box", side=sd)
    S.append(shift_metric(solve(nc, tc, n_modes=15)))
    ntets.append(inf["n_tets_removed"])
    print(f"    lado {sd:.2f} m -> max|Df/f| = {S[-1]:.3f}%  "
          f"(V {inf['V_removed_mesh']:.2f} m3, {inf['n_tets_removed']} tets)")
check("corrimiento decrece al afinar la columna (monotono)",
      S[0] > S[1] > S[2] > S[3], " > ".join(f"{s:.3f}" for s in S) + " %")
check("columna sub-malla (0.10 m < paso) -> efecto -> 0 (<0.25%)", S[-1] < 0.25,
      f"lado 0.10 m: {S[-1]:.3f}% ({ntets[-1]} tets removidos)")

# ---------------------------------------------------------------------------
print("\nO2: convergencia en npm (columna fija, Df estabiliza)")
# Columna cuadrada 0.5 m centrada; Df del (2,0,0) vs sala vacia al MISMO npm.
f200 = 343 / 5.0
dfs = []
for npm in (3.0, 4.0, 5.0):
    vv, nn, tt = room_mesh(5, 4, 3, npm=npm)
    fe = nearest(solve(nn, tt, n_modes=15), f200)
    nc, tc, _, _ = carve_column(vv, nn, tt, kind="box", side=0.5)
    fc = nearest(solve(nc, tc, n_modes=15), f200)
    dfs.append((fc - fe) / fe * 100)
    print(f"    npm {npm:.0f} -> Df(2,0,0) = {dfs[-1]:+.3f}%")
check("Df(2,0,0) > 0 en todo npm (antinodo en el centro: sube)",
      all(d > 0 for d in dfs), ", ".join(f"{d:+.3f}%" for d in dfs))
spread = max(dfs) - min(dfs)
check("Df(2,0,0) estable en npm (spread < 0.1%): convergido",
      spread < 0.1, f"spread {spread:.3f}% sobre npm 3/4/5")

# ---------------------------------------------------------------------------
print("\nO3: simetria — columna centrada en base cuadrada no parte la degeneracion")
vq, nq, tq = room_mesh(4, 4, 3, npm=4.0)
fe_q = solve(nq, tq, n_modes=15)
# Par degenerado (1,0,0)/(0,1,0): f = 343/8 = 42.875 Hz (los dos iguales).
fdeg = 343 / 8.0
pair_empty = np.sort(np.abs(fe_q - fdeg))[:2]           # dos modos mas cercanos
idx_e = np.argsort(np.abs(fe_q - fdeg))[:2]
split_empty = abs(fe_q[idx_e[0]] - fe_q[idx_e[1]])
nc, tc, _, _ = carve_column(vq, nq, tq, kind="box", side=0.5)   # centrada (0,0)
fc_q = solve(nc, tc, n_modes=15)
idx_c = np.argsort(np.abs(fc_q - fdeg))[:2]
split_col = abs(fc_q[idx_c[0]] - fc_q[idx_c[1]])
f_pair_col = fc_q[idx_c].mean()
f_pair_emp = fe_q[idx_e].mean()
shift_pair = (f_pair_col - f_pair_emp) / f_pair_emp * 100
check("la columna simetrica NO parte el par (split se mantiene chico)",
      split_col < 0.5 and abs(split_col - split_empty) < 0.5,
      f"split vacia={split_empty:.3f} Hz, con columna={split_col:.3f} Hz")
check("el par SI se corre (la columna actua)", abs(shift_pair) > 0.1,
      f"{f_pair_emp:.2f} -> {f_pair_col:.2f} Hz  ({shift_pair:+.3f}%)")

# ---------------------------------------------------------------------------
print("\nO4: regimen perturbativo ka<<1 — Dw ~ a^2 (doblar el lado -> ~4x)")
# El escalado a^2 vale cuando la columna es FINA frente a la longitud de onda del
# MODO (k_modo * a << 1). (2,0,0) tiene lambda corta (2.5 m): lados 0.5/1.0 dan
# k*a ~ 0.3/0.6 (NO <<1) y el escalado satura. Se usa (1,0,0), lambda=10 m: lados
# 0.25/0.5 dan k*a = 0.08/0.16 << 1. (1,0,0) tiene NODO de presion en el centro
# -> el corrimiento lo domina -rho|u|^2 (antinodo de velocidad), BAJA, ~ cte sobre
# la columna fina -> Dw ~ area ~ lado^2. Doblar el lado -> ~4x.
k100 = 2 * np.pi * 34.3 / 343.0        # numero de onda del modo (1,0,0)

def df100(side):
    nc, tc, _, _ = carve_column(v0, nodes0, tets0, kind="box", side=side)
    fc = nearest(solve(nc, tc, n_modes=15), 34.3)
    fe = nearest(f_empty, 34.3)
    return (fc - fe) / fe * 100

d_small = df100(0.25)
d_big = df100(0.50)
ratio = abs(d_big) / abs(d_small) if d_small else 0.0
print(f"    lado 0.25 (k*a={k100*0.125:.3f}) Df={d_small:+.3f}%  |  "
      f"lado 0.50 (k*a={k100*0.25:.3f}) Df={d_big:+.3f}%  ->  ratio {ratio:.2f}")
check("ambos corrimientos negativos (nodo de presion: baja)",
      d_small < 0 and d_big < 0, f"{d_small:+.3f}% , {d_big:+.3f}%")
check("escala con el area (~4x; descarta lineal ~2x)", 2.5 <= ratio <= 6.0,
      f"ratio {ratio:.2f} (esperado ~4 por Dw~a^2, M&I §9.2)")

# ---------------------------------------------------------------------------
n_ok = sum(1 for _n, c, _d in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
